import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from wav_core.db import get_conn
from wav_core.permissions import Role, resolve_effective_role_on_layer

from ..deps import get_current_user_id
from ..events import enqueue_job, publish_org_task_event, publish_resource_event

router = APIRouter(prefix="/tasks", tags=["tasks"])

TASK_COLUMNS = "id, layer_id, title, description, priority, due_date, created_by, status_column_id, task_number"

# Id leggibile di una task: <prefisso progetto>-<task_number>, es. "QA-1" (il
# prefisso ha lunghezza fissa, vedi PROJECT_PREFIX_LENGTH in projects.py, ma qui
# si resta permissivi sulla lunghezza per non dipendere da quella costante).
READABLE_ID_RE = re.compile(r"^([A-Z]+)-(\d+)$")


def _resolve_task_id(conn, task_id: str) -> str:
    """Ogni endpoint che riceve un task_id accetta sia lo UUID interno (usato da
    tutte le tabelle collegate: assignee, tag, dipendenze, commenti, eventi
    realtime) sia l'id leggibile <PREFISSO>-<numero>: qui si risolve il secondo
    caso al primo, così il resto del codice lavora sempre e solo con lo UUID.
    Se task_id non è nel formato leggibile viene restituito invariato (si
    assume già uno UUID)."""
    match = READABLE_ID_RE.match(task_id)
    if not match:
        return task_id
    prefix, number = match.group(1), int(match.group(2))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id FROM tasks t
            JOIN layers l ON l.id = t.layer_id
            JOIN projects p ON p.id = l.project_id
            WHERE p.prefix = %s AND t.task_number = %s
            """,
            (prefix, number),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task non trovata")
    return str(row[0])


class TaskCreate(BaseModel):
    layer_id: str
    title: str
    description: str | None = None


class TaskUpdate(BaseModel):
    """Tutti i campi opzionali: solo quelli effettivamente passati dal client
    vengono aggiornati (vedi model_dump(exclude_unset=True) in update_task).
    'status_column_id' è il campo che la kanban usa per spostare una task tra
    colonne (le colonne sono quelle del progetto, vedi projects.py)."""

    title: str | None = None
    description: str | None = None
    priority: int | None = None
    due_date: str | None = None
    status_column_id: str | None = None


class TaskOut(BaseModel):
    id: str
    readable_id: str
    layer_id: str
    project_id: str
    title: str
    description: str | None
    priority: int
    due_date: str | None
    created_by: str
    status_column_id: str | None
    # ruolo effettivo di chi ha fatto la richiesta su questa task: usato dal
    # frontend per decidere se mostrare i controlli di modifica (vedi TaskDetailPage).
    viewer_role: str | None = None


class AssigneeAdd(BaseModel):
    """Un assegnatario può essere un utente o un team intero (stesso pattern di
    principal_type/principal_id già usato da role_assignments): assegnare a un
    team equivale logicamente ad assegnare a ciascuno dei suoi membri."""

    principal_type: str = "user"
    principal_id: str


def _row_to_task(row, viewer_role: Role | None = None, project_id: str | None = None, prefix: str = "") -> TaskOut:
    return TaskOut(
        id=str(row[0]),
        readable_id=f"{prefix}-{row[8]}",
        layer_id=str(row[1]),
        project_id=project_id or "",
        title=row[2],
        description=row[3],
        priority=row[4],
        due_date=row[5].isoformat() if row[5] else None,
        created_by=str(row[6]),
        status_column_id=str(row[7]) if row[7] else None,
        viewer_role=viewer_role.name if viewer_role else None,
    )


def _require_role(conn, user_id: str, layer_id: str, minimum: Role) -> Role:
    role = resolve_effective_role_on_layer(conn, user_id, layer_id)
    if role is None or role < minimum:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    return role


def _get_layer_id_or_404(conn, task_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT layer_id FROM tasks WHERE id = %s", (task_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task non trovata")
    return row[0]


def _organization_id_for_layer(conn, layer_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.organization_id
            FROM layers l JOIN projects p ON p.id = l.project_id
            WHERE l.id = %s
            """,
            (layer_id,),
        )
        return cur.fetchone()[0]


