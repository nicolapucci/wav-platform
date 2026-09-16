"""Fixture condivise. Il DB di test è un clone "usa e getta" dello schema
reale: stessa immagine postgres:16 e stesse migrazioni di db/migrations, in un
container Docker isolato creato e distrutto per l'intera sessione di test -
non tocca mai il Postgres di sviluppo/k8s.

ATTENZIONE ALL'ORDINE: wav_core.db costruisce il ConnectionPool (e
wav_core.config legge Settings()) al momento dell'IMPORT, non lazy. Per questo
i container Postgres/Redis vengono avviati e DATABASE_URL/REDIS_URL impostate
come codice a livello di modulo qui sotto - PRIMA di "from app.main import
app" più in basso in questo stesso file - invece che dentro una fixture:
una fixture, anche session-scoped e autouse, gira troppo tardi, perché pytest
importa già tutti i test_*.py (e quindi app.main) in fase di collection.
"""

import os
import random
import socket
import string
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

_PG_CONTAINER = "wav-test-postgres"
_REDIS_CONTAINER = "wav-test-redis"


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
from wav_core.security import create_access_token  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    _teardown_containers()


@pytest.fixture(scope="session")
def client():
    # deve restare un context manager per tutta la sessione: TestClient apre un
    # unico event loop/portal nel suo __enter__, condiviso da tutte le request.
    # Senza il "with", ogni chiamata può girare su un loop diverso e il client
    # redis.asyncio singleton (wav_core.redis_client) resta legato al primo
    # loop, poi "RuntimeError: Event loop is closed" alla richiesta successiva.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_conn():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


@pytest.fixture(autouse=True)
def _reset_redis_singleton():
    """wav_core.redis_client.get_redis() è un singleton di processo legato al
    loop asyncio in cui viene creato la prima volta. Il fixture "client"
    (TestClient) gira su un suo portal/loop dedicato, mentre i test asincroni
    diretti (test_events_publish.py) girano ognuno sul proprio loop
    pytest-asyncio: senza azzerarlo prima di ogni test, il secondo che lo usa
    erediterebbe una connessione legata a un loop ormai chiuso
    ("RuntimeError: Event loop is closed")."""
    import wav_core.redis_client as redis_client_module

    redis_client_module._redis = None
    yield


@pytest.fixture(autouse=True)
def _clean_db(db_conn):
    """Ogni test parte da un DB pulito: TRUNCATE di tutte le tabelle applicative
    dopo ciascun test (autocommit=True come il pool reale, quindi niente
    isolamento via rollback di transazione)."""
    yield
    with db_conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [r[0] for r in cur.fetchall()]
    if tables:
        with db_conn.cursor() as cur:
            cur.execute(f"TRUNCATE {', '.join(tables)} CASCADE")


def _random_prefix() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=4))


@pytest.fixture
def auth_headers():
    def _headers(user_id: str) -> dict:
        return {"Authorization": f"Bearer {create_access_token(user_id)}"}
    return _headers


@pytest.fixture
def make_user(db_conn):
    def _make(email: str | None = None, display_name: str = "Test User") -> str:
        email = email or f"{uuid.uuid4()}@example.com"
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, display_name, password_hash) VALUES (%s, %s, 'x') RETURNING id",
                (email, display_name),
            )
            return str(cur.fetchone()[0])
    return _make


@pytest.fixture
def make_org(db_conn):
    def _make(name: str = "Test Org", slug: str | None = None) -> str:
        slug = slug or f"org-{uuid.uuid4().hex[:8]}"
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (name, slug) VALUES (%s, %s) RETURNING id",
                (name, slug),
            )
            return str(cur.fetchone()[0])
    return _make


@pytest.fixture
def make_team(db_conn):
    def _make(organization_id: str, name: str = "Test Team") -> str:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO teams (organization_id, name) VALUES (%s, %s) RETURNING id",
                (organization_id, name),
            )
            return str(cur.fetchone()[0])
    return _make


@pytest.fixture
def add_team_member(db_conn):
    def _add(team_id: str, user_id: str) -> None:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO team_members (team_id, user_id) VALUES (%s, %s)",
                (team_id, user_id),
            )
    return _add


@pytest.fixture
def grant_role(db_conn):
    def _grant(principal_type: str, principal_id: str, resource_type: str, resource_id: str, role: str) -> None:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO role_assignments "
                "(principal_type, principal_id, resource_type, resource_id, role) VALUES (%s, %s, %s, %s, %s)",
                (principal_type, principal_id, resource_type, resource_id, role),
            )
    return _grant


@pytest.fixture
def make_project(db_conn):
    def _make(organization_id: str, name: str = "Test Project", prefix: str | None = None) -> str:
        prefix = prefix or _random_prefix()
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO projects (organization_id, name, prefix) VALUES (%s, %s, %s) RETURNING id",
                (organization_id, name, prefix),
            )
            project_id = str(cur.fetchone()[0])
            for position, col_name in enumerate(["Da fare", "In corso", "Fatto"]):
                cur.execute(
                    "INSERT INTO board_columns (project_id, name, position) VALUES (%s, %s, %s)",
                    (project_id, col_name, position),
                )
        return project_id
    return _make


@pytest.fixture
def make_layer(db_conn):
    def _make(project_id: str, parent_layer_id: str | None = None, name: str = "Test Layer") -> str:
        from app.routers.layers import _insert_layer_row
        return _insert_layer_row(db_conn, project_id, parent_layer_id, name)
    return _make
