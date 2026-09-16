"""app/main.py e app/redis_listener.py. Il test più importante qui è la
consegna end-to-end via WebSocket reale: connessione -> subscribe -> publish
su Redis (come farebbe api-service) -> il client riceve il messaggio. È
esattamente lo scenario del bug corretto in questa sessione (RedisBridge che
moriva in silenzio all'avvio, prima di qualunque subscribe reale) - un mock
del pubsub non lo avrebbe mai potuto intercettare."""

import asyncio
import json
import os

import pytest
import redis.asyncio as redis

from app.connection_manager import ConnectionManager
from app.main import _channel_for, _channels_for_subscribe_message, _resolve_my_organization_ids


def test_channel_for_notifications_ignores_resource_id():
    assert _channel_for("notifications", "qualsiasi-id", "user-1") == "evt:user:user-1:notifications"
    assert _channel_for("notifications", None, "user-1") == "evt:user:user-1:notifications"


def test_channel_for_generic_channel_when_no_resource_id():
    assert _channel_for("tasks", None, "user-1") == "evt:tasks"


def test_channel_for_specific_resource():
    assert _channel_for("task", "task-123", "user-1") == "evt:task:task-123"


def test_resolve_my_organization_ids_direct_and_via_team(make_user, make_org, make_team, add_team_member, grant_role):
    user_id = make_user()
    org_direct = make_org()
    org_via_team = make_org()
    org_no_access = make_org()

    grant_role("user", user_id, "organization", org_direct, "reader")
    team_id = make_team(org_via_team)
    add_team_member(team_id, user_id)
    grant_role("team", team_id, "organization", org_via_team, "editor")

    org_ids = set(_resolve_my_organization_ids(user_id))
    assert org_ids == {org_direct, org_via_team}
    assert org_no_access not in org_ids


@pytest.mark.asyncio
async def test_channels_for_my_tasks_expands_to_one_channel_per_organization(
    make_user, make_org, grant_role
):
    user_id = make_user()
    org_a = make_org()
    org_b = make_org()
    grant_role("user", user_id, "organization", org_a, "reader")
    grant_role("user", user_id, "organization", org_b, "reader")

    channels = await _channels_for_subscribe_message("my_tasks", None, user_id)
    assert set(channels) == {f"evt:org:{org_a}:tasks", f"evt:org:{org_b}:tasks"}


@pytest.mark.asyncio
async def test_channels_for_other_resources_is_passthrough():
    channels = await _channels_for_subscribe_message("task", "task-123", "user-1")
    assert channels == ["evt:task:task-123"]


def test_connection_manager_tracks_subscribers_and_disconnect():
    manager = ConnectionManager()
    ws = object()  # non serve un vero WebSocket per questi controlli sugli insiemi

    assert manager.local_subscriber_count("evt:tasks") == 0
    manager.subscribe(ws, "evt:tasks")
    manager.subscribe(ws, "evt:task:1")
    assert manager.local_subscriber_count("evt:tasks") == 1
    assert ws in manager.subscribers_of("evt:tasks")

    manager.unsubscribe(ws, "evt:tasks")
    assert manager.local_subscriber_count("evt:tasks") == 0
    assert manager.local_subscriber_count("evt:task:1") == 1

    channels = manager.disconnect(ws)
    assert channels == ["evt:task:1"]
    assert manager.local_subscriber_count("evt:task:1") == 0


def test_websocket_rejects_invalid_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=non-un-jwt-valido"):
            pass


@pytest.mark.asyncio
async def test_websocket_subscribe_and_receive_published_event(client, auth_headers, make_user):
    """Regressione mirata sul bug corretto in questa sessione: RedisBridge
    moriva in silenzio all'avvio perché self.pubsub non aveva ancora una
    connessione reale finché non arrivava la prima subscribe. Qui si passa
    davvero da Redis (publish di un client indipendente), non da una chiamata
    diretta in-process, quindi esercita l'intera catena reale."""
    user_id = make_user()
    token = auth_headers(user_id)["Authorization"].removeprefix("Bearer ")

    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"action": "subscribe", "resource": "task", "id": "task-abc"})
        await asyncio.sleep(0.3)  # tempo per la vera SUBSCRIBE su Redis lato server

        redis_client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        try:
            await redis_client.publish(
                "evt:task:task-abc", json.dumps({"type": "task.updated", "task_id": "task-abc"})
            )
        finally:
            await redis_client.aclose()

        message = await asyncio.wait_for(asyncio.to_thread(ws.receive_json), timeout=5.0)
        assert message == {"channel": "evt:task:task-abc", "type": "task.updated", "task_id": "task-abc"}


@pytest.mark.asyncio
async def test_websocket_unsubscribe_stops_delivery(client, auth_headers, make_user):
    user_id = make_user()
    token = auth_headers(user_id)["Authorization"].removeprefix("Bearer ")

    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"action": "subscribe", "resource": "task", "id": "task-xyz"})
        await asyncio.sleep(0.3)
        ws.send_json({"action": "unsubscribe", "resource": "task", "id": "task-xyz"})
        await asyncio.sleep(0.3)

        redis_client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        try:
            await redis_client.publish("evt:task:task-xyz", json.dumps({"type": "task.updated"}))
        finally:
            await redis_client.aclose()

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.to_thread(ws.receive_json), timeout=2.0)
