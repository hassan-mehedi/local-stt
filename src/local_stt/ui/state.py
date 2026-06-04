"""Runtime discovery of the settings server: ~/.cache/local-stt/ui.json.

The tray writes {url, port, token} here when it starts the HTTP server, so
`stt settings` can find and open the right authenticated URL.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..config import CACHE_DIR

UI_STATE_PATH = CACHE_DIR / "ui.json"


def write_state(port: int, token: str) -> str:
    UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{port}/?token={token}"
    UI_STATE_PATH.write_text(json.dumps({"port": port, "token": token, "url": url}))
    os.chmod(UI_STATE_PATH, 0o600)  # token is a secret
    return url


def read_state() -> dict | None:
    try:
        return json.loads(UI_STATE_PATH.read_text())
    except (OSError, ValueError):
        return None


def clear_state() -> None:
    UI_STATE_PATH.unlink(missing_ok=True)
