"""faster-whisper (CTranslate2) backend for the Whisper models."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import models
from .backend import AsrBackend, Segment, Transcript, TranscribeOptions, Word

log = logging.getLogger(__name__)


def _cpu_threads() -> int:
    """Performance cores on Apple Silicon (8 threads: 4.1s vs 5.7s on an M4 Pro
    Bengali clip); 0 keeps the library default elsewhere."""
    if sys.platform != "darwin":
        return 0
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.perflevel0.physicalcpu"],
            capture_output=True, text=True, check=True,
        ).stdout
        return int(out.strip())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return 0


class FasterWhisperBackend(AsrBackend):
    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        device: str = "auto",
        compute_type: str = "float16",
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._batched = None
        # CTranslate2 models aren't safe for concurrent transcribe calls;
        # serialize them (the tray shares one backend across dictation +
        # meeting transcription).
        self._infer_lock = threading.Lock()

    def _resolve_device(self) -> tuple[str, str]:
        if self.device == "cuda" or (self.device == "auto" and models.cuda_available()):
            return "cuda", self.compute_type
        # CPU: float16 is unsupported; int8 is the sane default
        ct = "int8" if "float16" in self.compute_type else self.compute_type
        return "cpu", ct

    def load(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        if not models.is_downloaded(self.model_name):
            raise FileNotFoundError(
                f"Model '{self.model_name}' is not downloaded. "
                + models.download_hint(self.model_name)
            )
        models.preload_cuda_libraries()
        device, compute_type = self._resolve_device()
        t0 = time.monotonic()
        try:
            self._model = WhisperModel(
                str(models.model_dir(self.model_name)),
                device=device,
                compute_type=compute_type,
                cpu_threads=_cpu_threads(),
            )
        except (RuntimeError, ValueError) as e:
            if device != "cuda":
                raise
            log.warning("CUDA load failed (%s); falling back to CPU int8", e)
            device, compute_type = "cpu", "int8"
            self._model = WhisperModel(
                str(models.model_dir(self.model_name)),
                device=device,
                compute_type=compute_type,
                cpu_threads=_cpu_threads(),
            )
        log.info(
            "Loaded %s on %s (%s) in %.1fs",
            self.model_name, device, compute_type, time.monotonic() - t0,
        )
        return self._model

    def unload(self) -> None:
        self._model = None
        self._batched = None

    def transcribe_file(self, path: Path, opts: TranscribeOptions) -> Transcript:
        from ..audio.decode import decode_to_pcm

        pcm = decode_to_pcm(path)
        return self.transcribe_audio(pcm, 16000, opts)

    def transcribe_audio(
        self, pcm: np.ndarray, sample_rate: int, opts: TranscribeOptions
    ) -> Transcript:
        if sample_rate != 16000:
            raise ValueError(f"expected 16kHz audio, got {sample_rate}")
        model = self.load()
        duration = len(pcm) / 16000.0
        language = opts.language or None

        kwargs = dict(
            language=language,
            task=opts.task,
            word_timestamps=opts.word_timestamps,
            vad_filter=True,  # hallucination guard: never transcribe non-speech
            vad_parameters=dict(min_silence_duration_ms=opts.vad_min_silence_ms),
        )

        # faster-whisper returns a lazy generator that runs inference as it's
        # iterated, so the lock must cover the whole loop, not just the call.
        with self._infer_lock:
            if opts.batched:
                if self._batched is None:
                    from faster_whisper import BatchedInferencePipeline

                    self._batched = BatchedInferencePipeline(model=model)
                seg_iter, info = self._batched.transcribe(
                    pcm, batch_size=opts.batch_size, **kwargs
                )
            else:
                seg_iter, info = model.transcribe(pcm, **kwargs)

            segments: list[Segment] = []
            for s in seg_iter:
                text = s.text.strip()
                if not text:
                    continue
                words = [
                    Word(start=w.start, end=w.end, word=w.word)
                    for w in (s.words or [])
                ]
                segments.append(
                    Segment(start=s.start, end=s.end, text=text, words=words)
                )
                if opts.progress_cb:
                    opts.progress_cb(min(s.end, duration), duration)

        return Transcript(
            segments=segments,
            language=info.language,
            duration=duration,
            model=self.model_name,
        )
