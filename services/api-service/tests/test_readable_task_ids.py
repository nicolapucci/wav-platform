"""Id leggibili delle task (<PREFISSO>-<numero>): regex, risoluzione a UUID e
numerazione atomica per progetto (app/routers/tasks.py)."""

import pytest

from app.routers.tasks import READABLE_ID_RE, _resolve_task_id


@pytest.mark.parametrize(
    "value,expected",
    [
        ("QA-1", ("QA", "1")),
        ("PROJ-123", ("PROJ", "123")),
        ("A-0", ("A", "0")),
    ],
)
def test_readable_id_regex_matches(value, expected):
    match = READABLE_ID_RE.match(value)
    assert match is not None
    assert match.groups() == expected


@pytest.mark.parametrize(
    "value",
    ["qa-1", "QA1", "QA-", "-1", "QA-1x", "QA_1", ""],
)
def test_readable_id_regex_rejects(value):
    assert READABLE_ID_RE.match(value) is None


def test_resolve_task_id_passes_through_uuid_like_strings(db_conn):
    not_readable = "9c5c3b78-87a1-4558-8c4e-3881cec39e08"
    assert _resolve_task_id(db_conn, not_readable) == not_readable


def test_resolve_task_id_raises_404_for_unknown_readable_id(db_conn):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _resolve_task_id(db_conn, "ZZZZ-999")
    assert exc_info.value.status_code == 404


def test_create_task_assigns_sequential_readable_ids(client, auth_headers, make_user, make_org, grant_role):
    user_id = make_user()
    org_id = make_org()
    grant_role("user", user_id, "organization", org_id, "owner")
    headers = auth_headers(user_id)

    project = client.post(
        "/projects",
        json={"organization_id": org_id, "name": "Progetto", "prefix": "QATT"},
        headers=headers,
    ).json()
    layer = client.post(
        "/layers", json={"project_id": project["id"], "name": "Layer"}, headers=headers
    ).json()

    first = client.post("/tasks", json={"layer_id": layer["id"], "title": "Prima"}, headers=headers).json()
    second = client.post("/tasks", json={"layer_id": layer["id"], "title": "Seconda"}, headers=headers).json()

    assert first["readable_id"] == "QATT-1"
    assert second["readable_id"] == "QATT-2"


def test_get_task_by_readable_id_matches_get_by_uuid(client, auth_headers, make_user, make_org, grant_role):
    user_id = make_user()
    org_id = make_org()
    grant_role("user", user_id, "organization", org_id, "owner")
    headers = auth_headers(user_id)

    project = client.post(
        "/projects", json={"organization_id": org_id, "name": "Progetto", "prefix": "ABCD"}, headers=headers
    ).json()
    layer = client.post(
        "/layers", json={"project_id": project["id"], "name": "Layer"}, headers=headers
    ).json()
    created = client.post("/tasks", json={"layer_id": layer["id"], "title": "Task"}, headers=headers).json()

    by_uuid = client.get(f"/tasks/{created['id']}", headers=headers).json()
    by_readable_id = client.get(f"/tasks/{created['readable_id']}", headers=headers).json()

    assert by_uuid["id"] == by_readable_id["id"] == created["id"]


def test_get_task_by_unknown_readable_id_returns_404(client, auth_headers, make_user):
    user_id = make_user()
    response = client.get("/tasks/ZZZZ-999", headers=auth_headers(user_id))
    assert response.status_code == 404
