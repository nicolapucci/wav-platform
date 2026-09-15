from psycopg_pool import ConnectionPool

from .config import settings

# Pool condiviso dal processo: ogni pod (api-service, ws-gateway, worker-service)
# ne istanzia uno proprio all'avvio.
pool = ConnectionPool(
    conninfo=settings.database_url,
    min_size=2,
    max_size=10,
    kwargs={"autocommit": True},
)


def get_conn():
    """Dependency FastAPI: fornisce una connessione dal pool per la durata della request."""
    with pool.connection() as conn:
        yield conn
