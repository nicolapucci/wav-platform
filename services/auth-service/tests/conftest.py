"""Stesso pattern di services/api-service/tests/conftest.py: cloni Postgres e
Redis usa-e-getta (container Docker, stesse migrazioni di db/migrations),
DATABASE_URL/REDIS_URL impostate PRIMA di importare app.main perché
wav_core.db/wav_core.config leggono l'ambiente al momento dell'import (vedi
commento lì per i dettagli). Redis serve da quando main.py ha guadagnato
rate-limiting per IP e lockout per account (get_redis_sync)."""

import os
import socket
import subprocess
import time
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

_PG_CONTAINER = "wav-test-postgres-auth"
_REDIS_CONTAINER = "wav-test-redis-auth"


def _docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} fallito: {result.stderr}")
    return result.stdout.strip()


def _host_port(container: str, container_port: str) -> int:
    output = _docker("port", container, container_port)
    return int(output.splitlines()[0].rsplit(":", 1)[1])


def _wait_tcp(host: str, port: int, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"{host}:{port} non raggiungibile entro {timeout}s")


def _start_postgres() -> str:
    subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True)
    _docker(
        "run", "-d", "--rm", "--name", _PG_CONTAINER,
        "-e", "POSTGRES_USER=wav_test",
        "-e", "POSTGRES_PASSWORD=wav_test",
        "-e", "POSTGRES_DB=wav_test",
        "-p", "127.0.0.1::5432",
        "postgres:16",
    )
    port = _host_port(_PG_CONTAINER, "5432/tcp")
    url = f"postgresql://wav_test:wav_test@127.0.0.1:{port}/wav_test"

    deadline = time.time() + 30
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(url, autocommit=True) as conn:
                for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                    conn.execute(migration.read_text(encoding="utf-8"))
            return url
        except psycopg.OperationalError as exc:
            last_err = exc
            time.sleep(0.5)
    raise RuntimeError(f"Postgres di test non pronto in tempo: {last_err}")


def _start_redis() -> str:
    subprocess.run(["docker", "rm", "-f", _REDIS_CONTAINER], capture_output=True)
    _docker("run", "-d", "--rm", "--name", _REDIS_CONTAINER, "-p", "127.0.0.1::6379", "redis:7")
    port = _host_port(_REDIS_CONTAINER, "6379/tcp")
    _wait_tcp("127.0.0.1", port, timeout=15)
    return f"redis://127.0.0.1:{port}/0"


def _teardown_containers() -> None:
    subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True)
    subprocess.run(["docker", "rm", "-f", _REDIS_CONTAINER], capture_output=True)


os.environ["DATABASE_URL"] = _start_postgres()
os.environ["REDIS_URL"] = _start_redis()
os.environ.setdefault("JWT_SECRET", "test-secret-non-usato-in-produzione")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "30")

from app.main import app  # noqa: E402 (deve seguire il setup env sopra)
from fastapi.testclient import TestClient  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    _teardown_containers()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_conn():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


@pytest.fixture(autouse=True)
def _clean_db(db_conn):
    yield
    with db_conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [r[0] for r in cur.fetchall()]
    if tables:
        with db_conn.cursor() as cur:
            cur.execute(f"TRUNCATE {', '.join(tables)} CASCADE")


@pytest.fixture(autouse=True)
def _clean_rate_limit_state():
    """rate-limit e lockout vivono in Redis per l'intera sessione di test, non
    per singolo test come il DB - senza pulizia un test che conta le proprie
    richieste erediterebbe il contatore lasciato da quello precedente."""
    from wav_core.redis_client import get_redis_sync

    yield
    r = get_redis_sync()
    for pattern in ("ratelimit:*", "loginfail:*"):
        for key in r.scan_iter(match=pattern):
            r.delete(key)
