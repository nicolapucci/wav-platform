from fastapi import WebSocket


class ConnectionManager:
    """Registro locale al singolo pod: per ogni canale (es. 'evt:task:123',
    'evt:org:abc:tasks', 'evt:user:xyz:notifications') tiene i socket locali
    interessati. Un canale qui corrisponde 1:1 a un canale Redis Pub/Sub."""

    def __init__(self):
        self._subscribers: dict[str, set[WebSocket]] = {}
        self._socket_channels: dict[WebSocket, set[str]] = {}

    def subscribe(self, websocket: WebSocket, channel: str):
        self._subscribers.setdefault(channel, set()).add(websocket)
        self._socket_channels.setdefault(websocket, set()).add(channel)

    def unsubscribe(self, websocket: WebSocket, channel: str):
        self._subscribers.get(channel, set()).discard(websocket)
        self._socket_channels.get(websocket, set()).discard(channel)

    def disconnect(self, websocket: WebSocket) -> list[str]:
        """Rimuove il socket da tutti i canali e ritorna i canali che erano interessati
        (così il chiamante può eventualmente fare UNSUBSCRIBE su Redis se non serve più)."""
        channels = list(self._socket_channels.pop(websocket, set()))
        for channel in channels:
            self._subscribers.get(channel, set()).discard(websocket)
        return channels

    def local_subscriber_count(self, channel: str) -> int:
        return len(self._subscribers.get(channel, set()))

    def subscribers_of(self, channel: str) -> set[WebSocket]:
        return self._subscribers.get(channel, set())
