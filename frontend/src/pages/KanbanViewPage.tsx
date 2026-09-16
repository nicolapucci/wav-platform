import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";
import KanbanBoard, { KanbanColumn, KanbanTask } from "../components/KanbanBoard";
import MultiSelect, { MultiSelectOption } from "../components/MultiSelect";
import { realtimeSocket } from "../ws/socket";

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

  const [selectedProjects, setSelectedProjects] = useState<MultiSelectOption[]>([]);
  const [selectedTeams, setSelectedTeams] = useState<MultiSelectOption[]>([]);
  const [selectedAssignees, setSelectedAssignees] = useState<MultiSelectOption[]>([]);
  const [currentUser, setCurrentUser] = useState<UserResult | null>(null);

  const filter: Filter = {
    project_ids: selectedProjects.map((o) => o.id),
    assignee_ids: selectedAssignees.map((o) => o.id),
    team_ids: selectedTeams.map((o) => o.id),
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

  async function searchUsers(query: string): Promise<MultiSelectOption[]> {
    const res = await apiFetch(`/api/users/search?q=${encodeURIComponent(query)}`);
    if (!res.ok) return [];
    const users: UserResult[] = await res.json();
    return users.map((u) => ({ id: u.id, label: `${u.display_name} (${u.email})` }));
  }

  // scorciatoia "Assegnate a me": l'assegnatario può essere anche un gruppo di
  // cui l'utente fa parte, il filtro lato server (projects.py::_task_filter_clauses)
  // include già quel caso, qui basta selezionare se stessi come assignee_ids.
  function toggleAssignedToMe() {
    if (!currentUser) return;
    const me: MultiSelectOption = { id: currentUser.id, label: currentUser.display_name };
    setSelectedAssignees((prev) =>
      prev.some((o) => o.id === currentUser.id) ? prev.filter((o) => o.id !== currentUser.id) : [...prev, me],
    );
  }
  const isAssignedToMeActive = !!currentUser && selectedAssignees.some((o) => o.id === currentUser.id);

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

  // pagina "lista" (task di più progetti, non ancorata a una task specifica):
  // sottoscrive il canale generico evt:tasks (architettura.md §6.1) e ricarica
  // la board quando arriva un evento. Rifatta ad ogni cambio filtro solo per
  // tenere la closure di loadBoard aggiornata sul filtro corrente - il canale
  // sottoscritto è sempre lo stesso, "tasks".
  useEffect(() => {
    realtimeSocket.connect();
    realtimeSocket.subscribe("tasks");

    const unsubscribe = realtimeSocket.onMessage((message) => {
      if (message.type === "task.created" || message.type === "task.updated" || message.type === "task.deleted") {
        loadBoard(filter);
      }
    });

    return () => {
      unsubscribe();
      realtimeSocket.unsubscribe("tasks");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filter)]);

  async function handleMoveTask(taskId: string, columnId: string) {
    const res = await apiFetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status_column_id: columnId }),
    });
    if (!res.ok) window.alert("Impossibile spostare la task: permessi insufficienti.");
    loadBoard(filter);
  }

  function clearFilters() {
    setSelectedProjects([]);
    setSelectedTeams([]);
    setSelectedAssignees([]);
  }

  const hasActiveFilter = selectedProjects.length > 0 || selectedTeams.length > 0 || selectedAssignees.length > 0;

  return (
    <>
      <div className="page-header">
        <h1>
          Kanban
          <InfoTooltip text="Tutte le task su cui hai almeno il permesso di lettura, filtrabili e raggruppate per progetto." />
        </h1>
      </div>

      <div className="toolbar">
        <button type="button" className={isAssignedToMeActive ? "active" : ""} onClick={toggleAssignedToMe}>
          Assegnate a me
        </button>
        {hasActiveFilter && (
          <button type="button" className="link-button" onClick={clearFilters}>
            Azzera filtri
          </button>
        )}
      </div>

      <div className="board-form">
        <MultiSelect
          label="Progetto"
          placeholder="Tutti i progetti"
          selected={selectedProjects}
          onChange={setSelectedProjects}
          options={allProjects.map((p) => ({ id: p.id, label: p.name }))}
        />

        <MultiSelect
          label="Gruppo"
          placeholder="Tutti i gruppi"
          selected={selectedTeams}
          onChange={setSelectedTeams}
          options={teams.map((t) => ({ id: t.id, label: t.name }))}
        />

        <MultiSelect
          label="Assegnatari specifici"
          placeholder="Cerca utente per email o nome..."
          selected={selectedAssignees}
          onChange={setSelectedAssignees}
          onSearch={searchUsers}
        />
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
