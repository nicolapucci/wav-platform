from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from wav_core.db import get_conn
from wav_core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

app = FastAPI(title="auth-service")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
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
def register(body: RegisterRequest, conn=Depends(get_conn)):
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
def login(body: LoginRequest, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (body.email,))
        row = cur.fetchone()
        if not row or not row[1] or not verify_password(body.password, row[1]):
            raise HTTPException(status_code=401, detail="Credenziali non valide")
        user_id = row[0]

    return TokenResponse(
        access_token=create_access_token(str(user_id)),
        refresh_token=create_refresh_token(str(user_id)),
    )


@app.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest):
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token non valido o scaduto")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Il token fornito non è un refresh token")

    user_id = payload["sub"]
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
