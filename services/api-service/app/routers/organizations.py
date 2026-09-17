from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from wav_core.db import get_conn
from wav_core.permissions import Role, candidate_role_at_resource

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
            WHERE o.archived_at IS NULL
              AND (
                (ra.principal_type = 'user' AND ra.principal_id = %(uid)s)
                OR (ra.principal_type = 'team' AND ra.principal_id = tm.team_id)
              )
            """,
            {"uid": user_id},
        )
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "slug": r[2]} for r in rows]


@router.delete("/{organization_id}")
def delete_organization(organization_id: str, user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    """Cancellazione logica: archivia l'organizzazione e, a cascata, tutti i
    suoi progetti, i layer di quei progetti, e le task di quei layer - stessa
    idea di projects.py::delete_project, un livello più in alto nella
    gerarchia. Richiede 'admin'+ sull'organizzazione, come crearne i progetti
    (create_project)."""
    role = candidate_role_at_resource(conn, user_id, "organization", organization_id)
    if role is None or role < Role.admin:
        raise HTTPException(status_code=403, detail="Servono permessi da admin sull'organizzazione per eliminarla")

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE layers SET archived_at = now() "
            "WHERE project_id IN (SELECT id FROM projects WHERE organization_id = %s) AND archived_at IS NULL",
            (organization_id,),
        )
        cur.execute(
            "UPDATE tasks SET archived_at = now() WHERE layer_id IN ("
            "  SELECT id FROM layers WHERE project_id IN ("
            "    SELECT id FROM projects WHERE organization_id = %s"
            "  )"
            ") AND archived_at IS NULL",
            (organization_id,),
        )
        cur.execute(
            "UPDATE projects SET archived_at = now() WHERE organization_id = %s AND archived_at IS NULL",
            (organization_id,),
        )
        cur.execute("UPDATE organizations SET archived_at = now() WHERE id = %s", (organization_id,))
    return {"status": "ok"}
