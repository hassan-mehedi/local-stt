from types import SimpleNamespace

import numpy as np

import local_stt.dictation.daemon as daemon_mod
from local_stt.cleanup.api import ApiError
from local_stt.config import Config
from local_stt.dictation.daemon import DictationDaemon
from local_stt.store import FrontApp


class FakeRecorder:
    def __init__(self):
        self.recording = False

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        return np.zeros(16000, dtype=np.float32)  # 1s of audio


def _daemon(monkeypatch, mode):
    monkeypatch.setattr(daemon_mod, "make_output", lambda mode: None)
    cfg = Config()
    cfg.dictation.mode = mode
    cfg.dictation.notify = False
    d = DictationDaemon(cfg, backend=None)
    d.recorder = FakeRecorder()
    return d


def test_toggle_press_starts_press_stops(monkeypatch):
    d = _daemon(monkeypatch, "toggle")
    d._on_activate()
    assert d.recorder.recording
    d._on_deactivate()  # key release must NOT stop in toggle mode
    assert d.recorder.recording
    d._on_activate()
    assert not d.recorder.recording
    assert d._queue.qsize() == 1  # utterance queued for transcription


def test_hold_press_starts_release_stops(monkeypatch):
    d = _daemon(monkeypatch, "hold")
    d._on_activate()
    assert d.recorder.recording
    d._on_deactivate()
    assert not d.recorder.recording
    assert d._queue.qsize() == 1


def test_toggle_arms_cap_timer(monkeypatch):
    d = _daemon(monkeypatch, "toggle")
    d.config.dictation.max_duration_ms = 60000
    d._on_activate()
    assert d._cap_timer is not None and d._cap_timer.is_alive()
    d._on_activate()  # stop
    assert d._cap_timer is None  # cancelled on stop


def test_hold_mode_has_no_cap_timer(monkeypatch):
    d = _daemon(monkeypatch, "hold")
    d.config.dictation.max_duration_ms = 60000
    d._on_activate()
    assert d._cap_timer is None  # cap is toggle-only
    d._on_deactivate()


def test_cap_zero_disables_timer(monkeypatch):
    d = _daemon(monkeypatch, "toggle")
    d.config.dictation.max_duration_ms = 0
    d._on_activate()
    assert d._cap_timer is None


def test_auto_stop_ends_recording(monkeypatch):
    d = _daemon(monkeypatch, "toggle")
    d._on_activate()
    assert d.recorder.recording
    d._auto_stop()  # what the timer fires
    assert not d.recorder.recording
    assert d._queue.qsize() == 1


def test_auto_stop_and_manual_stop_dont_double_queue(monkeypatch):
    # the cap timer and a hotkey press can race; only one utterance should queue
    d = _daemon(monkeypatch, "toggle")
    d._on_activate()
    d._auto_stop()
    d._on_activate()  # user presses after auto-stop already fired
    assert d._queue.qsize() == 1


def test_cancel_discards_the_recording(monkeypatch):
    d = _daemon(monkeypatch, "toggle")
    states = []
    d.on_state = states.append
    d._on_activate()
    assert d.cancel_utterance()
    assert not d.recorder.recording
    assert d._queue.qsize() == 0
    assert states[-1] == "idle"
    assert not d.cancel_utterance()  # nothing left to cancel


def test_toggle_utterance_works_in_hold_mode(monkeypatch):
    d = _daemon(monkeypatch, "hold")
    d.toggle_utterance()
    assert d.recorder.recording
    d.toggle_utterance()
    assert not d.recorder.recording
    assert d._queue.qsize() == 1


def test_front_app_travels_with_the_utterance(monkeypatch):
    d = _daemon(monkeypatch, "toggle")
    d.front_app = lambda: "Slack"
    d._on_activate()
    d._on_activate()
    _, app = d._queue.get_nowait()
    assert app == "Slack"


def test_finish_text_applies_transform_before_the_space(monkeypatch):
    d = _daemon(monkeypatch, "toggle")
    d.transform = lambda text: text.replace("gonna", "going to")
    assert d._finish_text("  I'm   gonna go ") == "I'm going to go "
    d.transform = lambda text: 1 / 0
    assert d._finish_text("kept as heard") == "kept as heard "


class FakeCleaner:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error
        self.calls = []

    def complete(self, messages, max_tokens):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.reply


def test_finish_text_cleans_with_app_and_words_then_applies_the_dictionary(monkeypatch):
    d = _daemon(monkeypatch, "hold")
    d.cleaner = FakeCleaner("Pull pro-1285 from Plane.")
    d.vocabulary = lambda: ["PRO-1285"]
    d.transform = lambda text: text.replace("pro-1285", "PRO-1285")
    assert d._finish_text("Um pull Pro 1285 from plane.", FrontApp(None, "Slack")) == "Pull PRO-1285 from Plane. "
    prompt = d.cleaner.calls[0][1]["content"]
    assert "Slack" in prompt and "PRO-1285" in prompt
    assert "<transcript>\nPull Pro 1285 from plane.\n</transcript>" in prompt  # fillers go first


def test_finish_text_types_the_filtered_text_when_cleanup_fails(monkeypatch):
    notices = []
    monkeypatch.setattr(daemon_mod, "notify", lambda title, body="", **kw: notices.append((title, body)))
    d = _daemon(monkeypatch, "hold")
    d.cleaner = FakeCleaner(error=ApiError("api.deepseek.com answered 401: Authentication Fails"))
    assert d._finish_text("Um ship it.") == "Ship it. "
    assert notices == [("Cleanup failed", "api.deepseek.com answered 401: Authentication Fails")]


def test_worker_hands_on_what_the_model_heard(monkeypatch):
    d = _daemon(monkeypatch, "hold")
    d.backend = SimpleNamespace(transcribe_audio=lambda *a: SimpleNamespace(text=" um ship  it "))
    d.output = SimpleNamespace(emit=lambda text: None)
    d.cleaner = FakeCleaner("Ship it.")
    got = []
    d.on_text = got.append
    d._queue.put((np.zeros(16000, np.float32), None))
    d._queue.put(None)
    d._worker_loop()
    assert (got[0].text, got[0].raw) == ("Ship it. ", "um ship it")
