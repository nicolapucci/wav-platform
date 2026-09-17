from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from wav_core.db import get_conn
from wav_core.permissions import Role, invalidate_team_permissions, invalidate_user_permissions, resolve_effective_role

from ..deps import get_current_user_id

router = APIRouter(prefix="/permissions", tags=["permissions"])

VALID_RESOURCE_TYPES = {"organization", "project", "layer"}
VALID_PRINCIPAL_TYPES = {"user", "team"}


class PermissionGrant(BaseModel):
    resource_type: str
    resource_id: str
    principal_type: str
    principal_id: str
    role: str


def _require_admin(conn, user_id: str, resource_type: str, resource_id: str):
    if resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="resource_type non valido")
    role = resolve_effective_role(conn, user_id, resource_type, resource_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin su questa risorsa")


@router.get("")
def list_permissions(
    resource_type: str,
    resource_id: str,
    user_id: str = Depends(get_current_user_id),
    conn=Depends(get_conn),
):
    """Elenca chi ha un permesso DIRETTO su questa risorsa (non l'elenco di chi vi
    ha accesso per ereditarietà: quello richiederebbe di risalire l'intera gerarchia
    in senso opposto, più costoso e meno utile per una UI di gestione)."""
    _require_admin(conn, user_id, resource_type, resource_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ra.id, ra.principal_type, ra.principal_id, ra.role,
                   COALESCE(u.display_name, t.name) AS principal_label,
                   COALESCE(u.email, '') AS principal_email
            FROM role_assignments ra
            LEFT JOIN users u ON ra.principal_type = 'user' AND u.id = ra.principal_id
            LEFT JOIN teams t ON ra.principal_type = 'team' AND t.id = ra.principal_id
            WHERE ra.resource_type = %s AND ra.resource_id = %s
            ORDER BY ra.role DESC, principal_label
            """,
            (resource_type, resource_id),
        )
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "principal_type": r[1],
            "principal_id": r[2],
            "role": r[3],
            "principal_label": r[4],
            "principal_email": r[5],
        }
        for r in rows
    ]


@router.post("")
def grant_permission(body: PermissionGrant, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    if body.principal_type not in VALID_PRINCIPAL_TYPES:
        raise HTTPException(status_code=400, detail="principal_type non valido")

    _require_admin(conn, user_id, body.resource_type, body.resource_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO role_assignments (principal_type, principal_id, resource_type, resource_id, role)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (principal_type, principal_id, resource_type, resource_id)
            DO UPDATE SET role = EXCLUDED.role
            RETURNING id
            """,
            (body.principal_type, body.principal_id, body.resource_type, body.resource_id, body.role),
        )
        new_id = cur.fetchone()[0]

    if body.principal_type == "user":
        invalidate_user_permissions(body.principal_id)
    else:
        invalidate_team_permissions(conn, body.principal_id)
    return {"id": new_id, "status": "ok"}


@router.delete("/{assignment_id}")
def revoke_permission(assignment_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT resource_type, resource_id, principal_type, principal_id FROM role_assignments WHERE id = %s",
            (assignment_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Permesso non trovato")
        resource_type, resource_id, principal_type, principal_id = row

        _require_admin(conn, user_id, resource_type, resource_id)
        cur.execute("DELETE FROM role_assignments WHERE id = %s", (assignment_id,))

    if principal_type == "user":
        invalidate_user_permissions(principal_id)
    else:
        invalidate_team_permissions(conn, principal_id)
    return {"status": "ok"}

# NOTA: per assegnare un permesso a un TEAM invece che a un utente, il frontend
# chiama questo stesso endpoint con principal_type="team" e principal_id=<team_id>
# (ottenuto da GET /teams?organization_id=...). Non serve un endpoint separato.
