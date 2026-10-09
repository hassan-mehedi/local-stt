import sys
import threading
import time
import types

import numpy as np
import pytest

from local_stt.audio import capture
from local_stt.audio.capture import Recorder


class FakeStream:
    """Feeds one block of audio on start; stop() waits for `release`."""

    def __init__(self, release: threading.Event, callback, **_):
        self.release = release
        self.callback = callback

    def start(self):
        self.callback(np.full((1600, 1), 0.5, dtype=np.float32), 1600, None, None)

    def stop(self):
        self.release.wait()

    def close(self):
        pass


@pytest.fixture
def stream_release(monkeypatch):
    release = threading.Event()
    sd = types.SimpleNamespace(
        InputStream=lambda **kw: FakeStream(release, **kw), PortAudioError=OSError
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setattr(capture, "STOP_TIMEOUT_S", 0.2)
    yield release
    release.set()


def test_recorder_stop_returns_the_audio_when_the_stream_hangs(stream_release, caplog):
    rec = Recorder()
    rec.start()

    t0 = time.monotonic()
    pcm = rec.stop()

    assert time.monotonic() - t0 < 1
    assert len(pcm) == 1600
    assert not rec.recording
    assert "microphone did not stop" in caplog.text


def test_recorder_starts_again_while_the_old_stream_still_closes(stream_release):
    rec = Recorder()
    rec.start()
    rec.stop()

    rec.start()

    assert rec.recording
    assert len(rec.stop()) == 1600
