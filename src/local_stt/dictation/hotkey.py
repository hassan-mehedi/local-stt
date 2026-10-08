"""Hotkey string parsing: '<alt>+t' -> (modifiers, trigger key). Kept free of
pynput so tests run headless; the daemon resolves the pynput keys."""

from __future__ import annotations

import re
from dataclasses import dataclass

# canonical modifier names
_MOD_ALIASES = {
    "super": "super",
    "win": "super",
    "cmd": "super",
    "meta": "super",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
}

MODIFIERS = frozenset(_MOD_ALIASES.values())


@dataclass(frozen=True)
class Hotkey:
    modifiers: frozenset[str]  # subset of MODIFIERS
    trigger: str  # single char ('z') or named key ('f9', 'space')


def parse_hotkey(spec: str) -> Hotkey:
    """Parse e.g. '<alt>+t', '<ctrl>+<alt>+d', '<f9>'."""
    parts = [p.strip() for p in spec.strip().lower().split("+") if p.strip()]
    if not parts:
        raise ValueError(f"Empty hotkey spec: {spec!r}")

    mods: set[str] = set()
    trigger: str | None = None
    for part in parts:
        name = re.fullmatch(r"<(\w+)>", part)
        name = name.group(1) if name else part
        if name in _MOD_ALIASES:
            mods.add(_MOD_ALIASES[name])
        elif trigger is None:
            trigger = name
        else:
            raise ValueError(f"Hotkey {spec!r} has more than one non-modifier key")
    if trigger is None:
        raise ValueError(
            f"Hotkey {spec!r} needs a non-modifier trigger key, e.g. '<alt>+t'"
        )
    return Hotkey(modifiers=frozenset(mods), trigger=trigger)
