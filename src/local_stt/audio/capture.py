"""Microphone capture: start/stop, returns 16kHz mono float32 PCM."""

from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

TARGET_RATE = 16000


class Recorder:
    """Records the default input device at 16 kHz, or resampled to it on stop. The
    callback only appends, so it never blocks; on_level gets each block's RMS."""

    def __init__(self, device: int | str | None = None, on_level=None):
        self.device = device
        self.on_level = on_level
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._rate = TARGET_RATE
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return
            self._frames = []

            def callback(indata, frames, time_info, status):
                if status:
                    log.debug("capture status: %s", status)
                block = indata[:, 0].copy()
                self._frames.append(block)
                if self.on_level is not None and len(block):
                    self.on_level(float(np.sqrt(np.mean(block * block))))

            try:
                self._stream = sd.InputStream(
                    samplerate=TARGET_RATE, channels=1, dtype="float32",
                    device=self.device, callback=callback,
                )
                self._rate = TARGET_RATE
            except sd.PortAudioError:
                # device refuses 16kHz; use its default rate and resample later
                info = sd.query_devices(self.device, kind="input")
                self._rate = int(info["default_samplerate"])
                self._stream = sd.InputStream(
                    samplerate=self._rate, channels=1, dtype="float32",
                    device=self.device, callback=callback,
                )
            self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return 16kHz mono PCM."""
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            pcm = (
                np.concatenate(self._frames)
                if self._frames
                else np.zeros(0, dtype=np.float32)
            )
            self._frames = []
        if self._rate != TARGET_RATE and len(pcm):
            import soxr

            pcm = soxr.resample(pcm, self._rate, TARGET_RATE)
        return pcm.astype(np.float32, copy=False)
