import re
from datetime import date, timedelta

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from wav_core.db import get_conn
from wav_core.permissions import Role, candidate_role_at_resource, resolve_effective_role_on_project

from ..deps import get_current_user_id
from ..visibility import visible_layers_cte
from .layers import _insert_layer_row

router = APIRouter(prefix="/projects", tags=["projects"])

DEFAULT_COLUMN_NAMES = ["Da fare", "In corso", "Fatto"]

# Lunghezza fissa del prefisso usato per gli id leggibili delle task del progetto
# (<PREFISSO>-<numero>, es. "QA-1"): stessa lunghezza per tutti i progetti, così
# gli id restano prevedibili. Scelto una sola volta alla creazione del progetto
# (vedi ProjectCreate.prefix) e mai più modificabile: non c'è un endpoint PATCH
# per rinominarlo, perché cambierebbe retroattivamente l'id di ogni task esistente.
PROJECT_PREFIX_LENGTH = 4
PROJECT_PREFIX_RE = re.compile(rf"^[A-Z]{{{PROJECT_PREFIX_LENGTH}}}$")


def _normalize_and_validate_prefix(value: str) -> str:
    value = value.strip().upper()
    if not PROJECT_PREFIX_RE.match(value):
        raise ValueError(f"Il prefisso deve essere di {PROJECT_PREFIX_LENGTH} lettere maiuscole (es. 'PROJ')")
    return value


class ProjectCreate(BaseModel):
    organization_id: str
    name: str
    prefix: str
    description: str | None = None

    @field_validator("prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        return _normalize_and_validate_prefix(value)


class DemoProjectCreate(BaseModel):
    organization_id: str
    name: str = "Progetto Demo"
    prefix: str

    @field_validator("prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        return _normalize_and_validate_prefix(value)


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
    return visible_layers_cte(scoped_to_project=True)


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


def _insert_project_row(conn, organization_id: str, name: str, prefix: str, description: str | None = None) -> str:
    """INSERT del progetto + le sue 3 colonne kanban di default. Non fa il
    controllo permessi (a carico del chiamante): usato sia da create_project
    sia da create_demo_project."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (organization_id, name, description, prefix) VALUES (%s, %s, %s, %s) "
            "RETURNING id",
            (organization_id, name, description, prefix),
        )
        project_id = str(cur.fetchone()[0])

        # ogni progetto nasce con 3 colonne di default: gli utenti con permessi
        # da admin potranno poi rinominarle, riordinarle, aggiungerne altre o
        # eliminarle (vedi endpoint /columns sotto).
        for position, col_name in enumerate(DEFAULT_COLUMN_NAMES, start=1):
            cur.execute(
                "INSERT INTO board_columns (project_id, name, position) VALUES (%s, %s, %s)",
                (project_id, col_name, position),
            )
    return project_id


def _next_task_number(conn, project_id: str) -> int:
    """Stesso UPDATE atomico di tasks.py::create_task (vedi lì il perché non c'è
    un vincolo UNIQUE lato DB): duplicato qui perché è un one-liner e importarlo
    da tasks.py creerebbe una dipendenza nella direzione sbagliata (tasks.py non
    dipende da projects.py, non deve iniziare a farlo per un dettaglio come questo)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE projects SET next_task_number = next_task_number + 1 WHERE id = %s RETURNING next_task_number - 1",
            (project_id,),
        )
        return cur.fetchone()[0]


def _seed_demo_content(conn, project_id: str, creator_user_id: str):
    """Struttura dimostrativa: due rami di layer con due sotto-layer ciascuno,
    task distribuite su tutte le colonne kanban di default con tag/priorità/
    scadenze/assegnatario variati, un paio di dipendenze e un commento - pensata
    per mostrare in una demo la struttura a layer, la kanban, i tag, gli
    assegnatari, le dipendenze e i commenti in un colpo solo. Non è pensata per
    uso reale (niente eventi realtime/audit per ogni singola riga: sarebbe solo
    rumore per un progetto che nasce già pieno)."""
    with conn.cursor() as cur:
        cur.execute("SELECT name, id FROM board_columns WHERE project_id = %s", (project_id,))
        columns = {name: str(cid) for name, cid in cur.fetchall()}
    todo, doing, done = columns["Da fare"], columns["In corso"], columns["Fatto"]

    frontend = _insert_layer_row(conn, project_id, None, "Frontend")
    frontend_auth = _insert_layer_row(conn, project_id, frontend, "Autenticazione")
    frontend_dash = _insert_layer_row(conn, project_id, frontend, "Dashboard")
    backend = _insert_layer_row(conn, project_id, None, "Backend")
    backend_api = _insert_layer_row(conn, project_id, backend, "API")
    backend_db = _insert_layer_row(conn, project_id, backend, "Database")

    tag_ids: dict[str, str] = {}
    for tag_name, color in [("Bug", "#e74c3c"), ("Feature", "#4c6fe0"), ("Urgente", "#f39c12")]:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tags (project_id, name, color, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
                (project_id, tag_name, color, creator_user_id),
            )
            tag_ids[tag_name] = str(cur.fetchone()[0])

    # (layer, titolo, colonna, priorità 0-3, tag, assegna al creatore, giorni alla scadenza da oggi)
    task_specs = [
        (frontend_auth, "Implementare login OAuth", doing, 2, ["Feature"], True, 3),
        (frontend_auth, "Aggiungere autenticazione a due fattori", todo, 1, ["Feature"], False, 14),
        (frontend_dash, "Disegnare wireframe dashboard", done, 1, [], False, None),
        (frontend_dash, "Grafici in tempo reale sulla dashboard", doing, 2, ["Feature"], True, 7),
        (backend_api, "Endpoint REST per le task", done, 1, [], False, None),
        (backend_api, "Rate limiting sulle API pubbliche", todo, 3, ["Urgente"], True, 2),
        (backend_db, "Migrazione schema v2", todo, 2, [], False, 10),
        (backend_db, "Ottimizzare le query più lente", doing, 1, ["Bug"], False, 5),
    ]

    today = date.today()
    task_ids: dict[str, str] = {}
    for layer_id, title, column_id, priority, tag_names, assign_to_creator, due_in_days in task_specs:
        due_date = today + timedelta(days=due_in_days) if due_in_days else None
        task_number = _next_task_number(conn, project_id)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tasks (layer_id, title, created_by, status_column_id, priority, due_date, task_number) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (layer_id, title, creator_user_id, column_id, priority, due_date, task_number),
            )
            task_id = str(cur.fetchone()[0])
        task_ids[title] = task_id

        with conn.cursor() as cur:
            for tag_name in tag_names:
                cur.execute(
                    "INSERT INTO task_tags (task_id, tag_id) VALUES (%s, %s)", (task_id, tag_ids[tag_name])
                )
            if assign_to_creator:
                cur.execute(
                    "INSERT INTO task_assignees (task_id, principal_type, principal_id) VALUES (%s, 'user', %s)",
                    (task_id, creator_user_id),
                )

    dependency_pairs = [
        ("Aggiungere autenticazione a due fattori", "Implementare login OAuth"),
        ("Rate limiting sulle API pubbliche", "Endpoint REST per le task"),
    ]
    with conn.cursor() as cur:
        for task_title, depends_on_title in dependency_pairs:
            cur.execute(
                "INSERT INTO task_dependencies (task_id, depends_on_task_id) VALUES (%s, %s)",
                (task_ids[task_title], task_ids[depends_on_title]),
            )

        cur.execute(
            "INSERT INTO comments (task_id, author_id, body) VALUES (%s, %s, %s)",
            (
                task_ids["Implementare login OAuth"],
                creator_user_id,
                "Partiamo da qui: una volta pronto il login sblocchiamo anche la 2FA.",
            ),
        )


