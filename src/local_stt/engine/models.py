"""Model registry, local cache management, CUDA library preload."""

from __future__ import annotations

import ctypes
import glob
import os
import shutil
import sys
from pathlib import Path

from ..config import MODELS_DIR

# Known model names accepted by faster-whisper, smallest to largest.
KNOWN_MODELS = [
    "tiny",
    "base",
    "small",
    "medium",
    "distil-large-v3",
    "large-v3",
    "large-v3-turbo",
]


def model_dir(name: str) -> Path:
    return MODELS_DIR / name


def is_downloaded(name: str) -> bool:
    d = model_dir(name)
    return d.is_dir() and (d / "model.bin").exists()


def download(name: str) -> Path:
    """Download a model into the local cache; returns its directory."""
    from faster_whisper import download_model

    dest = model_dir(name)
    dest.mkdir(parents=True, exist_ok=True)
    download_model(name, output_dir=str(dest))
    return dest


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
