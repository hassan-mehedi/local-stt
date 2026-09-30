import time

from local_stt.engine.backend import Segment, Transcript
from local_stt.meeting.recorder import slugify
from local_stt.meeting.transcribe import label, merge


def _t(segs, duration=10.0):
    return Transcript(segments=segs, language="en", duration=duration, model="tiny")


def test_slugify():
    assert slugify("Weekly Standup!") == "weekly-standup"
    assert slugify("  ") == "meeting"
    assert slugify("1:1 w/ Sam") == "1-1-w-sam"


def test_label():
    t = label(_t([Segment(0, 1, "hi")]), "Me")
    assert t.segments[0].speaker == "Me"


def test_merge_interleaves_by_timestamp():
    mine = label(_t([Segment(0.0, 2.0, "Hello"), Segment(10.0, 12.0, "Sure")]), "Me")
    theirs = label(_t([Segment(3.0, 8.0, "Hi, can you hear me?")], duration=15.0), "Them")
    merged = merge(mine, theirs)
    assert [(s.speaker, s.text) for s in merged.segments] == [
        ("Me", "Hello"),
        ("Them", "Hi, can you hear me?"),
        ("Me", "Sure"),
    ]
    assert merged.duration == 15.0


def test_merge_empty_track():
    mine = label(_t([Segment(0.0, 1.0, "Testing")]), "Me")
    theirs = label(_t([], duration=0.0), "Them")
    merged = merge(mine, theirs)
    assert len(merged.segments) == 1
    assert merged.segments[0].speaker == "Me"


import pytest  # noqa: E402

import local_stt.engine.models as models  # noqa: E402
from local_stt.config import Config  # noqa: E402
from local_stt.meeting.transcribe import (  # noqa: E402
    choose_model, load_settings, save_settings,
)


@pytest.fixture
def downloaded(monkeypatch):
    """Pretend exactly these models are downloaded, on Apple Silicon."""
    have: set[str] = set()
    monkeypatch.setattr(models, "is_downloaded", lambda name: name in have)
    monkeypatch.setattr(models, "is_apple_silicon", lambda: True)
    return have


def _cfg():
    cfg = Config()
    cfg.model.name = "parakeet-tdt-0.6b-v2"
    cfg.model.language = "en"
    return cfg


def test_meeting_uses_dictation_model_by_default(downloaded):
    assert choose_model(_cfg()) == ("parakeet-tdt-0.6b-v2", "en")


def test_bengali_picks_the_bengali_fine_tune(downloaded):
    downloaded |= {"parakeet-tdt-0.6b-v2", "large-v3-turbo", "bengali-whisper-medium"}
    assert choose_model(_cfg(), language="bn") == ("bengali-whisper-medium", "bn")


def test_bengali_falls_back_to_a_general_whisper(downloaded):
    downloaded |= {"parakeet-tdt-0.6b-v2", "large-v3-turbo"}
    assert choose_model(_cfg(), language="bn") == ("large-v3-turbo", "bn")


def test_bengali_without_a_model_explains_the_download(downloaded):
    with pytest.raises(ValueError, match="stt models download bengali-whisper-medium"):
        choose_model(_cfg(), language="bn")


def test_meeting_section_overrides_dictation(downloaded):
    cfg = _cfg()
    cfg.meeting.model, cfg.meeting.language = "bengali-whisper-medium", "bn"
    assert choose_model(cfg) == ("bengali-whisper-medium", "bn")


def test_session_settings_round_trip(tmp_path):
    save_settings(tmp_path, "bengali-whisper-medium", "bn")
    assert load_settings(tmp_path) == {"model": "bengali-whisper-medium", "language": "bn"}
    assert load_settings(tmp_path / "missing") == {}


def test_tray_offers_a_meeting_per_downloaded_language_model(downloaded):
    from local_stt.tray import TrayApp

    downloaded |= {"parakeet-tdt-0.6b-v2", "bengali-whisper-medium"}
    app = TrayApp(_cfg())
    labels = [row[0]() for row in app.menu() if row is not None]
    assert "● Record meeting in Bengali" in labels
    assert not any("English" in label for label in labels if label)

    app._meeting = object()  # while recording, only the stop item shows
    labels = [row[0]() for row in app.menu() if row is not None]
    assert "■ Stop & transcribe meeting" in labels
    assert None in labels


def test_finishing_onboarding_closes_the_window_and_starts_dictation(tmp_path, monkeypatch):
    import local_stt.config as cfgmod
    from local_stt.tray import TrayApp

    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.toml")
    app = TrayApp(_cfg())
    closed, started = [], []

    class Shell:
        def close_page(self):
            closed.append(True)

    app._ui = Shell()
    monkeypatch.setattr(app, "start_dictation", lambda: started.append(True))
    app.finish_onboarding()
    assert cfgmod.onboarding_done()
    assert closed
    for _ in range(50):
        if started:
            break
        time.sleep(0.01)
    assert started
    assert "Setup guide…" in [row[0]() for row in app.menu() if row is not None]


class _FakeBackend:
    def __init__(self):
        self.unloaded = False

    def unload(self):
        self.unloaded = True


def test_failed_dictation_start_frees_the_model(monkeypatch):
    import local_stt.cli as cli
    import local_stt.dictation.daemon as daemon_mod
    from local_stt.tray import TrayApp

    backend = _FakeBackend()
    stopped = []

    class FailingDaemon:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("macOS blocks reading the shortcut.")

        def stop(self):
            stopped.append(True)

    monkeypatch.setattr(cli, "_build_backend", lambda cfg: backend)
    monkeypatch.setattr(daemon_mod, "DictationDaemon", FailingDaemon)
    monkeypatch.setattr("local_stt.tray._notify", lambda *a: None)
    app = TrayApp(_cfg())
    assert app.start_dictation() == "macOS blocks reading the shortcut."
    assert not app.dictation_on()
    assert stopped and backend.unloaded


def test_saving_meeting_settings_keeps_dictation_running(monkeypatch):
    import copy

    from local_stt.tray import TrayApp

    app = TrayApp(_cfg())
    app._daemon = object()
    restarts = []
    monkeypatch.setattr(app, "_stop_daemon_locked", lambda: restarts.append("stop"))
    monkeypatch.setattr(app, "_start_daemon_locked", lambda notify=True: restarts.append("start"))

    cfg = copy.deepcopy(app.config)
    cfg.meeting.output_dir = "~/elsewhere"
    assert app.apply_config(cfg) is None
    assert restarts == []

    cfg = copy.deepcopy(cfg)
    cfg.dictation.hotkey = "alt_r"
    app.apply_config(cfg)
    assert restarts == ["stop", "start"]