def _project_info_for_layer(conn, layer_id: str) -> tuple[str, str]:
    """(project_id, prefix) del progetto a cui appartiene il layer: serve sia per
    popolare TaskOut.project_id sia per costruire l'id leggibile della task."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.id, p.prefix FROM layers l JOIN projects p ON p.id = l.project_id WHERE l.id = %s",
            (layer_id,),
        )
        row = cur.fetchone()
    return str(row[0]), row[1]


def _default_column_id_for_layer(conn, layer_id: str) -> str | None:
    """Colonna 'di partenza' per una nuova task: la prima (per posizione) del
    progetto a cui appartiene il layer."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bc.id
            FROM board_columns bc
            JOIN layers l ON l.project_id = bc.project_id
            WHERE l.id = %s
            ORDER BY bc.position
            LIMIT 1
            """,
            (layer_id,),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


@router.post("", response_model=TaskOut)
async def create_task(body: TaskCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = _require_role(conn, user_id, body.layer_id, Role.editor)
    default_column_id = _default_column_id_for_layer(conn, body.layer_id)
    project_id, prefix = _project_info_for_layer(conn, body.layer_id)

    with conn.cursor() as cur:
        # numero progressivo della task nel progetto: UPDATE atomico (lock di riga
        # su projects) nella stessa transazione dell'INSERT, vedi _resolve_task_id
        # e la nota nella migrazione 0002 sul perché non c'è un vincolo UNIQUE lato DB.
        cur.execute(
            "UPDATE projects SET next_task_number = next_task_number + 1 WHERE id = %s "
            "RETURNING next_task_number - 1",
            (project_id,),
        )
        task_number = cur.fetchone()[0]

        cur.execute(
            f"INSERT INTO tasks (layer_id, title, description, created_by, status_column_id, task_number) "
            f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {TASK_COLUMNS}",
            (body.layer_id, body.title, body.description, user_id, default_column_id, task_number),
        )
        row = cur.fetchone()

    task = _row_to_task(row, role, project_id, prefix)
    organization_id = _organization_id_for_layer(conn, body.layer_id)

    await publish_resource_event("task", task.id, "task.created", {"task": task.model_dump()})
    await publish_org_task_event(organization_id, "task.created", {"task_id": task.id})
    await enqueue_job(
        {"type": "audit", "entity_type": "task", "entity_id": task.id, "action": "created", "actor_id": user_id}
    )
    return task


@router.get("")
def list_tasks(layer_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = _require_role(conn, user_id, layer_id, Role.reader)
    project_id, prefix = _project_info_for_layer(conn, layer_id)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {TASK_COLUMNS} FROM tasks WHERE layer_id = %s AND archived_at IS NULL ORDER BY created_at",
            (layer_id,),
        )
        rows = cur.fetchall()
    return [_row_to_task(r, role, project_id, prefix) for r in rows]


@router.get("/search")
def search_tasks(
    q: str,
    exclude_task_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
    conn=Depends(get_conn),
):
    """Ricerca per titolo, ristretta alle task visibili all'utente (stessa logica
    di visibilità di /me/tasks). Usata dall'autocomplete delle dipendenze.

    NOTA: questa query duplica la CTE 'visible_layers' di me.py::my_tasks; se in
    futuro compaiono altri punti che hanno bisogno della stessa visibilità, vale
    la pena estrarla in una funzione condivisa in wav_core."""
    resolved_exclude_id = _resolve_task_id(conn, exclude_task_id) if exclude_task_id else None

    query = """
        WITH visible_layers AS (
            SELECT DISTINCT l.id AS layer_id
            FROM layers l
            JOIN projects p ON p.id = l.project_id
            LEFT JOIN role_assignments ra_layer
                ON ra_layer.resource_type = 'layer' AND ra_layer.resource_id = l.id
            LEFT JOIN role_assignments ra_project
                ON ra_project.resource_type = 'project' AND ra_project.resource_id = p.id
            LEFT JOIN role_assignments ra_org
                ON ra_org.resource_type = 'organization' AND ra_org.resource_id = p.organization_id
            LEFT JOIN team_members tm ON tm.user_id = %(user_id)s
            WHERE
                (ra_layer.principal_type = 'user' AND ra_layer.principal_id = %(user_id)s)
                OR (ra_layer.principal_type = 'team' AND ra_layer.principal_id = tm.team_id)
                OR (ra_project.principal_type = 'user' AND ra_project.principal_id = %(user_id)s)
                OR (ra_project.principal_type = 'team' AND ra_project.principal_id = tm.team_id)
                OR (ra_org.principal_type = 'user' AND ra_org.principal_id = %(user_id)s)
                OR (ra_org.principal_type = 'team' AND ra_org.principal_id = tm.team_id)
        )
        SELECT t.id, t.title, p.prefix, t.task_number
        FROM tasks t
        JOIN layers l ON l.id = t.layer_id
        JOIN projects p ON p.id = l.project_id
        JOIN visible_layers vl ON vl.layer_id = t.layer_id
        WHERE t.archived_at IS NULL
          AND t.title ILIKE '%%' || %(q)s || '%%'
          AND (%(exclude_id)s::uuid IS NULL OR t.id <> %(exclude_id)s::uuid)
        ORDER BY t.updated_at DESC
        LIMIT 10
    """
    with conn.cursor() as cur:
        cur.execute(query, {"user_id": user_id, "q": q, "exclude_id": resolved_exclude_id})
        rows = cur.fetchall()
    return [{"id": str(r[0]), "title": r[1], "readable_id": f"{r[2]}-{r[3]}"} for r in rows]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    task_id = _resolve_task_id(conn, task_id)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = %s", (task_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task non trovata")

    role = _require_role(conn, user_id, row[1], Role.reader)
    project_id, prefix = _project_info_for_layer(conn, row[1])
    return _row_to_task(row, role, project_id, prefix)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: str, body: TaskUpdate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    task_id = _resolve_task_id(conn, task_id)
    layer_id = _get_layer_id_or_404(conn, task_id)
    role = _require_role(conn, user_id, layer_id, Role.editor)

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")

    # i nomi dei campi vengono solo da TaskUpdate (whitelist fissa via Pydantic),
    # quindi comporli nella query è sicuro anche senza parametrizzarli singolarmente.
    set_clauses = [f"{field} = %s" for field in updates]
    values = list(updates.values()) + [task_id]

    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE tasks SET {', '.join(set_clauses)}, updated_at = now() "
            f"WHERE id = %s RETURNING {TASK_COLUMNS}",
            values,
        )
        row = cur.fetchone()

    project_id, prefix = _project_info_for_layer(conn, layer_id)
    task = _row_to_task(row, role, project_id, prefix)
    organization_id = _organization_id_for_layer(conn, layer_id)

    await publish_resource_event("task", task.id, "task.updated", {"task": task.model_dump()})
    await publish_org_task_event(organization_id, "task.updated", {"task_id": task.id})
    await enqueue_job(
        {
            "type": "audit",
            "entity_type": "task",
            "entity_id": task.id,
            "action": "updated",
            "actor_id": user_id,
            "diff": updates,
        }
    )
    return task


@router.get("/{task_id}/assignees")
def list_assignees(task_id: str, conn=Depends(get_conn)):
    task_id = _resolve_task_id(conn, task_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ta.principal_type, ta.principal_id, COALESCE(u.display_name, team.name), u.email
            FROM task_assignees ta
            LEFT JOIN users u ON ta.principal_type = 'user' AND u.id = ta.principal_id
            LEFT JOIN teams team ON ta.principal_type = 'team' AND team.id = ta.principal_id
            WHERE ta.task_id = %s
            ORDER BY 3
            """,
            (task_id,),
        )
        rows = cur.fetchall()
    return [{"principal_type": r[0], "id": str(r[1]), "display_name": r[2], "email": r[3]} for r in rows]


