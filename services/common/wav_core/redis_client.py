import redis as redis_sync
import redis.asyncio as redis

from .config import settings

_redis: redis.Redis | None = None
_redis_sync: redis_sync.Redis | None = None


def get_redis() -> redis.Redis:
    """Client Redis asincrono, singleton per processo.

    Usato per: Pub/Sub degli eventi realtime (evt:*) e come base per gli
    Streams della coda job (stream:jobs) - entrambi chiamati da codice async.
    Per la cache dei permessi vedi get_redis_sync() sotto.
    """
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def get_redis_sync() -> redis_sync.Redis:
    """Client Redis sincrono, singleton per processo.

    Usato dalla cache dei permessi (wav_core.permissions): la risoluzione
    permessi gira in endpoint FastAPI sincroni (query psycopg sincrone), quindi
    serve un client bloccante - redis.asyncio.Redis (get_redis, sopra) non è
    utilizzabile lì senza rendere async l'intera catena di chiamata.
    """
    global _redis_sync
    if _redis_sync is None:
        _redis_sync = redis_sync.from_url(settings.redis_url, decode_responses=True)
    return _redis_sync
