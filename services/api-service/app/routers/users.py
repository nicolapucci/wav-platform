from fastapi import APIRouter, Depends, Query
from wav_core.db import get_conn

from ..deps import get_current_user_id

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search")
def search_users(q: str = Query(..., min_length=2), user_id: str = Depends(get_current_user_id), conn=Depends(get_conn)):
    """Ricerca per email O nome visualizzato: usata sia per l'autocomplete di
    permessi/assegnatari (di solito si cerca per email) sia per le menzioni nei
    commenti (di solito si digita il nome).

    Ristretta a utenti che condividono almeno un'organizzazione (ruolo diretto
    o via team) con chi cerca, invece che su tutta la tabella users: prima non
    lo era (né richiedeva autenticazione), quindi chiunque potesse raggiungere
    l'API poteva enumerare email/nomi di ogni utente della piattaforma, non
    solo dei propri colleghi. Semplificazione consapevole: guarda solo i ruoli
    ORGANIZATION diretti (propri o di un team), non quelli concessi solo a un
    project/layer specifico - coerente con come le altre "list X di
    un'organizzazione" (es. teams.py::list_teams) già funzionano in questo
    codebase."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH my_orgs AS (
                SELECT DISTINCT ra.resource_id AS org_id
                FROM role_assignments ra
                LEFT JOIN team_members tm ON tm.user_id = %(uid)s
                WHERE ra.resource_type = 'organization'
                  AND (
                    (ra.principal_type = 'user' AND ra.principal_id = %(uid)s)
                    OR (ra.principal_type = 'team' AND ra.principal_id = tm.team_id)
                  )
            )
            SELECT DISTINCT u.id, u.email, u.display_name
            FROM users u
            JOIN role_assignments ra2
                ON ra2.resource_type = 'organization' AND ra2.resource_id IN (SELECT org_id FROM my_orgs)
            LEFT JOIN team_members tm2 ON ra2.principal_type = 'team' AND tm2.team_id = ra2.principal_id
            WHERE u.deactivated_at IS NULL
              AND (u.email ILIKE %(q)s OR u.display_name ILIKE %(q)s)
              AND (
                (ra2.principal_type = 'user' AND ra2.principal_id = u.id)
                OR (ra2.principal_type = 'team' AND tm2.user_id = u.id)
              )
            ORDER BY u.display_name
            LIMIT 10
            """,
            {"uid": user_id, "q": f"%{q}%"},
        )
        rows = cur.fetchall()
    return [{"id": str(r[0]), "email": r[1], "display_name": r[2]} for r in rows]
