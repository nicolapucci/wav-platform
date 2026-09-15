import redis.asyncio as redis

from .config import settings

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Client Redis asincrono, singleton per processo.

    Usato per: cache dei permessi, Pub/Sub degli eventi realtime (evt:*),
    e come base per gli Streams della coda job (stream:jobs).
    """
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis
