"""In-process sliding-window rate limiter.

Enough to stop credential stuffing and review spam on a single-node deployment.
Swap for Redis when there is more than one process.
"""
from __future__ import annotations

import time

_buckets: dict[str, list[float]] = {}


def allow(key: str, limit: int, window_seconds: float = 60.0) -> bool:
    if limit <= 0:
        return True
    now = time.time()
    hits = [t for t in _buckets.get(key, []) if now - t < window_seconds]
    if len(hits) >= limit:
        _buckets[key] = hits
        return False
    hits.append(now)
    _buckets[key] = hits
    return True


def reset() -> None:
    _buckets.clear()
