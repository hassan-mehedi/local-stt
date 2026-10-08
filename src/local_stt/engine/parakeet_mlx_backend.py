"""NVIDIA Parakeet on the Apple Silicon GPU via parakeet-mlx."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import models
from .backend import AsrBackend, Segment, Transcript, TranscribeOptions, Word

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# audio longer than this is split into overlapping chunks, which bounds memory
CHUNK_S = 120.0
OVERLAP_S = 15.0


def _words(tokens) -> list[Word]:
    """Join subword tokens into words; a token starting with a space opens one."""
    words: list[Word] = []
    for t in tokens:
        if words and not t.text.startswith(" "):
            w = words[-1]
            words[-1] = Word(start=w.start, end=t.end, word=w.word + t.text)
        else:
            words.append(Word(start=t.start, end=t.end, word=t.text))
    return words


class ParakeetMlxBackend(AsrBackend):
    """Runs all MLX work on one thread: MLX binds streams to the thread that made
    them, and the tray loads and transcribes on different threads."""

    def __init__(self, model_name: str = "parakeet-tdt-0.6b-v3"):
        self.model_name = model_name
        self.spec = models.spec(model_name)
        self._model = None
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    def _on_mlx_thread(self, fn, *args):
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="mlx"
                )
            executor = self._executor
        return executor.submit(fn, *args).result()

    def load(self):
        return self._on_mlx_thread(self._load)

    def _load(self):
        if self._model is not None:
            return self._model
        if reason := models.unavailable_reason(self.model_name):
            raise RuntimeError(f"{self.model_name}: {reason}")
        if not models.is_downloaded(self.model_name):
            raise FileNotFoundError(
                f"Model '{self.model_name}' is not downloaded. "
                + models.download_hint(self.model_name)
            )
        from parakeet_mlx import from_pretrained

        t0 = time.monotonic()
        self._model = from_pretrained(str(models.model_dir(self.model_name)))
        log.info(
            "Loaded %s on mlx (bfloat16) in %.1fs",
            self.model_name, time.monotonic() - t0,
        )
        return self._model

    def unload(self) -> None:
        with self._executor_lock:
            executor, self._executor = self._executor, None
        if executor is None:
            return
        executor.submit(self._unload).result()
        executor.shutdown()

    def _unload(self) -> None:
        self._model = None
        import mlx.core as mx

        mx.clear_cache()

    def is_model_available(self, model: str) -> bool:
        return models.is_downloaded(model)

    def download_model(self, model: str) -> None:
        models.download(model)

    def transcribe_file(self, path: Path, opts: TranscribeOptions) -> Transcript:
        from ..audio.decode import decode_to_pcm

        return self.transcribe_audio(decode_to_pcm(path), SAMPLE_RATE, opts)

    def transcribe_audio(
        self, pcm: np.ndarray, sample_rate: int, opts: TranscribeOptions
    ) -> Transcript:
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"expected 16kHz audio, got {sample_rate}")
        if opts.task != "transcribe":
            raise ValueError(f"{self.model_name} only supports task='transcribe'")
        return self._on_mlx_thread(self._transcribe, pcm, opts)

    def _transcribe(self, pcm: np.ndarray, opts: TranscribeOptions) -> Transcript:
        model = self._load()
        duration = len(pcm) / SAMPLE_RATE
        if duration <= CHUNK_S:
            result = self._run_short(model, pcm)
        else:
            result = self._run_chunked(model, pcm, opts)

        segments = [
            Segment(
                start=s.start,
                end=s.end,
                text=s.text.strip(),
                words=_words(s.tokens) if opts.word_timestamps else [],
            )
            for s in result.sentences
            if s.text.strip()
        ]
        if opts.progress_cb:
            opts.progress_cb(duration, duration)

        languages = self.spec.languages or frozenset()
        language = opts.language or (next(iter(languages)) if len(languages) == 1 else "")
        return Transcript(
            segments=segments, language=language, duration=duration, model=self.model_name
        )

    @staticmethod
    def _mel(model, pcm: np.ndarray):
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        win = model.preprocessor_config.win_length
        if len(pcm) < win:
            pcm = np.pad(pcm, (0, win - len(pcm)))
        return get_logmel(mx.array(pcm, dtype=mx.float32), model.preprocessor_config)

    def _run_short(self, model, pcm: np.ndarray):
        return model.generate(self._mel(model, pcm))[0]

    def _run_chunked(self, model, pcm: np.ndarray, opts: TranscribeOptions):
        """Same overlap-and-merge as parakeet-mlx's own transcribe(), which
        only accepts a file path."""
        from parakeet_mlx.alignment import (
            merge_longest_common_subsequence,
            merge_longest_contiguous,
            sentences_to_result,
            tokens_to_sentences,
        )

        chunk = int(CHUNK_S * SAMPLE_RATE)
        step = chunk - int(OVERLAP_S * SAMPLE_RATE)
        tokens = []
        for start in range(0, len(pcm), step):
            end = min(start + chunk, len(pcm))
            if end - start < model.preprocessor_config.hop_length:
                break
            result = model.generate(self._mel(model, pcm[start:end]))[0]
            offset = start / SAMPLE_RATE
            chunk_tokens = result.tokens
            for t in chunk_tokens:
                t.start += offset
                t.end = t.start + t.duration
            if not tokens:
                tokens = chunk_tokens
            else:
                try:
                    tokens = merge_longest_contiguous(
                        tokens, chunk_tokens, overlap_duration=OVERLAP_S
                    )
                except RuntimeError:
                    tokens = merge_longest_common_subsequence(
                        tokens, chunk_tokens, overlap_duration=OVERLAP_S
                    )
            if opts.progress_cb:
                opts.progress_cb(end / SAMPLE_RATE, len(pcm) / SAMPLE_RATE)
            if end == len(pcm):
                break
        return sentences_to_result(tokens_to_sentences(tokens))
