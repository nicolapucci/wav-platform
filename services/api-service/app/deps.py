from fastapi import Header, HTTPException
from wav_core.security import decode_token


def get_current_user_id(authorization: str = Header(...)) -> str:
    """Valida solo la firma/scadenza del JWT emesso da auth-service: nessuna
    chiamata di rete ad auth-service è necessaria (vedi architettura.md §8)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Header Authorization mancante o malformato")

    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Token non valido o scaduto")

    return payload["sub"]
