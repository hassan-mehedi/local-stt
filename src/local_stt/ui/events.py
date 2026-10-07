"""Live events for the app window and the recording pill, sent as
server-sent events from /api/events."""

from __future__ import annotations

import json
import queue
import threading


class EventBus:
    def __init__(self, max_backlog: int = 256):
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []
        self._max_backlog = max_backlog

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(self._max_backlog)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, kind: str, data: dict | None = None) -> None:
        message = f"event: {kind}\ndata: {json.dumps(data or {})}\n\n".encode()
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(message)
            except queue.Full:
                pass  # a stalled reader misses events rather than holding memory
