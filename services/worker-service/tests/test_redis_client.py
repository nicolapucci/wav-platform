"""wav_core.redis_client.get_redis(): il client condiviso deve sopravvivere a
un XREADGROUP bloccante su uno stream vuoto - regressione su un bug trovato in
questa sessione (non nei test, dal vivo: il worker in compose e in k8s girava
da ore stampando "Timeout reading from redis" ad ogni ciclo, senza mai
accorgersene perché il retry nascondeva il sintomo)."""

import asyncio

import pytest

from wav_core.redis_client import get_redis

STREAM = "stream:jobs-test-redis-client"
GROUP = "test-group"


@pytest.mark.asyncio
async def test_blocking_xreadgroup_on_empty_stream_does_not_raise():
    r = get_redis()
    await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)

    # prima del fix (nessun socket_timeout esplicito passato a redis.from_url),
    # questa stessa chiamata falliva SEMPRE con redis.exceptions.TimeoutError
    # quando lo stream è vuoto - mai quando c'è un messaggio da leggere, la
    # risposta in quel caso arriva prima che un timeout abbia modo di scattare.
    resp = await asyncio.wait_for(
        r.xreadgroup(GROUP, "test-consumer", {STREAM: ">"}, count=1, block=5000), timeout=8
    )
    assert resp in (None, [])
