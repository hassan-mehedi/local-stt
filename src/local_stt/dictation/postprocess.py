"""Clean transcribed text before emitting. Whisper already punctuates and
capitalizes; we only normalize whitespace."""

from __future__ import annotations

import re


def postprocess(text: str, append_space: bool = True) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if text and append_space:
        text += " "
    return text