@router.post("/{task_id}/assignees")
async def add_assignee(
    task_id: str, body: AssigneeAdd, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    if body.principal_type not in ("user", "team"):
        raise HTTPException(status_code=400, detail="principal_type non valido")

    task_id = _resolve_task_id(conn, task_id)
    layer_id = _get_layer_id_or_404(conn, task_id)
    _require_role(conn, user_id, layer_id, Role.editor)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO task_assignees (task_id, principal_type, principal_id) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (task_id, body.principal_type, body.principal_id),
        )
        cur.execute("SELECT title FROM tasks WHERE id = %s", (task_id,))
        task_title = cur.fetchone()[0]

        # assegnare a un team notifica tutti i suoi membri: "un gruppo è
        # logicamente un utente" vale anche per l'assegnazione, non solo per i
        # permessi/le menzioni.
        if body.principal_type == "team":
            cur.execute("SELECT user_id FROM team_members WHERE team_id = %s", (body.principal_id,))
            recipient_ids = [str(r[0]) for r in cur.fetchall()]
        else:
            recipient_ids = [body.principal_id]

    await publish_resource_event("task", task_id, "task.updated", {"task_id": task_id})
    if recipient_ids:
        await enqueue_job(
            {
                "type": "notification",
                "notification_type": "task_assigned",
                "recipient_ids": recipient_ids,
                "entity_type": "task",
                "entity_id": task_id,
                "payload": {"task_title": task_title},
            }
        )
    return {"status": "ok"}


@router.delete("/{task_id}/assignees/{principal_id}")
async def remove_assignee(
    task_id: str,
    principal_id: str,
    principal_type: str = "user",
    user_id: str = Depends(get_current_user_id),
    conn=Depends(get_conn),
):
    task_id = _resolve_task_id(conn, task_id)
    layer_id = _get_layer_id_or_404(conn, task_id)
    _require_role(conn, user_id, layer_id, Role.editor)

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_assignees WHERE task_id = %s AND principal_type = %s AND principal_id = %s",
            (task_id, principal_type, principal_id),
        )

    await publish_resource_event("task", task_id, "task.updated", {"task_id": task_id})
    return {"status": "ok"}


