"""
Async Redis client — used for rate limiting in the RAG bot.
Thin wrapper around redis.asyncio.
"""
from redis.asyncio import Redis, from_url
from core.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return _redis


async def increment_rate(key: str, window_seconds: int = 3600) -> int:
    """
    Atomically increment counter for `key`.
    Sets expiry of `window_seconds` on first increment.
    Returns the new counter value.
    """
    r = get_redis()
    current = await r.incr(key)
    if current == 1:
        await r.expire(key, window_seconds)
    return current
