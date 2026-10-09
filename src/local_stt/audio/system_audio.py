"""Meeting tracks on Linux via pw-record: both share PipeWire's clock, so they do
not drift, and stream to disk as 16 kHz mono s16 WAV."""

from __future__ import annotations

import logging
import shutil
import signal
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class PwRecorder:
    """One pw-record stream writing a wav file until stopped."""

    def __init__(self, dest: Path, capture_sink: bool):
        """capture_sink=True records what the speakers play (the 'Them'
        track); False records the default mic (the 'Me' track)."""
        self.dest = dest
        self.capture_sink = capture_sink
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        if not shutil.which("pw-record"):
            raise RuntimeError(
                "pw-record is required for meeting recording. "
                "Install it with: sudo apt install pipewire-bin"
            )
        cmd = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16"]
        if self.capture_sink:
            cmd += ["-P", "{ stream.capture.sink = true }"]
        cmd.append(str(self.dest))
        # start_new_session: a terminal Ctrl+C must not reach pw-record; stop()
        # owns its shutdown, not the terminal's process group.
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

    def stop(self) -> None:
        """SIGINT lets pw-record finalize the wav header."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.send_signal(signal.SIGINT)
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        elif self._wav_is_valid():
            # exited before stop() (e.g. a stray SIGINT) but finalized a
            # readable recording. pw-record exits 1 on SIGINT, so the file
            # is the only reliable signal of success
            log.warning(
                "pw-record for %s exited before stop() (rc=%s); recording kept",
                self.dest.name, self._proc.returncode,
            )
        else:
            stderr = (self._proc.stderr.read() or b"").decode().strip()
            raise RuntimeError(
                f"pw-record for {self.dest.name} exited early"
                + (f": {stderr}" if stderr else "")
            )
        self._proc = None

    def _wav_is_valid(self) -> bool:
        import wave

        try:
            with wave.open(str(self.dest)) as w:
                return w.getnframes() > 0
        except (OSError, EOFError, wave.Error):
            return False
