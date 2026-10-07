"""Local settings server: one static page + a small JSON API.

Bound to 127.0.0.1 with a per-session token. The tray passes a `controller`
exposing live actions (daemon status/restart, model download/switch); without
one, the server still edits config.toml (the page shows "daemon: off").

The desktop app's engine also gives the controller a history store and an
event bus, which turns on the routes in app_api and the /api/events stream.
Its window loads from another origin, so those replies carry CORS headers.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import secrets
import socketserver
import sys
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import permissions
from ..config import (
    Config,
    default_model,
    load_config,
    load_onboarding,
    mark_onboarding_done,
    save_config,
    save_onboarding,
)
from ..desktop import app_bundle
from ..engine import models
from . import app_api
from .state import clear_state, write_state

log = logging.getLogger(__name__)

# the Tauri window on macOS and Linux/Windows, and its dev server
APP_ORIGINS = frozenset({"tauri://localhost", "http://tauri.localhost", "http://localhost:1420"})

STATIC_DIR = Path(__file__).parent / "static"
PAGES = {"/": "settings.html", "/onboarding": "onboarding.html"}
ASSETS = {
    "/static/common.css": "text/css; charset=utf-8",
    "/static/common.js": "text/javascript; charset=utf-8",
}

class Controller:
    """Interface the tray implements for live actions. The default no-op
    version is used when the page runs without a tray (config-only)."""

    store = None  # store.Store, for the app routes
    events = None  # events.EventBus, for /api/events

    def extra_state(self) -> dict:
        return {}

    def publish_state(self) -> None:
        """Sends the current state to /api/events listeners."""

    def daemon_running(self) -> bool:
        return False

    def apply_config(self, cfg: Config) -> str | None:
        """Called after a validated save so the daemon can reload in place.
        Returns an error message if the reload failed."""
        return None

    def current_model(self) -> str | None:
        return None

    def dictation_state(self) -> str:
        return "off"

    def start_dictation(self) -> str | None:
        return "dictation runs in the menu bar app; start it with: stt tray"

    def finish_onboarding(self) -> None:
        mark_onboarding_done()

    def relaunch(self) -> None:
        raise RuntimeError("relaunch needs the menu bar app")


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
    downloading = _downloads.status()
    return {
        "config": asdict(cfg),
        "platform": sys.platform,
        "default_model": default_model(),
        "onboarding": load_onboarding(),
        "daemon_running": controller.daemon_running(),
        "dictation_state": controller.dictation_state(),
        "models": model_list,
        "downloading": downloading,
        "progress": {
            name: models.download_progress(name)
            for name, s in downloading.items() if s == "running"
        },
        **controller.extra_state(),
    }


def permissions_state() -> dict:
    return {
        "supported": permissions.supported(),
        "status": permissions.status(),
        "login_item": permissions.login_item(),
        "app_bundle": app_bundle() is not None,
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

        def _cors(self):
            origin = self.headers.get("Origin")
            if origin in APP_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "X-Token, Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def _send_file_reply(self, reply: app_api.FileReply):
            """Byte ranges included: WebKit only plays audio served with them."""
            size = reply.path.stat().st_size
            start, end = 0, size - 1
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if match and (match.group(1) or match.group(2)):
                if match.group(1):
                    start = int(match.group(1))
                    end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
                else:
                    start = max(0, size - int(match.group(2)))
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self._cors()
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", reply.content_type)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            with open(reply.path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _stream_events(self):
            events = controller.events.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self._cors()
                self.end_headers()
                self.wfile.write(b"retry: 1000\n\n")
                self.wfile.flush()
                controller.publish_state()
                while True:
                    try:
                        message = events.get(timeout=15)
                    except queue.Empty:
                        message = b": ping\n\n"
                    self.wfile.write(message)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                controller.events.unsubscribe(events)

        def _reply(self, result):
            if isinstance(result, app_api.FileReply):
                return self._send_file_reply(result)
            return self._send_json(result)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        # -- routing --------------------------------------------------------

        def do_GET(self):
            path = urlparse(self.path).path
            if path in PAGES:
                return self._serve_file(PAGES[path], "text/html; charset=utf-8")
            if path in ASSETS:
                return self._serve_file(path.removeprefix("/static/"), ASSETS[path])
            if not path.startswith("/api/"):
                return self._send_json({"error": "not found"}, 404)  # e.g. favicon.ico
            if not self._authed():
                return self._send_json({"error": "unauthorized"}, 401)
            if path == "/api/state":
                return self._send_json(build_state(controller))
            if path == "/api/permissions":
                return self._send_json(permissions_state())
            if path == "/api/events" and controller.events is not None:
                return self._stream_events()
            if controller.store is not None:
                try:
                    result = app_api.handle_get(controller, path, parse_qs(urlparse(self.path).query))
                except LookupError as e:
                    return self._send_json({"error": str(e)}, 404)
                except ValueError as e:
                    return self._send_json({"error": str(e)}, 400)
                except Exception as e:
                    log.exception("API error")
                    return self._send_json({"error": str(e)}, 500)
                if result is not None:
                    return self._reply(result)
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
                if path == "/api/permissions/request":
                    permissions.request(self._read_json()["name"])
                    return self._send_json(permissions_state())
                if path == "/api/login-item":
                    permissions.set_login_item(bool(self._read_json()["enabled"]))
                    return self._send_json(permissions_state())
                if path == "/api/dictation/start":
                    error = controller.start_dictation()
                    return self._send_json({"ok": error is None, "error": error})
                if path == "/api/onboarding/step":
                    save_onboarding(step=int(self._read_json()["step"]))
                    return self._send_json({"ok": True})
                if path == "/api/relaunch":
                    if app_bundle() is None:
                        return self._send_json({"error": "relaunch needs local-stt.app"}, 400)
                    # after the reply is out, since quitting stops this server
                    threading.Timer(0.3, controller.relaunch).start()
                    return self._send_json({"ok": True})
                if path == "/api/onboarding/done":
                    controller.finish_onboarding()
                    return self._send_json({"ok": True})
                if controller.store is not None:
                    result = app_api.handle_post(controller, path, self._read_json())
                    if result is not None:
                        return self._send_json(result)
            except LookupError as e:
                return self._send_json({"error": str(e)}, 404)
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

        def _serve_file(self, name: str, content_type: str):
            body = (STATIC_DIR / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


class _LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind resolves the host name with a reverse DNS
        # lookup, which stalls for good inside the app bundle; the name is
        # known anyway
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class SettingsServer:
    def __init__(self, controller: Controller | None = None):
        self.controller = controller or Controller()
        self.token = secrets.token_urlsafe(24)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url: str | None = None

    def start(self) -> str:
        handler = make_handler(self.token, self.controller)
        self._httpd = _LocalServer(("127.0.0.1", 0), handler)
        port = self._httpd.server_address[1]
        self.url = write_state(port, self.token)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        log.info("settings server at %s", self.url)
        return self.url

    def page_url(self, page: str) -> str:
        port = self._httpd.server_address[1]
        return f"http://127.0.0.1:{port}/{page}?token={self.token}"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        clear_state()
