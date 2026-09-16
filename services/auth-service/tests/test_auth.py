"""register/login/refresh di auth-service, contro un Postgres reale."""

from wav_core.security import decode_token


def test_register_creates_user_and_returns_valid_tokens(client, db_conn):
    response = client.post(
        "/register",
        json={"email": "nuovo@example.com", "password": "supersegreto", "display_name": "Nuovo Utente"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"

    access_payload = decode_token(body["access_token"])
    refresh_payload = decode_token(body["refresh_token"])
    assert access_payload["type"] == "access"
    assert refresh_payload["type"] == "refresh"
    assert access_payload["sub"] == refresh_payload["sub"]

    with db_conn.cursor() as cur:
        cur.execute("SELECT email, display_name FROM users WHERE id = %s", (access_payload["sub"],))
        row = cur.fetchone()
    assert row == ("nuovo@example.com", "Nuovo Utente")


def test_register_rejects_duplicate_email(client):
    body = {"email": "duplicato@example.com", "password": "pw123456", "display_name": "A"}
    assert client.post("/register", json=body).status_code == 200
    second = client.post("/register", json={**body, "display_name": "B"})
    assert second.status_code == 409


def test_password_is_not_stored_in_clear_text(client, db_conn):
    client.post(
        "/register", json={"email": "hash@example.com", "password": "unapasswordvera", "display_name": "X"}
    )
    with db_conn.cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE email = %s", ("hash@example.com",))
        (stored_hash,) = cur.fetchone()
    assert stored_hash != "unapasswordvera"
    assert stored_hash.startswith("$argon2")


def test_login_with_correct_credentials_returns_tokens(client):
    client.post(
        "/register", json={"email": "login@example.com", "password": "correctpw", "display_name": "L"}
    )
    response = client.post("/login", json={"email": "login@example.com", "password": "correctpw"})
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_with_wrong_password_returns_401(client):
    client.post(
        "/register", json={"email": "wrongpw@example.com", "password": "correctpw", "display_name": "L"}
    )
    response = client.post("/login", json={"email": "wrongpw@example.com", "password": "sbagliata"})
    assert response.status_code == 401


def test_login_with_unknown_email_returns_401(client):
    response = client.post("/login", json={"email": "non-esiste@example.com", "password": "qualsiasi"})
    assert response.status_code == 401


def test_login_rejects_user_without_password_hash(client, db_conn):
    """Utente creato solo via OAuth (password_hash NULL, vedi schema): il login
    con password deve rifiutare, non fare 500 su un verify_password(None)."""
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, display_name, password_hash) VALUES (%s, %s, NULL)",
            ("oauth-only@example.com", "OAuth User"),
        )
    response = client.post("/login", json={"email": "oauth-only@example.com", "password": "qualsiasi"})
    assert response.status_code == 401


def test_refresh_with_valid_refresh_token_issues_new_pair(client):
    tokens = client.post(
        "/register", json={"email": "refresh@example.com", "password": "pw123456", "display_name": "R"}
    ).json()
    response = client.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    new_tokens = response.json()
    assert decode_token(new_tokens["access_token"])["sub"] == decode_token(tokens["refresh_token"])["sub"]


def test_refresh_rejects_access_token_used_as_refresh_token(client):
    """Un access token non deve poter essere usato al posto di un refresh token
    (controllo payload["type"] == "refresh")."""
    tokens = client.post(
        "/register", json={"email": "typeconfusion@example.com", "password": "pw123456", "display_name": "T"}
    ).json()
    response = client.post("/refresh", json={"refresh_token": tokens["access_token"]})
    assert response.status_code == 401


def test_refresh_rejects_garbage_token(client):
    response = client.post("/refresh", json={"refresh_token": "non-e-un-jwt"})
    assert response.status_code == 401
