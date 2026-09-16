"""Autorizzazione di ogni endpoint di app/routers/teams.py. Regressione mirata
sulla falla corretta in questa sessione: grant_role_to_team deve controllare i
permessi admin sulla RISORSA da concedere (stesso _require_admin di
permissions.py), non sull'organizzazione del team - altrimenti un admin
dell'organizzazione del team potrebbe concedere accessi su risorse di
QUALSIASI altra organizzazione."""


def test_endpoints_require_authentication(client):
    """Nessuna Authorization header: FastAPI rifiuta a livello di validazione del
    parametro (422, il campo Header(...) è obbligatorio) prima ancora che
    get_current_user_id giri - il bug originale era la totale assenza di un
    Depends(get_current_user_id), che avrebbe fatto passare queste richieste
    con 200. Qui basta verificare che nessuna riesca."""
    assert client.post("/teams", json={"organization_id": "x", "name": "T"}).status_code == 422
    assert client.get("/teams", params={"organization_id": "x"}).status_code == 422
    assert client.get("/teams/some-id/members").status_code == 422
    assert client.post("/teams/some-id/members", json={"user_id": "x"}).status_code == 422
    assert client.delete("/teams/some-id/members/some-user").status_code == 422
    assert client.post(
        "/teams/some-id/roles", json={"resource_type": "project", "resource_id": "x", "role": "admin"}
    ).status_code == 422


def test_endpoints_reject_invalid_bearer_token(client):
    """Header presente ma non valido: qui gira davvero get_current_user_id, che
    deve rispondere 401 (non 500 per un token che non decodifica)."""
    bad_headers = {"Authorization": "Bearer not-a-real-jwt"}
    assert client.post("/teams", json={"organization_id": "x", "name": "T"}, headers=bad_headers).status_code == 401
    assert client.get("/teams", params={"organization_id": "x"}, headers=bad_headers).status_code == 401


def test_create_team_requires_org_admin(client, auth_headers, make_user, make_org, grant_role):
    admin_id = make_user()
    reader_id = make_user()
    outsider_id = make_user()
    org_id = make_org()
    grant_role("user", admin_id, "organization", org_id, "admin")
    grant_role("user", reader_id, "organization", org_id, "reader")

    body = {"organization_id": org_id, "name": "Team"}
    assert client.post("/teams", json=body, headers=auth_headers(admin_id)).status_code == 200
    assert client.post("/teams", json=body, headers=auth_headers(reader_id)).status_code == 403
    assert client.post("/teams", json=body, headers=auth_headers(outsider_id)).status_code == 403


def test_list_teams_allows_reader_but_not_outsider(client, auth_headers, make_user, make_org, make_team, grant_role):
    reader_id = make_user()
    outsider_id = make_user()
    org_id = make_org()
    make_team(org_id)
    grant_role("user", reader_id, "organization", org_id, "reader")

    ok = client.get("/teams", params={"organization_id": org_id}, headers=auth_headers(reader_id))
    forbidden = client.get("/teams", params={"organization_id": org_id}, headers=auth_headers(outsider_id))
    assert ok.status_code == 200
    assert forbidden.status_code == 403


def test_member_management_requires_org_admin_not_just_reader(
    client, auth_headers, make_user, make_org, make_team, grant_role
):
    admin_id = make_user()
    reader_id = make_user()
    target_user_id = make_user()
    org_id = make_org()
    team_id = make_team(org_id)
    grant_role("user", admin_id, "organization", org_id, "admin")
    grant_role("user", reader_id, "organization", org_id, "reader")

    add_body = {"user_id": target_user_id}
    assert client.post(f"/teams/{team_id}/members", json=add_body, headers=auth_headers(reader_id)).status_code == 403
    added = client.post(f"/teams/{team_id}/members", json=add_body, headers=auth_headers(admin_id))
    assert added.status_code == 200

    members = client.get(f"/teams/{team_id}/members", headers=auth_headers(reader_id))
    assert members.status_code == 200
    assert any(m["id"] == target_user_id for m in members.json())

    assert client.delete(
        f"/teams/{team_id}/members/{target_user_id}", headers=auth_headers(reader_id)
    ).status_code == 403
    assert client.delete(
        f"/teams/{team_id}/members/{target_user_id}", headers=auth_headers(admin_id)
    ).status_code == 200


def test_grant_role_to_team_checks_target_resource_not_team_org(
    client, auth_headers, make_user, make_org, make_project, make_team, grant_role
):
    """Caso centrale della falla corretta: admin_a è admin dell'organizzazione
    del team (org_a) ma NON ha alcun permesso su project_b, che appartiene a
    org_b. Deve ricevere 403, non riuscire a concedere il ruolo."""
    admin_a_id = make_user()
    org_a = make_org()
    team_a = make_team(org_a)
    grant_role("user", admin_a_id, "organization", org_a, "admin")

    org_b = make_org()
    project_b = make_project(org_b)

    response = client.post(
        f"/teams/{team_a}/roles",
        json={"resource_type": "project", "resource_id": project_b, "role": "admin"},
        headers=auth_headers(admin_a_id),
    )
    assert response.status_code == 403


def test_grant_role_to_team_succeeds_when_admin_on_target_resource(
    client, auth_headers, db_conn, make_user, make_org, make_project, make_team, add_team_member, grant_role
):
    admin_id = make_user()
    member_id = make_user()
    org_id = make_org()
    project_id = make_project(org_id)
    team_id = make_team(org_id)
    add_team_member(team_id, member_id)
    grant_role("user", admin_id, "project", project_id, "admin")

    response = client.post(
        f"/teams/{team_id}/roles",
        json={"resource_type": "project", "resource_id": project_id, "role": "editor"},
        headers=auth_headers(admin_id),
    )
    assert response.status_code == 200

    # round-trip: un membro del team ora ha "editor" sul progetto per via del team
    from wav_core.permissions import Role, resolve_effective_role_on_project

    assert resolve_effective_role_on_project(db_conn, member_id, project_id) == Role.editor
