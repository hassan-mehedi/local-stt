"""Tray icon PNGs for AppIndicator: a white mic with a status dot (green idle,
red recording, amber transcribing), drawn large and downscaled."""

from __future__ import annotations

from pathlib import Path

from ..config import CACHE_DIR

ICON_DIR = CACHE_DIR / "icons"
SIZE = 128  # AppIndicator picks the panel size; render large and let it scale

DOT = {
    "idle": (64, 200, 110, 255),
    "recording": (235, 64, 64, 255),
    "transcribing": (242, 176, 44, 255),
}


def _draw(state: str):
    from PIL import Image, ImageDraw

    u = 8  # supersample; all coordinates below are in a 128px design grid
    S = SIZE * u
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def px(*xs):
        return [int(x * u) for x in xs]

    # symbolic-ish, matches the panel's other icons; dimmed when off
    fg = (168, 174, 182, 255) if state == "off" else (230, 234, 240, 255)
    w = 9 * u  # line weight for cradle/stem

    # mic body: a filled vertical capsule (reads clearly at panel size)
    d.rounded_rectangle(px(50, 16, 78, 64), radius=14 * u, fill=fg)
    # cradle: lower-half arc hugging the body (PIL: 0°=3 o'clock, 180°=9)
    d.arc(px(38, 28, 90, 80), start=0, end=180, fill=fg, width=w)
    # stem + base
    d.line(px(64, 80, 64, 92), fill=fg, width=w)
    d.line(px(50, 92, 78, 92), fill=fg, width=w)

    dot = DOT.get(state)
    if dot:
        # status dot, bottom-right, with a dark rim for contrast on any panel
        d.ellipse(
            px(86, 86, 120, 120), fill=dot, outline=(28, 30, 34, 255), width=3 * u
        )

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def ensure_icons() -> Path:
    """Render all state icons into ICON_DIR (idempotent); return the dir."""
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for state in ("off", "idle", "recording", "transcribing"):
        _draw(state).save(ICON_DIR / f"local-stt-{state}.png")
    return ICON_DIR


def icon_name(state: str) -> str:
    return f"local-stt-{state}"
