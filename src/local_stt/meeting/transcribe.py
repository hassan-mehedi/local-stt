"""Transcribe the two meeting tracks and merge into one labeled transcript."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Callable

from ..engine.backend import AsrBackend, Transcript, TranscribeOptions, build_backend
from ..export import export

log = logging.getLogger(__name__)

SETTINGS_FILE = "session.json"


def choose_model(cfg, model: str | None = None, language: str | None = None) -> tuple[str, str]:
    """(model, language) for a meeting: arguments win, then [meeting], then [model].
    Given only a language the model lacks, it picks a downloaded model with it."""
    from ..engine import models

    if language is None:
        language = cfg.meeting.language or cfg.model.language
    if model:
        return model, language
    model = cfg.meeting.model or cfg.model.name
    langs = models.spec(model).languages
    if language and langs is not None and language not in langs:
        fallback = models.best_for_language(language)
        if fallback is None:
            hint = models.download_hint("bengali-whisper-medium") if language == "bn" else ""
            raise ValueError(f"No downloaded model transcribes {language!r}. {hint}".strip())
        model = fallback
    return model, language


def save_settings(session_dir: Path, model: str, language: str, **extra) -> None:
    """extra: e.g. title and started_at, which the app shows."""
    (session_dir / SETTINGS_FILE).write_text(
        json.dumps({"model": model, "language": language, **extra}, indent=2) + "\n"
    )


def load_settings(session_dir: Path) -> dict:
    try:
        return json.loads((session_dir / SETTINGS_FILE).read_text())
    except (OSError, ValueError):
        return {}


def label(transcript: Transcript, speaker: str) -> Transcript:
    return replace(
        transcript,
        segments=[replace(s, speaker=speaker) for s in transcript.segments],
    )


def merge(mine: Transcript, theirs: Transcript) -> Transcript:
    """Interleave the Me/Them tracks by timestamp. The recorder starts both
    tracks at the same moment, so their timestamps line up."""
    segments = sorted(mine.segments + theirs.segments, key=lambda s: (s.start, s.end))
    return Transcript(
        segments=segments,
        language=mine.language or theirs.language,
        duration=max(mine.duration, theirs.duration),
        model=mine.model,
    )


def transcribe_meeting(
    mic_wav: Path,
    system_wav: Path,
    backend: AsrBackend,
    opts: TranscribeOptions,
) -> Transcript:
    mine = label(backend.transcribe_file(mic_wav, opts), "Me")
    theirs = label(backend.transcribe_file(system_wav, opts), "Them")
    return merge(mine, theirs)


def transcribe_session(
    session_dir: Path, title: str, cfg, model: str | None = None, language: str | None = None,
    diarize: bool = False, backend: AsrBackend | None = None,
    progress_cb: Callable[[float, float], None] | None = None,
) -> list[Path]:
    """Transcribes a recorded session into transcript.md, .json and .srt next to
    its tracks. A given backend (the dictation model) is used instead of a new one."""
    mic_wav = session_dir / "raw" / "mic.wav"
    system_wav = session_dir / "raw" / "system.wav"
    for p in (mic_wav, system_wav):
        if not p.exists():
            raise FileNotFoundError(f"{p} not found; is this a meeting session folder?")

    saved = load_settings(session_dir)
    model, language = choose_model(
        cfg, model or saved.get("model"), language if language is not None else saved.get("language")
    )
    owns_backend = backend is None
    if backend is None:
        backend = build_backend(cfg, model)
    log.info("transcribing %s with %s, language %s", session_dir.name, model, language or "auto")
    opts = TranscribeOptions(language=language or None, batched=True, progress_cb=progress_cb)
    transcript = transcribe_meeting(mic_wav, system_wav, backend, opts)

    if diarize:
        if owns_backend:
            backend.unload()  # free VRAM before loading pyannote
        transcript = _diarize(transcript, system_wav, cfg.diarize.hf_token or None)

    written = []
    for fmt in ("md", "json", "srt"):
        dest = session_dir / f"transcript.{fmt}"
        export(transcript, fmt, dest, title=title)
        written.append(dest)
    return written


def _diarize(transcript: Transcript, system_wav: Path, hf_token: str | None) -> Transcript:
    from .diarize import assign_speakers, diarize_wav

    log.info("diarizing the Them track...")
    turns = diarize_wav(system_wav, hf_token=hf_token)
    them = [s for s in transcript.segments if s.speaker == "Them"]
    relabeled = {id(s): r for s, r in zip(them, assign_speakers(them, turns))}
    transcript = replace(transcript, segments=[relabeled.get(id(s), s) for s in transcript.segments])
    n = len({s.speaker for s in transcript.segments if s.speaker != "Me"})
    log.info("found %d remote speaker(s)", n)
    return transcript
