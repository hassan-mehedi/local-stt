"""`stt engine`: the tray app without a menu bar, run by the desktop app. Prints
{"port", "token"} first, serves the API and /api/events, exits when stdin closes."""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from . import tray
from .config import Config, load_config, onboarding_done
from .desktop import set_notify_handler
from .store import FrontApp, Store
from .ui.events import EventBus

log = logging.getLogger(__name__)

LEVEL_INTERVAL = 1 / 30  # mic level events per second, at most


class FrontAppTracker:
    """Follows which app is in front through NSWorkspace's activation
    notifications, delivered on the main run loop."""

    def __init__(self):
        from AppKit import NSWorkspace, NSWorkspaceDidActivateApplicationNotification

        workspace = NSWorkspace.sharedWorkspace()
        self._app = self._describe(workspace.frontmostApplication())
        self._observer = workspace.notificationCenter().addObserverForName_object_queue_usingBlock_(
            NSWorkspaceDidActivateApplicationNotification, None, None, self._activated
        )

    @staticmethod
    def _describe(app) -> FrontApp | None:
        if app is None:
            return None
        return FrontApp(bundle_id=app.bundleIdentifier(), name=app.localizedName())

    def _activated(self, notification) -> None:
        from AppKit import NSWorkspaceApplicationKey

        self._app = self._describe(notification.userInfo()[NSWorkspaceApplicationKey])

    def current(self) -> FrontApp | None:
        return self._app


