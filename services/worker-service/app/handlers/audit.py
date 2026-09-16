import json


async def handle_audit(conn, job: dict):
    diff = job.get("diff")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_logs (actor_id, entity_type, entity_id, action, diff) VALUES (%s, %s, %s, %s, %s)",
            (
                job.get("actor_id"),
                job["entity_type"],
                job["entity_id"],
                job["action"],
                json.dumps(diff) if diff is not None else None,
            ),
        )
