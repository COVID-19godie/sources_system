from __future__ import annotations

import threading
import time
from typing import Any

from app.core.config import settings


_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, Any]] = {}


def get_cached_graph(key: str) -> Any | None:
    ttl = max(1, int(settings.RAG_GRAPH_CACHE_TTL_SECONDS))
    now = time.time()
    with _LOCK:
        value = _CACHE.get(key)
        if value is None:
            return None
        created_at, payload = value
        if now - created_at > ttl:
            _CACHE.pop(key, None)
            return None
        return payload


def set_cached_graph(key: str, payload: Any) -> None:
    with _LOCK:
        _CACHE[key] = (time.time(), payload)


def invalidate_graph_cache(prefix: str | None = None) -> None:
    with _LOCK:
        if not prefix:
            _CACHE.clear()
            return
        keys = [item for item in _CACHE.keys() if item.startswith(prefix)]
        for key in keys:
            _CACHE.pop(key, None)
