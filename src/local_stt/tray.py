"""Tray / menu bar app: dictation toggle, meeting record, settings, and a
status icon. The app logic lives here; the platform UI is a shell from
ui.tray_gtk (Linux) or ui.tray_mac (macOS).

Icon states: off, idle (listening), recording (dictation utterance or
meeting), transcribing.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from .config import CACHE_DIR, Config, load_config, mark_onboarding_done, onboarding_done
from .desktop import notify, open_target, relaunch

log = logging.getLogger(__name__)

PIDFILE = CACHE_DIR / "tray.pid"


def _make_shell():
    if sys.platform == "darwin":
        from .ui.tray_mac import MacShell

        return MacShell()
    from .ui.tray_gtk import GtkShell

    return GtkShell()


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
    notify(summary, body, timeout_ms=2500)


class TrayApp:
    def __init__(self, config: Config):
        self.config = config
        self._ui = None
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
        if self._ui is not None:
            self._ui.set_state(state)

    def _refresh(self) -> None:
        if self._ui is not None:
            self._ui.refresh()

    def _on_dictation_state(self, state: str) -> None:
        self._set_state(state)
        self._refresh()

    # -- dictation ------------------------------------------------------------

    def dictation_on(self) -> bool:
        return self._daemon is not None

    def _start_daemon_locked(self, notify: bool = True) -> str | None:
        """Returns an error message if the daemon failed to start."""
        from .cli import _build_backend
        from .dictation.daemon import DictationDaemon

        backend = daemon = None
        try:
            backend = _build_backend(self.config)
            daemon = DictationDaemon(self.config, backend, on_state=self._on_dictation_state)
            daemon.start()
        except Exception as e:
            log.exception("failed to start dictation")
            if daemon is not None:
                daemon.stop()
            if backend is not None:
                backend.unload()
            _notify("Dictation failed", str(e))
            return str(e)
        self._daemon = daemon
        if notify:
            verb = "hold" if self.config.dictation.mode == "hold" else "press"
            _notify("Dictation on", f"{verb} {self.config.dictation.hotkey}")
        return None

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
        self._refresh()

    # -- settings controller (called from the HTTP server thread) -------------

    def daemon_running(self) -> bool:
        return self._daemon is not None

    def current_model(self) -> str | None:
        return self.config.model.name if self._daemon is not None else None

    def dictation_state(self) -> str:
        return self._dictation_state

    def start_dictation(self) -> str | None:
        """Starts dictation unless it runs already; returns an error message
        if it failed."""
        with self._lock:
            error = None if self._daemon is not None else self._start_daemon_locked()
        self._refresh()
        return error

    def relaunch(self) -> None:
        relaunch()
        self.quit()

    def finish_onboarding(self) -> None:
        mark_onboarding_done()
        if self._ui is not None:
            self._ui.close_page()
        threading.Thread(target=self.start_dictation, daemon=True).start()

    def apply_config(self, cfg: Config) -> str | None:
        """Adopt validated config; restart the daemon in place if running so
        the new hotkey/mode/output/model take effect without a logout.
        Returns an error message if the restart failed."""
        with self._lock:
            unchanged = (cfg.model, cfg.dictation) == (self.config.model, self.config.dictation)
            self.config = cfg
            if self._daemon is None or unchanged:
                return None
            self._stop_daemon_locked()
            error = self._start_daemon_locked(notify=False)
        self._refresh()
        if error:
            self._set_state("off")
        return error

    # -- meetings ---------------------------------------------------------------

    def meeting_on(self) -> bool:
        return self._meeting is not None

    def toggle_meeting(self, language: str | None = None) -> None:
        """Start a meeting (in `language`, default from config), or stop the
        running one whichever menu item was used."""
        with self._lock:
            if self._meeting is None:
                from .meeting.recorder import MeetingRecorder
                from .meeting.transcribe import choose_model, save_settings

                out_root = Path(self.config.meeting.output_dir).expanduser()
                rec = MeetingRecorder(
                    out_root, f"{datetime.now():%H-%M}", when=datetime.now()
                )
                try:
                    rec.model, rec.language = choose_model(self.config, language=language)
                    rec.start()
                    save_settings(rec.session_dir, rec.model, rec.language)
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
        self._refresh()

    def _transcribe_meeting(self, rec) -> None:
        try:
            from .cli import _transcribe_session

            # reuse the dictation daemon's already-loaded model if it's the
            # one this meeting needs, so we don't load a second copy
            daemon = self._daemon
            backend = (
                daemon.backend
                if daemon is not None and daemon.config.model.name == rec.model
                else None
            )
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
        open_target(str(d))

    def open_settings(self, icon=None, item=None) -> None:
        if self._server is not None and self._server.url:
            self._ui.show_page(self._server.url, "local-stt settings")

    def open_onboarding(self, icon=None, item=None) -> None:
        if self._server is not None and self._server.url:
            self._ui.show_page(self._server.page_url("onboarding"), "Welcome to local-stt")

    def quit(self) -> None:
        if self._server is not None:
            self._server.stop()
        if self._daemon is not None:
            self._daemon.stop()
        if self._meeting is not None:
            self._meeting.stop()
        PIDFILE.unlink(missing_ok=True)
        self._ui.quit()

    # -- menu -----------------------------------------------------------------

    @staticmethod
    def _in_thread(fn):
        """Menu clicks arrive on the UI thread; model loads must not block it."""
        return lambda: threading.Thread(target=fn, daemon=True).start()

    def _language_meetings(self) -> list:
        """A 'Record meeting in X' row per downloaded single-language model
        (bengali-whisper-medium -> Bengali), hidden while a meeting runs."""
        from .engine import models

        rows = []
        for spec in models.MODELS.values():
            langs = spec.languages or frozenset()
            if len(langs) != 1 or langs == {"en"} or not models.is_downloaded(spec.name):
                continue
            (language,) = langs
            rows.append((
                lambda label=spec.languages_label: (
                    None if self.meeting_on() else f"● Record meeting in {label}"
                ),
                self._in_thread(lambda language=language: self.toggle_meeting(language)),
            ))
        return rows

    def menu(self) -> list:
        """Rows of (label function, handler), or None for a separator. The
        shell re-reads labels on refresh(); a None label hides the row."""
        return [
            (
                lambda: "■ Stop dictation" if self.dictation_on() else "▶ Start dictation",
                self._in_thread(self.toggle_dictation),
            ),
            (
                lambda: "■ Stop & transcribe meeting" if self.meeting_on() else "● Record meeting",
                self._in_thread(self.toggle_meeting),
            ),
            *self._language_meetings(),
            None,
            (lambda: "Open meetings folder", self.open_meetings),
            (lambda: "Settings…", self.open_settings),
            (lambda: "Setup guide…", self.open_onboarding),
            None,
            (lambda: "Quit", self.quit),
        ]

    # -- lifecycle ------------------------------------------------------------

    def run(self) -> None:
        if not _single_instance():
            log.warning("another local-stt tray is already running; exiting")
            _notify("local-stt already running", "It is already in the menu bar / panel.")
            return

        try:
            self._run()
        finally:
            PIDFILE.unlink(missing_ok=True)

    def _run(self) -> None:
        self._ui = _make_shell()
        self._ui.build(self.menu())
        self._ui.set_state(self._dictation_state)

        from .ui.server import SettingsServer

        self._server = SettingsServer(controller=self)
        try:
            self._server.start()
        except Exception:
            log.exception("settings server failed to start")
            self._server = None

        if sys.platform == "darwin" and not onboarding_done() and self._server is not None:
            # dictation starts when onboarding finishes, after the model and
            # permissions are in place
            self.open_onboarding()
        else:
            # start dictation by default: the reason the tray exists
            threading.Thread(target=self.toggle_dictation, daemon=True).start()
        self._ui.run(on_signal=self.quit)


def main(config: Config | None = None) -> int:
    app = TrayApp(config or load_config())
    app.run()
    return 0
