"""Local settings server: one static page + a small JSON API.

Bound to 127.0.0.1 with a per-session token. The tray passes a `controller`
exposing live actions (daemon status/restart, model download/switch); without
one, the server still edits config.toml (the page shows "daemon: off").
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import Config, load_config, save_config
from ..engine import models
from .state import clear_state, write_state

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

class Controller:
    """Interface the tray implements for live actions. The default no-op
    version is used when the page runs without a tray (config-only)."""

    def daemon_running(self) -> bool:
        return False

    def apply_config(self, cfg: Config) -> str | None:
        """Called after a validated save so the daemon can reload in place.
        Returns an error message if the reload failed."""
        return None

    def current_model(self) -> str | None:
        return None


def build_state(controller: Controller) -> dict:
    cfg = load_config()
    loaded = controller.current_model()
    model_list = [
        {
            "name": spec.name,
            "family": spec.family,
            "languages": spec.languages_label,
            "downloaded": models.is_downloaded(spec.name),
            "loaded": spec.name == loaded,
            "size_mb": spec.size_mb,
            "unavailable": models.unavailable_reason(spec.name),
        }
        for spec in models.MODELS.values()
    ]
    return {
        "config": asdict(cfg),
        "daemon_running": controller.daemon_running(),
        "models": model_list,
        "downloading": _downloads.status(),
    }


def _config_from_payload(payload: dict) -> Config:
    """Build a Config from posted sections, ignoring unknown keys."""
    from ..config import (
        DiarizeConfig,
        DictationConfig,
        MeetingConfig,
        ModelConfig,
        _section,
    )

    base = load_config()
    return Config(
        model=_section(ModelConfig, {**asdict(base.model), **payload.get("model", {})}),
        dictation=_section(
            DictationConfig, {**asdict(base.dictation), **payload.get("dictation", {})}
        ),
        meeting=_section(
            MeetingConfig, {**asdict(base.meeting), **payload.get("meeting", {})}
        ),
        diarize=_section(
            DiarizeConfig, {**asdict(base.diarize), **payload.get("diarize", {})}
        ),
    )


class _Downloads:
    """Tracks background model downloads for progress polling."""

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


_downloads = _Downloads()


def make_handler(token: str, controller: Controller):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # silence default stderr access log

        # -- helpers --------------------------------------------------------

        def _authed(self) -> bool:
            q = parse_qs(urlparse(self.path).query)
            header = self.headers.get("X-Token")
            return secrets.compare_digest(
                (q.get("token", [""])[0] or header or ""), token
            )

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        # -- routing --------------------------------------------------------

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                return self._serve_page()
            if not self._authed():
                return self._send_json({"error": "unauthorized"}, 401)
            if path == "/api/state":
                return self._send_json(build_state(controller))
            return self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._authed():
                return self._send_json({"error": "unauthorized"}, 401)
            path = urlparse(self.path).path
            try:
                if path == "/api/config":
                    return self._save_config()
                if path == "/api/models/download":
                    _downloads.start(self._read_json()["name"])
                    return self._send_json({"ok": True})
                if path == "/api/models/remove":
                    models.remove(self._read_json()["name"])
                    return self._send_json({"ok": True})
            except ValueError as e:  # ConfigError, unknown model, bad JSON
                return self._send_json({"error": str(e)}, 400)
            except Exception as e:
                log.exception("API error")
                return self._send_json({"error": str(e)}, 500)
            return self._send_json({"error": "not found"}, 404)

        def _save_config(self):
            cfg = _config_from_payload(self._read_json())
            save_config(cfg)  # validates, then writes (atomic)
            reload_error = controller.apply_config(cfg)  # live-reload the daemon
            return self._send_json({
                "ok": True,
                "config": asdict(cfg),
                "daemon_running": controller.daemon_running(),
                "reload_error": reload_error,
            })

        def _serve_page(self):
            html = (STATIC_DIR / "settings.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    return Handler


class SettingsServer:
    def __init__(self, controller: Controller | None = None):
        self.controller = controller or Controller()
        self.token = secrets.token_urlsafe(24)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url: str | None = None

    def start(self) -> str:
        handler = make_handler(self.token, self.controller)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = self._httpd.server_address[1]
        self.url = write_state(port, self.token)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        log.info("settings server at %s", self.url)
        return self.url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        clear_state()
