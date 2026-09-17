from fastapi import APIRouter, Depends, Query
from wav_core.db import get_conn

from ..deps import get_current_user_id
from .projects import _parse_csv, _task_filter_clauses

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
def my_profile(user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, display_name, avatar_url FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    return {"id": row[0], "email": row[1], "display_name": row[2], "avatar_url": row[3]}


@router.get("/tasks")
def my_tasks(
    search: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
    conn=Depends(get_conn),
):
    """Tutte le task su cui l'utente ha almeno ruolo reader (diretto o via team),
    con ricerca opzionale sul titolo. Alimenta la pagina 'Le mie task' (vista a
    tabella, con progetto/stato/assegnatari/tag già risolti per riga - evita un
    giro a parte per ciascuna colonna) e il canale realtime evt:org:{id}:tasks
    (architettura.md §6.3).

    Implementazione di riferimento, da ottimizzare con vista materializzata o cache
    se il volume di layer/task cresce molto (vedi architettura.md §10).
    """
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
        SELECT
            t.id, t.title, t.layer_id, t.updated_at,
            p.id, p.name,
            t.status_column_id, bc.name,
            t.priority, t.due_date,
            assignee_agg.items,
            tag_agg.tags_json,
            p.prefix, t.task_number
        FROM tasks t
        JOIN layers l ON l.id = t.layer_id
        JOIN projects p ON p.id = l.project_id
        JOIN visible_layers vl ON vl.layer_id = l.id
        LEFT JOIN board_columns bc ON bc.id = t.status_column_id
        LEFT JOIN LATERAL (
            SELECT json_agg(
                     json_build_object('type', ta.principal_type, 'name', COALESCE(u.display_name, team.name))
                     ORDER BY COALESCE(u.display_name, team.name)
                   ) AS items
            FROM task_assignees ta
            LEFT JOIN users u ON ta.principal_type = 'user' AND u.id = ta.principal_id
            LEFT JOIN teams team ON ta.principal_type = 'team' AND team.id = ta.principal_id
            WHERE ta.task_id = t.id
        ) assignee_agg ON true
        LEFT JOIN LATERAL (
            SELECT json_agg(json_build_object('id', tg.id, 'name', tg.name, 'color', tg.color) ORDER BY tg.name) AS tags_json
            FROM task_tags tt JOIN tags tg ON tg.id = tt.tag_id
            WHERE tt.task_id = t.id
        ) tag_agg ON true
        WHERE t.archived_at IS NULL
          AND (%(search)s::text IS NULL OR t.title ILIKE '%%' || %(search)s::text || '%%')
        ORDER BY t.updated_at DESC
        LIMIT 100
    """
    with conn.cursor() as cur:
        cur.execute(query, {"user_id": user_id, "search": search})
        rows = cur.fetchall()

    return [
        {
            "id": str(r[0]),
            "readable_id": f"{r[12]}-{r[13]}",
            "title": r[1],
            "layer_id": str(r[2]),
            "updated_at": r[3].isoformat(),
            "project_id": str(r[4]),
            "project_name": r[5],
            "status_column_id": str(r[6]) if r[6] else None,
            "column_name": r[7],
            "priority": r[8],
            "due_date": r[9].isoformat() if r[9] else None,
            "assignees": r[10] or [],
            "tags": r[11] or [],
        }
        for r in rows
    ]


@router.get("/tasks/assigned")
def my_assigned_tasks(user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    """Task assegnate direttamente a user_id o a un team di cui è membro (un
    gruppo è trattato come un utente anche qui, coerente con tasks.py::add_assignee),
    escluse quelle "completate". Alimenta il widget task della home page.

    Non c'è un flag "completata" nello schema (le colonne kanban sono libere,
    definite per progetto - vedi board_columns): si usa come proxy l'ultima
    colonna per posizione di ciascun progetto, la stessa convenzione con cui le
    board vengono create (["Da fare", "In corso", "Fatto"], l'ultima è quella
    terminale) anche se l'utente le ha rinominate."""
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
        ),
        last_columns AS (
            SELECT DISTINCT ON (project_id) project_id, id AS last_column_id
            FROM board_columns
            ORDER BY project_id, position DESC
        )
        SELECT
            t.id, t.title, t.updated_at,
            p.id, p.name,
            t.status_column_id, bc.name,
            t.priority, t.due_date,
            p.prefix, t.task_number
        FROM tasks t
        JOIN layers l ON l.id = t.layer_id
        JOIN projects p ON p.id = l.project_id
        JOIN visible_layers vl ON vl.layer_id = l.id
        LEFT JOIN board_columns bc ON bc.id = t.status_column_id
        LEFT JOIN last_columns lc ON lc.project_id = p.id
        WHERE t.archived_at IS NULL
          AND (t.status_column_id IS NULL OR t.status_column_id IS DISTINCT FROM lc.last_column_id)
          AND EXISTS (
            SELECT 1 FROM task_assignees ta
            WHERE ta.task_id = t.id
              AND (
                (ta.principal_type = 'user' AND ta.principal_id = %(user_id)s)
                OR (ta.principal_type = 'team' AND ta.principal_id IN (
                    SELECT team_id FROM team_members WHERE user_id = %(user_id)s
                ))
              )
          )
        ORDER BY t.due_date NULLS LAST, t.updated_at DESC
        LIMIT 50
    """
    with conn.cursor() as cur:
        cur.execute(query, {"user_id": user_id})
        rows = cur.fetchall()

    return [
        {
            "id": str(r[0]),
            "readable_id": f"{r[9]}-{r[10]}",
            "title": r[1],
            "updated_at": r[2].isoformat(),
            "project_id": str(r[3]),
            "project_name": r[4],
            "status_column_id": str(r[5]) if r[5] else None,
            "column_name": r[6],
            "priority": r[7],
            "due_date": r[8].isoformat() if r[8] else None,
        }
        for r in rows
    ]


@router.get("/tasks/board")
def my_tasks_board(
    project_ids: str | None = Query(default=None, description="CSV di project id"),
    layer_ids: str | None = Query(default=None, description="CSV di layer id"),
    assignee_ids: str | None = Query(default=None, description="CSV di user id"),
    team_ids: str | None = Query(default=None, description="CSV di team id"),
    tag_ids: str | None = Query(default=None, description="CSV di tag id"),
    user_id: str = Depends(get_current_user_id),
    conn=Depends(get_conn),
):
    """Task visibili all'utente (stessa visibilità di /me/tasks) filtrate e
    raggruppate per progetto, con le colonne kanban di ciascun progetto: usata
    dalla vista Kanban standalone (non legata a un singolo progetto). Le colonne
    board_columns sono per-progetto, quindi non si può fare un'unica board
    cross-progetto: si raggruppa una sotto-board per progetto, ciascuna con le
    proprie colonne.
    """
    clauses, params = _task_filter_clauses(
        _parse_csv(layer_ids), _parse_csv(assignee_ids), _parse_csv(team_ids), _parse_csv(tag_ids)
    )
    project_id_list = _parse_csv(project_ids)
    if project_id_list:
        clauses.append("p.id = ANY(%(f_project_ids)s::uuid[])")
        params["f_project_ids"] = project_id_list
    where_extra = (" AND " + " AND ".join(clauses)) if clauses else ""

    query = (
        """
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
        """
        + f"""
        SELECT t.id, t.title, t.status_column_id, t.priority, t.due_date, t.layer_id, p.id, p.name,
               p.prefix, t.task_number
        FROM tasks t
        JOIN layers l ON l.id = t.layer_id
        JOIN projects p ON p.id = l.project_id
        JOIN visible_layers vl ON vl.layer_id = l.id
        WHERE t.archived_at IS NULL{where_extra}
        ORDER BY t.updated_at DESC
        LIMIT 500
        """
    )
    with conn.cursor() as cur:
        cur.execute(query, {"user_id": user_id, **params})
        rows = cur.fetchall()

        project_ids_found = sorted({str(r[6]) for r in rows})
        columns_by_project: dict[str, list[dict]] = {pid: [] for pid in project_ids_found}
        if project_ids_found:
            cur.execute(
                "SELECT id, project_id, name, position FROM board_columns "
                "WHERE project_id = ANY(%s::uuid[]) ORDER BY project_id, position",
                (project_ids_found,),
            )
            for col_id, col_project_id, col_name, position in cur.fetchall():
                columns_by_project[str(col_project_id)].append(
                    {"id": str(col_id), "name": col_name, "position": position}
                )

    projects: dict[str, dict] = {}
    for r in rows:
        pid = str(r[6])
        if pid not in projects:
            projects[pid] = {"id": pid, "name": r[7], "columns": columns_by_project[pid], "tasks": []}
        projects[pid]["tasks"].append(
            {
                "id": str(r[0]),
                "readable_id": f"{r[8]}-{r[9]}",
                "title": r[1],
                "column_id": str(r[2]) if r[2] else None,
                "priority": r[3],
                "due_date": r[4].isoformat() if r[4] else None,
                "layer_id": str(r[5]),
            }
        )

    return {"projects": sorted(projects.values(), key=lambda p: p["name"])}


@router.get("/notifications")
def my_notifications(user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, type, entity_type, entity_id, payload, read_at, created_at FROM notifications "
            "WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "type": r[1],
            "entity_type": r[2],
            "entity_id": r[3],
            "payload": r[4],
            "read_at": r[5].isoformat() if r[5] else None,
            "created_at": r[6].isoformat(),
        }
        for r in rows
    ]


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET read_at = now() WHERE id = %s AND user_id = %s",
            (notification_id, user_id),
        )
    return {"status": "ok"}
