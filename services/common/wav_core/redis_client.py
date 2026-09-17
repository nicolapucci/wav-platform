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

    socket_timeout esplicito: senza, worker-service/app/main.py::main() vedeva
    ogni singola XREADGROUP con block=5000 fallire con
    "redis.exceptions.TimeoutError: Timeout reading from redis:6379" quando lo
    stream era vuoto (mai quando c'era un job da leggere, la risposta lì arriva
    subito) - non perdeva job, ma girava a vuoto ogni ~1s invece di bloccarsi
    per i 5s previsti, sprecando CPU e riempiendo i log di rumore. Il timeout
    di lettura che redis-py applica di default a un comando generico (non
    Pub/Sub, che ha una gestione a parte) risulta più corto del block più
    lungo usato in questo codebase (5s): 10s dà margine a qualunque block
    presente o futuro senza dover ricalcolarlo caso per caso.
    """
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=10)
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
