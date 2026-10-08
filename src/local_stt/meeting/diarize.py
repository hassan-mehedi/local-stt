"""Optional pyannote diarization of the 'Them' track into 'Them 1', 'Them 2', ...
Needs the [diarize] extra and a HuggingFace token with the gated models accepted."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path

from ..engine.backend import Segment

log = logging.getLogger(__name__)

PIPELINE = "pyannote/speaker-diarization-community-1"

GATED_MODELS_HELP = (
    "Diarization needs a HuggingFace token with access to the gated pyannote "
    "models.\n"
    "  1. Accept the conditions at:\n"
    "       https://huggingface.co/pyannote/speaker-diarization-community-1\n"
    "  2. Create a token at https://huggingface.co/settings/tokens\n"
    "  3. Put it in ~/.config/local-stt/config.toml:\n"
    "       [diarize]\n"
    '       hf_token = "hf_..."\n'
    "     (or export HF_TOKEN)"
)


@dataclass
class Turn:
    start: float
    end: float
    label: str  # raw pyannote label, e.g. SPEAKER_00


def diarize_wav(path: Path, hf_token: str | None = None) -> list[Turn]:
    """Run pyannote speaker diarization on a wav file."""
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        raise RuntimeError(
            "pyannote.audio is not installed. Install the diarize extra:\n"
            "  uv tool install --editable '.[cuda,diarize]' --overrides overrides.txt"
        ) from None

    token = hf_token or os.environ.get("HF_TOKEN") or None
    try:
        pipeline = Pipeline.from_pretrained(PIPELINE, token=token)
    except Exception as e:
        raise RuntimeError(f"Could not load pyannote pipeline: {e}\n\n{GATED_MODELS_HELP}") from e
    if pipeline is None:
        raise RuntimeError(GATED_MODELS_HELP)

    try:
        import torch

        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
    except Exception:
        log.warning("could not move diarization to GPU; using CPU", exc_info=True)

    output = pipeline(str(path))
    # exclusive diarization allows one speaker at a time, which maps cleanly
    # onto transcript segments
    annotation = getattr(output, "exclusive_speaker_diarization", None)
    if annotation is None:
        annotation = getattr(output, "speaker_diarization", output)
    return [
        Turn(start=turn.start, end=turn.end, label=label)
        for turn, _, label in annotation.itertracks(yield_label=True)
    ]


def assign_speakers(
    segments: list[Segment], turns: list[Turn], prefix: str = "Them"
) -> list[Segment]:
    """Relabels segments by largest overlap with the turns, numbered by first
    appearance. With one speaker or none, the original labels stay."""
    raw_labels = sorted({t.label for t in turns}, key=lambda label: min(
        t.start for t in turns if t.label == label
    ))
    if len(raw_labels) < 2:
        return segments
    names = {raw: f"{prefix} {i + 1}" for i, raw in enumerate(raw_labels)}

    out = []
    for seg in segments:
        overlap: dict[str, float] = {}
        for t in turns:
            o = min(seg.end, t.end) - max(seg.start, t.start)
            if o > 0:
                overlap[t.label] = overlap.get(t.label, 0.0) + o
        if overlap:
            best = max(overlap, key=overlap.get)
            out.append(replace(seg, speaker=names[best]))
        else:
            out.append(seg)
    return out
