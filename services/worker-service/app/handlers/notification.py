import json

from wav_core.redis_client import get_redis


async def handle_notification(conn, job: dict):
    """Scrive la notifica persistente per ciascun destinatario e pubblica l'evento
    realtime evt:user:{id}:notifications per aggiornare il badge lato client
    (architettura.md §4.5, §6.4)."""
    recipient_ids = job["recipient_ids"]
    payload = json.dumps(job.get("payload", {}))

    with conn.cursor() as cur:
        for user_id in recipient_ids:
            cur.execute(
                "INSERT INTO notifications (user_id, type, entity_type, entity_id, payload) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, job["notification_type"], job["entity_type"], job["entity_id"], payload),
            )

    r = get_redis()
    for user_id in recipient_ids:
        await r.publish(f"evt:user:{user_id}:notifications", json.dumps({"type": "notification.created"}))
