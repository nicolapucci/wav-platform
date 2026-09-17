import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from wav_core.db import get_conn
from wav_core.permissions import Role, resolve_effective_role_on_layer

from ..deps import get_current_user_id
from ..events import enqueue_job, publish_resource_event
from .tasks import _resolve_task_id

router = APIRouter(prefix="/comments", tags=["comments"])

MENTION_RE = re.compile(r"@([a-zA-Z0-9_.]+)")


class CommentCreate(BaseModel):
    task_id: str
    body: str
    parent_comment_id: str | None = None
    mentioned_user_ids: list[str] = []
    # menzionare un team equivale a menzionare ciascuno dei suoi membri: qui
    # arrivano gli id dei TEAM scelti dall'autocomplete, espansi ai membri sotto
    # (comment_mentions resta una tabella di soli utenti, niente riga "a parte"
    # per il team - chi la legge non ha bisogno di sapere se un utente è stato
    # menzionato direttamente o tramite un suo gruppo).
    mentioned_team_ids: list[str] = []


def _layer_id_for_task(conn, task_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT layer_id FROM tasks WHERE id = %s", (task_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task non trovata")
    return row[0]


@router.post("")
async def create_comment(body: CommentCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    body.task_id = _resolve_task_id(conn, body.task_id)
    layer_id = _layer_id_for_task(conn, body.task_id)
    role = resolve_effective_role_on_layer(conn, user_id, layer_id)
    if role is None or role < Role.editor:
        raise HTTPException(status_code=403, detail="Permessi insufficienti per commentare questa task")

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO comments (task_id, parent_comment_id, author_id, body) VALUES (%s, %s, %s, %s) "
            "RETURNING id",
            (body.task_id, body.parent_comment_id, user_id, body.body),
        )
        comment_id = cur.fetchone()[0]

        # se il client (il composer con autocomplete) ha già risolto le menzioni in
        # id utente/team, si usano direttamente quelli: più affidabile del parsing
        # testuale, che resta come fallback per client che mandano solo testo grezzo.
        mentioned_user_ids = list(dict.fromkeys(body.mentioned_user_ids))
        mentioned_team_ids = list(dict.fromkeys(body.mentioned_team_ids))
        if not mentioned_user_ids and not mentioned_team_ids:
            handles = MENTION_RE.findall(body.body)
            if handles:
                cur.execute("SELECT id FROM users WHERE display_name = ANY(%s::text[])", (handles,))
                mentioned_user_ids = [str(r[0]) for r in cur.fetchall()]
                cur.execute("SELECT id FROM teams WHERE name = ANY(%s::text[])", (handles,))
                mentioned_team_ids = [str(r[0]) for r in cur.fetchall()]

        if mentioned_team_ids:
            cur.execute(
                "SELECT DISTINCT user_id FROM team_members WHERE team_id = ANY(%s::uuid[])",
                (mentioned_team_ids,),
            )
            mentioned_user_ids = list(dict.fromkeys(mentioned_user_ids + [str(r[0]) for r in cur.fetchall()]))

        for uid in mentioned_user_ids:
            cur.execute(
                "INSERT INTO comment_mentions (comment_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (comment_id, uid),
            )

    await publish_resource_event("task", body.task_id, "comment.created", {"comment_id": str(comment_id)})
    if mentioned_user_ids:
        await enqueue_job(
            {
                "type": "notification",
                "notification_type": "mention",
                "recipient_ids": [str(uid) for uid in mentioned_user_ids],
                "entity_type": "comment",
                "entity_id": str(comment_id),
                # l'entità della notifica è il commento, non la task: senza il
                # task_id qui il centro notifiche non saprebbe dove linkare.
                "payload": {"task_id": body.task_id, "comment_excerpt": body.body[:140]},
            }
        )
    return {"id": str(comment_id), "task_id": body.task_id, "body": body.body}


@router.get("")
def list_comments(task_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    task_id = _resolve_task_id(conn, task_id)
    layer_id = _layer_id_for_task(conn, task_id)
    role = resolve_effective_role_on_layer(conn, user_id, layer_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Nessun accesso a questa task")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.author_id, u.display_name, c.body, c.parent_comment_id, c.created_at
            FROM comments c
            JOIN users u ON u.id = c.author_id
            WHERE c.task_id = %s
            ORDER BY c.created_at ASC
            """,
            (task_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "author_id": str(r[1]),
            "author_name": r[2],
            "body": r[3],
            "parent_comment_id": str(r[4]) if r[4] else None,
            "created_at": r[5].isoformat(),
        }
        for r in rows
    ]

# TODO: endpoint allegati:
# 1) POST /attachments/presign  -> genera una presigned URL S3/MinIO (client upload diretto)
# 2) POST /attachments/confirm  -> INSERT INTO attachments con la storage_key confermata
# Il body del commento resta markdown puro: i link sono autolink gestiti dal renderer
# del frontend, nessuna struttura dati aggiuntiva richiesta lato server.
