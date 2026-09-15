import asyncio
import json

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from wav_core.db import pool
from wav_core.security import decode_token

from .connection_manager import ConnectionManager
from .redis_listener import RedisBridge

app = FastAPI(title="ws-gateway")
manager = ConnectionManager()


async def permission_filter(ws: WebSocket, channel: str, data: dict) -> bool:
    """Controllo permessi per i canali "larghi" (evt:org:{id}:tasks), dove non tutti
    gli iscritti al canale possono necessariamente vedere ogni evento che vi transita.

    TODO: per channel.startswith("evt:org:") e evento su una task, risolvere il
    layer_id della task (data["task_id"]) e chiamare
    wav_core.permissions.resolve_effective_role_on_layer(conn, ws.state.user_id, layer_id),
    usando una connessione dal pool sync in un executor per non bloccare l'event loop
    (o una cache Redis dei permessi per evitare la query ad ogni evento).
    Per ora si inoltra sempre, e va sostituito prima di andare in produzione.
    """
    return True


bridge = RedisBridge(manager, permission_filter=permission_filter)


@app.on_event("startup")
async def startup():
    await bridge.start()


@app.get("/health")
def health():
    return {"status": "ok"}


def _channel_for(resource: str, resource_id: str | None, user_id: str) -> str:
    if resource == "notifications":
        return f"evt:user:{user_id}:notifications"
    if resource_id is None:
        # canale generico "a tipo" (es. resource="tasks" -> evt:tasks): riceve ogni
        # evento su risorse di quel tipo, non ancorato a una singola risorsa - lato
        # publish è events.py::publish_resource_event a scrivere qui, in aggiunta al
        # canale specifico evt:{tipo singolare}:{id}. Diverso da "my_tasks" qui sotto,
        # che resta filtrato per organizzazione.
        return f"evt:{resource}"
    return f"evt:{resource}:{resource_id}"


def _resolve_my_organization_ids(user_id: str) -> list[str]:
    """Organizzazioni di cui l'utente è membro, dirette o via team - stessa query
    di api-service/routers/organizations.py::list_my_organizations (duplicata qui:
    ws-gateway non importa i router di api-service). Sincrona apposta: va lanciata
    con asyncio.to_thread, il pool psycopg è thread-safe e pensato per essere usato
    così da codice async (architettura.md §6.3)."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT o.id
            FROM organizations o
            LEFT JOIN role_assignments ra
                ON ra.resource_type = 'organization' AND ra.resource_id = o.id
            LEFT JOIN team_members tm ON tm.user_id = %(uid)s
            WHERE (ra.principal_type = 'user' AND ra.principal_id = %(uid)s)
               OR (ra.principal_type = 'team' AND ra.principal_id = tm.team_id)
            """,
            {"uid": user_id},
        )
        return [str(row[0]) for row in cur.fetchall()]


async def _channels_for_subscribe_message(resource: str, resource_id: str | None, user_id: str) -> list[str]:
    """La sottoscrizione "my_tasks" (pagina Le mie task, non ancorata a una singola
    risorsa) si traduce in N canali evt:org:{id}:tasks, uno per ogni organizzazione
    dell'utente (architettura.md §6.3) - tutti gli altri resource restano un canale
    singolo, come prima."""
    if resource == "my_tasks":
        org_ids = await asyncio.to_thread(_resolve_my_organization_ids, user_id)
        return [f"evt:org:{oid}:tasks" for oid in org_ids]
    return [_channel_for(resource, resource_id, user_id)]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=4401)
        return

    user_id = payload["sub"]
    websocket.state.user_id = user_id
    await websocket.accept()

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")
            resource = msg.get("resource")
            resource_id = msg.get("id")
            channels = await _channels_for_subscribe_message(resource, resource_id, user_id)

            if action == "subscribe":
                for channel in channels:
                    manager.subscribe(websocket, channel)
                    await bridge.ensure_subscribed(channel)
            elif action == "unsubscribe":
                for channel in channels:
                    manager.unsubscribe(websocket, channel)
                    await bridge.maybe_unsubscribe(channel)
    except WebSocketDisconnect:
        channels = manager.disconnect(websocket)
        for channel in channels:
            await bridge.maybe_unsubscribe(channel)
