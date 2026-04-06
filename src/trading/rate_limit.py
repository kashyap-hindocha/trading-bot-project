from __future__ import annotations

import threading
import time
from collections import deque


class OrderRateLimiter:
    """Sliding window limiter for order submissions (default 2000 / 60s per spec)."""

    def __init__(self, max_calls: int = 2000, window_sec: float = 60.0) -> None:
        self.max_calls = max_calls
        self.window_sec = window_sec
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            wait = 0.0
            with self._lock:
                now = time.monotonic()
                cutoff = now - self.window_sec
                while self._times and self._times[0] < cutoff:
                    self._times.popleft()
                if len(self._times) < self.max_calls:
                    self._times.append(now)
                    return
                wait = self.window_sec - (now - self._times[0]) + 0.001
            time.sleep(max(wait, 0.01))
