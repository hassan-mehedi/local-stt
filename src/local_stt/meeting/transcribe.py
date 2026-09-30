"""Transcribe the two meeting tracks and merge into one labeled transcript."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from ..engine.backend import AsrBackend, Transcript, TranscribeOptions

SETTINGS_FILE = "session.json"


def choose_model(cfg, model: str | None = None, language: str | None = None) -> tuple[str, str]:
    """(model, language) for a meeting. Explicit arguments win, then
    [meeting], then [model]. Asking for a language the chosen model lacks,
    with no model given, picks a downloaded model that has it: `--language
    bn` finds bengali-whisper-medium."""
    from ..engine import models

    if language is None:
        language = cfg.meeting.language or cfg.model.language
    if model:
        return model, language
    model = cfg.meeting.model or cfg.model.name
    langs = models.spec(model).languages
    if language and langs is not None and language not in langs:
        fallback = models.best_for_language(language)
        if fallback is None:
            raise ValueError(
                f"No downloaded model transcribes {language!r}. For Bengali run: "
                "stt models download bengali-whisper-medium"
            )
        model = fallback
    return model, language


def save_settings(session_dir: Path, model: str, language: str) -> None:
    (session_dir / SETTINGS_FILE).write_text(
        json.dumps({"model": model, "language": language}, indent=2) + "\n"
    )


def load_settings(session_dir: Path) -> dict:
    try:
        return json.loads((session_dir / SETTINGS_FILE).read_text())
    except (OSError, ValueError):
        return {}


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
