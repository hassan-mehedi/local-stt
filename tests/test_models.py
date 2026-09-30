import pytest

import local_stt.engine.models as models


@pytest.fixture(autouse=True)
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path / "models")
    return tmp_path


@pytest.mark.parametrize("name", ["../..", "../../Documents", "/etc", "org/repo"])
def test_remove_rejects_names_outside_the_registry(models_dir, name):
    keep = models_dir / "Documents"
    keep.mkdir()
    with pytest.raises(ValueError):
        models.remove(name)
    assert keep.exists()


def test_is_downloaded_is_false_for_unknown_names():
    assert models.is_downloaded("../..") is False


def test_remove_deletes_a_known_model(models_dir):
    d = models_dir / "models" / "tiny"
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"")
    assert models.is_downloaded("tiny")
    models.remove("tiny")
    assert not d.exists()


def test_parakeet_needs_both_files(models_dir):
    d = models_dir / "models" / "parakeet-tdt-0.6b-v3"
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    assert not models.is_downloaded("parakeet-tdt-0.6b-v3")
    (d / "model.safetensors").write_bytes(b"")
    assert models.is_downloaded("parakeet-tdt-0.6b-v3")


def test_parakeet_is_unavailable_off_apple_silicon(monkeypatch):
    monkeypatch.setattr(models, "is_apple_silicon", lambda: False)
    assert models.unavailable_reason("parakeet-tdt-0.6b-v3")
    assert models.unavailable_reason("large-v3-turbo") is None
    with pytest.raises(RuntimeError):
        models.download("parakeet-tdt-0.6b-v3")


def test_download_progress_compares_bytes_on_disk_to_the_model_size(models_dir):
    d = models.model_dir("tiny")
    assert models.download_progress("tiny") == 0
    (d / ".cache").mkdir(parents=True)
    (d / ".cache" / "model.bin.incomplete").write_bytes(b"x" * 15_000_000)
    size = models.spec("tiny").size_mb * 1_000_000
    assert models.download_progress("tiny") == pytest.approx(15_000_000 / size)


def test_download_progress_is_unknown_while_converting(models_dir):
    assert models.download_progress("bengali-whisper-medium") is None


def test_download_hint_depends_on_the_install(monkeypatch):
    import local_stt.desktop as desktop
    from local_stt.engine import models

    monkeypatch.setattr(desktop, "app_bundle", lambda: None)
    assert models.download_hint("parakeet-tdt-0.6b-v2") == "Run: stt models download parakeet-tdt-0.6b-v2"
    monkeypatch.setattr(desktop, "app_bundle", lambda: "/Applications/local-stt.app")
    assert "local-stt Settings" in models.download_hint("parakeet-tdt-0.6b-v2")
