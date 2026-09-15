import asyncio
import json
from typing import Awaitable, Callable

from fastapi import WebSocket
from wav_core.redis_client import get_redis

from .connection_manager import ConnectionManager

PermissionFilter = Callable[[WebSocket, str, dict], Awaitable[bool]]

# Canale "fittizio" mai disiscritto: serve solo a garantire che self.pubsub abbia
# una connessione Redis attiva fin dall'avvio (vedi start()).
_KEEPALIVE_CHANNEL = "evt:__keepalive__"


class RedisBridge:
    """Un'unica connessione Redis Pub/Sub per pod, con SUBSCRIBE/UNSUBSCRIBE dinamici
    guidati dal ConnectionManager locale (architettura.md §6.2)."""

    def __init__(self, manager: ConnectionManager, permission_filter: PermissionFilter | None = None):
        self.manager = manager
        self.permission_filter = permission_filter
        self.redis = get_redis()
        self.pubsub = self.redis.pubsub()
        self._task: asyncio.Task | None = None

    async def ensure_subscribed(self, channel: str):
        if self.manager.local_subscriber_count(channel) == 1:  # primo interessato locale
            await self.pubsub.subscribe(channel)

    async def maybe_unsubscribe(self, channel: str):
        if self.manager.local_subscriber_count(channel) == 0:
            await self.pubsub.unsubscribe(channel)

    async def start(self):
        # self.pubsub.get_message()/parse_response() sollevano RuntimeError se non
        # è ancora mai stata fatta una subscribe (self.pubsub.connection è None: la
        # connessione Redis dedicata al pubsub si stabilisce solo alla prima
        # subscribe). bridge.start() gira all'avvio dell'app, prima che qualunque
        # client si sia connesso, quindi senza questa subscribe "di servizio" il
        # task _listen() qui sotto morirebbe con un'eccezione mai osservata da
        # nessuno (asyncio.create_task senza await/callback la inghiotte in
        # silenzio) al primissimo giro, ben prima che arrivi una subscribe vera.
        await self.pubsub.subscribe(_KEEPALIVE_CHANNEL)
        self._task = asyncio.create_task(self._listen())

    async def _listen(self):
        # NON usare "async for message in self.pubsub.listen()": quel generatore
        # gira su "while self.subscribed", controllato all'inizio di ogni giro - se
        # non ci fosse la subscribe di keepalive sopra, al primo giro la troverebbe
        # falsa e terminerebbe per sempre, prima ancora che arrivi la prima
        # subscribe reale da un client. get_message() con un timeout è il pattern
        # che redis-py stesso raccomanda per un consumo continuo in loop.
        while True:
            message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue

            channel = message["channel"]
            data = json.loads(message["data"])

            for ws in list(self.manager.subscribers_of(channel)):
                if self.permission_filter and not await self.permission_filter(ws, channel, data):
                    continue
                try:
                    await ws.send_json({"channel": channel, **data})
                except Exception:
                    self.manager.disconnect(ws)
