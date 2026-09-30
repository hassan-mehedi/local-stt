"""Meeting tracks on macOS: system audio via a compiled Swift helper (Core
Audio process tap) and the mic via sounddevice. Both stream to WAV on disk.

The helper is compiled from source on first use and cached by source hash,
so it needs the Xcode command line tools (xcode-select --install) once.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import shutil
import signal
import subprocess
import threading
import wave
from pathlib import Path

from ..config import CACHE_DIR

log = logging.getLogger(__name__)

HELPER_SOURCE = Path(__file__).parent / "macos" / "system_audio_capture.swift"
HELPER_DIR = CACHE_DIR / "bin"
MIC_RATE = 16000


def helper_path() -> Path:
    digest = hashlib.sha256(HELPER_SOURCE.read_bytes()).hexdigest()[:12]
    return HELPER_DIR / f"system-audio-capture-{digest}"


def ensure_helper() -> Path:
    binary = helper_path()
    if binary.exists():
        return binary
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        raise RuntimeError(
            "Recording system audio needs the Swift compiler once. Install the "
            "Xcode command line tools with: xcode-select --install"
        )
    HELPER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = binary.with_suffix(".tmp")
    log.info("compiling the system audio helper (one time)...")
    proc = subprocess.run(
        [swiftc, "-O", "-swift-version", "5", str(HELPER_SOURCE), "-o", str(tmp)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"compiling {HELPER_SOURCE.name} failed:\n{proc.stderr.strip()}")
    tmp.replace(binary)
    return binary


class MacSystemAudioRecorder:
    """Records everything the Mac plays (the 'Them' track) until stopped."""

    def __init__(self, dest: Path):
        self.dest = dest
        self.peak: float | None = None  # set on stop; 0.0 means silence
        self._proc: subprocess.Popen | None = None

    def start(self, timeout: float = 10.0) -> None:
        """Returns once audio flows, so a track started after this one
        lines up with it (the helper takes ~2s to set up the tap)."""
        # start_new_session: terminal Ctrl+C must not reach the helper;
        # shutdown is owned by stop()
        self._proc = subprocess.Popen(
            [str(ensure_helper()), str(self.dest)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        first_line: queue.Queue[str] = queue.Queue()
        threading.Thread(
            target=lambda: first_line.put(self._proc.stdout.readline()), daemon=True
        ).start()
        try:
            line = first_line.get(timeout=timeout)
        except queue.Empty:
            line = ""
        if not line.startswith("ready"):
            self._proc.kill()
            _, err = self._proc.communicate()
            self._proc = None
            reason = err.strip() or f"no audio within {timeout:.0f}s"
            raise RuntimeError(f"system audio capture did not start: {reason}")

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        if self._proc is None:
            return
        proc, self._proc = self._proc, None
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"system audio capture failed: {err.strip() or f'exit {proc.returncode}'}"
            )
        for line in out.splitlines():
            if line.startswith("peak "):
                self.peak = float(line.split()[1])
        if self.peak == 0.0:
            log.warning(
                "system audio track is silent. If audio was playing, allow "
                "System Settings > Privacy & Security > Screen & System Audio "
                "Recording > System Audio Recording Only for the app running stt"
            )


class MicWavRecorder:
    """Default mic to a 16kHz mono WAV. The audio callback only queues
    blocks; a writer thread does the disk IO."""

    def __init__(self, dest: Path, device: int | str | None = None):
        self.dest = dest
        self.device = device
        self._stream = None
        self._blocks: queue.Queue[bytes | None] = queue.Queue()
        self._writer: threading.Thread | None = None

    def start(self) -> None:
        import sounddevice as sd

        def callback(indata, frames, time_info, status):
            if status:
                log.debug("mic status: %s", status)
            self._blocks.put(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=MIC_RATE, channels=1, dtype="int16",
            device=self.device, callback=callback,
        )
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._writer.start()
        self._stream.start()

    def _write(self) -> None:
        with wave.open(str(self.dest), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(MIC_RATE)
            while (block := self._blocks.get()) is not None:
                w.writeframes(block)

    @property
    def running(self) -> bool:
        return self._stream is not None

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._blocks.put(None)
        self._writer.join()
