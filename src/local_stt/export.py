"""Export transcripts to txt / md / srt / vtt / json."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .engine.backend import Transcript

FORMATS = ("txt", "md", "srt", "vtt", "json")


def _ts_clock(seconds: float) -> str:
    """HH:MM:SS for human-facing formats."""
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _ts_srt(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def _ts_vtt(seconds: float) -> str:
    return _ts_srt(seconds).replace(",", ".")


def _line_prefix(seg) -> str:
    return f"{seg.speaker}: " if seg.speaker else ""


def to_txt(t: Transcript) -> str:
    return "\n".join(_line_prefix(s) + s.text for s in t.segments) + "\n"


def to_md(t: Transcript, title: str = "Transcript") -> str:
    lines = [f"# {title}", ""]
    for s in t.segments:
        lines.append(f"[{_ts_clock(s.start)}] {_line_prefix(s)}{s.text}")
    return "\n".join(lines) + "\n"


def to_srt(t: Transcript) -> str:
    blocks = []
    for i, s in enumerate(t.segments, 1):
        blocks.append(
            f"{i}\n{_ts_srt(s.start)} --> {_ts_srt(s.end)}\n{_line_prefix(s)}{s.text}"
        )
    return "\n\n".join(blocks) + "\n"


def to_vtt(t: Transcript) -> str:
    blocks = ["WEBVTT"]
    for s in t.segments:
        blocks.append(
            f"{_ts_vtt(s.start)} --> {_ts_vtt(s.end)}\n{_line_prefix(s)}{s.text}"
        )
    return "\n\n".join(blocks) + "\n"


def to_json(t: Transcript) -> str:
    return json.dumps(asdict(t), ensure_ascii=False, indent=2) + "\n"


_RENDERERS = {
    "txt": lambda t, title: to_txt(t),
    "md": to_md,
    "srt": lambda t, title: to_srt(t),
    "vtt": lambda t, title: to_vtt(t),
    "json": lambda t, title: to_json(t),
}


def export(t: Transcript, fmt: str, dest: Path, title: str) -> Path:
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format {fmt!r} (expected one of {', '.join(FORMATS)})")
    dest.write_text(_RENDERERS[fmt](t, title), encoding="utf-8")
    return dest
