import asyncio
import json
import os
import time

import redis.exceptions
from wav_core.db import pool
from wav_core.redis_client import get_redis

from handlers.audit import handle_audit
from handlers.notification import handle_notification

STREAM = "stream:jobs"
GROUP = "workers"

HANDLERS = {
    "audit": handle_audit,
    "notification": handle_notification,
}


async def ensure_group(r):
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception:
        pass  # gruppo già esistente, ok


async def main():
    r = get_redis()
    await ensure_group(r)

    # nome univoco per pod/container: la distribuzione round-robin tra consumer
    # dello stesso gruppo è gestita nativamente da Redis (XREADGROUP), non serve
    # logica applicativa aggiuntiva.
    consumer_name = f"worker-{os.getpid()}-{int(time.time())}"

    while True:
        try:
            # con block=5000 e coda vuota, XREADGROUP torna semplicemente None/[]
            # allo scadere del timeout: non è un errore. Il try/except qui serve
            # per gli imprevisti reali (Redis momentaneamente irraggiungibile,
            # connessione caduta, ecc.), che altrimenti ucciderebbero il processo.
            resp = await r.xreadgroup(GROUP, consumer_name, {STREAM: ">"}, count=1, block=5000)
        except redis.exceptions.RedisError as exc:
            print(f"[worker] errore Redis durante xreadgroup, ritento tra 1s: {exc!r}")
            await asyncio.sleep(1)
            continue

        if not resp:
            continue

        for _stream_name, messages in resp:
            for message_id, fields in messages:
                job = json.loads(fields["data"])
                handler = HANDLERS.get(job.get("type"))

                if not handler:
                    print(f"[worker] tipo di job sconosciuto, scartato: {job.get('type')!r}")
                    await r.xack(STREAM, GROUP, message_id)
                    continue

                try:
                    with pool.connection() as conn:
                        await handler(conn, job)
                except Exception as exc:
                    # non facciamo XACK: il messaggio resta "pending" nel gruppo e potrà
                    # essere ripreso in futuro con XPENDING/XCLAIM (vedi TODO sotto),
                    # invece di perderlo o far crashare il worker per un job malformato.
                    print(f"[worker] errore nell'handler '{job.get('type')}', job lasciato pending: {exc!r}")
                    continue

                await r.xack(STREAM, GROUP, message_id)

        # TODO produzione: gestire i messaggi "pending" di consumer morti con
        # XPENDING/XCLAIM (retry), e un dead-letter per job che falliscono ripetutamente.


if __name__ == "__main__":
    asyncio.run(main())
