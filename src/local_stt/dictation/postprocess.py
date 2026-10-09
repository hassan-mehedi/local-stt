"""Clean transcribed text before emitting: whitespace, filler sounds and
stuttered words. Whisper and Parakeet already punctuate and capitalize."""

from __future__ import annotations

import re

_FILLER = r"(?<![\w'-])(?:u+h+m*|u+m+|e+r+m*|h+m+|m{2,})(?![\w'-])[,.;]?"
_FILLERS = re.compile(rf"\s*{_FILLER}", re.IGNORECASE)
_STUTTER = re.compile(r"\b(\w+)(?:\s+\1\b)+", re.IGNORECASE)
# repeats that are often real grammar: "I know that that is wrong"
_REAL_REPEATS = {"that", "had", "is"}


def postprocess(text: str, append_space: bool = True) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if text and append_space:
        text += " "
    return text


def drop_fillers(text: str) -> str:
    """Removes um/uh/erm/hmm and a word said twice in a row."""
    # a capitalized filler opened a sentence, so the word after it now does
    text = _FILLERS.sub(lambda m: "\0" if m.group(0).lstrip()[0].isupper() else "", text)
    text = re.sub(r"\0+\s*(\w)", lambda m: " " + m.group(1).upper(), text).replace("\0", "")
    text = _STUTTER.sub(
        lambda m: m.group(0) if m.group(1).lower() in _REAL_REPEATS else m.group(1), text
    )
    return re.sub(r"\s+", " ", text).strip()
