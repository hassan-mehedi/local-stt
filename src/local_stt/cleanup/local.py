"""Cleanup models that run on this Mac through mlx-lm."""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import MODELS_DIR
from ..engine import mlx_thread
from ..engine.models import is_apple_silicon

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanupModel:
    repo: str
    size_mb: int  # approximate download size, display-only
    label: str


MODELS = {
    "qwen3-4b": CleanupModel("mlx-community/Qwen3-4B-Instruct-2507-4bit", 2280, "Qwen3 4B"),
}


def _spec(name: str) -> CleanupModel:
    try:
        return MODELS[name]
    except KeyError:
        raise ValueError(f"Unknown cleanup model {name!r}") from None


def model_dir(name: str) -> Path:
    _spec(name)
    return MODELS_DIR / f"cleanup-{name}"


def is_downloaded(name: str) -> bool:
    d = model_dir(name)
    return (d / "config.json").exists() and any(d.glob("*.safetensors"))


def download_progress(name: str) -> float:
    d = model_dir(name)
    done = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.is_dir() else 0
    return min(done / (_spec(name).size_mb * 1_000_000), 0.99)


def download(name: str) -> Path:
    from huggingface_hub import constants, snapshot_download

    # xet transfers stall on some networks where plain HTTPS works
    constants.HF_HUB_DISABLE_XET = True

    if not is_apple_silicon():
        raise RuntimeError("Cleanup on this computer needs Apple Silicon; use an API instead")
    dest = model_dir(name)
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(_spec(name).repo, local_dir=dest)
    return dest


def remove(name: str) -> None:
    d = model_dir(name)
    if d.is_dir():
        shutil.rmtree(d)


class LocalCleaner:
    def __init__(self, name: str):
        self.name = name
        self._model = None
        self._tokenizer = None

    def load(self) -> None:
        mlx_thread.run(self._load)

    def _load(self) -> None:
        if self._model is not None:
            return
        if not is_downloaded(self.name):
            raise FileNotFoundError(
                f"The cleanup model {_spec(self.name).label} is not downloaded."
                " Download it in Settings."
            )
        from mlx_lm import generate, load

        t0 = time.monotonic()
        self._model, self._tokenizer = load(str(model_dir(self.name)))
        # warm the kernels so the first real cleanup isn't slow
        generate(self._model, self._tokenizer, "Hello", max_tokens=1)
        log.info("Loaded cleanup model %s in %.1fs", self.name, time.monotonic() - t0)

    def unload(self) -> None:
        if self._model is not None:
            mlx_thread.run(self._unload)

    def _unload(self) -> None:
        import mlx.core as mx

        self._model = self._tokenizer = None
        mx.clear_cache()

    def complete(self, messages: list[dict], max_tokens: int) -> str:
        return mlx_thread.run(self._complete, messages, max_tokens)

    def _complete(self, messages: list[dict], max_tokens: int) -> str:
        from mlx_lm import generate

        self._load()
        prompt = self._tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        return generate(self._model, self._tokenizer, prompt, max_tokens=max_tokens)
