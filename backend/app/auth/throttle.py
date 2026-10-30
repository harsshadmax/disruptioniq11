"""Login throttle: too many failures for one email (or from one address) in a window earns a 429.

In memory and per process, which is enough to stop a script guessing passwords against one API instance.
A multi-instance deployment would move the counters to the database or a cache.
"""
import threading
import time
from collections import defaultdict, deque

MAX_FAILURES = 8
WINDOW_SECONDS = 600

_lock = threading.Lock()
_failures: dict[str, deque[float]] = defaultdict(deque)


def _recent(key: str, now: float) -> deque[float]:
    q = _failures[key]
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    return q


def blocked(*keys: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    with _lock:
        return any(len(_recent(k, now)) >= MAX_FAILURES for k in keys)


def record_failure(*keys: str, now: float | None = None) -> int:
    """Count one failed login against every key; returns the highest count so the caller can audit the first block."""
    now = time.monotonic() if now is None else now
    with _lock:
        counts = []
        for k in keys:
            q = _recent(k, now)
            q.append(now)
            counts.append(len(q))
        return max(counts)


def clear(*keys: str) -> None:
    with _lock:
        for k in keys:
            _failures.pop(k, None)


def reset_all() -> None:
    with _lock:
        _failures.clear()
