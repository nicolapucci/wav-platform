from fastapi import APIRouter, Depends, Query
from wav_core.db import get_conn

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search")
def search_users(q: str = Query(..., min_length=2), conn=Depends(get_conn)):
    """Ricerca per email O nome visualizzato: usata sia per l'autocomplete di
    permessi/assegnatari (di solito si cerca per email) sia per le menzioni nei
    commenti (di solito si digita il nome).
    TODO produzione: paginare, e forse restringere ai soli utenti già membri
    della stessa organizzazione invece che su tutta la tabella users."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, display_name FROM users "
            "WHERE email ILIKE %s OR display_name ILIKE %s "
            "ORDER BY display_name LIMIT 10",
            (f"%{q}%", f"%{q}%"),
        )
        rows = cur.fetchall()
    return [{"id": str(r[0]), "email": r[1], "display_name": r[2]} for r in rows]
