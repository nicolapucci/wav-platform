from fastapi import APIRouter, Depends
from pydantic import BaseModel
from wav_core.db import get_conn

from ..deps import get_current_user_id

router = APIRouter(prefix="/organizations", tags=["organizations"])


class OrgCreate(BaseModel):
    name: str
    slug: str


@router.post("")
def create_organization(body: OrgCreate, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO organizations (name, slug) VALUES (%s, %s) RETURNING id",
            (body.name, body.slug),
        )
        org_id = cur.fetchone()[0]
        # chi crea l'organizzazione ne diventa owner
        cur.execute(
            "INSERT INTO role_assignments (principal_type, principal_id, resource_type, resource_id, role) "
            "VALUES ('user', %s, 'organization', %s, 'owner')",
            (user_id, org_id),
        )
    return {"id": org_id, "name": body.name, "slug": body.slug}


@router.get("")
def list_my_organizations(user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    """Organizzazioni visibili all'utente: dirette o tramite un team di cui è membro."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT o.id, o.name, o.slug
            FROM organizations o
            LEFT JOIN role_assignments ra
                ON ra.resource_type = 'organization' AND ra.resource_id = o.id
            LEFT JOIN team_members tm ON tm.user_id = %(uid)s
            WHERE (ra.principal_type = 'user' AND ra.principal_id = %(uid)s)
               OR (ra.principal_type = 'team' AND ra.principal_id = tm.team_id)
            """,
            {"uid": user_id},
        )
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "slug": r[2]} for r in rows]
