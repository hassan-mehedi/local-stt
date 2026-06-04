"""Meeting session recording: mic + system audio as two separate tracks."""

from __future__ import annotations

import os
import re
import signal
from datetime import datetime
from pathlib import Path

from ..audio.system_audio import PwRecorder
from ..config import CACHE_DIR

PIDFILE = CACHE_DIR / "meeting.pid"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "meeting"


class MeetingRecorder:
    """Records mic ('Me') and sink monitor ('Them') into a session directory.

    Layout: <output_dir>/<YYYY-MM-DD>-<title>/raw/{mic,system}.wav
    Both tracks stream to disk while recording — nothing is held in RAM.
    """

    def __init__(self, output_dir: Path, title: str, when: datetime):
        self.title = title
        self.session_dir = output_dir / f"{when:%Y-%m-%d}-{slugify(title)}"
        n = 2
        while self.session_dir.exists():  # don't clobber an earlier session
            self.session_dir = output_dir / f"{when:%Y-%m-%d}-{slugify(title)}-{n}"
            n += 1
        raw = self.session_dir / "raw"
        self.mic_path = raw / "mic.wav"
        self.system_path = raw / "system.wav"
        self._mic = PwRecorder(self.mic_path, capture_sink=False)
        self._system = PwRecorder(self.system_path, capture_sink=True)

    def start(self) -> None:
        self.mic_path.parent.mkdir(parents=True, exist_ok=True)
        self._mic.start()
        try:
            self._system.start()
        except Exception:
            self._mic.stop()
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
