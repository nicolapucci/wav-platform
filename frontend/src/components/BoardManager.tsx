import { useEffect, useState } from "react";

import { apiFetch } from "../api/client";
import { realtimeSocket } from "../ws/socket";
import KanbanBoard, { KanbanColumn } from "./KanbanBoard";
import StatusPieChart from "./StatusPieChart";

type Layer = { id: string; name: string };
type Team = { id: string; name: string };
type Tag = { id: string; name: string; color: string | null };
type UserResult = { id: string; email: string; display_name: string };
type TaskFilter = { layer_ids: string[]; assignee_ids: string[]; team_ids: string[]; tag_ids: string[] };
type Board = { id: string; project_id: string; created_by: string; name: string; task_filter: TaskFilter };
type FilteredTask = {
  id: string;
  readable_id: string;
  title: string;
  column_id: string | null;
  priority: number;
  layer_id: string;
};
type ColumnStat = { column_id: string; name: string; position: number; count: number };
type Stats = { columns: ColumnStat[]; total: number };

const EMPTY_FILTER: TaskFilter = { layer_ids: [], assignee_ids: [], team_ids: [], tag_ids: [] };
const EMPTY_STATS: Stats = { columns: [], total: 0 };
const DEFAULT_LABEL = "Dashboard progetto (tutte le task)";

function filterToQuery(filter: TaskFilter) {
  const params = new URLSearchParams();
  if (filter.layer_ids?.length) params.set("layer_ids", filter.layer_ids.join(","));
  if (filter.assignee_ids?.length) params.set("assignee_ids", filter.assignee_ids.join(","));
  if (filter.team_ids?.length) params.set("team_ids", filter.team_ids.join(","));
  if (filter.tag_ids?.length) params.set("tag_ids", filter.tag_ids.join(","));
  return params.toString();
}

