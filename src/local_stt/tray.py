"""System tray app (GTK AppIndicator): dictation toggle, meeting record,
settings, and a status icon.

Icon state: dimmed mic = dictation off, green dot = listening, red dot =
recording (dictation utterance or meeting), amber dot = transcribing.

Uses Ayatana AppIndicator via the system PyGObject (the isolated uv venv has
no `gi`, but the system one is ABI-compatible — we append dist-packages to
sys.path so it's importable without shadowing venv packages).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from .config import CACHE_DIR, Config, load_config

log = logging.getLogger(__name__)

PIDFILE = CACHE_DIR / "tray.pid"
_SYSTEM_SITE = "/usr/lib/python3/dist-packages"


def _load_gi():
    """Make the system PyGObject importable from the venv. Appended (not
    prepended) so venv packages keep priority over system ones."""
    if _SYSTEM_SITE not in sys.path and os.path.isdir(_SYSTEM_SITE):
        sys.path.append(_SYSTEM_SITE)
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3, GLib, Gtk

    return Gtk, GLib, AyatanaAppIndicator3


def _single_instance() -> bool:
    """True if we acquired the singleton; False if another tray is alive."""
    if PIDFILE.exists():
        try:
            pid = int(PIDFILE.read_text().strip())
            os.kill(pid, 0)  # raises if not running
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale pidfile
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    return True


def _notify(summary: str, body: str = "") -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(
            ["notify-send", "-a", "local-stt", "-t", "2500", summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class TrayApp:
    def __init__(self, config: Config):
        self.config = config
        self.indicator = None
        self._gtk = None
        self._glib = None
        self._menu_items = {}
        self._daemon = None
        self._meeting = None
        self._server = None
        self._dictation_state = "off"
        self._lock = threading.Lock()

    # -- state / icon --------------------------------------------------------

    def _set_state(self, state: str) -> None:
        # meeting recording dominates the icon unless dictation is mid-utterance
        if self._meeting is not None and state == "idle":
            state = "recording"
        self._dictation_state = state
        if self.indicator is None:
            return
        from .ui.icons import icon_name

        # GTK is not thread-safe; marshal the icon change onto the main loop
        self._glib.idle_add(self.indicator.set_icon_full, icon_name(state), state)

    def _on_dictation_state(self, state: str) -> None:
        self._set_state(state)
        self._glib.idle_add(self._refresh_labels)

    # -- dictation ------------------------------------------------------------

    def dictation_on(self) -> bool:
        return self._daemon is not None

    def _start_daemon_locked(self, notify: bool = True) -> None:
        from .cli import _build_backend
        from .dictation.daemon import DictationDaemon

        try:
            self._daemon = DictationDaemon(
                self.config,
                _build_backend(self.config),
                on_state=self._on_dictation_state,
            )
            self._daemon.start()
            if notify:
                verb = "hold" if self.config.dictation.mode == "hold" else "press"
                _notify("Dictation on", f"{verb} {self.config.dictation.hotkey}")
        except Exception as e:
            self._daemon = None
            log.exception("failed to start dictation")
            _notify("Dictation failed", str(e))

    def _stop_daemon_locked(self) -> None:
        if self._daemon is None:
            return
        self._daemon.stop()
        self._daemon.backend.unload()  # free VRAM (matters when switching models)
        self._daemon = None

    def toggle_dictation(self, icon=None, item=None) -> None:
        with self._lock:
            if self._daemon is None:
                self._start_daemon_locked()
            else:
                self._stop_daemon_locked()
                self._set_state("off")
                _notify("Dictation off")
        if self._glib is not None:
            self._glib.idle_add(self._refresh_labels)

    # -- settings controller (called from the HTTP server thread) -------------

    def daemon_running(self) -> bool:
        return self._daemon is not None

    def current_model(self) -> str | None:
        return self.config.model.name if self._daemon is not None else None

    def apply_config(self, cfg: Config) -> None:
        """Adopt validated config; restart the daemon in place if running so
        the new hotkey/mode/output/model take effect without a logout."""
        with self._lock:
            self.config = cfg
            if self._daemon is not None:
                self._stop_daemon_locked()
                self._start_daemon_locked(notify=False)

    # -- meetings ---------------------------------------------------------------

    def meeting_on(self) -> bool:
        return self._meeting is not None

    def toggle_meeting(self, icon=None, item=None) -> None:
        with self._lock:
            if self._meeting is None:
                from .meeting.recorder import MeetingRecorder

                out_root = Path(self.config.meeting.output_dir).expanduser()
                rec = MeetingRecorder(
                    out_root, f"{datetime.now():%H-%M}", when=datetime.now()
                )
                try:
                    rec.start()
                except Exception as e:
                    log.exception("failed to start meeting")
                    _notify("Meeting failed", str(e))
                    return
                self._meeting = rec
                self._set_state("recording")
                _notify("Meeting recording", str(rec.session_dir))
            else:
                rec, self._meeting = self._meeting, None
                rec.stop()
                self._set_state("transcribing" if self._daemon is None else "idle")
                _notify("Meeting stopped", "transcribing...")
                threading.Thread(
                    target=self._transcribe_meeting, args=(rec,), daemon=True
                ).start()
        if self._glib is not None:
            self._glib.idle_add(self._refresh_labels)

    def _transcribe_meeting(self, rec) -> None:
        try:
            from .cli import _transcribe_session

            # reuse the dictation daemon's already-loaded model if present,
            # so we don't load a second copy into VRAM
            backend = self._daemon.backend if self._daemon is not None else None
            _transcribe_session(
                rec.session_dir, title=rec.title, cfg=self.config, backend=backend
            )
            _notify("Transcript ready", str(rec.session_dir / "transcript.md"))
        except Exception as e:
            log.exception("meeting transcription failed")
            _notify("Transcription failed", str(e))
        finally:
            self._set_state("off" if self._daemon is None else "idle")

    # -- misc -----------------------------------------------------------------------

    def open_meetings(self, icon=None, item=None) -> None:
        d = Path(self.config.meeting.output_dir).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(d)])

    def open_settings(self, icon=None, item=None) -> None:
        if self._server is not None and self._server.url:
            subprocess.Popen(["xdg-open", self._server.url])

    def quit(self, *args) -> None:
        if self._server is not None:
            self._server.stop()
        if self._daemon is not None:
            self._daemon.stop()
        if self._meeting is not None:
            self._meeting.stop()
        PIDFILE.unlink(missing_ok=True)
        self._gtk.main_quit()

    # -- menu -----------------------------------------------------------------

    def _refresh_labels(self) -> None:
        """Keep menu labels in sync with state (runs on the GTK thread)."""
        if "dictation" in self._menu_items:
            self._menu_items["dictation"].set_label(
                "■ Stop dictation" if self.dictation_on() else "▶ Start dictation"
            )
        if "meeting" in self._menu_items:
            self._menu_items["meeting"].set_label(
                "■ Stop & transcribe meeting"
                if self.meeting_on()
                else "● Record meeting"
            )

    def _build_menu(self):
        Gtk = self._gtk
        menu = Gtk.Menu()

        def item(key, handler):
            mi = Gtk.MenuItem(label="")
            mi.connect("activate", lambda *_: handler())
            menu.append(mi)
            if key:
                self._menu_items[key] = mi
            return mi

        item("dictation", lambda: threading.Thread(
            target=self.toggle_dictation, daemon=True).start())
        item("meeting", lambda: threading.Thread(
            target=self.toggle_meeting, daemon=True).start())
        menu.append(Gtk.SeparatorMenuItem())
        m = Gtk.MenuItem(label="Open meetings folder")
        m.connect("activate", lambda *_: self.open_meetings())
        menu.append(m)
        m = Gtk.MenuItem(label="Settings…")
        m.connect("activate", lambda *_: self.open_settings())
        menu.append(m)
        menu.append(Gtk.SeparatorMenuItem())
        m = Gtk.MenuItem(label="Quit")
        m.connect("activate", self.quit)
        menu.append(m)

        menu.show_all()
        self._refresh_labels()
        return menu

    # -- lifecycle ------------------------------------------------------------

    def run(self) -> None:
        if not _single_instance():
            log.warning("another local-stt tray is already running; exiting")
            _notify("local-stt already running", "The tray is already in the panel.")
            return

        try:
            self._run()
        finally:
            PIDFILE.unlink(missing_ok=True)

    def _run(self) -> None:
        from .ui.icons import ensure_icons, icon_name

        self._gtk, self._glib, AppIndicator = _load_gi()
        icon_dir = ensure_icons()

        self.indicator = AppIndicator.Indicator.new(
            "local-stt",
            icon_name("off"),
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_icon_theme_path(str(icon_dir))
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("local-stt")
        self.indicator.set_menu(self._build_menu())
        log.info("tray running (AppIndicator)")

        from .ui.server import SettingsServer

        self._server = SettingsServer(controller=self)
        try:
            self._server.start()
        except Exception:
            log.exception("settings server failed to start")
            self._server = None

        # start dictation by default — the reason the tray exists
        threading.Thread(target=self.toggle_dictation, daemon=True).start()
        self._gtk.main()


def main(config: Config | None = None) -> int:
    app = TrayApp(config or load_config())
    app.run()
    return 0
