from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from wav_core.config import settings
from wav_core.db import get_conn
from wav_core.redis_client import get_redis_sync
from wav_core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

app = FastAPI(title="auth-service")


def _client_ip(request: Request) -> str:
    # Dietro nginx arriva già X-Real-IP (vedi nginx/nginx.conf, location
    # /auth/): request.client.host da solo sarebbe l'IP del container nginx,
    # uguale per ogni chiamante.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def _enforce_rate_limit(request: Request, bucket: str) -> None:
    """Limite per IP, indipendente tra /register e /login (bucket separati):
    oltre auth_rate_limit_max richieste in auth_rate_limit_window_seconds
    secondi dallo stesso IP, 429 invece di lasciar passare un attacco a forza
    bruta o registrazioni spam."""
    r = get_redis_sync()
    key = f"ratelimit:{bucket}:{_client_ip(request)}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, settings.auth_rate_limit_window_seconds)
    if count > settings.auth_rate_limit_max:
        raise HTTPException(status_code=429, detail="Troppe richieste, riprova più tardi")


class RegisterRequest(BaseModel):
    email: EmailStr
    # min_length 8 replica solo lato server il vincolo HTML dell'input password
    # nel form di registrazione (frontend/src/pages/LoginPage.tsx): quello da
    # solo è aggirabile da chiunque chiami l'API direttamente. max_length
    # limita il lavoro che argon2 (hash_password) deve fare per richiesta, così
    # una password volutamente enorme non diventa un modo economico per
    # rallentare il servizio.
    password: str = Field(min_length=8, max_length=128)
    display_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, request: Request, conn=Depends(get_conn)):
    _enforce_rate_limit(request, "register")
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (body.email,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Email già registrata")
        cur.execute(
            "INSERT INTO users (email, password_hash, display_name) VALUES (%s, %s, %s) RETURNING id",
            (body.email, hash_password(body.password), body.display_name),
        )
        user_id = cur.fetchone()[0]

    return TokenResponse(
        access_token=create_access_token(str(user_id)),
        refresh_token=create_refresh_token(str(user_id)),
    )


@app.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, conn=Depends(get_conn)):
    _enforce_rate_limit(request, "login")

    # Blocco per account, non per IP: incrementato sull'email indipendentemente
    # da row/verify_password sotto, così un'email inesistente si blocca esattamente
    # come una esistente con password sbagliata - non deve diventare un modo per
    # scoprire quali email sono registrate osservando quando scatta il 429 invece
    # del 401 (stesso motivo del messaggio generico più sotto).
    r = get_redis_sync()
    lockout_key = f"loginfail:{body.email}"
    if int(r.get(lockout_key) or 0) >= settings.login_lockout_threshold:
        raise HTTPException(status_code=429, detail="Troppi tentativi falliti, riprova più tardi")

    with conn.cursor() as cur:
        cur.execute("SELECT id, password_hash, deactivated_at FROM users WHERE email = %s", (body.email,))
        row = cur.fetchone()
        # stesso messaggio generico per credenziali sbagliate e account
        # disattivato: non si vuole rivelare a chi prova ad accedere se
        # l'email esiste ma è stata disattivata, solo che il login è fallito.
        if not row or not row[1] or not verify_password(body.password, row[1]) or row[2] is not None:
            failures = r.incr(lockout_key)
            if failures == 1:
                r.expire(lockout_key, settings.login_lockout_minutes * 60)
            raise HTTPException(status_code=401, detail="Credenziali non valide")
        user_id = row[0]

    r.delete(lockout_key)
    return TokenResponse(
        access_token=create_access_token(str(user_id)),
        refresh_token=create_refresh_token(str(user_id)),
    )


@app.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, conn=Depends(get_conn)):
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token non valido o scaduto")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Il token fornito non è un refresh token")

    user_id = payload["sub"]

    # a differenza dell'access token (vedi deps.py::get_current_user_id in
    # api-service, che non tocca il DB per restare veloce su ogni richiesta),
    # qui una query in più è accettabile: /refresh è raro rispetto alle
    # richieste autenticate normali, ed è il punto naturale per far scadere
    # una sessione di un account disattivato dopo al più
    # ACCESS_TOKEN_EXPIRE_MINUTES invece che dopo REFRESH_TOKEN_EXPIRE_DAYS.
    with conn.cursor() as cur:
        cur.execute("SELECT deactivated_at FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row or row[0] is not None:
            raise HTTPException(status_code=401, detail="Account disattivato")

    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


# TODO OAuth2/OIDC (Google, GitHub, ...):
# - GET /oauth/{provider}/login   -> redirect all'authorization endpoint del provider (authlib)
# - GET /oauth/{provider}/callback -> scambia il code, recupera l'email dal provider,
#   fa upsert su users + oauth_identities, e infine chiama create_access_token/create_refresh_token
#   esattamente come /login: a valle, api-service e ws-gateway non sanno né gli interessa
#   se l'utente si è loggato con password o con un provider esterno.
