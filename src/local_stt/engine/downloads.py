"""Model downloads in the background, with a status the app polls."""

from __future__ import annotations

import logging
import threading

from . import models

log = logging.getLogger(__name__)


class Downloads:
    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, str] = {}  # model -> "running"|"done"|"error: ..."

    def status(self) -> dict[str, str]:
        with self._lock:
            return dict(self._state)

    def start(self, name: str) -> None:
        models.model_dir(name)  # rejects unknown names before a thread starts
        with self._lock:
            if self._state.get(name) == "running":
                return
            self._state[name] = "running"
        threading.Thread(target=self._run, args=(name,), daemon=True).start()

    def _run(self, name: str) -> None:
        try:
            models.download(name)
            with self._lock:
                self._state[name] = "done"
        except Exception as e:
            log.exception("download failed: %s", name)
            with self._lock:
                self._state[name] = f"error: {e}"


downloads = Downloads()
