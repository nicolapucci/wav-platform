import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../api/client";
import KanbanBoard, { KanbanColumn, KanbanTask } from "../components/KanbanBoard";

type Organization = { id: string; name: string; slug: string };
type Project = { id: string; name: string; description: string | null };
type Team = { id: string; name: string };
type UserResult = { id: string; email: string; display_name: string };

type ProjectBoard = { id: string; name: string; columns: KanbanColumn[]; tasks: KanbanTask[] };

type Filter = { project_ids: string[]; assignee_ids: string[]; team_ids: string[] };

const EMPTY_FILTER: Filter = { project_ids: [], assignee_ids: [], team_ids: [] };

function filterToQuery(filter: Filter) {
  const params = new URLSearchParams();
  if (filter.project_ids.length) params.set("project_ids", filter.project_ids.join(","));
  if (filter.assignee_ids.length) params.set("assignee_ids", filter.assignee_ids.join(","));
  if (filter.team_ids.length) params.set("team_ids", filter.team_ids.join(","));
  return params.toString();
}

export default function KanbanViewPage() {
  const [allProjects, setAllProjects] = useState<Project[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);
  const [projectBoards, setProjectBoards] = useState<ProjectBoard[]>([]);

  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [selectedTeamIds, setSelectedTeamIds] = useState<string[]>([]);
  const [assigneeQuery, setAssigneeQuery] = useState("");
  const [assigneeResults, setAssigneeResults] = useState<UserResult[]>([]);
  const [selectedAssignees, setSelectedAssignees] = useState<UserResult[]>([]);
  const [currentUser, setCurrentUser] = useState<UserResult | null>(null);

  const filter: Filter = {
    project_ids: selectedProjectIds,
    assignee_ids: selectedAssignees.map((u) => u.id),
    team_ids: selectedTeamIds,
  };

  // filtri disponibili: progetti e gruppi vengono raccolti attraverso tutte le
  // organizzazioni visibili all'utente, così il filtro copre davvero "tutte le
  // task visibili", non solo quelle di un'organizzazione.
  useEffect(() => {
    async function loadFilterOptions() {
      const orgsRes = await apiFetch("/api/organizations");
      const orgs: Organization[] = orgsRes.ok ? await orgsRes.json() : [];

      const projectLists = await Promise.all(
        orgs.map(async (org) => {
          const res = await apiFetch(`/api/projects?organization_id=${org.id}`);
          return res.ok ? ((await res.json()) as Project[]) : [];
        }),
      );
      setAllProjects(projectLists.flat());

      const teamLists = await Promise.all(
        orgs.map(async (org) => {
          const res = await apiFetch(`/api/teams?organization_id=${org.id}`);
          return res.ok ? ((await res.json()) as Team[]) : [];
        }),
      );
      const dedupedTeams = new Map<string, Team>();
      teamLists.flat().forEach((t) => dedupedTeams.set(t.id, t));
      setTeams([...dedupedTeams.values()]);
    }
    loadFilterOptions();
    apiFetch("/api/me").then(async (res) => {
      if (res.ok) setCurrentUser(await res.json());
    });
  }, []);

  // scorciatoia "Assegnate a me": l'assegnatario può essere anche un gruppo di
  // cui l'utente fa parte, il filtro lato server (projects.py::_task_filter_clauses)
  // include già quel caso, qui basta selezionare se stessi come assignee_ids.
  function toggleAssignedToMe() {
    if (!currentUser) return;
    setSelectedAssignees((prev) =>
      prev.some((u) => u.id === currentUser.id) ? prev.filter((u) => u.id !== currentUser.id) : [...prev, currentUser],
    );
  }
  const isAssignedToMeActive = !!currentUser && selectedAssignees.some((u) => u.id === currentUser.id);

  async function loadBoard(currentFilter: Filter) {
    setLoading(true);
    const qs = filterToQuery(currentFilter);
    const res = await apiFetch(`/api/me/tasks/board${qs ? `?${qs}` : ""}`);
    if (res.ok) {
      const data = await res.json();
      setProjectBoards(data.projects);
    }
    setLoading(false);
  }

  useEffect(() => {
    loadBoard(filter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filter)]);

  useEffect(() => {
    if (assigneeQuery.length < 2) {
      setAssigneeResults([]);
      return;
    }
    const timeout = setTimeout(async () => {
      const res = await apiFetch(`/api/users/search?q=${encodeURIComponent(assigneeQuery)}`);
      if (res.ok) setAssigneeResults(await res.json());
    }, 250);
    return () => clearTimeout(timeout);
  }, [assigneeQuery]);

  async function handleMoveTask(taskId: string, columnId: string) {
    const res = await apiFetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status_column_id: columnId }),
    });
    if (!res.ok) window.alert("Impossibile spostare la task: permessi insufficienti.");
    loadBoard(filter);
  }

  function clearFilters() {
    setSelectedProjectIds([]);
    setSelectedTeamIds([]);
    setSelectedAssignees([]);
  }

  const hasActiveFilter = selectedProjectIds.length > 0 || selectedTeamIds.length > 0 || selectedAssignees.length > 0;

  return (
    <>
      <div className="page-header">
        <h1>Kanban</h1>
        <p>Tutte le task su cui hai almeno il permesso di lettura, filtrabili e raggruppate per progetto.</p>
      </div>

      <div className="toolbar">
        <button type="button" className={isAssignedToMeActive ? "active" : ""} onClick={toggleAssignedToMe}>
          Assegnate a me
        </button>
      </div>

      <div className="board-form">
        <div className="field">
          <label>Progetto (opzionale)</label>
          <select
            multiple
            value={selectedProjectIds}
            onChange={(e) => setSelectedProjectIds(Array.from(e.target.selectedOptions, (o) => o.value))}
          >
            {allProjects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>Gruppo (opzionale)</label>
          <select
            multiple
            value={selectedTeamIds}
            onChange={(e) => setSelectedTeamIds(Array.from(e.target.selectedOptions, (o) => o.value))}
          >
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>Assegnatari specifici (opzionale)</label>
          {selectedAssignees.length > 0 && (
            <div className="chip-list">
              {selectedAssignees.map((u) => (
                <span key={u.id} className="chip">
                  {u.display_name}
                  <button
                    type="button"
                    onClick={() => setSelectedAssignees((prev) => prev.filter((x) => x.id !== u.id))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <input
            placeholder="Cerca utente per email o nome..."
            value={assigneeQuery}
            onChange={(e) => setAssigneeQuery(e.target.value)}
          />
          {assigneeResults.length > 0 && (
            <ul className="permissions-suggestions">
              {assigneeResults.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedAssignees((prev) => (prev.some((x) => x.id === u.id) ? prev : [...prev, u]));
                      setAssigneeQuery("");
                      setAssigneeResults([]);
                    }}
                  >
                    {u.display_name} ({u.email})
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {hasActiveFilter && (
          <button type="button" className="link-button" onClick={clearFilters}>
            Azzera filtri
          </button>
        )}
      </div>

      {loading && <p>Caricamento...</p>}

      {!loading && projectBoards.length === 0 && <p>Nessuna task trovata per questo filtro.</p>}

      {!loading &&
        projectBoards.map((board) => (
          <div key={board.id} style={{ marginTop: 24 }}>
            <h2 className="task-chat-title">
              <Link to={`/projects/${board.id}`}>{board.name}</Link>
            </h2>
            <KanbanBoard columns={board.columns} tasks={board.tasks} onMoveTask={handleMoveTask} />
          </div>
        ))}
    </>
  );
}
