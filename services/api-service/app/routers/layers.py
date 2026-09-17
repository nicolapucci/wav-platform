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


def _insert_layer_row(
    conn, project_id: str, parent_layer_id: str | None, name: str, description: str | None = None
) -> str:
    """INSERT di un layer, calcolando il suo path ltree (label = uuid senza
    trattini, concatenato a quello del padre). Non fa il controllo permessi (a
    carico del chiamante): usato sia da create_layer sia dal seeding del
    progetto demo in projects.py."""
    with conn.cursor() as cur:
        cur.execute("SELECT gen_random_uuid()")
        new_id = cur.fetchone()[0]
        label = _ltree_label(str(new_id))

        if parent_layer_id:
            cur.execute("SELECT path FROM layers WHERE id = %s", (parent_layer_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Layer padre non trovato")
            new_path = f"{row[0]}.{label}"
        else:
            new_path = label

        cur.execute(
            "INSERT INTO layers (id, project_id, parent_layer_id, name, description, path) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (new_id, project_id, parent_layer_id, name, description, new_path),
        )
        return str(cur.fetchone()[0])


@router.post("")
def create_layer(body: LayerCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    if body.parent_layer_id:
        role = resolve_effective_role_on_layer(conn, user_id, body.parent_layer_id)
    else:
        role = resolve_effective_role_on_project(conn, user_id, body.project_id)

    if role is None or role < Role.editor:
        raise HTTPException(status_code=403, detail="Permessi insufficienti per creare un layer qui")

    layer_id = _insert_layer_row(conn, body.project_id, body.parent_layer_id, body.name, body.description)

    return {
        "id": layer_id,
        "project_id": body.project_id,
        "parent_layer_id": body.parent_layer_id,
        "name": body.name,
    }


@router.get("")
def list_layers(project_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = resolve_effective_role_on_project(conn, user_id, project_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Nessun accesso a questo progetto")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, parent_layer_id, name, description FROM layers "
            "WHERE project_id = %s AND archived_at IS NULL ORDER BY nlevel(path)",
            (project_id,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "parent_layer_id": r[1], "name": r[2], "description": r[3]} for r in rows]


@router.delete("/{layer_id}")
def delete_layer(layer_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    """Cancellazione logica: archivia il layer e, a cascata, ogni suo
    sotto-layer (via ltree path, "path <@ path" include il nodo stesso) e le
    task che vivono in uno qualsiasi di questi layer. Richiede 'admin'+: un
    sotto-albero intero è un impatto più ampio della singola task che
    editor/reader normalmente gestiscono (stesso criterio di
    projects.py::delete_project e tags.py::delete_tag)."""
    role = resolve_effective_role_on_layer(conn, user_id, layer_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin sul layer per eliminarlo")

    with conn.cursor() as cur:
        cur.execute("SELECT path FROM layers WHERE id = %s", (layer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Layer non trovato")
        subtree_path = row[0]

        cur.execute(
            "UPDATE layers SET archived_at = now() WHERE path <@ %s AND archived_at IS NULL",
            (subtree_path,),
        )
        cur.execute(
            "UPDATE tasks SET archived_at = now() "
            "WHERE layer_id IN (SELECT id FROM layers WHERE path <@ %s) AND archived_at IS NULL",
            (subtree_path,),
        )
    return {"status": "ok"}
