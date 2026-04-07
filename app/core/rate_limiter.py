from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check_and_increment(self, key: str, *, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            bucket = self._events[key]

            while bucket and (now - bucket[0]) >= window_seconds:
                bucket.popleft()

            if len(bucket) >= max_requests:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                return False, retry_after

            bucket.append(now)
            return True, 0


rate_limiter = InMemoryRateLimiter()
