"""Response cache for provider calls.

Caching is an optimisation, not a safety control, so a Redis outage degrades to
"no cache" (logged) rather than blocking research. Cached payloads keep their
ORIGINAL retrieval time so provenance is never refreshed by a cache hit.
"""

from __future__ import annotations

import logging
from typing import Protocol

import redis

from app.core.rate_limit import get_redis

log = logging.getLogger(__name__)


class ResponseCache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...


class RedisResponseCache:
    prefix = "mdcache:"

    def get(self, key: str) -> str | None:
        try:
            raw = get_redis().get(self.prefix + key)
        except redis.RedisError:
            log.warning("market-data cache unavailable (get %s)", key)
            return None
        return raw.decode() if raw is not None else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        try:
            get_redis().set(self.prefix + key, value, ex=ttl_seconds)
        except redis.RedisError:
            log.warning("market-data cache unavailable (set %s)", key)


class NullCache:
    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        return None
