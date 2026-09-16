import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";
import { realtimeSocket } from "../ws/socket";

type Tag = { id: string; name: string; color: string | null };
type AssigneeRef = { type: "user" | "team"; name: string };

type Task = {
  id: string;
  readable_id: string;
  title: string;
  layer_id: string;
  updated_at: string;
  project_id: string;
  project_name: string;
  status_column_id: string | null;
  column_name: string | null;
  priority: number;
  due_date: string | null;
  assignees: AssigneeRef[];
  tags: Tag[];
};

const PRIORITY_LABELS = ["Bassa", "Media", "Alta", "Urgente"];

export default function MyTasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  async function loadTasks(currentSearch: string) {
    setLoading(true);
    const params = new URLSearchParams();
    if (currentSearch) params.set("search", currentSearch);

    const res = await apiFetch(`/api/me/tasks?${params.toString()}`);
    if (res.ok) {
      setTasks(await res.json());
    }
    setLoading(false);
  }

  // caricamento iniziale + ogni volta che cambia la ricerca (con un piccolo debounce)
  useEffect(() => {
    const timeout = setTimeout(() => loadTasks(search), 300);
    return () => clearTimeout(timeout);
  }, [search]);

  // sottoscrizione realtime: pagina "lista" (non ancorata a una singola task),
  // quindi si sottoscrive al canale generico evt:tasks (ogni evento su
  // qualunque task, vedi architettura.md §6.1) e ricarica la lista quando ne
  // arriva uno. Alla navigazione verso il dettaglio di una task specifica
  // questa pagina si smonta (l'effect fa unsubscribe) e TaskDetailPage si
  // iscrive invece al canale specifico di quella task.
  useEffect(() => {
    realtimeSocket.connect();
    realtimeSocket.subscribe("tasks");

    const unsubscribe = realtimeSocket.onMessage((message) => {
      if (message.type === "task.created" || message.type === "task.updated" || message.type === "task.deleted") {
        loadTasks(search);
      }
    });

    return () => {
      unsubscribe();
      realtimeSocket.unsubscribe("tasks");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <div className="page-header">
        <h1>
          Le mie task
          <InfoTooltip text="Tutte le task su cui hai almeno il permesso di lettura." />
        </h1>
      </div>

      <input
        placeholder="Cerca per titolo..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ width: "100%", padding: "0.5rem", marginBottom: "1rem" }}
      />

      {loading && <p>Caricamento...</p>}
      {!loading && tasks.length === 0 && <p>Nessuna task trovata.</p>}

      {!loading && tasks.length > 0 && (
        <div className="task-table-wrap">
          <table className="task-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Titolo</th>
                <th>Progetto</th>
                <th>Stato</th>
                <th>Priorità</th>
                <th>Scadenza</th>
                <th>Assegnatari</th>
                <th>Tag</th>
                <th>Aggiornata</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id}>
                  <td className="task-table-id" title={task.id}>
                    {task.readable_id}
                  </td>
                  <td>
                    <Link to={`/tasks/${task.readable_id}`}>
                      <strong>{task.title}</strong>
                    </Link>
                  </td>
                  <td>
                    <Link to={`/projects/${task.project_id}`}>{task.project_name}</Link>
                  </td>
                  <td>
                    {task.column_name ? (
                      <span className="chip">{task.column_name}</span>
                    ) : (
                      <span style={{ color: "var(--text-secondary)" }}>—</span>
                    )}
                  </td>
                  <td>{PRIORITY_LABELS[task.priority] ?? task.priority}</td>
                  <td>{task.due_date ? new Date(task.due_date).toLocaleDateString() : "—"}</td>
                  <td>
                    {task.assignees.length > 0
                      ? task.assignees.map((a) => (a.type === "team" ? `Gruppo: ${a.name}` : a.name)).join(", ")
                      : "—"}
                  </td>
                  <td>
                    {task.tags.length > 0 ? (
                      <div className="chip-list" style={{ marginBottom: 0 }}>
                        {task.tags.map((t) => (
                          <span key={t.id} className="chip" style={t.color ? { background: t.color } : undefined}>
                            {t.name}
                          </span>
                        ))}
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td style={{ color: "var(--text-secondary)" }}>{new Date(task.updated_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
