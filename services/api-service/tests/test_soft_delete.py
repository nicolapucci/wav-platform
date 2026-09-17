"""Cancellazione logica di task/layer/progetti/organizzazioni: ogni DELETE
archivia (archived_at) invece di rimuovere fisicamente, e per layer/progetto/
organizzazione la cascata deve raggiungere tutto quello che contengono."""

import pytest


def test_delete_task_is_excluded_from_list_and_get(client, auth_headers, make_user, make_org, make_project, make_layer, grant_role):
    user_id = make_user()
    headers = auth_headers(user_id)
    org_id = make_org()
    grant_role("user", user_id, "organization", org_id, "owner")
    project_id = make_project(org_id)
    layer_id = make_layer(project_id)
    task = client.post("/tasks", json={"layer_id": layer_id, "title": "Da eliminare"}, headers=headers).json()

    res = client.delete(f"/tasks/{task['id']}", headers=headers)
    assert res.status_code == 200

    assert client.get(f"/tasks/{task['id']}", headers=headers).status_code == 404
    listed = client.get("/tasks", params={"layer_id": layer_id}, headers=headers).json()
    assert listed == []


def test_delete_task_requires_editor(client, auth_headers, make_user, make_org, make_project, make_layer, grant_role):
    owner_id = make_user()
    reader_id = make_user()
    org_id = make_org()
    grant_role("user", owner_id, "organization", org_id, "owner")
    project_id = make_project(org_id)
    layer_id = make_layer(project_id)
    grant_role("user", reader_id, "layer", layer_id, "reader")
    task = client.post("/tasks", json={"layer_id": layer_id, "title": "T"}, headers=auth_headers(owner_id)).json()

    res = client.delete(f"/tasks/{task['id']}", headers=auth_headers(reader_id))
    assert res.status_code == 403


def test_delete_layer_cascades_to_sublayers_and_tasks(
    client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
):
    user_id = make_user()
    headers = auth_headers(user_id)
    org_id = make_org()
    grant_role("user", user_id, "organization", org_id, "owner")
    project_id = make_project(org_id)
    root = make_layer(project_id, name="root")
    child = make_layer(project_id, parent_layer_id=root, name="child")
    root_task = client.post("/tasks", json={"layer_id": root, "title": "In root"}, headers=headers).json()
    child_task = client.post("/tasks", json={"layer_id": child, "title": "In child"}, headers=headers).json()

    res = client.delete(f"/layers/{root}", headers=headers)
    assert res.status_code == 200

    assert client.get(f"/tasks/{root_task['id']}", headers=headers).status_code == 404
    assert client.get(f"/tasks/{child_task['id']}", headers=headers).status_code == 404
    assert client.get("/layers", params={"project_id": project_id}, headers=headers).json() == []


def test_delete_layer_requires_admin_not_just_editor(
    client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
):
    owner_id = make_user()
    editor_id = make_user()
    org_id = make_org()
    grant_role("user", owner_id, "organization", org_id, "owner")
    project_id = make_project(org_id)
    layer_id = make_layer(project_id)
    grant_role("user", editor_id, "layer", layer_id, "editor")

    res = client.delete(f"/layers/{layer_id}", headers=auth_headers(editor_id))
    assert res.status_code == 403


def test_delete_project_cascades_to_layers_and_tasks(
    client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
):
    user_id = make_user()
    headers = auth_headers(user_id)
    org_id = make_org()
    grant_role("user", user_id, "organization", org_id, "owner")
    project_id = make_project(org_id)
    layer_id = make_layer(project_id)
    task = client.post("/tasks", json={"layer_id": layer_id, "title": "T"}, headers=headers).json()

    res = client.delete(f"/projects/{project_id}", headers=headers)
    assert res.status_code == 200

    assert client.get(f"/projects/{project_id}", headers=headers).status_code == 404
    assert client.get(f"/tasks/{task['id']}", headers=headers).status_code == 404
    assert client.get("/layers", params={"project_id": project_id}, headers=headers).json() == []


def test_delete_project_requires_admin(client, auth_headers, make_user, make_org, make_project, grant_role):
    org_id = make_org()
    editor_id = make_user()
    grant_role("user", editor_id, "organization", org_id, "editor")
    project_id = make_project(org_id)

    res = client.delete(f"/projects/{project_id}", headers=auth_headers(editor_id))
    assert res.status_code == 403


def test_delete_organization_cascades_to_everything(
    client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
):
    user_id = make_user()
    headers = auth_headers(user_id)
    org_id = make_org()
    grant_role("user", user_id, "organization", org_id, "owner")
    project_id = make_project(org_id)
    layer_id = make_layer(project_id)
    task = client.post("/tasks", json={"layer_id": layer_id, "title": "T"}, headers=headers).json()

    res = client.delete(f"/organizations/{org_id}", headers=headers)
    assert res.status_code == 200

    assert client.get(f"/projects/{project_id}", headers=headers).status_code == 404
    assert client.get(f"/tasks/{task['id']}", headers=headers).status_code == 404
    orgs = client.get("/organizations", headers=headers).json()
    assert org_id not in [o["id"] for o in orgs]


def test_delete_organization_requires_admin(client, auth_headers, make_user, make_org, grant_role):
    org_id = make_org()
    reader_id = make_user()
    grant_role("user", reader_id, "organization", org_id, "reader")

    res = client.delete(f"/organizations/{org_id}", headers=auth_headers(reader_id))
    assert res.status_code == 403


@pytest.mark.parametrize("endpoint", ["/tasks/some-id", "/layers/some-id", "/projects/some-id", "/organizations/some-id"])
def test_delete_endpoints_require_authentication(client, endpoint):
    assert client.delete(endpoint).status_code == 422  # Header(...) obbligatorio mancante, vedi test_teams_auth.py


def test_deactivate_me_sets_deactivated_at(client, auth_headers, db_conn, make_user):
    user_id = make_user()

    res = client.post("/me/deactivate", headers=auth_headers(user_id))
    assert res.status_code == 200

    with db_conn.cursor() as cur:
        cur.execute("SELECT deactivated_at FROM users WHERE id = %s", (user_id,))
        (deactivated_at,) = cur.fetchone()
    assert deactivated_at is not None


def test_deactivated_user_excluded_from_search(client, auth_headers, make_user, make_org, grant_role):
    # search_users è ristretto a chi condivide un'organizzazione col cercante
    # (vedi test_security.py::TestIDOR::test_search_users_is_scoped_to_shared_organizations):
    # senza una condivisa qui, target_id non comparirebbe comunque, e il test
    # non isolerebbe più la sola variabile che gli interessa (la disattivazione).
    searcher_id = make_user()
    target_id = make_user(email="deactivate-search@example.com", display_name="Findable User")
    org_id = make_org()
    grant_role("user", searcher_id, "organization", org_id, "reader")
    grant_role("user", target_id, "organization", org_id, "reader")

    before = client.get("/users/search", params={"q": "Findable"}, headers=auth_headers(searcher_id)).json()
    assert any(u["id"] == target_id for u in before)

    client.post("/me/deactivate", headers=auth_headers(target_id))

    after = client.get("/users/search", params={"q": "Findable"}, headers=auth_headers(searcher_id)).json()
    assert all(u["id"] != target_id for u in after)
