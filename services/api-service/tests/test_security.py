"""Test di sicurezza mirati: controllo accessi cross-organizzazione (IDOR),
attacchi al JWT, injection, mass assignment, esposizione di dati sensibili.

I test IDOR sono una regressione diretta su un audit di questa sessione che ha
trovato 9 endpoint (list_assignees/list_dependencies/list_task_tags in
tasks.py, list_layers, list_comments, list_projects/get_project/list_columns
in projects.py, users.py::search_users) senza alcun controllo di autenticazione
- chiunque potesse raggiungere l'API poteva leggere dati di qualsiasi
organizzazione, non solo la propria. Corretti nello stesso giro in cui sono
stati scritti questi test."""

import os

import jwt

from wav_core.security import create_access_token


def _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role):
    """Due organizzazioni isolate, ciascuna con un proprio owner: usato da ogni
    test IDOR per verificare che l'owner di A non veda nulla di B."""
    owner_a = make_user()
    org_a = make_org()
    grant_role("user", owner_a, "organization", org_a, "owner")
    project_a = make_project(org_a)
    layer_a = make_layer(project_a)

    owner_b = make_user()
    org_b = make_org()
    grant_role("user", owner_b, "organization", org_b, "owner")
    project_b = make_project(org_b)
    layer_b = make_layer(project_b)

    return {
        "owner_a": owner_a, "org_a": org_a, "project_a": project_a, "layer_a": layer_a,
        "owner_b": owner_b, "org_b": org_b, "project_b": project_b, "layer_b": layer_b,
    }


