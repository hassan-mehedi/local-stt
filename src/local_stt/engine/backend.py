"""ASR backend interface. All callers talk to ASR through this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np


@dataclass
class Word:
    start: float
    end: float
    word: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None


@dataclass
class Transcript:
    segments: list[Segment]
    language: str
    duration: float  # seconds of input audio
    model: str

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())


@dataclass
class TranscribeOptions:
    language: str | None = None  # None = auto-detect
    task: str = "transcribe"
    batched: bool = False  # batched pipeline for long files
    batch_size: int = 8
    word_timestamps: bool = False
    # min silence (ms) for VAD splitting: short for dictation, longer for files
    vad_min_silence_ms: int = 500
    progress_cb: Callable[[float, float], None] | None = None  # (done_s, total_s)


class AsrBackend(ABC):
    @abstractmethod
    def transcribe_file(self, path: Path, opts: TranscribeOptions) -> Transcript: ...

    @abstractmethod
    def transcribe_audio(
        self, pcm: np.ndarray, sample_rate: int, opts: TranscribeOptions
    ) -> Transcript: ...

    @abstractmethod
    def unload(self) -> None:
        """Free VRAM."""