@router.get("/{task_id}/dependencies")
def list_dependencies(task_id: str, conn=Depends(get_conn)):
    task_id = _resolve_task_id(conn, task_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.title, p.prefix, t.task_number FROM task_dependencies td
            JOIN tasks t ON t.id = td.depends_on_task_id
            JOIN layers l ON l.id = t.layer_id
            JOIN projects p ON p.id = l.project_id
            WHERE td.task_id = %s
            """,
            (task_id,),
        )
        blocked_by = [{"id": str(r[0]), "title": r[1], "readable_id": f"{r[2]}-{r[3]}"} for r in cur.fetchall()]

        cur.execute(
            """
            SELECT t.id, t.title, p.prefix, t.task_number FROM task_dependencies td
            JOIN tasks t ON t.id = td.task_id
            JOIN layers l ON l.id = t.layer_id
            JOIN projects p ON p.id = l.project_id
            WHERE td.depends_on_task_id = %s
            """,
            (task_id,),
        )
        blocks = [{"id": str(r[0]), "title": r[1], "readable_id": f"{r[2]}-{r[3]}"} for r in cur.fetchall()]

    return {"blocked_by": blocked_by, "blocks": blocks}


@router.post("/{task_id}/dependencies/{depends_on_task_id}")
def add_dependency(
    task_id: str, depends_on_task_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    """Aggiunge una dipendenza task_id -> depends_on_task_id (task_id è bloccata finché
    depends_on_task_id non è completata). Previene i cicli con una CTE ricorsiva."""
    task_id = _resolve_task_id(conn, task_id)
    depends_on_task_id = _resolve_task_id(conn, depends_on_task_id)
    if task_id == depends_on_task_id:
        raise HTTPException(status_code=400, detail="Una task non può dipendere da se stessa")

    layer_id = _get_layer_id_or_404(conn, task_id)
    _require_role(conn, user_id, layer_id, Role.editor)

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH RECURSIVE chain AS (
                SELECT depends_on_task_id AS id FROM task_dependencies WHERE task_id = %s
                UNION
                SELECT td.depends_on_task_id
                FROM task_dependencies td
                JOIN chain c ON td.task_id = c.id
            )
            SELECT 1 FROM chain WHERE id = %s
            """,
            (depends_on_task_id, task_id),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Questa dipendenza creerebbe un ciclo")

        cur.execute(
            "INSERT INTO task_dependencies (task_id, depends_on_task_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (task_id, depends_on_task_id),
        )
    return {"status": "ok"}


@router.delete("/{task_id}/dependencies/{depends_on_task_id}")
def remove_dependency(
    task_id: str, depends_on_task_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    task_id = _resolve_task_id(conn, task_id)
    depends_on_task_id = _resolve_task_id(conn, depends_on_task_id)
    layer_id = _get_layer_id_or_404(conn, task_id)
    _require_role(conn, user_id, layer_id, Role.editor)

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_dependencies WHERE task_id = %s AND depends_on_task_id = %s",
            (task_id, depends_on_task_id),
        )
    return {"status": "ok"}


@router.get("/{task_id}/tags")
def list_task_tags(task_id: str, conn=Depends(get_conn)):
    task_id = _resolve_task_id(conn, task_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.name, t.color
            FROM task_tags tt JOIN tags t ON t.id = tt.tag_id
            WHERE tt.task_id = %s
            ORDER BY t.name
            """,
            (task_id,),
        )
        rows = cur.fetchall()
    return [{"id": str(r[0]), "name": r[1], "color": r[2]} for r in rows]


@router.post("/{task_id}/tags/{tag_id}")
async def add_tag_to_task(
    task_id: str, tag_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    task_id = _resolve_task_id(conn, task_id)
    layer_id = _get_layer_id_or_404(conn, task_id)
    _require_role(conn, user_id, layer_id, Role.editor)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO task_tags (task_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (task_id, tag_id),
        )
    await publish_resource_event("task", task_id, "task.updated", {"task_id": task_id})
    return {"status": "ok"}


@router.delete("/{task_id}/tags/{tag_id}")
async def remove_tag_from_task(
    task_id: str, tag_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    task_id = _resolve_task_id(conn, task_id)
    layer_id = _get_layer_id_or_404(conn, task_id)
    _require_role(conn, user_id, layer_id, Role.editor)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM task_tags WHERE task_id = %s AND tag_id = %s", (task_id, tag_id))
    await publish_resource_event("task", task_id, "task.updated", {"task_id": task_id})
    return {"status": "ok"}

# TODO: DELETE /{task_id} (archiviazione soft, non cancellazione fisica, coerente
# con archived_at già presente nello schema).
