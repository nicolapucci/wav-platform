"""reclaim_stale_jobs(): un job resta "pending" nel gruppo Redis se il
consumer a cui XREADGROUP lo ha assegnato muore prima di fare XACK (crash,
pod ucciso, ecc.) - senza un passo di recupero resterebbe bloccato per
sempre (era il TODO in cima a main.py). Qui si simula un consumer morto
leggendo il job con un nome di consumer che poi non fa più nulla, e si
verifica che reclaim_stale_jobs lo riassegni e lo riprocessi; per non
dover davvero aspettare STALE_IDLE_MS, i test passano stale_idle_ms=0."""

import json
import uuid

import pytest

from main import DEAD_LETTER_STREAM, GROUP, STREAM, ensure_group, reclaim_stale_jobs
from wav_core.redis_client import get_redis


@pytest.mark.asyncio
async def test_reclaim_stale_jobs_reprocesses_job_of_dead_consumer(db_conn, make_user):
    r = get_redis()
    await ensure_group(r)
    actor_id = make_user()
    entity_id = str(uuid.uuid4())
    await r.xadd(
        STREAM,
        {"data": f'{{"type": "audit", "actor_id": "{actor_id}", "entity_type": "task", '
                 f'"entity_id": "{entity_id}", "action": "created"}}'},
    )

    # "dead-consumer" legge il job e non fa mai XACK: da qui in poi è pending
    # e attribuito a un consumer che, come un pod ucciso, non tornerà più.
    await r.xreadgroup(GROUP, "dead-consumer", {STREAM: ">"}, count=1)

    await reclaim_stale_jobs(r, "live-consumer", stale_idle_ms=0)

    with db_conn.cursor() as cur:
        cur.execute("SELECT entity_id FROM audit_logs WHERE entity_id = %s", (entity_id,))
        assert cur.fetchone() is not None

    still_pending = await r.xpending_range(STREAM, GROUP, min="-", max="+", count=10)
    assert still_pending == []


@pytest.mark.asyncio
async def test_reclaim_stale_jobs_moves_permanently_failing_job_to_dead_letter():
    r = get_redis()
    await ensure_group(r)
    # entity_id non è uno UUID valido: handle_audit fallirà sempre con lo
    # stesso errore, qualunque sia il consumer che lo riprova.
    await r.xadd(STREAM, {"data": '{"type": "audit", "entity_type": "task", "entity_id": "not-a-uuid", "action": "x"}'})
    await r.xreadgroup(GROUP, "dead-consumer", {STREAM: ">"}, count=1)

    for _ in range(3):
        await reclaim_stale_jobs(r, "live-consumer", stale_idle_ms=0, max_deliveries=3)

    still_pending = await r.xpending_range(STREAM, GROUP, min="-", max="+", count=10)
    assert still_pending == []

    dead_letters = await r.xrange(DEAD_LETTER_STREAM, min="-", max="+")
    assert len(dead_letters) == 1
    _dead_id, fields = dead_letters[0]
    assert json.loads(fields["data"])["entity_id"] == "not-a-uuid"
    assert str(fields["_delivery_count"]) == "3"


@pytest.mark.asyncio
async def test_reclaim_stale_jobs_ignores_jobs_still_within_idle_threshold():
    r = get_redis()
    await ensure_group(r)
    await r.xadd(STREAM, {"data": '{"type": "audit", "entity_type": "task", "entity_id": "not-a-uuid", "action": "x"}'})
    await r.xreadgroup(GROUP, "slow-but-alive-consumer", {STREAM: ">"}, count=1)

    # soglia altissima: il job è pending da pochi istanti, molto meno del
    # min-idle-time richiesto, quindi non deve essere reclamato.
    await reclaim_stale_jobs(r, "live-consumer", stale_idle_ms=60_000)

    pending = await r.xpending_range(STREAM, GROUP, min="-", max="+", count=10)
    assert len(pending) == 1
    assert pending[0]["consumer"] == "slow-but-alive-consumer"
