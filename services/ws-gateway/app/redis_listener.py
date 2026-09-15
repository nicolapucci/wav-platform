import asyncio
import json
from typing import Awaitable, Callable

from fastapi import WebSocket
from wav_core.redis_client import get_redis

from .connection_manager import ConnectionManager

PermissionFilter = Callable[[WebSocket, str, dict], Awaitable[bool]]


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
        self._task = asyncio.create_task(self._listen())

    async def _listen(self):
        async for message in self.pubsub.listen():
            if message["type"] != "message":
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
