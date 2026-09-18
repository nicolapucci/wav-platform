from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurazione condivisa, letta da variabili d'ambiente (vedi .env.example)."""

    database_url: str
    redis_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Limite per IP su /register e /login (vedi auth-service/app/main.py).
    auth_rate_limit_max: int = 10
    auth_rate_limit_window_seconds: int = 60
    # Blocco per account dopo troppi login falliti di fila, indipendente dall'IP
    # di chi li fa (un attacco distribuito su più IP aggira il limite sopra).
    login_lockout_threshold: int = 5
    login_lockout_minutes: int = 15

    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "wav-attachments"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
