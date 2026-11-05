"""Small in-memory sliding-window rate limiter (single-process; fine for local use)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import HTTPException, Request, status

from app.config import get_settings

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def _check(key: str, limit: int, window: float = 60.0) -> None:
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down and try again shortly.",
            )
        q.append(now)


def rate_limit(name: str, limit_getter: Callable[[], int]):
    def dependency(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        _check(f"{name}:{client}", limit_getter())

    return dependency


general_limit = rate_limit("general", lambda: get_settings().rate_limit_per_minute)
login_limit = rate_limit("login", lambda: get_settings().login_rate_limit_per_minute)