class TestIDOR:
    """Ogni endpoint qui deve rifiutare (401/403), mai restituire dati di
    un'organizzazione a cui il chiamante non ha alcun accesso."""

    def test_list_assignees_requires_access_to_the_task(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)
        task = client.post(
            "/tasks", json={"layer_id": ctx["layer_a"], "title": "Segreta"}, headers=auth_headers(ctx["owner_a"])
        ).json()

        assert client.get(f"/tasks/{task['id']}/assignees").status_code == 422  # nessun header Authorization
        assert client.get(f"/tasks/{task['id']}/assignees", headers=auth_headers(ctx["owner_b"])).status_code == 403
        assert client.get(f"/tasks/{task['id']}/assignees", headers=auth_headers(ctx["owner_a"])).status_code == 200

    def test_list_dependencies_requires_access_to_the_task(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)
        task = client.post(
            "/tasks", json={"layer_id": ctx["layer_a"], "title": "Segreta"}, headers=auth_headers(ctx["owner_a"])
        ).json()

        assert client.get(f"/tasks/{task['id']}/dependencies").status_code == 422
        assert client.get(f"/tasks/{task['id']}/dependencies", headers=auth_headers(ctx["owner_b"])).status_code == 403

    def test_list_task_tags_requires_access_to_the_task(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)
        task = client.post(
            "/tasks", json={"layer_id": ctx["layer_a"], "title": "Segreta"}, headers=auth_headers(ctx["owner_a"])
        ).json()

        assert client.get(f"/tasks/{task['id']}/tags").status_code == 422
        assert client.get(f"/tasks/{task['id']}/tags", headers=auth_headers(ctx["owner_b"])).status_code == 403

    def test_add_dependency_requires_access_to_both_tasks(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        """Editor su task_id non deve bastare per agganciarla (e quindi, via
        list_dependencies, scoprirne il titolo) a una task di un'altra org mai vista."""
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)
        task_a = client.post(
            "/tasks", json={"layer_id": ctx["layer_a"], "title": "A"}, headers=auth_headers(ctx["owner_a"])
        ).json()
        task_b = client.post(
            "/tasks", json={"layer_id": ctx["layer_b"], "title": "Segreta B"}, headers=auth_headers(ctx["owner_b"])
        ).json()

        res = client.post(f"/tasks/{task_a['id']}/dependencies/{task_b['id']}", headers=auth_headers(ctx["owner_a"]))
        assert res.status_code == 403

    def test_list_layers_requires_access_to_the_project(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)

        assert client.get("/layers", params={"project_id": ctx["project_a"]}).status_code == 422
        assert (
            client.get("/layers", params={"project_id": ctx["project_a"]}, headers=auth_headers(ctx["owner_b"])).status_code
            == 403
        )
        assert (
            client.get("/layers", params={"project_id": ctx["project_a"]}, headers=auth_headers(ctx["owner_a"])).status_code
            == 200
        )

    def test_list_comments_requires_access_to_the_task(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)
        task = client.post(
            "/tasks", json={"layer_id": ctx["layer_a"], "title": "T"}, headers=auth_headers(ctx["owner_a"])
        ).json()
        client.post(
            "/comments", json={"task_id": task["id"], "body": "Segreto"}, headers=auth_headers(ctx["owner_a"])
        )

        assert client.get("/comments", params={"task_id": task["id"]}).status_code == 422
        assert (
            client.get("/comments", params={"task_id": task["id"]}, headers=auth_headers(ctx["owner_b"])).status_code
            == 403
        )

    def test_list_projects_requires_access_to_the_organization(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)

        assert client.get("/projects", params={"organization_id": ctx["org_a"]}).status_code == 422
        assert (
            client.get("/projects", params={"organization_id": ctx["org_a"]}, headers=auth_headers(ctx["owner_b"])).status_code
            == 403
        )

    def test_get_project_requires_access(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)

        assert client.get(f"/projects/{ctx['project_a']}").status_code == 422
        assert client.get(f"/projects/{ctx['project_a']}", headers=auth_headers(ctx["owner_b"])).status_code == 403
        assert client.get(f"/projects/{ctx['project_a']}", headers=auth_headers(ctx["owner_a"])).status_code == 200

    def test_list_columns_requires_access_to_the_project(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        ctx = _two_orgs_with_a_task(make_user, make_org, make_project, make_layer, grant_role)

        assert client.get(f"/projects/{ctx['project_a']}/columns").status_code == 422
        assert (
            client.get(f"/projects/{ctx['project_a']}/columns", headers=auth_headers(ctx["owner_b"])).status_code == 403
        )

    def test_search_users_is_scoped_to_shared_organizations(
        self, client, auth_headers, make_user, make_org, grant_role
    ):
        org_a = make_org()
        org_b = make_org()
        member_a = make_user(display_name="Findable Alice")
        member_b = make_user(display_name="Findable Bob")
        grant_role("user", member_a, "organization", org_a, "editor")
        grant_role("user", member_b, "organization", org_b, "editor")

        assert client.get("/users/search", params={"q": "Findable"}).status_code == 422

        results = client.get("/users/search", params={"q": "Findable"}, headers=auth_headers(member_a)).json()
        ids = {u["id"] for u in results}
        assert member_a in ids
        assert member_b not in ids


class TestJWTAttacks:
    def test_token_with_tampered_signature_is_rejected(self, client, make_user):
        user_id = make_user()
        token = create_access_token(user_id)
        tampered = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
        res = client.get("/me", headers={"Authorization": f"Bearer {tampered}"})
        assert res.status_code == 401

    def test_token_signed_with_a_different_secret_is_rejected(self, client, make_user):
        user_id = make_user()
        forged = jwt.encode({"sub": user_id, "type": "access", "exp": 9999999999}, "not-the-real-secret", algorithm="HS256")
        res = client.get("/me", headers={"Authorization": f"Bearer {forged}"})
        assert res.status_code == 401

    def test_expired_token_is_rejected(self, client, make_user):
        user_id = make_user()
        expired = jwt.encode(
            {"sub": user_id, "type": "access", "exp": 1},  # 1970, ben scaduto
            os.environ["JWT_SECRET"],
            algorithm="HS256",
        )
        res = client.get("/me", headers={"Authorization": f"Bearer {expired}"})
        assert res.status_code == 401

    def test_none_algorithm_token_is_rejected(self, client, make_user):
        """Classe di vulnerabilità nota (JWT "alg: none"): un token che dichiara
        di non essere firmato non deve mai essere accettato. wav_core.security
        la blocca già passando algorithms=[settings.jwt_algorithm] esplicito a
        jwt.decode (un allowlist, non un default permissivo) - qui solo per
        provarlo con un test, non per introdurre la protezione."""
        user_id = make_user()
        forged = jwt.encode({"sub": user_id, "type": "access", "exp": 9999999999}, key="", algorithm="none")
        res = client.get("/me", headers={"Authorization": f"Bearer {forged}"})
        assert res.status_code == 401


class TestInjectionAndMassAssignment:
    def test_sql_injection_payload_in_task_title_is_stored_literally(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role, db_conn
    ):
        user_id = make_user()
        org_id = make_org()
        grant_role("user", user_id, "organization", org_id, "owner")
        project_id = make_project(org_id)
        layer_id = make_layer(project_id)

        payload = "'; DROP TABLE tasks; --"
        res = client.post("/tasks", json={"layer_id": layer_id, "title": payload}, headers=auth_headers(user_id))
        assert res.status_code == 200
        assert res.json()["title"] == payload

        # la tabella tasks esiste ancora ed è interrogabile normalmente
        with db_conn.cursor() as cur:
            cur.execute("SELECT title FROM tasks WHERE layer_id = %s", (layer_id,))
            assert cur.fetchone()[0] == payload

    def test_update_task_ignores_fields_outside_its_whitelist(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        """set_clauses in update_task è costruito con un f-string sui nomi
        campo, ma quei nomi vengono SOLO da TaskUpdate (whitelist Pydantic fissa):
        un campo extra nel JSON (qui created_by, per provare a spacciarsi per un
        altro creatore) deve essere ignorato in silenzio, non eseguito."""
        user_id = make_user()
        other_user_id = make_user()
        org_id = make_org()
        grant_role("user", user_id, "organization", org_id, "owner")
        project_id = make_project(org_id)
        layer_id = make_layer(project_id)
        task = client.post("/tasks", json={"layer_id": layer_id, "title": "T"}, headers=auth_headers(user_id)).json()
        assert task["created_by"] == user_id

        res = client.patch(
            f"/tasks/{task['id']}",
            json={"title": "T2", "created_by": other_user_id, "id": "00000000-0000-0000-0000-000000000000"},
            headers=auth_headers(user_id),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["title"] == "T2"
        assert body["created_by"] == user_id  # non other_user_id
        assert body["id"] == task["id"]  # non l'id iniettato

    def test_create_task_ignores_client_supplied_created_by(
        self, client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
    ):
        user_id = make_user()
        other_user_id = make_user()
        org_id = make_org()
        grant_role("user", user_id, "organization", org_id, "owner")
        project_id = make_project(org_id)
        layer_id = make_layer(project_id)

        res = client.post(
            "/tasks",
            json={"layer_id": layer_id, "title": "T", "created_by": other_user_id},
            headers=auth_headers(user_id),
        )
        assert res.status_code == 200
        assert res.json()["created_by"] == user_id


class TestSensitiveDataExposure:
    def test_password_hash_never_appears_in_any_response(self, client, auth_headers, make_user):
        user_id = make_user(email="hash-exposure@example.com")
        profile_res = client.get("/me", headers=auth_headers(user_id))
        search_res = client.get("/users/search", params={"q": "hash-exposure"}, headers=auth_headers(user_id))

        for res in (profile_res, search_res):
            assert "password_hash" not in res.text
            assert "password" not in res.text
