"""Dictation daemon: hold hotkey -> record -> transcribe -> emit text.

Listener callbacks never block on inference: the utterance is handed to a
worker thread via a queue, and utterances are emitted in order.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from ..audio.capture import Recorder
from ..config import Config
from ..desktop import notify
from ..engine.backend import AsrBackend, TranscribeOptions
from .hotkey import Hotkey, parse_hotkey
from .listeners import make_listener
from .output import make_output
from .postprocess import postprocess

log = logging.getLogger(__name__)


def _notify(summary: str, body: str = "") -> None:
    notify(summary, body, timeout_ms=1200)


@dataclass
class Utterance:
    """What the worker hands to on_text after a transcription."""

    text: str
    pcm: np.ndarray
    elapsed_ms: int
    app: object = None  # whatever front_app() returned when recording began
    error: str | None = None  # set when typing the text failed


class DictationDaemon:
    def __init__(
        self, config: Config, backend: AsrBackend, on_state=None, *,
        on_level=None, on_text=None, transform=None, front_app=None,
    ):
        self.config = config
        self.backend = backend
        self.hotkey: Hotkey = parse_hotkey(config.dictation.hotkey)
        self.output = make_output(config.dictation.output)
        self.recorder = Recorder(on_level=on_level)
        self.on_state = on_state  # optional callback: 'idle'|'recording'|'transcribing'
        self.on_text = on_text  # optional callback(Utterance), after the text is emitted
        self.transform = transform  # optional str -> str, e.g. the dictionary
        self.front_app = front_app  # optional () -> app, read when recording begins
        self._app = None
        self._queue: queue.Queue[tuple[np.ndarray, object] | None] = queue.Queue()
        self._listener = None
        self._worker: threading.Thread | None = None
        # guards the start/stop transition (the cap timer fires from its own
        # thread and may race the hotkey)
        self._utt_lock = threading.Lock()
        self._cap_timer: threading.Timer | None = None

    def _state(self, state: str) -> None:
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                log.exception("state callback failed")

    # -- listener callbacks (must stay fast; never block) -----------------------

    def _on_activate(self) -> None:
        """Combo pressed. hold: start recording; toggle: flip start/stop."""
        if self.config.dictation.mode == "toggle" and self.recorder.recording:
            self._end_utterance()
            return
        self._begin_utterance()

    def _on_deactivate(self) -> None:
        """Trigger released. Only meaningful in hold (push-to-talk) mode."""
        if self.config.dictation.mode == "hold":
            self._end_utterance()

    def toggle_utterance(self) -> None:
        """Start or stop a recording whatever the mode, e.g. from a click."""
        if self.recorder.recording:
            self._end_utterance()
        else:
            self._begin_utterance()

    def cancel_utterance(self) -> bool:
        """Throw the current recording away. False if nothing was recording."""
        with self._utt_lock:
            if not self.recorder.recording:
                return False
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
            self.recorder.stop()
        log.info("recording cancelled")
        self._state("idle")
        return True

    def _begin_utterance(self) -> None:
        with self._utt_lock:
            if self.recorder.recording:
                return
            self._app = self._read_front_app()
            self.recorder.start()
            self._arm_cap_timer()
        log.info("recording...")
        self._state("recording")
        if self.config.dictation.notify:
            body = (
                f"press {self.config.dictation.hotkey} again to stop"
                if self.config.dictation.mode == "toggle"
                else ""
            )
            _notify("● Recording", body)

    def _read_front_app(self):
        if self.front_app is None:
            return None
        try:
            return self.front_app()
        except Exception:
            log.exception("reading the front app failed")
            return None

    def _arm_cap_timer(self) -> None:
        """In toggle mode, auto-stop after max_duration_ms so a forgotten
        recording can't run forever. Caller holds _utt_lock."""
        cap = self.config.dictation.max_duration_ms
        if self.config.dictation.mode == "toggle" and cap > 0:
            self._cap_timer = threading.Timer(cap / 1000, self._auto_stop)
            self._cap_timer.daemon = True
            self._cap_timer.start()

    def _auto_stop(self) -> None:
        log.info("auto-stopping: max recording duration reached")
        if self.config.dictation.notify:
            _notify("■ Auto-stopped", "max recording length reached")
        self._end_utterance()

    def _end_utterance(self) -> None:
        with self._utt_lock:
            if not self.recorder.recording:
                return
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
            pcm = self.recorder.stop()
        ms = len(pcm) / 16.0
        if ms < self.config.dictation.min_duration_ms:
            log.info("discarded %dms utterance (too short)", ms)
            self._state("idle")
            return
        log.info("captured %.1fs, transcribing...", ms / 1000)
        self._state("transcribing")
        self._queue.put((pcm, self._app))

    # -- worker -----------------------------------------------------------------

    def _worker_loop(self):
        opts = TranscribeOptions(
            language=self.config.model.language or None,
            vad_min_silence_ms=250,  # dictation: split on short pauses
        )
        while True:
            item = self._queue.get()
            if item is None:
                return
            pcm, app = item
            t0 = time.monotonic()
            try:
                transcript = self.backend.transcribe_audio(pcm, 16000, opts)
            except Exception:
                log.exception("transcription failed")
                self._state("idle")
                continue
            text = self._finish_text(transcript.text)
            elapsed = time.monotonic() - t0
            self._state("idle")
            if not text.strip():
                log.info("no speech detected (%.2fs)", elapsed)
                continue
            log.info("(%.2fs) %s", elapsed, text.strip())
            if self.config.dictation.notify:
                _notify("✓ " + text.strip()[:80])
            error = None
            try:
                self.output.emit(text)
            except Exception as e:
                log.exception("failed to emit text")
                error = str(e)
            if self.on_text:
                try:
                    self.on_text(Utterance(text, pcm, round(elapsed * 1000), app, error))
                except Exception:
                    log.exception("text callback failed")

    def _finish_text(self, raw: str) -> str:
        text = postprocess(raw, append_space=False)
        if self.transform and text:
            try:
                text = self.transform(text)
            except Exception:
                log.exception("dictionary failed; typing the text as heard")
        if text.strip() and self.config.dictation.append_space:
            text += " "
        return text

    # -- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        """Non-blocking: start the key listener, load the model, start the
        worker. The listener goes first so a missing permission shows up
        before a model load. A shortcut pressed during the load is queued."""
        self._listener = make_listener(
            self.config.dictation.listener,
            self.hotkey,
            on_activate=self._on_activate,
            on_deactivate=self._on_deactivate,
            on_cancel=self.cancel_utterance,
        )
        self._listener.start()
        log.info("loading model %s...", self.config.model.name)
        self.backend.load()  # pay the load cost now, not on first utterance
        # warm the kernels so the first real utterance isn't slow
        self.backend.transcribe_audio(
            np.zeros(8000, dtype=np.float32), 16000, TranscribeOptions()
        )
        verb = "hold" if self.config.dictation.mode == "hold" else "press"
        log.info("ready — %s %s to dictate", verb, self.config.dictation.hotkey)

        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        self._state("idle")

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._cap_timer is not None:
            self._cap_timer.cancel()
            self._cap_timer = None
        if self.recorder.recording:
            self.recorder.stop()
        if self._worker is not None:
            self._queue.put(None)
            self._worker.join(timeout=30)
            self._worker = None

    def run(self) -> None:
        """Blocking foreground mode (stt dictate)."""
        self.start()
        try:
            self._listener.join()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
