import re

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from wav_core.db import get_conn
from wav_core.permissions import Role, candidate_role_at_resource, resolve_effective_role_on_project

from ..deps import get_current_user_id

router = APIRouter(prefix="/projects", tags=["projects"])

DEFAULT_COLUMN_NAMES = ["Da fare", "In corso", "Fatto"]

# Lunghezza fissa del prefisso usato per gli id leggibili delle task del progetto
# (<PREFISSO>-<numero>, es. "QA-1"): stessa lunghezza per tutti i progetti, così
# gli id restano prevedibili. Scelto una sola volta alla creazione del progetto
# (vedi ProjectCreate.prefix) e mai più modificabile: non c'è un endpoint PATCH
# per rinominarlo, perché cambierebbe retroattivamente l'id di ogni task esistente.
PROJECT_PREFIX_LENGTH = 4
PROJECT_PREFIX_RE = re.compile(rf"^[A-Z]{{{PROJECT_PREFIX_LENGTH}}}$")


class ProjectCreate(BaseModel):
    organization_id: str
    name: str
    prefix: str
    description: str | None = None

    @field_validator("prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        value = value.strip().upper()
        if not PROJECT_PREFIX_RE.match(value):
            raise ValueError(f"Il prefisso deve essere di {PROJECT_PREFIX_LENGTH} lettere maiuscole (es. 'PROJ')")
        return value


class ColumnCreate(BaseModel):
    name: str


class ColumnUpdate(BaseModel):
    """Campi opzionali: 'position' serve per riordinare (vedi ColumnManager nel
    frontend, che scambia la position di due colonne alla volta)."""

    name: str | None = None
    position: int | None = None


class ColumnOut(BaseModel):
    id: str
    project_id: str
    name: str
    position: int


def _require_project_admin(conn, user_id: str, project_id: str):
    role = resolve_effective_role_on_project(conn, user_id, project_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin sul progetto per gestire le colonne")


def _visible_layers_cte() -> str:
    """CTE dei layer del progetto (%(project_id)s) visibili a %(user_id)s, diretto
    o via team - stessa logica di visibilità usata in tasks.py::search_tasks e
    me.py::my_tasks, qui ristretta a un solo progetto."""
    return """
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
            WHERE p.id = %(project_id)s
              AND (
                (ra_layer.principal_type = 'user' AND ra_layer.principal_id = %(user_id)s)
                OR (ra_layer.principal_type = 'team' AND ra_layer.principal_id = tm.team_id)
                OR (ra_project.principal_type = 'user' AND ra_project.principal_id = %(user_id)s)
                OR (ra_project.principal_type = 'team' AND ra_project.principal_id = tm.team_id)
                OR (ra_org.principal_type = 'user' AND ra_org.principal_id = %(user_id)s)
                OR (ra_org.principal_type = 'team' AND ra_org.principal_id = tm.team_id)
              )
        )
    """


def _task_filter_clauses(layer_ids: list[str], assignee_ids: list[str], team_ids: list[str], tag_ids: list[str]):
    """Traduce il 'task_filter' (di una board salvata, o passato ad-hoc dalla
    query string) in clausole WHERE aggiuntive + parametri. Le clausole vanno
    sempre applicate SOPRA la CTE di visibilità, mai al suo posto."""
    clauses = []
    params: dict = {}

    if layer_ids:
        # include automaticamente i sotto-layer, sfruttando ltree (l.path <@ antenato.path)
        clauses.append(
            "EXISTS (SELECT 1 FROM layers anc WHERE anc.id = ANY(%(f_layer_ids)s::uuid[]) AND l.path <@ anc.path)"
        )
        params["f_layer_ids"] = layer_ids

    if assignee_ids or team_ids:
        # un team assegnatario "conta" come assegnato per ciascuno dei suoi membri
        # (e viceversa, filtrare per team_ids include anche chi vi è assegnato
        # come singolo utente membro di quel team): "un gruppo è logicamente un
        # utente" vale anche qui, non solo per i permessi.
        sub_clauses = []
        if assignee_ids:
            sub_clauses.append("(ta.principal_type = 'user' AND ta.principal_id = ANY(%(f_assignee_ids)s::uuid[]))")
            sub_clauses.append(
                "(ta.principal_type = 'team' AND ta.principal_id IN "
                "(SELECT team_id FROM team_members WHERE user_id = ANY(%(f_assignee_ids)s::uuid[])))"
            )
            params["f_assignee_ids"] = assignee_ids
        if team_ids:
            sub_clauses.append("(ta.principal_type = 'team' AND ta.principal_id = ANY(%(f_team_ids)s::uuid[]))")
            sub_clauses.append(
                "(ta.principal_type = 'user' AND ta.principal_id IN "
                "(SELECT user_id FROM team_members WHERE team_id = ANY(%(f_team_ids)s::uuid[])))"
            )
            params["f_team_ids"] = team_ids
        clauses.append(
            f"EXISTS (SELECT 1 FROM task_assignees ta WHERE ta.task_id = t.id AND ({' OR '.join(sub_clauses)}))"
        )

    if tag_ids:
        clauses.append(
            "EXISTS (SELECT 1 FROM task_tags tt WHERE tt.task_id = t.id AND tt.tag_id = ANY(%(f_tag_ids)s::uuid[]))"
        )
        params["f_tag_ids"] = tag_ids

    return clauses, params


def _parse_csv(value: str | None) -> list[str]:
    return [v for v in value.split(",") if v] if value else []


# ---------------------------------------------------------------------------
# CRUD progetto
# ---------------------------------------------------------------------------


@router.post("")
def create_project(body: ProjectCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = candidate_role_at_resource(conn, user_id, "organization", body.organization_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin sull'organizzazione")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO projects (organization_id, name, description, prefix) VALUES (%s, %s, %s, %s) "
                "RETURNING id",
                (body.organization_id, body.name, body.description, body.prefix),
            )
            project_id = cur.fetchone()[0]

            # ogni progetto nasce con 3 colonne di default: gli utenti con permessi
            # da admin potranno poi rinominarle, riordinarle, aggiungerne altre o
            # eliminarle (vedi endpoint /columns sotto).
            for position, col_name in enumerate(DEFAULT_COLUMN_NAMES, start=1):
                cur.execute(
                    "INSERT INTO board_columns (project_id, name, position) VALUES (%s, %s, %s)",
                    (project_id, col_name, position),
                )
    except psycopg.errors.UniqueViolation:
        # autocommit: la INSERT fallita non lascia la connessione in uno stato
        # da ripulire (ogni statement è la propria transazione implicita).
        raise HTTPException(status_code=409, detail=f"Il prefisso '{body.prefix}' è già usato da un altro progetto")

    return {"id": project_id, "organization_id": body.organization_id, "name": body.name, "prefix": body.prefix}


@router.get("")
def list_projects(organization_id: str, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, description, prefix FROM projects WHERE organization_id = %s AND archived_at IS NULL",
            (organization_id,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "description": r[2], "prefix": r[3]} for r in rows]


@router.get("/{project_id}")
def get_project(project_id: str, conn=Depends(get_conn)):
    # TODO: verificare che l'utente abbia almeno ruolo 'reader' sul project
    # (resolve_effective_role_on_project) prima di restituirlo.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, organization_id, name, description, prefix FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Progetto non trovato")
    return {"id": row[0], "organization_id": row[1], "name": row[2], "description": row[3], "prefix": row[4]}


# ---------------------------------------------------------------------------
# Colonne kanban del progetto (condivise da tutte le viste: kanban di default
# per layer, board personalizzate)
# ---------------------------------------------------------------------------


@router.get("/{project_id}/columns", response_model=list[ColumnOut])
def list_columns(project_id: str, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, project_id, name, position FROM board_columns WHERE project_id = %s ORDER BY position",
            (project_id,),
        )
        rows = cur.fetchall()
    return [ColumnOut(id=str(r[0]), project_id=str(r[1]), name=r[2], position=r[3]) for r in rows]


@router.post("/{project_id}/columns", response_model=ColumnOut)
def create_column(
    project_id: str, body: ColumnCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    _require_project_admin(conn, user_id, project_id)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM board_columns WHERE project_id = %s",
            (project_id,),
        )
        next_position = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO board_columns (project_id, name, position) VALUES (%s, %s, %s) "
            "RETURNING id, project_id, name, position",
            (project_id, body.name, next_position),
        )
        row = cur.fetchone()
    return ColumnOut(id=str(row[0]), project_id=str(row[1]), name=row[2], position=row[3])


@router.patch("/{project_id}/columns/{column_id}", response_model=ColumnOut)
def update_column(
    project_id: str,
    column_id: str,
    body: ColumnUpdate,
    user_id: str = Depends(get_current_user_id),
    conn=Depends(get_conn),
):
    _require_project_admin(conn, user_id, project_id)

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")

    set_clauses = [f"{field} = %s" for field in updates]
    values = list(updates.values()) + [column_id, project_id]

    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE board_columns SET {', '.join(set_clauses)} WHERE id = %s AND project_id = %s "
            "RETURNING id, project_id, name, position",
            values,
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Colonna non trovata")
    return ColumnOut(id=str(row[0]), project_id=str(row[1]), name=row[2], position=row[3])


@router.delete("/{project_id}/columns/{column_id}")
def delete_column(
    project_id: str, column_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    _require_project_admin(conn, user_id, project_id)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM tasks WHERE status_column_id = %s", (column_id,))
        count = cur.fetchone()[0]
        if count > 0:
            raise HTTPException(status_code=409, detail="Sposta prima tutte le task fuori da questa colonna")

        cur.execute("DELETE FROM board_columns WHERE id = %s AND project_id = %s", (column_id, project_id))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Task filtrate + statistiche per status (dashboard e board personalizzate)
# ---------------------------------------------------------------------------


@router.get("/{project_id}/tasks")
def list_project_tasks(
    project_id: str,
    layer_ids: str | None = Query(default=None, description="CSV di layer id"),
    assignee_ids: str | None = Query(default=None, description="CSV di user id"),
    team_ids: str | None = Query(default=None, description="CSV di team id"),
    tag_ids: str | None = Query(default=None, description="CSV di tag id"),
    user_id: str = Depends(get_current_user_id),
    conn=Depends(get_conn),
):
    """Task del progetto visibili all'utente, con filtro opzionale (usato sia
    dalla kanban 'default' del progetto - nessun filtro - sia dalle board
    personalizzate, che passano il proprio task_filter come query string)."""
    clauses, params = _task_filter_clauses(
        _parse_csv(layer_ids), _parse_csv(assignee_ids), _parse_csv(team_ids), _parse_csv(tag_ids)
    )
    where_extra = (" AND " + " AND ".join(clauses)) if clauses else ""

    query = (
        _visible_layers_cte()
        + f"""
        SELECT t.id, t.title, t.status_column_id, t.priority, t.due_date, t.layer_id, p.prefix, t.task_number
        FROM tasks t
        JOIN layers l ON l.id = t.layer_id
        JOIN projects p ON p.id = l.project_id
        JOIN visible_layers vl ON vl.layer_id = l.id
        WHERE t.archived_at IS NULL{where_extra}
        ORDER BY t.updated_at DESC
        """
    )
    with conn.cursor() as cur:
        cur.execute(query, {"user_id": user_id, "project_id": project_id, **params})
        rows = cur.fetchall()

    return [
        {
            "id": str(r[0]),
            "readable_id": f"{r[6]}-{r[7]}",
            "title": r[1],
            "column_id": str(r[2]) if r[2] else None,
            "priority": r[3],
            "due_date": r[4].isoformat() if r[4] else None,
            "layer_id": str(r[5]),
        }
        for r in rows
    ]


@router.get("/{project_id}/task-stats")
def project_task_stats(
    project_id: str,
    layer_ids: str | None = Query(default=None),
    assignee_ids: str | None = Query(default=None),
    team_ids: str | None = Query(default=None),
    tag_ids: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
    conn=Depends(get_conn),
):
    """Conteggio task per colonna, con lo stesso filtro opzionale di /tasks:
    alimenta il grafico a torta della dashboard (di progetto, o di una board)."""
    clauses, params = _task_filter_clauses(
        _parse_csv(layer_ids), _parse_csv(assignee_ids), _parse_csv(team_ids), _parse_csv(tag_ids)
    )
    where_extra = (" AND " + " AND ".join(clauses)) if clauses else ""

    query = (
        _visible_layers_cte()
        + f"""
        SELECT t.status_column_id, COUNT(*)
        FROM tasks t
        JOIN layers l ON l.id = t.layer_id
        JOIN visible_layers vl ON vl.layer_id = l.id
        WHERE t.archived_at IS NULL{where_extra}
        GROUP BY t.status_column_id
        """
    )
    with conn.cursor() as cur:
        cur.execute(query, {"user_id": user_id, "project_id": project_id, **params})
        counts_by_column = {str(r[0]): r[1] for r in cur.fetchall() if r[0] is not None}

        cur.execute(
            "SELECT id, name, position FROM board_columns WHERE project_id = %s ORDER BY position",
            (project_id,),
        )
        columns = cur.fetchall()

    result = [
        {"column_id": str(c[0]), "name": c[1], "position": c[2], "count": counts_by_column.get(str(c[0]), 0)}
        for c in columns
    ]
    return {"columns": result, "total": sum(r["count"] for r in result)}
