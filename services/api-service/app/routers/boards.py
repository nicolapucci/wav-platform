import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from wav_core.db import get_conn
from wav_core.permissions import Role, resolve_effective_role_on_project

from ..deps import get_current_user_id

router = APIRouter(prefix="/boards", tags=["boards"])


class BoardCreate(BaseModel):
    project_id: str
    name: str
    # {"layer_ids": [...], "assignee_ids": [...], "team_ids": [...]} tutte opzionali
    task_filter: dict = {}


class BoardOut(BaseModel):
    id: str
    project_id: str
    created_by: str
    name: str
    task_filter: dict


@router.post("", response_model=BoardOut)
def create_board(body: BoardCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = resolve_effective_role_on_project(conn, user_id, body.project_id)
    if role is None or role < Role.reader:
        raise HTTPException(status_code=403, detail="Nessun accesso a questo progetto")

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO boards (project_id, created_by, name, task_filter) VALUES (%s, %s, %s, %s) "
            "RETURNING id, project_id, created_by, name, task_filter",
            (body.project_id, user_id, body.name, json.dumps(body.task_filter)),
        )
        row = cur.fetchone()
    return BoardOut(id=str(row[0]), project_id=str(row[1]), created_by=str(row[2]), name=row[3], task_filter=row[4])


@router.get("", response_model=list[BoardOut])
def list_boards(project_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    role = resolve_effective_role_on_project(conn, user_id, project_id)
    if role is None or role < Role.reader:
        raise HTTPException(status_code=403, detail="Nessun accesso a questo progetto")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, project_id, created_by, name, task_filter FROM boards "
            "WHERE project_id = %s ORDER BY created_at",
            (project_id,),
        )
        rows = cur.fetchall()
    return [
        BoardOut(id=str(r[0]), project_id=str(r[1]), created_by=str(r[2]), name=r[3], task_filter=r[4])
        for r in rows
    ]


@router.delete("/{board_id}")
def delete_board(board_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT project_id, created_by FROM boards WHERE id = %s", (board_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Board non trovata")

        project_id, created_by = row
        role = resolve_effective_role_on_project(conn, user_id, str(project_id))
        is_owner_of_board = str(created_by) == user_id
        if not is_owner_of_board and (role is None or role < Role.admin):
            raise HTTPException(status_code=403, detail="Solo chi l'ha creata o un admin del progetto può eliminarla")

        cur.execute("DELETE FROM boards WHERE id = %s", (board_id,))
    return {"status": "ok"}
