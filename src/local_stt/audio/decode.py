"""Decode any ffmpeg-readable media to 16kHz mono float32 PCM."""

from __future__ import annotations

import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000  # what every speech model here expects


def write_wav(path: Path, pcm: np.ndarray) -> None:
    """Writes float32 PCM at SAMPLE_RATE as a 16-bit mono WAV."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2").tobytes())


def _read_pcm16_wav(path: Path) -> np.ndarray | None:
    """16-bit PCM WAVs (what the meeting recorders write) need no ffmpeg.
    Returns None for anything else."""
    try:
        with wave.open(str(path)) as w:
            if w.getsampwidth() != 2:
                return None
            rate, channels = w.getframerate(), w.getnchannels()
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return None
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm[: len(pcm) // channels * channels].reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(pcm):
        import soxr

        pcm = soxr.resample(pcm, rate, SAMPLE_RATE)
    return pcm.astype(np.float32, copy=False)


def decode_to_pcm(path: Path) -> np.ndarray:
    if not Path(path).exists():
        raise FileNotFoundError(f"No such file: {path}")
    if Path(path).suffix.lower() == ".wav":
        pcm = _read_pcm16_wav(Path(path))
        if pcm is not None:
            return pcm
    if not shutil.which("ffmpeg"):
        hint = "brew install ffmpeg" if sys.platform == "darwin" else "sudo apt install ffmpeg"
        raise RuntimeError(
            f"ffmpeg is required to decode audio files. Install it with: {hint}"
        )
    proc = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-i", str(path),
            "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode().strip()}")
    return np.frombuffer(proc.stdout, dtype=np.float32)
