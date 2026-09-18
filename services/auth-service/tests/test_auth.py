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


def test_register_rejects_password_shorter_than_8_chars(client):
    """Il minLength=8 lato client (LoginPage.tsx) è aggirabile da chiunque
    chiami l'API direttamente: qui si prova che il server lo applica comunque."""
    response = client.post(
        "/register", json={"email": "corta@example.com", "password": "1234567", "display_name": "X"}
    )
    assert response.status_code == 422


def test_register_rejects_password_longer_than_128_chars(client):
    response = client.post(
        "/register", json={"email": "lunga@example.com", "password": "a" * 129, "display_name": "X"}
    )
    assert response.status_code == 422


def test_register_accepts_password_at_the_boundaries(client):
    ok_min = client.post(
        "/register", json={"email": "min8@example.com", "password": "a" * 8, "display_name": "X"}
    )
    assert ok_min.status_code == 200
    ok_max = client.post(
        "/register", json={"email": "max128@example.com", "password": "a" * 128, "display_name": "X"}
    )
    assert ok_max.status_code == 200


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


def test_login_rejects_deactivated_user(client, db_conn):
    client.post(
        "/register", json={"email": "deactivated@example.com", "password": "pw123456", "display_name": "D"}
    )
    with db_conn.cursor() as cur:
        cur.execute("UPDATE users SET deactivated_at = now() WHERE email = %s", ("deactivated@example.com",))

    response = client.post("/login", json={"email": "deactivated@example.com", "password": "pw123456"})
    assert response.status_code == 401


def test_refresh_rejects_token_of_deactivated_user(client, db_conn):
    """Un refresh token emesso PRIMA della disattivazione non deve continuare a
    funzionare indefinitamente: a differenza dell'access token (che scade da
    solo entro ACCESS_TOKEN_EXPIRE_MINUTES), /refresh fa una query apposta."""
    tokens = client.post(
        "/register", json={"email": "deactivate-refresh@example.com", "password": "pw123456", "display_name": "D"}
    ).json()
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET deactivated_at = now() WHERE email = %s", ("deactivate-refresh@example.com",)
        )

    response = client.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


def test_login_rate_limit_blocks_after_too_many_requests_from_same_ip(client):
    ip = {"X-Real-IP": "10.0.0.1"}
    # Email diversa a ogni richiesta: isola il rate-limit per IP dal lockout per
    # account sotto - 5 fallimenti sulla STESSA email farebbero scattare un 429
    # anche da soli, ma per un motivo diverso da quello che questo test verifica.
    for i in range(10):
        res = client.post("/login", json={"email": f"ratelimit{i}@example.com", "password": "x"}, headers=ip)
        assert res.status_code == 401
    blocked = client.post("/login", json={"email": "ratelimit-over@example.com", "password": "x"}, headers=ip)
    assert blocked.status_code == 429


def test_register_rate_limit_blocks_after_too_many_requests_from_same_ip(client):
    ip = {"X-Real-IP": "10.0.0.2"}
    for i in range(10):
        res = client.post(
            "/register",
            json={"email": f"regratelimit{i}@example.com", "password": "password123", "display_name": "X"},
            headers=ip,
        )
        assert res.status_code == 200
    blocked = client.post(
        "/register",
        json={"email": "regratelimit-over@example.com", "password": "password123", "display_name": "X"},
        headers=ip,
    )
    assert blocked.status_code == 429


def test_rate_limit_is_isolated_per_ip(client):
    for i in range(10):
        res = client.post(
            "/login", json={"email": f"perip{i}@example.com", "password": "x"}, headers={"X-Real-IP": "10.0.0.3"}
        )
        assert res.status_code == 401
    # IP diverso: non eredita il budget esaurito del primo.
    other_ip = client.post(
        "/login", json={"email": "perip-other@example.com", "password": "x"}, headers={"X-Real-IP": "10.0.0.4"}
    )
    assert other_ip.status_code == 401


def test_login_lockout_after_too_many_failed_attempts(client):
    email = "lockout@example.com"
    client.post("/register", json={"email": email, "password": "correctpw123", "display_name": "L"})

    for _ in range(5):
        res = client.post("/login", json={"email": email, "password": "sbagliata"})
        assert res.status_code == 401

    # bloccato ora, anche con la password giusta.
    locked = client.post("/login", json={"email": email, "password": "correctpw123"})
    assert locked.status_code == 429


def test_login_lockout_is_isolated_per_email(client):
    email_a = "lockout-a@example.com"
    email_b = "lockout-b@example.com"
    client.post("/register", json={"email": email_b, "password": "correctpw123", "display_name": "B"})

    for _ in range(5):
        client.post("/login", json={"email": email_a, "password": "sbagliata"})

    # email_b non ha fallimenti propri accumulati: login regolare.
    res = client.post("/login", json={"email": email_b, "password": "correctpw123"})
    assert res.status_code == 200


def test_successful_login_resets_lockout_counter(client):
    email = "lockout-reset@example.com"
    client.post("/register", json={"email": email, "password": "correctpw123", "display_name": "R"})

    for _ in range(3):
        client.post("/login", json={"email": email, "password": "sbagliata"})

    ok = client.post("/login", json={"email": email, "password": "correctpw123"})
    assert ok.status_code == 200

    # dopo il successo il contatore riparte da zero: altri 3 fallimenti (sotto
    # la soglia di 5) non bastano per il lockout, a differenza di 3+3 se il
    # contatore non fosse stato azzerato al login riuscito.
    for _ in range(3):
        res = client.post("/login", json={"email": email, "password": "sbagliata"})
        assert res.status_code == 401
