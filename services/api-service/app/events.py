import json

from wav_core.redis_client import get_redis


async def publish_resource_event(resource_type: str, resource_id: str, event_type: str, payload: dict):
    """Pubblica sia sul canale specifico della risorsa (evt:{resource_type}:{resource_id},
    per chi sta guardando QUESTA risorsa) sia su un canale generico "a tipo"
    (evt:{resource_type}s, per chi vuole sapere di ogni evento sulle risorse di quel
    tipo senza essere ancorato a una singola risorsa - es. una lista/dashboard).
    Stesso payload su entrambi, un solo publish di troppo per chi ascolta solo il
    canale specifico non è un problema: nessuno è per forza iscritto a entrambi."""
    r = get_redis()
    message = json.dumps({"type": event_type, **payload})
    await r.publish(f"evt:{resource_type}:{resource_id}", message)
    await r.publish(f"evt:{resource_type}s", message)


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
