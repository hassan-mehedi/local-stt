import numpy as np

import local_stt.dictation.daemon as daemon_mod
from local_stt.config import Config
from local_stt.dictation.daemon import DictationDaemon


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