# ---------------------------------------------------------------------------
# CRUD progetto
# ---------------------------------------------------------------------------


@router.post("")
def create_project(body: ProjectCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = candidate_role_at_resource(conn, user_id, "organization", body.organization_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin sull'organizzazione")

    try:
        project_id = _insert_project_row(conn, body.organization_id, body.name, body.prefix, body.description)
    except psycopg.errors.UniqueViolation:
        # autocommit: la INSERT fallita non lascia la connessione in uno stato
        # da ripulire (ogni statement è la propria transazione implicita).
        raise HTTPException(status_code=409, detail=f"Il prefisso '{body.prefix}' è già usato da un altro progetto")

    return {"id": project_id, "organization_id": body.organization_id, "name": body.name, "prefix": body.prefix}


@router.post("/demo")
def create_demo_project(
    body: DemoProjectCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    """Come create_project, ma popola subito il progetto con una struttura
    dimostrativa (layer, task, tag, dipendenze, un commento) pensata per una
    demo: niente da configurare a mano prima di mostrare l'app."""
    role = candidate_role_at_resource(conn, user_id, "organization", body.organization_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin sull'organizzazione")

    try:
        project_id = _insert_project_row(conn, body.organization_id, body.name, body.prefix)
        _seed_demo_content(conn, project_id, user_id)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"Il prefisso '{body.prefix}' è già usato da un altro progetto")

    return {"id": project_id, "organization_id": body.organization_id, "name": body.name, "prefix": body.prefix}


@router.get("")
def list_projects(organization_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = candidate_role_at_resource(conn, user_id, "organization", organization_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Nessun accesso a questa organizzazione")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, description, prefix FROM projects WHERE organization_id = %s AND archived_at IS NULL",
            (organization_id,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "description": r[2], "prefix": r[3]} for r in rows]


@router.get("/{project_id}")
def get_project(project_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = resolve_effective_role_on_project(conn, user_id, project_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Nessun accesso a questo progetto")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, organization_id, name, description, prefix FROM projects "
            "WHERE id = %s AND archived_at IS NULL",
            (project_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Progetto non trovato")
    return {"id": row[0], "organization_id": row[1], "name": row[2], "description": row[3], "prefix": row[4]}


@router.delete("/{project_id}")
def delete_project(project_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    """Cancellazione logica: archivia il progetto e, a cascata, tutti i suoi
    layer e le loro task (vedi la nota in 0004_soft_delete.sql sul perché).
    Richiede 'admin'+ sul progetto (non 'editor'+ come le mutazioni più
    circoscritte): stesso criterio "impatto più ampio della singola risorsa
    richiede una soglia più alta" già usato per l'eliminazione di un tag
    (tags.py::delete_tag) o di un layer (layers.py::delete_layer)."""
    role = resolve_effective_role_on_project(conn, user_id, project_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin sul progetto per eliminarlo")

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE layers SET archived_at = now() WHERE project_id = %s AND archived_at IS NULL",
            (project_id,),
        )
        cur.execute(
            "UPDATE tasks SET archived_at = now() "
            "WHERE layer_id IN (SELECT id FROM layers WHERE project_id = %s) AND archived_at IS NULL",
            (project_id,),
        )
        cur.execute("UPDATE projects SET archived_at = now() WHERE id = %s", (project_id,))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Colonne kanban del progetto (condivise da tutte le viste: kanban di default
# per layer, board personalizzate)
# ---------------------------------------------------------------------------


@router.get("/{project_id}/columns", response_model=list[ColumnOut])
def list_columns(project_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = resolve_effective_role_on_project(conn, user_id, project_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Nessun accesso a questo progetto")

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
