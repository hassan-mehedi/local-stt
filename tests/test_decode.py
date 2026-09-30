import wave

import numpy as np

from local_stt.audio.decode import decode_to_pcm


def _write_wav(path, rate, channels, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())


def test_pcm16_wav_is_read_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)  # no ffmpeg anywhere
    t = np.arange(48000) / 48000
    tone = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    stereo = np.stack([tone, tone], axis=1).reshape(-1)
    path = tmp_path / "system.wav"
    _write_wav(path, 48000, 2, stereo)

    pcm = decode_to_pcm(path)

    assert pcm.dtype == np.float32
    assert abs(len(pcm) - 16000) <= 1  # 1s, resampled 48k -> 16k, mono
    assert 0.45 < np.abs(pcm).max() < 0.5
