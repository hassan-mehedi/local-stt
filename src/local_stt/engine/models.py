"""Model registry, local cache management, CUDA library preload."""

from __future__ import annotations

import ctypes
import glob
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import MODELS_DIR

WHISPER = "whisper"
PARAKEET = "parakeet"

PARAKEET_V3_LANGUAGES = frozenset({
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "hr", "hu", "it",
    "lt", "lv", "mt", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "uk",
})


@dataclass(frozen=True)
class ModelSpec:
    name: str
    family: str  # WHISPER | PARAKEET
    size_mb: int  # approximate download size, display-only
    languages_label: str
    # None = any language Whisper knows; Parakeet cannot be forced to one
    languages: frozenset[str] | None = None
    mlx_repo: str | None = None
    # a Hugging Face transformers Whisper fine-tune, converted to CTranslate2
    # on download (needs the [convert] extra)
    convert_from: str | None = None


# smallest to largest within each family
MODELS = {
    spec.name: spec
    for spec in [
        ModelSpec("tiny", WHISPER, 75, "99 languages"),
        ModelSpec("base", WHISPER, 145, "99 languages"),
        ModelSpec("small", WHISPER, 484, "99 languages"),
        ModelSpec("medium", WHISPER, 1530, "99 languages"),
        ModelSpec("distil-large-v3", WHISPER, 1510, "English"),
        ModelSpec("large-v3", WHISPER, 3090, "99 languages"),
        ModelSpec("large-v3-turbo", WHISPER, 1620, "99 languages"),
        ModelSpec(
            "parakeet-tdt-0.6b-v2", PARAKEET, 2470, "English",
            languages=frozenset({"en"}),
            mlx_repo="mlx-community/parakeet-tdt-0.6b-v2",
        ),
        ModelSpec(
            "parakeet-tdt-0.6b-v3", PARAKEET, 2510, "25 European languages",
            languages=PARAKEET_V3_LANGUAGES,
            mlx_repo="mlx-community/parakeet-tdt-0.6b-v3",
        ),
        ModelSpec(
            "bengali-whisper-medium", WHISPER, 1530, "Bengali",
            languages=frozenset({"bn"}),
            convert_from="bengaliAI/tugstugi_bengaliai-asr_whisper-medium",
        ),
    ]
}
KNOWN_MODELS = list(MODELS)


def spec(name: str) -> ModelSpec:
    try:
        return MODELS[name]
    except KeyError:
        raise ValueError(
            f"Unknown model {name!r}. Choose one of: {', '.join(KNOWN_MODELS)}"
        ) from None


def is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def unavailable_reason(name: str) -> str | None:
    """Why this model can't run on this machine, or None if it can."""
    if spec(name).family == PARAKEET and not is_apple_silicon():
        return "Parakeet runs on Apple Silicon only for now"
    return None


def best_for_language(language: str) -> str | None:
    """A downloaded model for `language`, preferring single-language
    fine-tunes (e.g. bengali-whisper-medium for "bn") over general models."""
    candidates = [
        s for s in MODELS.values()
        if is_downloaded(s.name)
        and unavailable_reason(s.name) is None
        and (s.languages is None or language in s.languages)
    ]
    candidates.sort(key=lambda s: s.languages != frozenset({language}))
    return candidates[0].name if candidates else None


def model_dir(name: str) -> Path:
    return MODELS_DIR / spec(name).name


def is_downloaded(name: str) -> bool:
    if name not in MODELS:
        return False
    d = model_dir(name)
    if MODELS[name].family == PARAKEET:
        return (d / "config.json").exists() and (d / "model.safetensors").exists()
    return (d / "model.bin").exists()


def download_hint(name: str) -> str:
    from ..desktop import app_bundle

    if app_bundle():
        return f"Download {name} in local-stt Settings."
    return f"Run: stt models download {name}"


def download_progress(name: str) -> float | None:
    """Share of the expected size on disk so far, or None while a
    conversion runs (it downloads into a temp dir first)."""
    s = spec(name)
    if s.convert_from or not s.size_mb:
        return None
    d = model_dir(name)
    done = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.is_dir() else 0
    return min(done / (s.size_mb * 1_000_000), 0.99)


def download(name: str) -> Path:
    """Download a model into the local cache; returns its directory."""
    s = spec(name)
    if reason := unavailable_reason(name):
        raise RuntimeError(f"{name}: {reason}")
    dest = model_dir(name)
    dest.mkdir(parents=True, exist_ok=True)
    if s.family == PARAKEET:
        from huggingface_hub import snapshot_download

        snapshot_download(
            s.mlx_repo,
            local_dir=dest,
            allow_patterns=["config.json", "model.safetensors"],
        )
    elif s.convert_from:
        _convert_whisper(s.convert_from, dest)
    else:
        from faster_whisper import download_model

        download_model(name, output_dir=str(dest))
    return dest


def _convert_whisper(repo: str, dest: Path) -> None:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        from ctranslate2.converters import TransformersConverter
    except ImportError:
        raise RuntimeError(
            "Converting this model needs the convert extra (transformers + torch):\n"
            "  uv tool install --editable '.[convert]'"
        ) from None
    import tempfile

    from huggingface_hub import snapshot_download

    # download next to the cache (not into ~/.cache/huggingface) so the ~3 GB
    # of original weights are deleted once converted
    with tempfile.TemporaryDirectory(dir=MODELS_DIR, prefix=".convert-") as tmp:
        src = snapshot_download(repo, local_dir=tmp)
        TransformersConverter(
            src, copy_files=["tokenizer.json", "preprocessor_config.json"]
        ).convert(str(dest), quantization="float16", force=True)


def remove(name: str) -> None:
    d = model_dir(name)
    if d.is_dir():
        shutil.rmtree(d)


def preload_cuda_libraries() -> None:
    """Load cuBLAS/cuDNN shared libraries from pip-installed NVIDIA packages.

    ctranslate2 dlopens these at runtime; without this, CUDA inference fails
    unless the libs are on LD_LIBRARY_PATH. Safe no-op if packages are absent.
    """
    lib_dirs = []
    for pkg in ("nvidia.cublas.lib", "nvidia.cudnn.lib"):
        try:
            mod = __import__(pkg, fromlist=["__path__"])
            lib_dirs.extend(list(mod.__path__))
        except ImportError:
            pass
    for d in lib_dirs:
        for so in sorted(glob.glob(os.path.join(d, "*.so*"))):
            try:
                ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
