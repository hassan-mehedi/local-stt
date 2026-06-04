"""Decode any ffmpeg-readable media to 16kHz mono float32 PCM."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np


def decode_to_pcm(path: Path) -> np.ndarray:
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg is required to decode audio files. Install it with: "
            "sudo apt install ffmpeg"
        )
    if not Path(path).exists():
        raise FileNotFoundError(f"No such file: {path}")
    proc = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-i", str(path),
            "-f", "f32le", "-ac", "1", "-ar", "16000",
            "-",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode().strip()}")
    return np.frombuffer(proc.stdout, dtype=np.float32)
