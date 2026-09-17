from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from wav_core.db import get_conn
from wav_core.permissions import Role, candidate_role_at_resource, invalidate_team_permissions, invalidate_user_permissions

from ..deps import get_current_user_id
from .permissions import _require_admin

router = APIRouter(prefix="/teams", tags=["teams"])


class TeamCreate(BaseModel):
    organization_id: str
    name: str


class TeamMemberAdd(BaseModel):
    user_id: str


class TeamRoleGrant(BaseModel):
    resource_type: str  # 'organization' | 'project' | 'layer'
    resource_id: str
    role: str  # 'reader' | 'editor' | 'admin' | 'owner'


def _require_org_admin(conn, user_id: str, organization_id: str):
    role = candidate_role_at_resource(conn, user_id, "organization", organization_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin sull'organizzazione")


def _require_org_reader(conn, user_id: str, organization_id: str):
    role = candidate_role_at_resource(conn, user_id, "organization", organization_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Nessun accesso a questa organizzazione")


def _organization_id_for_team(conn, team_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT organization_id FROM teams WHERE id = %s", (team_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    return str(row[0])


@router.post("")
def create_team(body: TeamCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    _require_org_admin(conn, user_id, body.organization_id)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO teams (organization_id, name) VALUES (%s, %s) RETURNING id",
            (body.organization_id, body.name),
        )
        team_id = cur.fetchone()[0]
    return {"id": team_id, "organization_id": body.organization_id, "name": body.name}


@router.get("")
def list_teams(organization_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    _require_org_reader(conn, user_id, organization_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM teams WHERE organization_id = %s ORDER BY name",
            (organization_id,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]


@router.get("/{team_id}/members")
def list_team_members(team_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    _require_org_reader(conn, user_id, _organization_id_for_team(conn, team_id))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT u.id, u.display_name, u.email FROM team_members tm "
            "JOIN users u ON u.id = tm.user_id WHERE tm.team_id = %s ORDER BY u.display_name",
            (team_id,),
        )
        rows = cur.fetchall()
    return [{"id": str(r[0]), "display_name": r[1], "email": r[2]} for r in rows]


@router.post("/{team_id}/members")
def add_team_member(
    team_id: str, body: TeamMemberAdd, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    _require_org_admin(conn, user_id, _organization_id_for_team(conn, team_id))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO team_members (team_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (team_id, body.user_id),
        )
    # solo il nuovo membro è interessato, non serve invalidate_team_permissions
    # (che invalida OGNI membro): la sua composizione del team è l'unica cosa
    # cambiata qui, i ruoli degli altri membri restano quelli che erano.
    invalidate_user_permissions(body.user_id)
    return {"status": "ok"}


@router.delete("/{team_id}/members/{member_user_id}")
def remove_team_member(
    team_id: str, member_user_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    _require_org_admin(conn, user_id, _organization_id_for_team(conn, team_id))
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM team_members WHERE team_id = %s AND user_id = %s", (team_id, member_user_id)
        )
    invalidate_user_permissions(member_user_id)
    return {"status": "ok"}


@router.post("/{team_id}/roles")
def grant_role_to_team(
    team_id: str, body: TeamRoleGrant, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)
):
    """Assegna un ruolo al TEAM (non a un singolo utente) su una risorsa: tutti i membri
    del team erediteranno questo permesso (vedi wav_core.permissions).

    Il controllo qui è sulla risorsa che si vuole concedere (stesso _require_admin
    di permissions.py::grant_permission), non sull'organizzazione del team: un
    admin dell'organizzazione del team non ha automaticamente il diritto di
    concedere accessi su risorse di ALTRE organizzazioni.
    """
    _require_admin(conn, user_id, body.resource_type, body.resource_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO role_assignments (principal_type, principal_id, resource_type, resource_id, role)
            VALUES ('team', %s, %s, %s, %s)
            ON CONFLICT (principal_type, principal_id, resource_type, resource_id)
            DO UPDATE SET role = EXCLUDED.role
            """,
            (team_id, body.resource_type, body.resource_id, body.role),
        )
    invalidate_team_permissions(conn, team_id)
    return {"status": "ok"}

# NOTA: /teams/{id}/roles fa la stessa cosa di POST /permissions con
# principal_type="team" (vedi permissions.py) - il frontend usa quest'ultimo
# (PermissionsPanel), questo endpoint resta per eventuali chiamate dirette
# all'API che preferiscono assegnare il ruolo "dal lato team".
#
# TODO: endpoint DELETE per revocare un ruolo assegnato dal team (oggi si può
# revocare solo dal lato risorsa, DELETE /permissions/{assignment_id}).
