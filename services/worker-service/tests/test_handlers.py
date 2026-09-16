"""I due handler consumati dal loop di main.py (stream:jobs), testati
direttamente con una connessione reale: prendono conn come parametro esplicito,
non serve avviare il consumer loop per testarne la logica."""

import json
import os

import pytest
import redis.asyncio as redis

from handlers.audit import handle_audit
from handlers.notification import handle_notification


@pytest.mark.asyncio
async def test_handle_audit_inserts_row_without_diff(db_conn, make_user):
    actor_id = make_user()
    job = {"entity_type": "task", "entity_id": "11111111-1111-1111-1111-111111111111", "action": "created"}
    job["actor_id"] = actor_id

    await handle_audit(db_conn, job)

    with db_conn.cursor() as cur:
        cur.execute("SELECT actor_id, entity_type, entity_id, action, diff FROM audit_logs")
        row = cur.fetchone()
    assert str(row[0]) == actor_id
    assert row[1] == "task"
    assert str(row[2]) == "11111111-1111-1111-1111-111111111111"
    assert row[3] == "created"
    assert row[4] is None


@pytest.mark.asyncio
async def test_handle_audit_inserts_row_with_diff(db_conn, make_user):
    """Riproduce esattamente cosa arriva dal worker reale: enqueue_job fa
    json.dumps(job) e main.py fa json.loads(...) prima di chiamare l'handler,
    quindi "diff" arriva già come dict Python puro (non una stringa JSON) -
    stesso identico oggetto passato qui."""
    actor_id = make_user()
    job = json.loads(
        json.dumps(
            {
                "actor_id": actor_id,
                "entity_type": "task",
                "entity_id": "22222222-2222-2222-2222-222222222222",
                "action": "updated",
                "diff": {"title": "nuovo titolo"},
            }
        )
    )

    await handle_audit(db_conn, job)

    with db_conn.cursor() as cur:
        cur.execute("SELECT diff FROM audit_logs WHERE entity_id = %s", (job["entity_id"],))
        (diff,) = cur.fetchone()
    assert diff == {"title": "nuovo titolo"}


@pytest.mark.asyncio
async def test_handle_notification_writes_row_per_recipient_and_publishes(db_conn, make_user):
    recipient_1 = make_user()
    recipient_2 = make_user()
    job = {
        "recipient_ids": [recipient_1, recipient_2],
        "notification_type": "task_assigned",
        "entity_type": "task",
        "entity_id": "33333333-3333-3333-3333-333333333333",
        "payload": {"task_title": "Una task"},
    }

    redis_client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"evt:user:{recipient_1}:notifications")
    await pubsub.get_message(timeout=1.0)  # conferma subscribe

    try:
        await handle_notification(db_conn, job)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, type, entity_type, entity_id, payload FROM notifications ORDER BY user_id::text"
            )
            rows = cur.fetchall()
        assert {str(r[0]) for r in rows} == {recipient_1, recipient_2}
        for row in rows:
            assert row[1] == "task_assigned"
            assert row[2] == "task"
            assert str(row[3]) == "33333333-3333-3333-3333-333333333333"
            assert row[4] == {"task_title": "Una task"}

        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=3.0)
        assert message is not None
        assert json.loads(message["data"]) == {"type": "notification.created"}
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await redis_client.aclose()
