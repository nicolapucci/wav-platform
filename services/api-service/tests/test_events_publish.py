"""app/events.py::publish_resource_event deve pubblicare lo stesso messaggio sia
sul canale specifico della risorsa sia su quello generico "a tipo" (vedi
architettura.md §6 e la richiesta che ha introdotto il pattern). Verificato con
un vero subscriber Redis, non con un mock, per lo stesso motivo per cui i test
di questa sessione girano su un Postgres reale: qui il comportamento che conta
è quello del canale/pub-sub reale, non solo la chiamata Python."""

import asyncio
import json
import os

import pytest
import redis.asyncio as redis

from app.events import publish_resource_event


async def _collect_one(pubsub, timeout: float = 3.0):
    async def _read():
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None:
                return message
    return await asyncio.wait_for(_read(), timeout=timeout)


@pytest.mark.asyncio
async def test_publish_resource_event_reaches_both_specific_and_generic_channel():
    client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe("evt:task:task-123", "evt:tasks")

    try:
        # consuma i messaggi di conferma subscribe prima di pubblicare
        await pubsub.get_message(timeout=1.0)
        await pubsub.get_message(timeout=1.0)

        await publish_resource_event("task", "task-123", "task.updated", {"task_id": "task-123"})

        first = await _collect_one(pubsub)
        second = await _collect_one(pubsub)
        received_channels = {first["channel"], second["channel"]}
        assert received_channels == {"evt:task:task-123", "evt:tasks"}

        for message in (first, second):
            payload = json.loads(message["data"])
            assert payload == {"type": "task.updated", "task_id": "task-123"}
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_publish_resource_event_does_not_leak_to_other_resource_channel():
    client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe("evt:task:other-task")

    try:
        await pubsub.get_message(timeout=1.0)

        await publish_resource_event("task", "task-123", "task.updated", {"task_id": "task-123"})

        with pytest.raises(asyncio.TimeoutError):
            await _collect_one(pubsub, timeout=1.5)
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await client.aclose()
