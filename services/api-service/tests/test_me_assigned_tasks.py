"""GET /me/tasks/assigned: task assegnate all'utente (direttamente o via
team), escluse quelle nell'ultima colonna kanban del progetto (proxy per
"completata", vedi il docstring dell'endpoint in me.py)."""


def _setup_project(client, auth_headers, make_org, make_project, make_layer, grant_role, owner_id):
    org_id = make_org()
    grant_role("user", owner_id, "organization", org_id, "owner")
    project_id = make_project(org_id)
    layer_id = make_layer(project_id)
    return org_id, project_id, layer_id


def _create_task(client, headers, layer_id, title):
    return client.post("/tasks", json={"layer_id": layer_id, "title": title}, headers=headers).json()


def _columns(client, headers, project_id):
    cols = client.get(f"/projects/{project_id}/columns", headers=headers).json()
    return sorted(cols, key=lambda c: c["position"])


def test_task_assigned_to_me_in_non_last_column_is_included(
    client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
):
    user_id = make_user()
    headers = auth_headers(user_id)
    _, project_id, layer_id = _setup_project(client, auth_headers, make_org, make_project, make_layer, grant_role, user_id)

    task = _create_task(client, headers, layer_id, "Task da fare")
    client.post(f"/tasks/{task['id']}/assignees", json={"principal_type": "user", "principal_id": user_id}, headers=headers)

    res = client.get("/me/tasks/assigned", headers=headers)
    assert res.status_code == 200
    assert [t["title"] for t in res.json()] == ["Task da fare"]


def test_task_in_last_column_is_excluded(
    client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
):
    user_id = make_user()
    headers = auth_headers(user_id)
    _, project_id, layer_id = _setup_project(client, auth_headers, make_org, make_project, make_layer, grant_role, user_id)

    task = _create_task(client, headers, layer_id, "Task fatta")
    client.post(f"/tasks/{task['id']}/assignees", json={"principal_type": "user", "principal_id": user_id}, headers=headers)

    last_column = _columns(client, headers, project_id)[-1]
    client.patch(f"/tasks/{task['id']}", json={"status_column_id": last_column["id"]}, headers=headers)

    res = client.get("/me/tasks/assigned", headers=headers)
    assert res.json() == []


def test_task_assigned_to_my_team_is_included(
    client, auth_headers, make_user, make_org, make_project, make_layer, make_team, add_team_member, grant_role
):
    user_id = make_user()
    headers = auth_headers(user_id)
    org_id, project_id, layer_id = _setup_project(
        client, auth_headers, make_org, make_project, make_layer, grant_role, user_id
    )
    team_id = make_team(org_id)
    add_team_member(team_id, user_id)

    task = _create_task(client, headers, layer_id, "Task del gruppo")
    client.post(f"/tasks/{task['id']}/assignees", json={"principal_type": "team", "principal_id": team_id}, headers=headers)

    res = client.get("/me/tasks/assigned", headers=headers)
    assert [t["title"] for t in res.json()] == ["Task del gruppo"]


def test_task_not_assigned_to_me_is_excluded(
    client, auth_headers, make_user, make_org, make_project, make_layer, grant_role
):
    user_id = make_user()
    other_user_id = make_user()
    headers = auth_headers(user_id)
    other_headers = auth_headers(other_user_id)
    org_id, project_id, layer_id = _setup_project(
        client, auth_headers, make_org, make_project, make_layer, grant_role, user_id
    )
    grant_role("user", other_user_id, "organization", org_id, "editor")

    task = _create_task(client, headers, layer_id, "Task di qualcun altro")
    client.post(
        f"/tasks/{task['id']}/assignees", json={"principal_type": "user", "principal_id": other_user_id}, headers=headers
    )

    res = client.get("/me/tasks/assigned", headers=headers)
    assert res.json() == []
    res_other = client.get("/me/tasks/assigned", headers=other_headers)
    assert [t["title"] for t in res_other.json()] == ["Task di qualcun altro"]


def test_task_with_no_column_is_included(
    client, auth_headers, make_user, make_org, make_project, make_layer, grant_role, db_conn
):
    """Una task senza status_column_id (mai spostata, o colonna eliminata) non
    è nell'ultima colonna per definizione: deve comunque comparire."""
    user_id = make_user()
    headers = auth_headers(user_id)
    _, project_id, layer_id = _setup_project(client, auth_headers, make_org, make_project, make_layer, grant_role, user_id)

    task = _create_task(client, headers, layer_id, "Task senza colonna")
    client.post(f"/tasks/{task['id']}/assignees", json={"principal_type": "user", "principal_id": user_id}, headers=headers)
    with db_conn.cursor() as cur:
        cur.execute("UPDATE tasks SET status_column_id = NULL WHERE id = %s", (task["id"],))

    res = client.get("/me/tasks/assigned", headers=headers)
    assert [t["title"] for t in res.json()] == ["Task senza colonna"]
