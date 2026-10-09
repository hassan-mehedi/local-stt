import sys
import threading
from types import SimpleNamespace

import pytest

from local_stt.cleanup import local
from local_stt.cleanup.local import LocalCleaner


@pytest.fixture
def fake_mlx_lm(tmp_path, monkeypatch):
    """A downloaded-looking model folder and an mlx_lm that records its threads."""
    monkeypatch.setattr(local, "MODELS_DIR", tmp_path)
    threads = []

    class Tokenizer:
        def apply_chat_template(self, messages, add_generation_prompt, tokenize):
            return "|".join(m["content"] for m in messages)

    def load(path):
        threads.append(threading.current_thread())
        return object(), Tokenizer()

    def generate(model, tokenizer, prompt, max_tokens):
        threads.append(threading.current_thread())
        return f"cleaned:{prompt}"

    monkeypatch.setitem(sys.modules, "mlx_lm", SimpleNamespace(load=load, generate=generate))
    return threads


def _download(tmp_path):
    d = tmp_path / "cleanup-qwen3-4b"
    d.mkdir()
    (d / "config.json").write_text("{}")
    (d / "model.safetensors").write_bytes(b"")


def test_local_cleaner_runs_load_and_generate_on_the_mlx_thread(fake_mlx_lm, tmp_path):
    _download(tmp_path)
    cleaner = LocalCleaner("qwen3-4b")
    cleaner.load()
    reply = cleaner.complete([{"role": "user", "content": "um hi"}], 20)
    assert reply == "cleaned:um hi"
    assert len(set(fake_mlx_lm)) == 1
    assert threading.current_thread() not in fake_mlx_lm


def test_local_cleaner_asks_for_the_download_first(fake_mlx_lm):
    with pytest.raises(FileNotFoundError, match="Download it in Settings"):
        LocalCleaner("qwen3-4b").load()


@pytest.mark.parametrize("name", ["../models", "gpt-9"])
def test_local_model_dir_rejects_unknown_names(name):
    with pytest.raises(ValueError):
        local.model_dir(name)
