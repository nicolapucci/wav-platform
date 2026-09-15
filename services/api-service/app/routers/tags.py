from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from wav_core.db import get_conn
from wav_core.permissions import Role, resolve_effective_role_on_project

from ..deps import get_current_user_id

router = APIRouter(prefix="/tags", tags=["tags"])


class TagCreate(BaseModel):
    project_id: str
    name: str
    color: str | None = None


class TagOut(BaseModel):
    id: str
    project_id: str
    name: str
    color: str | None


@router.get("", response_model=list[TagOut])
def list_tags(project_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = resolve_effective_role_on_project(conn, user_id, project_id)
    if role is None or role < Role.reader:
        raise HTTPException(status_code=403, detail="Nessun accesso a questo progetto")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, project_id, name, color FROM tags WHERE project_id = %s ORDER BY name",
            (project_id,),
        )
        rows = cur.fetchall()
    return [TagOut(id=str(r[0]), project_id=str(r[1]), name=r[2], color=r[3]) for r in rows]


@router.post("", response_model=TagOut)
def create_tag(body: TagCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    # i tag sono più "leggeri" delle colonne kanban (non toccano il workflow
    # condiviso), quindi basta 'editor'+ sul progetto invece di 'admin'+.
    role = resolve_effective_role_on_project(conn, user_id, body.project_id)
    if role is None or role < Role.editor:
        raise HTTPException(status_code=403, detail="Servono permessi da editor sul progetto per creare tag")

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tags (project_id, name, color, created_by) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (project_id, name) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id, project_id, name, color",
            (body.project_id, body.name, body.color, user_id),
        )
        row = cur.fetchone()
    return TagOut(id=str(row[0]), project_id=str(row[1]), name=row[2], color=row[3])


@router.delete("/{tag_id}")
def delete_tag(tag_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT project_id FROM tags WHERE id = %s", (tag_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tag non trovato")

        # eliminare un tag lo toglie da tutte le task che lo usano (ON DELETE
        # CASCADE su task_tags): è un'azione ad impatto più ampio della singola
        # task, per questo richiede 'admin'+ e non solo 'editor'+.
        role = resolve_effective_role_on_project(conn, user_id, str(row[0]))
        if role is None or role < Role.admin:
            raise HTTPException(status_code=403, detail="Servono permessi da admin sul progetto per eliminare un tag")

        cur.execute("DELETE FROM tags WHERE id = %s", (tag_id,))
    return {"status": "ok"}

# NOTA: l'ON CONFLICT in create_tag rende la creazione "idempotente" per nome:
# utile per il flusso "crea e aggiungi al volo" dalla TaskDetailPage, che non
# deve preoccuparsi di controllare prima se il tag esiste già.
