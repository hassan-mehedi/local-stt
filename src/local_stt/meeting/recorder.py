"""Meeting session recording: mic + system audio as two separate tracks."""

from __future__ import annotations

import os
import re
import signal
import sys
from datetime import datetime
from pathlib import Path

from ..config import CACHE_DIR

PIDFILE = CACHE_DIR / "meeting.pid"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "meeting"


def _track_recorders(mic_path: Path, system_path: Path):
    if sys.platform == "darwin":
        from ..audio.mac_audio import MacSystemAudioRecorder, MicWavRecorder

        return MicWavRecorder(mic_path), MacSystemAudioRecorder(system_path)
    from ..audio.system_audio import PwRecorder

    return PwRecorder(mic_path, capture_sink=False), PwRecorder(system_path, capture_sink=True)


class MeetingRecorder:
    """Records mic ('Me') and system audio ('Them') straight to disk, into
    <output_dir>/<YYYY-MM-DD>-<title>/raw/{mic,system}.wav."""

    def __init__(self, output_dir: Path, title: str, when: datetime):
        self.title = title
        # what to transcribe with; the tray sets these before start()
        self.model: str | None = None
        self.language = ""
        self.session_dir = output_dir / f"{when:%Y-%m-%d}-{slugify(title)}"
        n = 2
        while self.session_dir.exists():  # don't clobber an earlier session
            self.session_dir = output_dir / f"{when:%Y-%m-%d}-{slugify(title)}-{n}"
            n += 1
        raw = self.session_dir / "raw"
        self.mic_path = raw / "mic.wav"
        self.system_path = raw / "system.wav"
        self._mic, self._system = _track_recorders(self.mic_path, self.system_path)

    def start(self) -> None:
        # system first: the macOS helper blocks until its audio flows, so the
        # mic then starts at the same moment and the tracks line up
        self.mic_path.parent.mkdir(parents=True, exist_ok=True)
        self._system.start()
        try:
            self._mic.start()
        except Exception:
            self._system.stop()
            raise
        PIDFILE.parent.mkdir(parents=True, exist_ok=True)
        PIDFILE.write_text(str(os.getpid()))

    def stop(self) -> tuple[Path, Path]:
        try:
            self._mic.stop()
        finally:
            self._system.stop()
        PIDFILE.unlink(missing_ok=True)
        return self.mic_path, self.system_path


def signal_running_session() -> bool:
    """Used by `stt meeting stop`: SIGINT the recording process if any."""
    if not PIDFILE.exists():
        return False
    try:
        pid = int(PIDFILE.read_text().strip())
        os.kill(pid, signal.SIGINT)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        PIDFILE.unlink(missing_ok=True)
        return False
