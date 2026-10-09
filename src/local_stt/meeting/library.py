"""The meetings folder as the app shows it: one entry per session directory,
its transcript and one mixed track for playback."""

from __future__ import annotations

import json
import re
import shutil
import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from ..audio.decode import write_wav
from ..config import CACHE_DIR
from ..engine.backend import Segment, Transcript
from ..export import FORMATS, export
from .transcribe import load_settings

MIX_DIR = CACHE_DIR / "mix"
_mix_lock = threading.Lock()  # the player asks for the audio and its waveform at once
_DATED = re.compile(r"(\d{4}-\d{2}-\d{2})-(.+)")
_CLOCK = re.compile(r"(\d{2})-(\d{2})(?:-\d+)?")


def session_dir(output_dir: Path, session_id: str) -> Path:
    """Rejects anything but a session folder directly inside output_dir."""
    if not session_id or "/" in session_id or "\\" in session_id or session_id.startswith("."):
        raise ValueError(f"no meeting {session_id!r}")
    path = output_dir / session_id
    if not (path / "raw").is_dir():
        raise ValueError(f"no meeting {session_id!r}")
    return path


def _wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    except (OSError, wave.Error, EOFError):
        return 0.0


def _title_and_start(path: Path, settings: dict) -> tuple[str, datetime]:
    start = None
    if settings.get("started_at"):
        try:
            start = datetime.fromisoformat(settings["started_at"])
        except ValueError:
            start = None
    title = settings.get("title") or ""
    match = _DATED.fullmatch(path.name)
    slug = match.group(2) if match else path.name
    clock = _CLOCK.fullmatch(slug)
    if start is None:
        if match:
            day = datetime.strptime(match.group(1), "%Y-%m-%d")
            start = day.replace(hour=int(clock.group(1)), minute=int(clock.group(2))) if clock else day
        else:
            start = datetime.fromtimestamp(path.stat().st_mtime)
    if not title or _CLOCK.fullmatch(title):
        title = (
            f"Meeting at {start:%H:%M}" if clock or _CLOCK.fullmatch(title)
            else slug.replace("-", " ").capitalize()
        )
    return title, start


def _summary(path: Path, active: dict) -> dict:
    settings = load_settings(path)
    title, start = _title_and_start(path, settings)
    if path.name == active.get("recording"):
        status = "recording"
    elif path.name in active.get("transcribing", ()):
        status = "transcribing"
    elif (path / "transcript.json").exists():
        status = "ready"
    else:
        status = "untranscribed"
    return {
        "id": path.name,
        "title": title,
        "started_at": start.isoformat(timespec="minutes"),
        "duration_s": round(_wav_seconds(path / "raw" / "mic.wav")),
        "language": settings.get("language") or "",
        "model": settings.get("model") or "",
        "status": status,
    }


def list_sessions(output_dir: Path, active: dict | None = None) -> list[dict]:
    """Newest first. `active` names the session being recorded and the ones
    being transcribed: {"recording": id, "transcribing": {ids}}."""
    if not output_dir.is_dir():
        return []
    sessions = [
        _summary(p, active or {}) for p in output_dir.iterdir()
        if p.is_dir() and (p / "raw").is_dir()
    ]
    return sorted(sessions, key=lambda s: s["started_at"], reverse=True)


def load_transcript(path: Path) -> Transcript | None:
    try:
        data = json.loads((path / "transcript.json").read_text())
    except (OSError, ValueError):
        return None
    return Transcript(
        segments=[
            Segment(start=s["start"], end=s["end"], text=s["text"], speaker=s.get("speaker"))
            for s in data.get("segments", [])
        ],
        language=data.get("language", ""),
        duration=data.get("duration", 0.0),
        model=data.get("model", ""),
    )


def session_detail(output_dir: Path, session_id: str, active: dict | None = None) -> dict:
    path = session_dir(output_dir, session_id)
    detail = _summary(path, active or {})
    transcript = load_transcript(path)
    detail["segments"] = [
        {"start": s.start, "end": s.end, "speaker": s.speaker or "", "text": s.text.strip()}
        for s in (transcript.segments if transcript else [])
    ]
    detail["path"] = str(path)
    return detail


def export_session(output_dir: Path, session_id: str, fmt: str, dest: Path) -> Path:
    """Writes the session's transcript as `fmt` to dest, copying the saved file when there is one."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    if not dest.is_absolute():
        raise ValueError("pick where to save the file")
    folder = session_dir(output_dir, session_id)
    existing = folder / f"transcript.{fmt}"
    if existing.exists():
        shutil.copyfile(existing, dest)
        return dest
    transcript = load_transcript(folder)
    if transcript is None:
        raise ValueError("this meeting has no transcript yet")
    export(transcript, fmt, dest, title=session_detail(output_dir, folder.name)["title"])
    return dest


def mixed_audio(output_dir: Path, session_id: str) -> Path:
    """Both tracks mixed to one 16 kHz WAV, cached until a track changes."""
    with _mix_lock:
        return _mixed_audio(output_dir, session_id)


def _mixed_audio(output_dir: Path, session_id: str) -> Path:
    from ..audio.decode import decode_to_pcm

    path = session_dir(output_dir, session_id)
    tracks = [path / "raw" / "mic.wav", path / "raw" / "system.wav"]
    stamp = int(max(t.stat().st_mtime for t in tracks if t.exists()))
    dest = MIX_DIR / f"{session_id}-{stamp}.wav"
    if dest.exists():
        return dest
    pcms = [decode_to_pcm(t) for t in tracks if t.exists()]
    length = max(len(p) for p in pcms)
    mix = np.zeros(length, dtype=np.float32)
    for p in pcms:
        mix[: len(p)] += p
    peak = float(np.max(np.abs(mix))) if length else 0.0
    if peak > 1.0:
        mix /= peak
    MIX_DIR.mkdir(parents=True, exist_ok=True)
    for old in MIX_DIR.glob(f"{session_id}-*.wav"):
        old.unlink(missing_ok=True)
    tmp = dest.with_suffix(".tmp")
    write_wav(tmp, mix)
    tmp.replace(dest)
    return dest


def waveform(wav: Path, bars: int = 120) -> list[float]:
    """Peak level per bar, 0..1, for drawing the player."""
    with wave.open(str(wav)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    if not len(pcm):
        return [0.0] * bars
    chunks = np.array_split(np.abs(pcm) / 32768.0, bars)
    peaks = np.array([c.max() if len(c) else 0.0 for c in chunks])
    top = peaks.max() or 1.0
    return [round(float(v / top), 3) for v in peaks]