export default function BoardManager({
  projectId,
  organizationId,
  layers,
  columns,
}: {
  projectId: string;
  organizationId: string;
  layers: Layer[];
  columns: KanbanColumn[];
}) {
  const [boards, setBoards] = useState<Board[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [projectTags, setProjectTags] = useState<Tag[]>([]);

  const [currentFilter, setCurrentFilter] = useState<TaskFilter>(EMPTY_FILTER);
  const [currentLabel, setCurrentLabel] = useState(DEFAULT_LABEL);
  const [view, setView] = useState<"kanban" | "chart">("chart");
  const [tasks, setTasks] = useState<FilteredTask[]>([]);
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [selectedLayerIds, setSelectedLayerIds] = useState<string[]>([]);
  const [selectedTeamIds, setSelectedTeamIds] = useState<string[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);
  const [assigneeQuery, setAssigneeQuery] = useState("");
  const [assigneeResults, setAssigneeResults] = useState<UserResult[]>([]);
  const [selectedAssignees, setSelectedAssignees] = useState<UserResult[]>([]);

  async function loadBoards() {
    const res = await apiFetch(`/api/boards?project_id=${projectId}`);
    if (res.ok) setBoards(await res.json());
  }

  useEffect(() => {
    loadBoards();
    apiFetch(`/api/teams?organization_id=${organizationId}`).then(async (res) => {
      if (res.ok) setTeams(await res.json());
    });
    apiFetch(`/api/tags?project_id=${projectId}`).then(async (res) => {
      if (res.ok) setProjectTags(await res.json());
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, organizationId]);

  async function loadFilteredData(filter: TaskFilter) {
    const qs = filterToQuery(filter);
    const [tasksRes, statsRes] = await Promise.all([
      apiFetch(`/api/projects/${projectId}/tasks${qs ? `?${qs}` : ""}`),
      apiFetch(`/api/projects/${projectId}/task-stats${qs ? `?${qs}` : ""}`),
    ]);
    if (tasksRes.ok) setTasks(await tasksRes.json());
    if (statsRes.ok) setStats(await statsRes.json());
  }

  useEffect(() => {
    loadFilteredData(currentFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(currentFilter)]);

  // la dashboard è un'altra "lista" di task (filtrata), montata solo finché la
  // tab Dashboard è attiva: sottoscrive il canale generico evt:tasks
  // (architettura.md §6.1) mentre è visualizzata, si disiscrive smontandosi
  // (cambio tab o uscita dalla pagina progetto).
  useEffect(() => {
    realtimeSocket.connect();
    realtimeSocket.subscribe("tasks");

    const unsubscribe = realtimeSocket.onMessage((message) => {
      if (message.type === "task.created" || message.type === "task.updated" || message.type === "task.deleted") {
        loadFilteredData(currentFilter);
      }
    });

    return () => {
      unsubscribe();
      realtimeSocket.unsubscribe("tasks");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(currentFilter)]);

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

  function handleSelectDefault() {
    setCurrentFilter(EMPTY_FILTER);
    setCurrentLabel(DEFAULT_LABEL);
  }

  function handleSelectBoard(board: Board) {
    setCurrentFilter({ ...EMPTY_FILTER, ...board.task_filter });
    setCurrentLabel(board.name);
  }

  async function handleMoveTask(taskId: string, columnId: string) {
    const res = await apiFetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status_column_id: columnId }),
    });
    if (!res.ok) window.alert("Impossibile spostare la task: permessi insufficienti.");
    loadFilteredData(currentFilter);
  }

  async function handleCreateBoard() {
    if (!name.trim()) return;
    const task_filter: TaskFilter = {
      layer_ids: selectedLayerIds,
      assignee_ids: selectedAssignees.map((u) => u.id),
      team_ids: selectedTeamIds,
      tag_ids: selectedTagIds,
    };
    const res = await apiFetch("/api/boards", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, name, task_filter }),
    });
    if (res.ok) {
      setName("");
      setSelectedLayerIds([]);
      setSelectedTeamIds([]);
      setSelectedTagIds([]);
      setSelectedAssignees([]);
      setShowForm(false);
      loadBoards();
    } else {
      window.alert("Impossibile creare la board.");
    }
  }

  async function handleDeleteBoard(board: Board) {
    const res = await apiFetch(`/api/boards/${board.id}`, { method: "DELETE" });
    if (!res.ok) {
      window.alert("Solo chi ha creato la board (o un admin del progetto) può eliminarla.");
      return;
    }
    if (currentLabel === board.name) handleSelectDefault();
    loadBoards();
  }

  return (
    <div>
      <div className="toolbar">
        <button type="button" onClick={() => setShowForm((v) => !v)}>
          + Board personalizzata
        </button>
      </div>

      {showForm && (
        <div className="board-form">
          <div className="field">
            <label>Nome</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="es. Task del team QA" />
          </div>

          <div className="field">
            <label>Layer (opzionale, include i sotto-layer)</label>
            <select
              multiple
              value={selectedLayerIds}
              onChange={(e) => setSelectedLayerIds(Array.from(e.target.selectedOptions, (o) => o.value))}
            >
              {layers.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
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
            <label>Tag (opzionale)</label>
            <select
              multiple
              value={selectedTagIds}
              onChange={(e) => setSelectedTagIds(Array.from(e.target.selectedOptions, (o) => o.value))}
            >
              {projectTags.map((t) => (
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

          <button type="button" className="btn-primary" onClick={handleCreateBoard}>
            Crea board
          </button>
        </div>
      )}

      <ul className="board-list">
        <li className={`board-list-item${currentLabel === DEFAULT_LABEL ? " active" : ""}`}>
          <button type="button" onClick={handleSelectDefault}>
            Dashboard progetto
          </button>
        </li>
        {boards.map((b) => (
          <li key={b.id} className={`board-list-item${currentLabel === b.name ? " active" : ""}`}>
            <button type="button" onClick={() => handleSelectBoard(b)}>
              {b.name}
            </button>
            <button type="button" className="link-button" onClick={() => handleDeleteBoard(b)}>
              Elimina
            </button>
          </li>
        ))}
      </ul>

      <div className="dashboard-header">
        <h2 className="task-chat-title">{currentLabel}</h2>
        <div className="view-toggle">
          <button type="button" className={view === "chart" ? "active" : ""} onClick={() => setView("chart")}>
            Torta
          </button>
          <button type="button" className={view === "kanban" ? "active" : ""} onClick={() => setView("kanban")}>
            Kanban
          </button>
        </div>
      </div>

      {view === "chart" ? (
        <StatusPieChart stats={stats} />
      ) : (
        <KanbanBoard columns={columns} tasks={tasks} onMoveTask={handleMoveTask} />
      )}
    </div>
  );
}
