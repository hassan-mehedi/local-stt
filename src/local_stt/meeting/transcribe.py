"""Transcribe the two meeting tracks and merge into one labeled transcript."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..engine.backend import AsrBackend, Transcript, TranscribeOptions


def label(transcript: Transcript, speaker: str) -> Transcript:
    return replace(
        transcript,
        segments=[replace(s, speaker=speaker) for s in transcript.segments],
    )


def merge(mine: Transcript, theirs: Transcript) -> Transcript:
    """Interleave the Me/Them tracks by timestamp. Both tracks share the
    PipeWire clock, so timestamps are directly comparable."""
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
