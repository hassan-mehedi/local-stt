"""Desktop notifications and opening files/URLs, per platform."""

from __future__ import annotations

import shutil
import subprocess
import sys

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


def notify(summary: str, body: str = "", timeout_ms: int = 2500) -> None:
    """Fire-and-forget; macOS ignores the timeout."""
    cmd = notify_command(summary, body, timeout_ms)
    if cmd:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_target(target: str) -> None:
    """Open a folder, file or URL with the default app."""
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
