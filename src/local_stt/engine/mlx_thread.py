"""The one thread all MLX work in the process runs on: MLX binds streams to the
thread that made them, and Parakeet and the cleanup model share the GPU."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def run(fn, *args):
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
        executor = _executor
    return executor.submit(fn, *args).result()
