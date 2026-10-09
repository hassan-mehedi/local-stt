"""Transcribe the two meeting tracks and merge into one labeled transcript."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from ..engine.backend import AsrBackend, Transcript, TranscribeOptions

SETTINGS_FILE = "session.json"


def choose_model(cfg, model: str | None = None, language: str | None = None) -> tuple[str, str]:
    """(model, language) for a meeting: arguments win, then [meeting], then [model].
    Given only a language the model lacks, it picks a downloaded model with it."""
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
            hint = models.download_hint("bengali-whisper-medium") if language == "bn" else ""
            raise ValueError(f"No downloaded model transcribes {language!r}. {hint}".strip())
        model = fallback
    return model, language


def save_settings(session_dir: Path, model: str, language: str, **extra) -> None:
    """extra: e.g. title and started_at, which the app shows."""
    (session_dir / SETTINGS_FILE).write_text(
        json.dumps({"model": model, "language": language, **extra}, indent=2) + "\n"
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
    """Interleave the Me/Them tracks by timestamp. The recorder starts both
    tracks at the same moment, so their timestamps line up."""
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
