def visible_layers_cte(scoped_to_project: bool = False) -> str:
    """CTE 'visible_layers': i layer visibili a %(user_id)s (diretto o via
    team), sui layer/project/organization che li contengono - esclude layer,
    progetti e organizzazioni cancellati logicamente (archived_at), così un
    task sotto una risorsa archiviata smette di comparire ovunque, senza dover
    ripetere il controllo in ogni query che la consuma.

    Con scoped_to_project=True aggiunge un filtro su %(project_id)s: usata da
    projects.py per le query ristrette a un solo progetto (dashboard, kanban
    di progetto), dove serve comunque sapere se project_id stesso esiste ed è
    visibile prima di elencarne le task.

    Prima duplicata quasi identica in me.py (my_tasks, my_tasks_board,
    my_tasks_assigned), tasks.py::search_tasks e projects.py - un solo posto
    ora, così un domani "chi vede cosa" non deve essere corretto in 5 file."""
    project_filter = "AND p.id = %(project_id)s\n              " if scoped_to_project else ""
    return f"""
        WITH visible_layers AS (
            SELECT DISTINCT l.id AS layer_id
            FROM layers l
            JOIN projects p ON p.id = l.project_id
            JOIN organizations o ON o.id = p.organization_id
            LEFT JOIN role_assignments ra_layer
                ON ra_layer.resource_type = 'layer' AND ra_layer.resource_id = l.id
            LEFT JOIN role_assignments ra_project
                ON ra_project.resource_type = 'project' AND ra_project.resource_id = p.id
            LEFT JOIN role_assignments ra_org
                ON ra_org.resource_type = 'organization' AND ra_org.resource_id = p.organization_id
            LEFT JOIN team_members tm ON tm.user_id = %(user_id)s
            WHERE l.archived_at IS NULL AND p.archived_at IS NULL AND o.archived_at IS NULL
              {project_filter}AND (
                (ra_layer.principal_type = 'user' AND ra_layer.principal_id = %(user_id)s)
                OR (ra_layer.principal_type = 'team' AND ra_layer.principal_id = tm.team_id)
                OR (ra_project.principal_type = 'user' AND ra_project.principal_id = %(user_id)s)
                OR (ra_project.principal_type = 'team' AND ra_project.principal_id = tm.team_id)
                OR (ra_org.principal_type = 'user' AND ra_org.principal_id = %(user_id)s)
                OR (ra_org.principal_type = 'team' AND ra_org.principal_id = tm.team_id)
              )
        )
    """
