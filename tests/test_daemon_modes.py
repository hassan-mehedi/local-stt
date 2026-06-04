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
