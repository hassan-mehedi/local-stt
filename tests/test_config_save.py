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


def test_validate_rejects_language_the_model_lacks(monkeypatch):
    import local_stt.engine.models as models

    monkeypatch.setattr(models, "is_apple_silicon", lambda: True)
    cfg = Config()
    cfg.model.name = "parakeet-tdt-0.6b-v2"
    cfg.model.language = "de"
    with pytest.raises(ConfigError, match="does not support language 'de'"):
        validate(cfg)
    cfg.model.name = "parakeet-tdt-0.6b-v3"
    assert validate(cfg)


def test_validate_rejects_parakeet_off_apple_silicon(monkeypatch):
    import local_stt.engine.models as models

    monkeypatch.setattr(models, "is_apple_silicon", lambda: False)
    cfg = Config()
    cfg.model.name = "parakeet-tdt-0.6b-v3"
    with pytest.raises(ConfigError, match="Apple Silicon"):
        validate(cfg)


@pytest.mark.parametrize("changes, error", [
    ({"api_url": "", "api_model": "deepseek-flash"}, "API URL"),
    ({"api_url": "ftp://x", "api_model": "m"}, "http"),
    ({"api_url": "http://api.deepseek.com", "api_model": "m"}, "https"),
    ({"api_url": "https://api.deepseek.com", "api_model": ""}, "model name"),
    ({"api_url": "https://api.deepseek.com", "api_model": "deepseek-flash"}, None),
    ({"api_url": "http://localhost:11434/v1", "api_model": "qwen3"}, None),
])
def test_validate_checks_cleanup_settings(monkeypatch, changes, error):
    import local_stt.engine.models as models

    monkeypatch.setattr(models, "is_apple_silicon", lambda: True)
    cfg = Config()
    cfg.cleanup.enabled = True
    for key, value in changes.items():
        setattr(cfg.cleanup, key, value)
    if error is None:
        assert validate(cfg)
    else:
        with pytest.raises(ConfigError, match=error):
            validate(cfg)


def test_load_turns_off_a_cleanup_with_no_api(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[cleanup]\nenabled = true\nprovider = "local"\nmodel = "qwen3-4b"\napi_url = ""\n')
    assert load_config(path).cleanup.enabled is False
    path.write_text('[cleanup]\nenabled = true\napi_url = "https://api.deepseek.com"\napi_model = "deepseek-flash"\n')
    assert load_config(path).cleanup.enabled is True


def test_save_drops_keys_the_config_no_longer_has(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[cleanup]\n# kept\nenabled = false\nprovider = "local"\nmodel = "qwen3-4b"\n\n[extra]\nmine = 1\n')
    save_config(load_config(path), path)
    text = path.read_text()
    assert "provider" not in text and "qwen3-4b" not in text
    assert "# kept" in text and "mine = 1" in text
