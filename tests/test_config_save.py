import pytest

from local_stt.config import Config, ConfigError, load_config, save_config, validate


def test_validate_rejects_unknown_model():
    cfg = Config()
    cfg.model.name = "huge-v9"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_validate_rejects_bad_enum():
    cfg = Config()
    cfg.dictation.mode = "sideways"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_validate_rejects_bad_hotkey():
    cfg = Config()
    cfg.dictation.hotkey = "<alt>+<ctrl>"  # no trigger key
    with pytest.raises(ConfigError):
        validate(cfg)


def test_validate_accepts_defaults():
    assert validate(Config()) is not None


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config()
    cfg.model.name = "medium"
    cfg.dictation.hotkey = "<ctrl>+<alt>+d"
    cfg.dictation.mode = "hold"
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.model.name == "medium"
    assert loaded.dictation.hotkey == "<ctrl>+<alt>+d"
    assert loaded.dictation.mode == "hold"


def test_save_preserves_comments(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[model]\n"
        "# I picked turbo on purpose\n"
        'name = "large-v3-turbo"\n'
    )
    cfg = load_config(path)
    cfg.model.name = "medium"
    save_config(cfg, path)

    text = path.read_text()
    assert "# I picked turbo on purpose" in text
    assert 'name = "medium"' in text


def test_save_rejects_invalid_without_writing(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config()
    cfg.model.name = "nonsense"
    with pytest.raises(ConfigError):
        save_config(cfg, path)
    assert not path.exists()  # nothing written on validation failure
