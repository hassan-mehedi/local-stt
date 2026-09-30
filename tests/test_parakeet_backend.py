import threading
from types import SimpleNamespace

import numpy as np

from local_stt.cli import _build_backend
from local_stt.config import Config
from local_stt.engine.backend import TranscribeOptions, Word
from local_stt.engine.faster_whisper_backend import FasterWhisperBackend
from local_stt.engine.parakeet_mlx_backend import ParakeetMlxBackend, _words


def _token(text, start, end):
    return SimpleNamespace(text=text, start=start, end=end)


def test_words_join_subword_tokens():
    tokens = [
        _token(" Hel", 0.0, 0.2), _token("lo,", 0.2, 0.4),
        _token(" Sa", 0.6, 0.7), _token("rah", 0.7, 0.9),
    ]
    assert _words(tokens) == [
        Word(0.0, 0.4, " Hello,"),
        Word(0.6, 0.9, " Sarah"),
    ]


def test_build_backend_picks_engine_by_model_family():
    cfg = Config()
    cfg.model.name = "large-v3-turbo"
    assert isinstance(_build_backend(cfg), FasterWhisperBackend)
    assert isinstance(
        _build_backend(cfg, model_override="parakeet-tdt-0.6b-v3"), ParakeetMlxBackend
    )


class FakeParakeet(ParakeetMlxBackend):
    """Records which thread each MLX step runs on; no MLX needed."""

    def __init__(self):
        super().__init__("parakeet-tdt-0.6b-v2")
        self.threads = []

    def _load(self):
        self.threads.append(threading.current_thread())
        self._model = self._model or object()
        return self._model

    def _run_short(self, model, pcm):
        self.threads.append(threading.current_thread())
        sentence = SimpleNamespace(
            text=" Hi there.", start=0.0, end=0.8,
            tokens=[_token(" Hi", 0.0, 0.3), _token(" there.", 0.3, 0.8)],
        )
        return SimpleNamespace(sentences=[sentence])

    def _unload(self):
        self.threads.append(threading.current_thread())
        self._model = None


def test_load_and_transcribe_share_one_thread_across_callers():
    b = FakeParakeet()
    loader = threading.Thread(target=b.load)
    loader.start()
    loader.join()

    out = {}
    worker = threading.Thread(
        target=lambda: out.update(
            t=b.transcribe_audio(np.zeros(16000, np.float32), 16000, TranscribeOptions())
        )
    )
    worker.start()
    worker.join()

    assert len(set(b.threads)) == 1
    assert threading.current_thread() not in b.threads
    assert out["t"].text == "Hi there."
    assert out["t"].language == "en"  # v2 is English-only


def test_unload_stops_the_worker_and_reload_starts_a_new_one():
    b = FakeParakeet()
    b.load()
    first = b.threads[-1]
    b.unload()
    assert b._executor is None
    b.load()
    assert b.threads[-1] != first
    b.unload()
