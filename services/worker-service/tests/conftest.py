"""I due handler (handlers/audit.py, handlers/notification.py) prendono la
connessione DB come parametro esplicito: non serve importare wav_core.db né
app.main (che costruirebbero un ConnectionPool reale al momento dell'import,
vedi lo stesso problema documentato in services/api-service/tests/conftest.py)
- qui basta passare una connessione psycopg diretta al DB di test. Serve
comunque Redis reale, perché handle_notification pubblica su un canale
evt:user:{id}:notifications con wav_core.redis_client.get_redis()."""

import os
import socket
import subprocess
import time
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

_PG_CONTAINER = "wav-test-postgres-worker"
_REDIS_CONTAINER = "wav-test-redis-worker"


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


def pytest_sessionfinish(session, exitstatus):
    _teardown_containers()


@pytest.fixture(autouse=True)
def _reset_redis_singleton():
    """Stesso motivo di api-service/tests/conftest.py: il client redis.asyncio
    resta legato al loop su cui è stato creato la prima volta, e ogni test
    async gira sul proprio loop pytest-asyncio."""
    import wav_core.redis_client as redis_client_module

    redis_client_module._redis = None
    yield


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


@pytest.fixture
def make_user(db_conn):
    import uuid

    def _make(email: str | None = None, display_name: str = "Test User") -> str:
        email = email or f"{uuid.uuid4()}@example.com"
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, display_name, password_hash) VALUES (%s, %s, 'x') RETURNING id",
                (email, display_name),
            )
            return str(cur.fetchone()[0])
    return _make
