import pytest

import local_stt.config as cfgmod
from local_stt.config import Config, load_config


def test_defaults_when_missing(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.model.name == cfgmod.default_model()
    assert cfg.dictation.hotkey == "<alt>+<shift>+t"
    assert cfg.dictation.mode == "toggle"
    assert cfg.dictation.output == "type"
    assert cfg.dictation.min_duration_ms == 300


@pytest.mark.parametrize(
    "plat, machine, expected",
    [
        ("darwin", "arm64", "parakeet-tdt-0.6b-v2"),
        ("darwin", "x86_64", "large-v3-turbo"),
        ("linux", "x86_64", "large-v3-turbo"),
    ],
)
def test_default_model_per_platform(monkeypatch, plat, machine, expected):
    monkeypatch.setattr(cfgmod.sys, "platform", plat)
    monkeypatch.setattr(cfgmod.platform, "machine", lambda: machine)
    assert Config().model.name == expected


def test_partial_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        """
[model]
name = "medium"

[dictation]
hotkey = "<ctrl>+<alt>+d"
"""
    )
    cfg = load_config(p)
    assert cfg.model.name == "medium"
    assert cfg.model.compute_type == "float16"  # default preserved
    assert cfg.dictation.hotkey == "<ctrl>+<alt>+d"
    assert cfg.dictation.output == "type"  # default preserved


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[model]\nname = 'small'\nfuture_option = true\n")
    cfg = load_config(p)
    assert cfg.model.name == "small"


def test_onboarding_state_round_trip(tmp_path, monkeypatch):
    import local_stt.config as cfgmod

    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.toml")
    assert cfgmod.load_onboarding() == {"done": False, "step": 0}
    cfgmod.save_onboarding(step=2)
    assert cfgmod.load_onboarding() == {"done": False, "step": 2}
    cfgmod.mark_onboarding_done()
    assert cfgmod.onboarding_done()
    assert cfgmod.load_onboarding()["step"] == 0


def test_corrupt_onboarding_file_counts_as_not_done(tmp_path, monkeypatch):
    import local_stt.config as cfgmod

    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.toml")
    (tmp_path / "onboarding.json").write_text("{not json")
    assert cfgmod.load_onboarding() == {"done": False, "step": 0}
