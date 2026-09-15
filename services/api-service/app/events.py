import json

from wav_core.redis_client import get_redis


async def publish_resource_event(resource_type: str, resource_id: str, event_type: str, payload: dict):
    """Canale evt:{resource_type}:{resource_id} - per client che stanno guardando questa risorsa."""
    r = get_redis()
    channel = f"evt:{resource_type}:{resource_id}"
    await r.publish(channel, json.dumps({"type": event_type, **payload}))


async def publish_org_task_event(organization_id: str, event_type: str, payload: dict):
    """Canale evt:org:{id}:tasks - per la pagina 'Le mie task' (architettura.md §6.3)."""
    r = get_redis()
    channel = f"evt:org:{organization_id}:tasks"
    await r.publish(channel, json.dumps({"type": event_type, **payload}))


async def enqueue_job(job: dict):
    """Accoda un job su stream:jobs (Redis Streams), consumato round-robin dai worker
    tramite consumer group (architettura.md §7)."""
    r = get_redis()
    await r.xadd("stream:jobs", {"data": json.dumps(job)})
