"""wav_core.permissions: risoluzione del ruolo effettivo (MAX tra ruolo
personale e ruolo ereditato via team, poi "vince il primo livello non nullo
risalendo da layer verso project verso organization" - vedi il docstring del
modulo)."""

from wav_core.permissions import (
    Role,
    candidate_role_at_resource,
    resolve_effective_role_on_layer,
    resolve_effective_role_on_project,
    resolve_layer_ancestor_ids,
)


def test_candidate_role_none_without_assignment(db_conn, make_user, make_org):
    user_id = make_user()
    org_id = make_org()
    assert candidate_role_at_resource(db_conn, user_id, "organization", org_id) is None


def test_candidate_role_direct_user_assignment(db_conn, make_user, make_org, grant_role):
    user_id = make_user()
    org_id = make_org()
    grant_role("user", user_id, "organization", org_id, "editor")
    assert candidate_role_at_resource(db_conn, user_id, "organization", org_id) == Role.editor


def test_candidate_role_via_team_membership(db_conn, make_user, make_org, make_team, add_team_member, grant_role):
    user_id = make_user()
    org_id = make_org()
    team_id = make_team(org_id)
    add_team_member(team_id, user_id)
    grant_role("team", team_id, "organization", org_id, "admin")
    assert candidate_role_at_resource(db_conn, user_id, "organization", org_id) == Role.admin


def test_candidate_role_is_max_of_personal_and_team(
    db_conn, make_user, make_org, make_team, add_team_member, grant_role
):
    """Requisito esplicito: il ruolo effettivo è il MASSIMO tra quello personale
    e quello ereditato via gruppo, non uno dei due a scelta fissa."""
    user_id = make_user()
    org_id = make_org()
    team_id = make_team(org_id)
    add_team_member(team_id, user_id)

    grant_role("user", user_id, "organization", org_id, "reader")
    grant_role("team", team_id, "organization", org_id, "admin")
    assert candidate_role_at_resource(db_conn, user_id, "organization", org_id) == Role.admin

    # invertito: personale più alto del team, deve comunque vincere il personale
    user_id_2 = make_user()
    add_team_member(team_id, user_id_2)
    grant_role("user", user_id_2, "organization", org_id, "owner")
    assert candidate_role_at_resource(db_conn, user_id_2, "organization", org_id) == Role.owner


def test_candidate_role_ignores_other_users_and_teams(db_conn, make_user, make_org, make_team, grant_role):
    user_id = make_user()
    other_user_id = make_user()
    org_id = make_org()
    other_team_id = make_team(org_id)
    grant_role("user", other_user_id, "organization", org_id, "owner")
    grant_role("team", other_team_id, "organization", org_id, "owner")
    assert candidate_role_at_resource(db_conn, user_id, "organization", org_id) is None


def test_resolve_layer_ancestor_ids_orders_most_specific_first(db_conn, make_org, make_project, make_layer):
    org_id = make_org()
    project_id = make_project(org_id)
    root_id = make_layer(project_id, name="root")
    child_id = make_layer(project_id, parent_layer_id=root_id, name="child")
    grandchild_id = make_layer(project_id, parent_layer_id=child_id, name="grandchild")

    ancestors = resolve_layer_ancestor_ids(db_conn, grandchild_id)
    assert [str(a) for a in ancestors] == [grandchild_id, child_id, root_id]


def test_resolve_effective_role_on_layer_inherits_from_parent(
    db_conn, make_user, make_org, make_project, make_layer, grant_role
):
    user_id = make_user()
    org_id = make_org()
    project_id = make_project(org_id)
    root_id = make_layer(project_id, name="root")
    child_id = make_layer(project_id, parent_layer_id=root_id, name="child")

    grant_role("user", user_id, "layer", root_id, "editor")
    assert resolve_effective_role_on_layer(db_conn, user_id, child_id) == Role.editor


def test_resolve_effective_role_on_layer_most_specific_wins_even_if_lower(
    db_conn, make_user, make_org, make_project, make_layer, grant_role
):
    """Comportamento non ovvio: NON è il massimo su tutta la catena. Un ruolo
    "reader" sul layer specifico vince su un "admin" ereditato dal progetto,
    perché si risale dal più specifico e ci si ferma al primo non nullo."""
    user_id = make_user()
    org_id = make_org()
    project_id = make_project(org_id)
    layer_id = make_layer(project_id, name="leaf")

    grant_role("user", user_id, "project", project_id, "admin")
    grant_role("user", user_id, "layer", layer_id, "reader")

    assert resolve_effective_role_on_layer(db_conn, user_id, layer_id) == Role.reader


def test_resolve_effective_role_on_layer_falls_back_to_project_then_org(
    db_conn, make_user, make_org, make_project, make_layer, grant_role
):
    user_id = make_user()
    org_id = make_org()
    project_id = make_project(org_id)
    layer_id = make_layer(project_id, name="leaf")

    # nessun ruolo su layer/project: eredita dall'organization
    grant_role("user", user_id, "organization", org_id, "reader")
    assert resolve_effective_role_on_layer(db_conn, user_id, layer_id) == Role.reader

    # un ruolo sul project prende precedenza sull'organization
    grant_role("user", user_id, "project", project_id, "editor")
    assert resolve_effective_role_on_layer(db_conn, user_id, layer_id) == Role.editor


def test_resolve_effective_role_on_layer_none_when_no_access(db_conn, make_user, make_org, make_project, make_layer):
    user_id = make_user()
    org_id = make_org()
    project_id = make_project(org_id)
    layer_id = make_layer(project_id)
    assert resolve_effective_role_on_layer(db_conn, user_id, layer_id) is None


def test_resolve_effective_role_on_project_direct_beats_org_fallback(
    db_conn, make_user, make_org, make_project, grant_role
):
    user_id = make_user()
    org_id = make_org()
    project_id = make_project(org_id)

    grant_role("user", user_id, "organization", org_id, "admin")
    grant_role("user", user_id, "project", project_id, "reader")

    assert resolve_effective_role_on_project(db_conn, user_id, project_id) == Role.reader
