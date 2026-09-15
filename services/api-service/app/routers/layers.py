from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from wav_core.db import get_conn
from wav_core.permissions import Role, resolve_effective_role_on_layer, resolve_effective_role_on_project

from ..deps import get_current_user_id

router = APIRouter(prefix="/layers", tags=["layers"])


class LayerCreate(BaseModel):
    project_id: str
    parent_layer_id: str | None = None
    name: str
    description: str | None = None


def _ltree_label(uuid_str: str) -> str:
    """ltree accetta solo [A-Za-z0-9_]: si tolgono i trattini dall'UUID."""
    return uuid_str.replace("-", "")


@router.post("")
def create_layer(body: LayerCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    if body.parent_layer_id:
        role = resolve_effective_role_on_layer(conn, user_id, body.parent_layer_id)
    else:
        role = resolve_effective_role_on_project(conn, user_id, body.project_id)

    if role is None or role < Role.editor:
        raise HTTPException(status_code=403, detail="Permessi insufficienti per creare un layer qui")

    with conn.cursor() as cur:
        cur.execute("SELECT gen_random_uuid()")
        new_id = cur.fetchone()[0]
        label = _ltree_label(str(new_id))

        if body.parent_layer_id:
            cur.execute("SELECT path FROM layers WHERE id = %s", (body.parent_layer_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Layer padre non trovato")
            new_path = f"{row[0]}.{label}"
        else:
            new_path = label

        cur.execute(
            "INSERT INTO layers (id, project_id, parent_layer_id, name, description, path) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (new_id, body.project_id, body.parent_layer_id, body.name, body.description, new_path),
        )
        layer_id = cur.fetchone()[0]

    return {
        "id": layer_id,
        "project_id": body.project_id,
        "parent_layer_id": body.parent_layer_id,
        "name": body.name,
    }


@router.get("")
def list_layers(project_id: str, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, parent_layer_id, name, description FROM layers "
            "WHERE project_id = %s AND archived_at IS NULL ORDER BY nlevel(path)",
            (project_id,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "parent_layer_id": r[1], "name": r[2], "description": r[3]} for r in rows]
