"""Risoluzione del ruolo effettivo di un utente su una risorsa (organization/project/layer).

Algoritmo (vedi docs/architettura.md §3):
1. Si risale la catena layer -> ... -> layer radice -> project -> organization.
2. Ad ogni livello si calcola il ruolo candidato come il MASSIMO tra il ruolo
   assegnato direttamente all'utente e quello assegnato a uno dei suoi team.
3. Vince il PRIMO livello (dal più specifico) che produce un candidato non nullo.
"""

from __future__ import annotations

from enum import IntEnum

from .redis_client import get_redis_sync

# TTL breve: rete di sicurezza per eventuali buchi di invalidazione, non il
# meccanismo principale di correttezza (quello sono le invalidate_* esplicite
# sotto, chiamate da ogni endpoint che cambia un role_assignment o una
# membership di team).
_PERM_CACHE_TTL_SECONDS = 30
_PERM_CACHE_NONE = "\x00none"  # distingue "risolto a None" da "non in cache"


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


def _perm_cache_key(user_id: str, resource_type: str, resource_id: str) -> str:
    return f"perm:{user_id}:{resource_type}:{resource_id}"


def candidate_role_at_resource(conn, user_id: str, resource_type: str, resource_id: str) -> Role | None:
    """Massimo tra il ruolo diretto dell'utente e quello dei suoi team su questa
    risorsa. È la query più ripetuta di tutto l'app (ogni resolve_effective_role_*
    la richiama una o più volte risalendo la gerarchia, e diversi router la
    chiamano anche direttamente), quindi il risultato è cache-ato in Redis
    (perm:{user_id}:{resource_type}:{resource_id}, vedi architettura.md §3).
    Mettere la cache qui, al livello più basso, invece che in ciascuna delle
    resolve_effective_role_* sopra di essa, significa che una risoluzione su un
    layer e una su un project dello stesso progetto/organizzazione condividono
    le stesse voci di cache per i livelli in comune, non solo il risultato
    finale di una singola chiamata."""
    cache_key = _perm_cache_key(user_id, resource_type, resource_id)
    r = get_redis_sync()
    cached = r.get(cache_key)
    if cached is not None:
        return None if cached == _PERM_CACHE_NONE else Role.from_str(cached)

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
        role = max(roles) if roles else None

    r.set(cache_key, role.name if role is not None else _PERM_CACHE_NONE, ex=_PERM_CACHE_TTL_SECONDS)
    return role


def invalidate_user_permissions(user_id: str) -> None:
    """Rimuove ogni voce di cache dei permessi di user_id: da chiamare dopo un
    INSERT/UPDATE/DELETE su role_assignments con principal_type='user' che lo
    riguarda direttamente. Per un cambiamento che coinvolge un TEAM (role
    grant al team, oppure la sua membership), vedi invalidate_team_permissions:
    qui non basterebbe, perché il ruolo effettivo di ogni membro dipende da
    quello del team, non solo dalle proprie righe dirette in role_assignments.
    SCAN invece di KEYS: non blocca Redis anche se le voci fossero molte."""
    r = get_redis_sync()
    for key in r.scan_iter(match=f"perm:{user_id}:*"):
        r.delete(key)


def invalidate_team_permissions(conn, team_id: str) -> None:
    """Come invalidate_user_permissions, ma per ciascun membro del team: usata
    quando cambia un role_assignment concesso al TEAM stesso, o quando cambia
    la sua composizione (aggiunta/rimozione membro) - in entrambi i casi il
    ruolo effettivo di ogni membro può essere cambiato."""
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM team_members WHERE team_id = %s", (team_id,))
        member_ids = [str(row[0]) for row in cur.fetchall()]
    for member_id in member_ids:
        invalidate_user_permissions(member_id)


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
