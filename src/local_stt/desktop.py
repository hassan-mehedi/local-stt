"""Desktop notifications and opening files/URLs, per platform."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# argv keeps quotes in the text from breaking the AppleScript
_OSASCRIPT_NOTIFY = [
    "-e", "on run argv",
    "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
    "-e", "end run",
]


def notify_command(summary: str, body: str = "", timeout_ms: int = 2500) -> list[str] | None:
    if sys.platform == "darwin":
        return ["osascript", *_OSASCRIPT_NOTIFY, summary, body]
    if shutil.which("notify-send"):
        return ["notify-send", "-a", "local-stt", "-t", str(timeout_ms), summary, body]
    return None


_notify_handler = None


def set_notify_handler(handler) -> None:
    """Sends notify() calls to handler(summary, body) instead of the desktop.
    The app window shows them itself."""
    global _notify_handler
    _notify_handler = handler


def notify(summary: str, body: str = "", timeout_ms: int = 2500) -> None:
    """Fire-and-forget; macOS ignores the timeout."""
    if _notify_handler is not None:
        _notify_handler(summary, body)
        return
    cmd = notify_command(summary, body, timeout_ms)
    if cmd:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_target(target: str) -> None:
    """Open a folder, file or URL with the default app."""
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def app_bundle() -> Path | None:
    """The local-stt.app this runs from, or None for a source install."""
    return next((p for p in Path(__file__).resolve().parents if p.suffix == ".app"), None)


def permission_hint(pane: str) -> str:
    """Where to allow a macOS privacy permission, for the app or a source install."""
    if app_bundle():
        return (
            f"Turn on local-stt in System Settings > Privacy & Security > {pane}, "
            "then quit and reopen local-stt. If it is on already, remove it with "
            "the minus button and allow it again."
        )
    return (
        f"Allow it in System Settings > Privacy & Security > {pane} (the terminal "
        f"you run stt from, or {os.path.realpath(sys.executable)} when it runs as "
        "a login agent), then restart."
    )


def relaunch() -> None:
    """Opens the app again once this process has exited."""
    bundle = app_bundle()
    if bundle is None:
        raise RuntimeError("relaunch needs local-stt.app")
    script = 'while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; open "$0"'
    subprocess.Popen(
        ["/bin/sh", "-c", script, str(bundle), str(os.getpid())], start_new_session=True
    )
