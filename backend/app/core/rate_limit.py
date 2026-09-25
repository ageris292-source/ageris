"""Redis fixed-window rate limiter. Fails closed: if Redis is down, the
limited action is refused rather than allowed unthrottled."""

from __future__ import annotations

from functools import lru_cache

import redis

from app.core.settings import get_settings


class RateLimitUnavailableError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis[bytes]:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=2)


def redis_healthy() -> bool:
    try:
        return bool(get_redis().ping())
    except redis.RedisError:
        return False


def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Record one attempt; return True if still within the limit."""
    try:
        pipe = get_redis().pipeline()
        pipe.incr(f"ratelimit:{key}")
        pipe.expire(f"ratelimit:{key}", window_seconds, nx=True)
        count, _ = pipe.execute()
    except redis.RedisError as exc:
        raise RateLimitUnavailableError("rate limiter unavailable") from exc
    return int(count) <= limit
