import time

import jwt
from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _create_token(sub: str, expires_in_seconds: int, extra_claims: dict | None = None) -> str:
    now = int(time.time())
    payload = {"sub": sub, "iat": now, "exp": now + expires_in_seconds}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str) -> str:
    return _create_token(user_id, settings.access_token_expire_minutes * 60, {"type": "access"})


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, settings.refresh_token_expire_days * 24 * 3600, {"type": "refresh"})


def decode_token(token: str) -> dict:
    """Solleva jwt.PyJWTError se il token è scaduto o non valido: il chiamante la gestisce."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
