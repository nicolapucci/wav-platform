"""wav_core.permissions: cache Redis di candidate_role_at_resource e la sua
invalidazione. I test in test_permissions.py verificano la correttezza del
risultato (con fixture consapevoli della cache, vedi conftest.py) ma non
provano che la cache sia davvero usata, né che l'invalidazione lato endpoint
reale funzioni - è lo scopo di questo file."""

from wav_core.permissions import Role, candidate_role_at_resource
from wav_core.redis_client import get_redis_sync


def test_candidate_role_populates_and_reads_from_cache(db_conn, make_user, make_org, grant_role):
    user_id = make_user()
    org_id = make_org()
    grant_role("user", user_id, "organization", org_id, "editor")

    candidate_role_at_resource(db_conn, user_id, "organization", org_id)
    cached = get_redis_sync().get(f"perm:{user_id}:organization:{org_id}")
    assert cached == "editor"

    # cambia il DB SENZA passare da grant_role (che invaliderebbe): se la
    # seconda chiamata legge ancora dalla cache invece di ririnterrogare il DB,
    # deve restituire il valore vecchio, non quello appena scritto.
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE role_assignments SET role = 'owner' WHERE principal_id = %s AND resource_id = %s",
            (user_id, org_id),
        )
    assert candidate_role_at_resource(db_conn, user_id, "organization", org_id) == Role.editor


def test_candidate_role_caches_none_result_too(db_conn, make_user, make_org):
    user_id = make_user()
    org_id = make_org()

    assert candidate_role_at_resource(db_conn, user_id, "organization", org_id) is None
    cached = get_redis_sync().get(f"perm:{user_id}:organization:{org_id}")
    assert cached is not None  # una entry esiste (il sentinel di "None"), non un semplice cache miss


def test_grant_then_revoke_via_real_endpoints_is_reflected_immediately(
    db_conn, client, auth_headers, make_user, make_org, grant_role
):
    """Percorso end-to-end attraverso POST/DELETE /permissions veri (non i
    fixture diretti sul DB): la revoca deve invalidare la cache, altrimenti un
    utente a cui è stato appena tolto l'accesso lo vedrebbe ancora per la
    durata del TTL."""
    admin_id = make_user()
    target_id = make_user()
    org_id = make_org()
    grant_role("user", admin_id, "organization", org_id, "owner")

    grant_res = client.post(
        "/permissions",
        json={
            "resource_type": "organization",
            "resource_id": org_id,
            "principal_type": "user",
            "principal_id": target_id,
            "role": "editor",
        },
        headers=auth_headers(admin_id),
    )
    assert grant_res.status_code == 200
    assignment_id = grant_res.json()["id"]

    assert candidate_role_at_resource(db_conn, target_id, "organization", org_id) == Role.editor

    revoke_res = client.delete(f"/permissions/{assignment_id}", headers=auth_headers(admin_id))
    assert revoke_res.status_code == 200

    assert candidate_role_at_resource(db_conn, target_id, "organization", org_id) is None
