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
DEAD_LETTER_STREAM = "stream:jobs:dead"

# Oltre questa inattività (ms) un job pending viene considerato abbandonato dal
# consumer a cui era assegnato (pod ucciso, crash, ecc.) e reclamato da un
# altro worker vivo - ben oltre il tempo di esecuzione atteso di un handler
# (una INSERT ed eventualmente un publish Redis), ma abbastanza breve da non
# lasciare a lungo un job bloccato per un worker davvero morto.
STALE_IDLE_MS = 30_000

# Numero di consegne (lettura iniziale inclusa) oltre il quale un job che
# continua a fallire non viene più ritentato: finisce nello stream dead-letter
# per ispezione manuale invece di essere reclamato all'infinito.
MAX_DELIVERIES = 3

HANDLERS = {
    "audit": handle_audit,
    "notification": handle_notification,
}


async def ensure_group(r):
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception:
        pass  # gruppo già esistente, ok


async def process_message(r, message_id: str, fields: dict) -> None:
    """Esegue l'handler per un messaggio già assegnato a questo consumer (letto
    da XREADGROUP o riassegnato da reclaim_stale_jobs): stesso trattamento in
    entrambi i casi, compreso il "non fare XACK se l'handler fallisce"."""
    job = json.loads(fields["data"])
    handler = HANDLERS.get(job.get("type"))

    if not handler:
        print(f"[worker] tipo di job sconosciuto, scartato: {job.get('type')!r}")
        await r.xack(STREAM, GROUP, message_id)
        return

    try:
        with pool.connection() as conn:
            await handler(conn, job)
    except Exception as exc:
        # non facciamo XACK: il messaggio resta "pending" nel gruppo. Se questo
        # worker muore prima di ritentarlo, reclaim_stale_jobs() lo riassegna a
        # un consumer vivo; se continua a fallire oltre MAX_DELIVERIES finisce
        # nel dead-letter invece di restare pending per sempre.
        print(f"[worker] errore nell'handler '{job.get('type')}', job lasciato pending: {exc!r}")
        return

    await r.xack(STREAM, GROUP, message_id)


async def reclaim_stale_jobs(
    r, consumer_name: str, stale_idle_ms: int = STALE_IDLE_MS, max_deliveries: int = MAX_DELIVERIES
) -> None:
    """Recupera i job pending rimasti fermi da almeno stale_idle_ms - tipicamente
    perché il consumer a cui erano stati assegnati è morto prima di fare XACK.
    XPENDING in forma estesa espone anche times_delivered per ciascuna entry,
    che qui serve per distinguere "consumer morto, va ritentato" da "il job
    stesso fallisce sempre, va smesso di ritentare"."""
    entries = await r.xpending_range(STREAM, GROUP, min="-", max="+", count=100, idle=stale_idle_ms)

    for entry in entries:
        message_id = entry["message_id"]
        times_delivered = entry["times_delivered"]

        # XCLAIM riassegna l'entry a questo consumer (e le fa ripartire da idle
        # 0) solo se è ancora pending: se nel frattempo un altro worker l'ha
        # già reclamata o l'handler originale ha fatto in tempo a fare XACK,
        # torna una lista vuota e non c'è nulla da fare.
        claimed = await r.xclaim(STREAM, GROUP, consumer_name, min_idle_time=stale_idle_ms, message_ids=[message_id])
        if not claimed:
            continue
        claimed_id, fields = claimed[0]

        if times_delivered >= max_deliveries:
            await r.xadd(DEAD_LETTER_STREAM, {**fields, "_original_id": claimed_id, "_delivery_count": times_delivered})
            await r.xack(STREAM, GROUP, claimed_id)
            print(f"[worker] job {claimed_id} spostato in dead-letter dopo {times_delivered} tentativi falliti")
            continue

        print(f"[worker] job {claimed_id} reclamato da un consumer inattivo (tentativo {times_delivered + 1})")
        await process_message(r, claimed_id, fields)


async def main():
    r = get_redis()
    await ensure_group(r)

    # nome univoco per pod/container: la distribuzione round-robin tra consumer
    # dello stesso gruppo è gestita nativamente da Redis (XREADGROUP), non serve
    # logica applicativa aggiuntiva.
    consumer_name = f"worker-{os.getpid()}-{int(time.time())}"

    while True:
        try:
            await reclaim_stale_jobs(r, consumer_name)
        except redis.exceptions.RedisError as exc:
            print(f"[worker] errore Redis durante il reclaim, ritento tra 1s: {exc!r}")
            await asyncio.sleep(1)
            continue

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
                await process_message(r, message_id, fields)


if __name__ == "__main__":
    asyncio.run(main())
