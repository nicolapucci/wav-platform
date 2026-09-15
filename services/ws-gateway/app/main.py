import json

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
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
    if resource == "my_tasks":
        # TODO: qui andrebbero risolte TUTTE le organizzazioni dell'utente e sottoscritto
        # un canale evt:org:{id}:tasks per ciascuna (architettura.md §6.3). Semplificato
        # a un solo canale placeholder per lo scaffold iniziale.
        return f"evt:user:{user_id}:my_tasks"
    if resource == "notifications":
        return f"evt:user:{user_id}:notifications"
    return f"evt:{resource}:{resource_id}"


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
            channel = _channel_for(resource, resource_id, user_id)

            if action == "subscribe":
                manager.subscribe(websocket, channel)
                await bridge.ensure_subscribed(channel)
            elif action == "unsubscribe":
                manager.unsubscribe(websocket, channel)
                await bridge.maybe_unsubscribe(channel)
    except WebSocketDisconnect:
        channels = manager.disconnect(websocket)
        for channel in channels:
            await bridge.maybe_unsubscribe(channel)
