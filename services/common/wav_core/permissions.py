"""Risoluzione del ruolo effettivo di un utente su una risorsa (organization/project/layer).

Algoritmo (vedi docs/architettura.md §3):
1. Si risale la catena layer -> ... -> layer radice -> project -> organization.
2. Ad ogni livello si calcola il ruolo candidato come il MASSIMO tra il ruolo
   assegnato direttamente all'utente e quello assegnato a uno dei suoi team.
3. Vince il PRIMO livello (dal più specifico) che produce un candidato non nullo.
"""

from __future__ import annotations

from enum import IntEnum


class Role(IntEnum):
    reader = 10
    editor = 20
    admin = 30
    owner = 40

    @classmethod
    def from_str(cls, value: str) -> "Role":
        return cls[value]


def resolve_layer_ancestor_ids(conn, layer_id: str) -> list[str]:
    """Id del layer e di tutti i suoi antenati, dal più specifico al più generico,
    sfruttando la colonna ltree `path` (indice GiST, niente CTE ricorsiva)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM layers
            WHERE path @> (SELECT path FROM layers WHERE id = %s)
            ORDER BY nlevel(path) DESC
            """,
            (layer_id,),
        )
        return [row[0] for row in cur.fetchall()]


def candidate_role_at_resource(conn, user_id: str, resource_type: str, resource_id: str) -> Role | None:
    """Massimo tra il ruolo diretto dell'utente e quello dei suoi team su questa risorsa."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ra.role
            FROM role_assignments ra
            WHERE ra.resource_type = %s AND ra.resource_id = %s
              AND (
                (ra.principal_type = 'user' AND ra.principal_id = %s)
                OR (ra.principal_type = 'team' AND ra.principal_id IN (
                    SELECT team_id FROM team_members WHERE user_id = %s
                ))
              )
            """,
            (resource_type, resource_id, user_id, user_id),
        )
        roles = [Role.from_str(row[0]) for row in cur.fetchall()]
        return max(roles) if roles else None


def resolve_effective_role_on_layer(conn, user_id: str, layer_id: str) -> Role | None:
    """Ruolo effettivo di `user_id` sulla task/risorsa che vive dentro `layer_id`."""
    for lid in resolve_layer_ancestor_ids(conn, layer_id):
        role = candidate_role_at_resource(conn, user_id, "layer", lid)
        if role is not None:
            return role

    with conn.cursor() as cur:
        cur.execute("SELECT project_id FROM layers WHERE id = %s", (layer_id,))
        row = cur.fetchone()
        if row is None:
            return None
        project_id = row[0]

    role = candidate_role_at_resource(conn, user_id, "project", project_id)
    if role is not None:
        return role

    with conn.cursor() as cur:
        cur.execute("SELECT organization_id FROM projects WHERE id = %s", (project_id,))
        organization_id = cur.fetchone()[0]

    return candidate_role_at_resource(conn, user_id, "organization", organization_id)


def resolve_effective_role_on_project(conn, user_id: str, project_id: str) -> Role | None:
    """Ruolo effettivo su un project: se non c'è un ruolo diretto (utente o team)
    sul project, si eredita dall'organization."""
    role = candidate_role_at_resource(conn, user_id, "project", project_id)
    if role is not None:
        return role

    with conn.cursor() as cur:
        cur.execute("SELECT organization_id FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if row is None:
            return None
        organization_id = row[0]

    return candidate_role_at_resource(conn, user_id, "organization", organization_id)


def resolve_effective_role(conn, user_id: str, resource_type: str, resource_id: str) -> Role | None:
    """Dispatcher generico: usato dagli endpoint che operano su un tipo di risorsa
    qualsiasi passato a runtime (es. la gestione permessi in app/routers/permissions.py)."""
    if resource_type == "layer":
        return resolve_effective_role_on_layer(conn, user_id, resource_id)
    if resource_type == "project":
        return resolve_effective_role_on_project(conn, user_id, resource_id)
    if resource_type == "organization":
        return candidate_role_at_resource(conn, user_id, "organization", resource_id)
    raise ValueError(f"resource_type sconosciuto: {resource_type!r}")


# NOTA implementativa: questa funzione fa 1-3 query sincrone per chiamata.
# In produzione va messa dietro una cache Redis (`perm:{user_id}:{resource_type}:{resource_id}`,
# TTL breve, invalidata sugli eventi di cambio membership) come descritto in architettura.md §3.
