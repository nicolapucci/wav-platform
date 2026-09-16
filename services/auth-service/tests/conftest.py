"""Stesso pattern di services/api-service/tests/conftest.py: un clone
Postgres usa-e-getta (container Docker, stesse migrazioni di db/migrations),
DATABASE_URL impostata PRIMA di importare app.main perché wav_core.db crea il
ConnectionPool al momento dell'import (vedi commento lì per i dettagli). Niente
container Redis qui: auth-service non lo usa (solo users via wav_core.db)."""

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


def _docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} fallito: {result.stderr}")
    return result.stdout.strip()


def _host_port(container: str, container_port: str) -> int:
    output = _docker("port", container, container_port)
    return int(output.splitlines()[0].rsplit(":", 1)[1])


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


def _teardown_containers() -> None:
    subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True)


os.environ["DATABASE_URL"] = _start_postgres()
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")  # mai usato, ma Settings() lo richiede
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
