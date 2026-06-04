"""Emit transcribed text into the focused window.

X11:     xdotool type / xclip + Ctrl+V
Wayland: wtype (or ydotool) / wl-copy + paste keystroke
The right backend is picked per session type at startup.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from abc import ABC, abstractmethod

from .listeners import is_wayland

log = logging.getLogger(__name__)


def _require(binary: str, hint: str) -> None:
    if not shutil.which(binary):
        raise RuntimeError(f"'{binary}' is required for this output mode. {hint}")


class TextOutput(ABC):
    @abstractmethod
    def emit(self, text: str) -> None: ...


# -- X11 ------------------------------------------------------------------------


class TypeOutput(TextOutput):
    """Simulated typing via xdotool. --clearmodifiers because the user may
    still be releasing the hotkey when typing starts; small --delay because
    some apps drop events at delay 0."""

    def __init__(self):
        _require("xdotool", "Install it with: sudo apt install xdotool")

    def emit(self, text: str) -> None:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", text],
            check=True,
        )


class ClipboardOutput(TextOutput):
    """Set the clipboard and send Ctrl+V. Faster for long text; clobbers
    the clipboard."""

    def __init__(self):
        _require("xclip", "Install it with: sudo apt install xclip")
        _require("xdotool", "Install it with: sudo apt install xdotool")

    def emit(self, text: str) -> None:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode(),
            check=True,
        )
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
            check=True,
        )


# -- Wayland ----------------------------------------------------------------------


class WtypeOutput(TextOutput):
    """Virtual-keyboard typing via wtype (wlroots/KDE; not GNOME)."""

    def __init__(self):
        _require("wtype", "Install it with: sudo apt install wtype")

    def emit(self, text: str) -> None:
        subprocess.run(["wtype", "-d", "12", "--", text], check=True)


class YdotoolOutput(TextOutput):
    """Typing via ydotool (needs the ydotoold daemon running)."""

    def __init__(self):
        _require("ydotool", "Install it with: sudo apt install ydotool")

    def emit(self, text: str) -> None:
        subprocess.run(
            ["ydotool", "type", "--key-delay", "12", "--", text], check=True
        )


class WaylandClipboardOutput(TextOutput):
    """wl-copy + a Ctrl+V keystroke (wtype if available, else manual paste)."""

    def __init__(self):
        _require("wl-copy", "Install it with: sudo apt install wl-clipboard")
        self._can_paste = bool(shutil.which("wtype"))
        if not self._can_paste:
            log.warning(
                "wtype not found — text will be copied; paste manually with Ctrl+V"
            )

    def emit(self, text: str) -> None:
        subprocess.run(["wl-copy"], input=text.encode(), check=True)
        if self._can_paste:
            subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], check=True)


# -- factory --------------------------------------------------------------------------


def make_output(mode: str) -> TextOutput:
    wayland = is_wayland()
    if mode == "type":
        if not wayland:
            return TypeOutput()
        if shutil.which("wtype"):
            return WtypeOutput()
        if shutil.which("ydotool"):
            return YdotoolOutput()
        raise RuntimeError(
            "No Wayland typing tool found. Install one of:\n"
            "  sudo apt install wtype        (wlroots/KDE compositors)\n"
            "  sudo apt install ydotool      (any compositor; needs ydotoold)\n"
            "or set output = \"clipboard\" in the config."
        )
    if mode == "clipboard":
        return WaylandClipboardOutput() if wayland else ClipboardOutput()
    raise ValueError(f"Unknown output mode: {mode!r} (expected 'type' or 'clipboard')")
