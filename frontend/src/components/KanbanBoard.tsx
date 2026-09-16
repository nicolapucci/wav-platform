import { useState } from "react";
import { Link } from "react-router-dom";

export type KanbanColumn = { id: string; name: string; position: number };

export type KanbanTask = {
  id: string;
  readable_id: string;
  title: string;
  column_id: string | null;
  priority: number;
};

const PRIORITY_LABELS = ["Bassa", "Media", "Alta", "Urgente"];

export default function KanbanBoard({
  columns,
  tasks,
  onMoveTask,
}: {
  columns: KanbanColumn[];
  tasks: KanbanTask[];
  onMoveTask: (taskId: string, columnId: string) => void;
}) {
  const [draggingTaskId, setDraggingTaskId] = useState<string | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);

  const sortedColumns = [...columns].sort((a, b) => a.position - b.position);

  function handleDragStart(e: React.DragEvent, taskId: string) {
    e.dataTransfer.setData("text/plain", taskId);
    e.dataTransfer.effectAllowed = "move";
    setDraggingTaskId(taskId);
  }

  function handleDragEnd() {
    setDraggingTaskId(null);
    setDragOverColumn(null);
  }

  function handleDragOver(e: React.DragEvent, columnId: string) {
    e.preventDefault(); // necessario per permettere il drop, altrimenti onDrop non scatta
    e.dataTransfer.dropEffect = "move";
    if (dragOverColumn !== columnId) setDragOverColumn(columnId);
  }

  function handleDrop(e: React.DragEvent, columnId: string) {
    e.preventDefault();
    const taskId = e.dataTransfer.getData("text/plain");
    setDraggingTaskId(null);
    setDragOverColumn(null);
    if (!taskId) return;

    const task = tasks.find((t) => t.id === taskId);
    if (task && task.column_id !== columnId) {
      onMoveTask(taskId, columnId);
    }
  }

  if (sortedColumns.length === 0) {
    return <p className="kanban-empty">Nessuna colonna configurata per questo progetto.</p>;
  }

  return (
    <div className="kanban-board" style={{ gridTemplateColumns: `repeat(${sortedColumns.length}, 1fr)` }}>
      {sortedColumns.map((col) => {
        const columnTasks = tasks.filter((t) => t.column_id === col.id);
        return (
          <div
            key={col.id}
            className={`kanban-column${dragOverColumn === col.id ? " drag-over" : ""}`}
            onDragOver={(e) => handleDragOver(e, col.id)}
            onDragLeave={() => setDragOverColumn((current) => (current === col.id ? null : current))}
            onDrop={(e) => handleDrop(e, col.id)}
          >
            <div className="kanban-column-header">
              {col.name}
              <span className="kanban-count">{columnTasks.length}</span>
            </div>
            <div className="kanban-column-body">
              {columnTasks.map((t) => (
                <div
                  key={t.id}
                  className={`kanban-card priority-${t.priority}${draggingTaskId === t.id ? " dragging" : ""}`}
                  draggable
                  onDragStart={(e) => handleDragStart(e, t.id)}
                  onDragEnd={handleDragEnd}
                >
                  {/* draggable=false sul link: altrimenti il browser avvia il suo
                      drag nativo del link (trascina l'URL) invece del nostro, sulla
                      stessa card */}
                  <Link to={`/tasks/${t.readable_id}`} draggable={false}>
                    {t.title}
                  </Link>
                  <div className="kanban-card-meta">
                    <span className="kanban-card-id">{t.readable_id}</span>
                    <span className={`kanban-priority priority-${t.priority}`}>
                      {PRIORITY_LABELS[t.priority] ?? t.priority}
                    </span>
                  </div>
                  <select
                    value={t.column_id ?? ""}
                    onChange={(e) => onMoveTask(t.id, e.target.value)}
                    aria-label={`Sposta "${t.title}" in un'altra colonna`}
                  >
                    {sortedColumns.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
              {columnTasks.length === 0 && <p className="kanban-empty">Nessuna task</p>}
            </div>
          </div>
        );
      })}

      {/* La <select> resta come fallback accessibile (tastiera, touch, screen
          reader): il drag&drop è il modo primario ma non l'unico per spostare
          una task tra colonne. Le colonne stesse si creano/modificano/eliminano
          da ColumnManager, non da qui - qui è solo vista + spostamento task. */}
    </div>
  );
}
