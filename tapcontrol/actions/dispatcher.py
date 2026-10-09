"""Action dispatcher: runs gesture actions off the audio threads.

Runs in its own worker thread, consumes a queue of GestureResults, and calls
the real Windows integration. If action execution takes longer than the queue
allows, duplicate suppression and queue cap protect the system.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

from ..gestures.recognizer import GestureResult
from . import win_actions


class ActionDispatcher:
    def __init__(self, max_queue: int = 32,
                 on_executed: Optional[Callable[[GestureResult, bool], None]] = None):
        self._q: "queue.Queue[GestureResult]" = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_executed = on_executed
        self._last_action: Optional[tuple[float, str]] = None
        self._dedupe_window_s = 0.35

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="TapActions",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._thread = None

    def submit(self, result: GestureResult) -> None:
        try:
            self._q.put_nowait(result)
        except queue.Full:
            pass   # drop, prevent backlog from replaying stale gestures

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            ok = False
            now = time.monotonic()
            if self._last_action and self._last_action[1] == result.action \
                    and (now - self._last_action[0]) < self._dedupe_window_s:
                ok = True    # already executed this action just now
            else:
                try:
                    ok = win_actions.execute_action(result.action)
                except Exception:
                    ok = False
                self._last_action = (now, result.action)
            if self._on_executed:
                try:
                    self._on_executed(result, ok)
                except Exception:
                    pass
