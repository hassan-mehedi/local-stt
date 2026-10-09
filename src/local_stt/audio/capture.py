"""Microphone capture: start/stop, returns 16kHz mono float32 PCM."""

from __future__ import annotations

import faulthandler
import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

TARGET_RATE = 16000
STOP_TIMEOUT_S = 0.5


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
            frames: list[np.ndarray] = []
            self._frames = frames

            def callback(indata, n, time_info, status):
                if frames is not self._frames:
                    return  # a stopped stream that is still closing
                if status:
                    log.debug("capture status: %s", status)
                block = indata[:, 0].copy()
                frames.append(block)
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
            stream, self._stream = self._stream, None
            if stream is None:
                return np.zeros(0, dtype=np.float32)
            frames, rate = self._frames, self._rate
        # CoreAudio can hang in stop, and the caller may be the hotkey's event tap
        closer = threading.Thread(target=_close, args=(stream,), daemon=True)
        closer.start()
        closer.join(STOP_TIMEOUT_S)
        if closer.is_alive():
            log.warning("the microphone did not stop in %.1fs; thread stacks follow", STOP_TIMEOUT_S)
            faulthandler.dump_traceback(all_threads=True)
        with self._lock:
            if self._frames is frames:
                self._frames = []
        pcm = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
        if rate != TARGET_RATE and len(pcm):
            import soxr

            pcm = soxr.resample(pcm, rate, TARGET_RATE)
        return pcm.astype(np.float32, copy=False)


def _close(stream) -> None:
    stream.stop()
    stream.close()