class HeadlessShell:
    """The tray's UI shell with no UI: the main thread runs a run loop until
    quit()."""

    def __init__(self, on_state):
        self._on_state = on_state
        self._stopped = threading.Event()
        self.front_apps: FrontAppTracker | None = None

    def build(self, rows) -> None:
        if sys.platform == "darwin":
            from .dictation.mac_layout import use_snapshot

            use_snapshot()  # dictation starts on a worker thread
            self.front_apps = FrontAppTracker()

    def set_state(self, state: str) -> None:
        self._on_state()

    def refresh(self) -> None:
        self._on_state()

    def show_page(self, url: str, title: str) -> None:
        pass  # the app owns its windows

    def close_page(self) -> None:
        pass

    def run(self, on_signal) -> None:
        if sys.platform != "darwin":
            for signum in (signal.SIGINT, signal.SIGTERM):
                signal.signal(signum, lambda *_: on_signal())
            while not self._stopped.wait(0.5):
                pass
            return
        from Foundation import NSDate, NSRunLoop, NSTimer
        from PyObjCTools import AppHelper, MachSignals

        for signum in (signal.SIGINT, signal.SIGTERM):
            MachSignals.signal(signum, lambda _signum: on_signal())
        # the console loop ends as soon as the run loop has no timer or port
        keepalive = NSTimer.alloc().initWithFireDate_interval_target_selector_userInfo_repeats_(
            NSDate.distantFuture(), 3600.0, self, "description", None, True
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(keepalive, "kCFRunLoopDefaultMode")
        AppHelper.runConsoleEventLoop(maxTimeout=0.5)

    def quit(self) -> None:
        self._stopped.set()
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(AppHelper.stopEventLoop)


def _notice_action(text: str) -> str | None:
    """The permission a failure points at, for the pill's Open Settings."""
    for name, words in (
        ("accessibility", ("Accessibility", "typing")),
        ("input_monitoring", ("Input Monitoring", "read the shortcut")),
        ("microphone", ("microphone", "Microphone")),
    ):
        if any(w in text for w in words):
            return name
    return None


class EngineApp(tray.TrayApp):
    def __init__(self, config: Config, store: Store | None = None):
        config.dictation.notify = False  # the pill shows each step instead
        super().__init__(config)
        self.store = store or Store()
        self.events = EventBus()
        self._dictation = "off"
        self._dictation_error: str | None = None
        self._meeting_started: datetime | None = None
        self._transcribing: set[str] = set()
        self._last_level = 0.0

    def extra_state(self) -> dict:
        meeting = self._meeting
        return {
            "engine": {
                "dictation": self._dictation,
                "error": self._dictation_error,
                "model": self.config.model.name,
                "hotkey": self.config.dictation.hotkey,
                "mode": self.config.dictation.mode,
                "meeting": {
                    "recording": meeting.session_dir.name if meeting else None,
                    "started_at": (
                        self._meeting_started.isoformat() if meeting and self._meeting_started else None
                    ),
                    "transcribing": sorted(self._transcribing),
                },
            }
        }

    def publish_state(self) -> None:
        self.events.publish("state", self.extra_state()["engine"])

    def _on_dictation_state(self, state: str) -> None:
        self._dictation = state
        super()._on_dictation_state(state)

    def _on_level(self, rms: float) -> None:
        now = time.monotonic()
        if now - self._last_level >= LEVEL_INTERVAL:
            self._last_level = now
            self.events.publish("level", {"level": round(rms, 4)})

    def _on_text(self, utt) -> None:
        row = self.store.add_dictation(
            utt.text, audio_ms=round(len(utt.pcm) / 16), elapsed_ms=utt.elapsed_ms,
            app=utt.app, pcm=utt.pcm, raw_text=utt.raw,
        )
        self.events.publish("dictation", {"item": row, "error": utt.error})
        if utt.error:
            self._on_notice("Typing failed", utt.error)

    def _on_notice(self, title: str, body: str = "") -> None:
        error = "failed" in title.lower()
        self.events.publish("notice", {
            "title": title,
            "body": body,
            "level": "error" if error else "info",
            "action": _notice_action(body) if error else None,
        })

    def _front_app(self) -> FrontApp | None:
        tracker = self._ui.front_apps if self._ui is not None else None
        return tracker.current() if tracker is not None else None

    def _daemon_hooks(self) -> dict:
        return {
            "on_level": self._on_level,
            "on_text": self._on_text,
            "transform": self.store.apply_dictionary,
            "front_app": self._front_app,
            "vocabulary": lambda: [e["phrase"] for e in self.store.dictionary()["words"]],
        }

    def _start_daemon_locked(self, notify: bool = True) -> str | None:
        self._dictation, self._dictation_error = "loading", None
        self.publish_state()
        error = super()._start_daemon_locked(notify=False)
        if error:
            self._dictation, self._dictation_error = "off", error
        self.publish_state()
        return error

    def _stop_daemon_locked(self) -> None:
        super()._stop_daemon_locked()
        self._dictation = "off"

    def stop_dictation(self) -> None:
        with self._lock:
            self._stop_daemon_locked()
            self._set_state("off")
        self._refresh()

    def toggle_recording(self) -> str | None:
        daemon = self._daemon
        if daemon is None:
            return "Dictation is off"
        daemon.toggle_utterance()
        return None

    def cancel_recording(self) -> bool:
        daemon = self._daemon
        return daemon.cancel_utterance() if daemon is not None else False

    def paste_text(self, text: str) -> str | None:
        """Types text into the app in front, after the window that asked has
        had time to hide."""
        from .dictation.output import make_output

        time.sleep(0.35)
        try:
            output = self._daemon.output if self._daemon is not None else make_output(
                self.config.dictation.output
            )
            output.emit(text)
        except Exception as e:
            log.exception("paste failed")
            return str(e)
        return None

    def apply_config(self, cfg: Config) -> str | None:
        cfg.dictation.notify = False
        error = super().apply_config(cfg)
        self._dictation_error = error
        self.publish_state()
        return error

    def meetings_dir(self) -> Path:
        return Path(self.config.meeting.output_dir).expanduser()

    def meeting_activity(self) -> dict:
        meeting = self._meeting
        return {
            "recording": meeting.session_dir.name if meeting else None,
            "transcribing": set(self._transcribing),
        }

    def toggle_meeting(self, language: str | None = None) -> str | None:
        from .meeting.transcribe import save_settings

        started = self._meeting is None
        error = super().toggle_meeting(language)
        rec = self._meeting
        if started and rec is not None:
            self._meeting_started = datetime.now()
            save_settings(
                rec.session_dir, rec.model, rec.language,
                started_at=self._meeting_started.isoformat(timespec="seconds"),
            )
        self.publish_state()
        self.events.publish("meetings", {})
        return error

    def _transcribe_meeting(self, rec) -> None:
        name = rec.session_dir.name
        self._transcribing.add(name)
        self.publish_state()
        self.events.publish("meetings", {})
        try:
            super()._transcribe_meeting(rec)
        finally:
            self._transcribing.discard(name)
            self.publish_state()
            self.events.publish("meetings", {"id": name})

    def retranscribe_meeting(self, session_id: str) -> None:
        from .meeting.library import session_dir
        from .meeting.transcribe import choose_model, load_settings

        folder = session_dir(self.meetings_dir(), session_id)
        if session_id in self._transcribing:
            return
        settings = load_settings(folder)
        model, _ = choose_model(self.config, settings.get("model"), settings.get("language"))
        rec = SimpleNamespace(session_dir=folder, title=session_id, model=model)
        threading.Thread(target=self._transcribe_meeting, args=(rec,), daemon=True).start()

    def _watch_stdin(self) -> None:
        try:
            while sys.stdin.read(4096):
                pass
        except (OSError, ValueError):
            pass
        log.info("stdin closed; quitting")
        self.quit()

    def run(self) -> None:
        if not tray._single_instance():
            print(json.dumps({"error": "local-stt is already running"}), flush=True)
            return
        try:
            self._run()
        finally:
            tray.PIDFILE.unlink(missing_ok=True)

    def _run(self) -> None:
        from .ui.server import SettingsServer

        self._ui = HeadlessShell(on_state=self.publish_state)
        self._ui.build([])
        set_notify_handler(self._on_notice)
        self._server = SettingsServer(controller=self)
        self._server.start()
        port = self._server._httpd.server_address[1]
        print(json.dumps({"port": port, "token": self._server.token}), flush=True)
        threading.Thread(target=self._watch_stdin, daemon=True).start()
        if onboarding_done():
            threading.Thread(target=self.start_dictation, daemon=True).start()
        self._ui.run(on_signal=self.quit)

    def quit(self) -> None:
        super().quit()
        self.store.close()


def main(config: Config | None = None) -> int:
    EngineApp(config or load_config()).run()
    return 0
