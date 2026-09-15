import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { apiFetch } from "../api/client";
import BoardManager from "../components/BoardManager";
import ColumnManager from "../components/ColumnManager";
import KanbanBoard, { KanbanColumn, KanbanTask } from "../components/KanbanBoard";
import PermissionsPanel from "../components/PermissionsPanel";
import TagManager from "../components/TagManager";

type Project = { id: string; organization_id: string; name: string; description: string | null; prefix: string };
type Layer = { id: string; parent_layer_id: string | null; name: string; description: string | null };
type Tag = { id: string; project_id: string; name: string; color: string | null };

type Tab = "structure" | "dashboard";

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [columns, setColumns] = useState<KanbanColumn[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tasksByLayer, setTasksByLayer] = useState<Record<string, KanbanTask[]>>({});
  const [loading, setLoading] = useState(true);
  const [showProjectPermissions, setShowProjectPermissions] = useState(false);
  const [showColumnManager, setShowColumnManager] = useState(false);
  const [showTagManager, setShowTagManager] = useState(false);
  const [tab, setTab] = useState<Tab>("structure");

  async function loadColumns() {
    if (!projectId) return;
    const res = await apiFetch(`/api/projects/${projectId}/columns`);
    if (res.ok) setColumns(await res.json());
  }

  async function loadTags() {
    if (!projectId) return;
    const res = await apiFetch(`/api/tags?project_id=${projectId}`);
    if (res.ok) setTags(await res.json());
  }

  async function loadAll() {
    if (!projectId) return;
    setLoading(true);

    const projectRes = await apiFetch(`/api/projects/${projectId}`);
    if (projectRes.ok) setProject(await projectRes.json());

    await loadColumns();
    await loadTags();

    const layersRes = await apiFetch(`/api/layers?project_id=${projectId}`);
    const layerList: Layer[] = layersRes.ok ? await layersRes.json() : [];
    setLayers(layerList);

    const entries = await Promise.all(
      layerList.map(async (layer) => {
        const res = await apiFetch(`/api/tasks?layer_id=${layer.id}`);
        if (!res.ok) return [layer.id, []] as const;
        const rawTasks = await res.json();
        // GET /tasks restituisce status_column_id (TaskOut): qui serve solo
        // column_id per il componente KanbanBoard, che è agnostico rispetto
        // al resto dei campi della task.
        const mapped: KanbanTask[] = rawTasks.map((t: any) => ({
          id: t.id,
          readable_id: t.readable_id,
          title: t.title,
          column_id: t.status_column_id,
          priority: t.priority,
        }));
        return [layer.id, mapped] as const;
      }),
    );
    setTasksByLayer(Object.fromEntries(entries));
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function handleCreateLayer(parentLayerId: string | null) {
    const name = window.prompt(parentLayerId ? "Nome del nuovo sotto-layer?" : "Nome del nuovo layer?");
    if (!name || !projectId) return;
    const res = await apiFetch("/api/layers", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, parent_layer_id: parentLayerId, name }),
    });
    if (!res.ok) window.alert("Permessi insufficienti per creare un layer qui.");
    loadAll();
  }

  async function handleCreateTask(layerId: string) {
    const title = window.prompt("Titolo della nuova task?");
    if (!title) return;
    const res = await apiFetch("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ layer_id: layerId, title }),
    });
    if (!res.ok) window.alert("Permessi insufficienti per creare una task qui.");
    loadAll();
  }

  async function handleMoveTask(taskId: string, columnId: string) {
    const res = await apiFetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status_column_id: columnId }),
    });
    if (!res.ok) window.alert("Impossibile spostare la task: permessi insufficienti.");
    loadAll();
  }

  const rootLayers = layers.filter((l) => l.parent_layer_id === null);

  return (
    <>
      <div className="page-header">
        <h1>
          {project && <span className="task-detail-readable-id">{project.prefix}</span>} {project?.name ?? "Progetto"}
        </h1>
        <p>{project?.description || "Struttura a layer e task."}</p>
      </div>

      <div className="tabs">
        <button
          type="button"
          className={`tab-button${tab === "structure" ? " active" : ""}`}
          onClick={() => setTab("structure")}
        >
          Struttura
        </button>
        <button
          type="button"
          className={`tab-button${tab === "dashboard" ? " active" : ""}`}
          onClick={() => setTab("dashboard")}
        >
          Dashboard
        </button>
      </div>

      {loading && <p>Caricamento...</p>}

      {!loading && tab === "structure" && (
        <>
          <div className="toolbar">
            <button type="button" onClick={() => handleCreateLayer(null)}>
              + Layer
            </button>
            <button type="button" onClick={() => setShowColumnManager((v) => !v)}>
              Gestisci colonne kanban
            </button>
            <button type="button" onClick={() => setShowTagManager((v) => !v)}>
              Gestisci tag
            </button>
            <button type="button" onClick={() => setShowProjectPermissions((v) => !v)}>
              Permessi progetto
            </button>
          </div>

          {showColumnManager && projectId && (
            <div style={{ marginBottom: 20 }}>
              <ColumnManager projectId={projectId} columns={columns} onChange={loadColumns} />
            </div>
          )}

          {showTagManager && projectId && (
            <div style={{ marginBottom: 20 }}>
              <TagManager projectId={projectId} tags={tags} onChange={loadTags} />
            </div>
          )}

          {showProjectPermissions && (
            <div style={{ marginBottom: 20 }}>
              <PermissionsPanel
                resourceType="project"
                resourceId={projectId!}
                organizationId={project?.organization_id ?? ""}
              />
            </div>
          )}

          {rootLayers.length === 0 && <p style={{ color: "var(--text-secondary)" }}>Nessun layer ancora.</p>}

          <div className="layer-tree">
            {rootLayers.map((layer) => (
              <LayerNode
                key={layer.id}
                layer={layer}
                allLayers={layers}
                columns={columns}
                tasksByLayer={tasksByLayer}
                organizationId={project?.organization_id ?? ""}
                onCreateLayer={handleCreateLayer}
                onCreateTask={handleCreateTask}
                onMoveTask={handleMoveTask}
                depth={0}
              />
            ))}
          </div>
        </>
      )}

      {!loading && tab === "dashboard" && project && (
        <BoardManager
          projectId={project.id}
          organizationId={project.organization_id}
          layers={layers}
          columns={columns}
        />
      )}
    </>
  );
}

function LayerNode({
  layer,
  allLayers,
  columns,
  tasksByLayer,
  organizationId,
  onCreateLayer,
  onCreateTask,
  onMoveTask,
  depth,
}: {
  layer: Layer;
  allLayers: Layer[];
  columns: KanbanColumn[];
  tasksByLayer: Record<string, KanbanTask[]>;
  organizationId: string;
  onCreateLayer: (parentLayerId: string) => void;
  onCreateTask: (layerId: string) => void;
  onMoveTask: (taskId: string, columnId: string) => void;
  depth: number;
}) {
  const [showPermissions, setShowPermissions] = useState(false);
  const children = allLayers.filter((l) => l.parent_layer_id === layer.id);
  const tasks = tasksByLayer[layer.id] || [];

  return (
    <div className="layer-node" style={{ marginLeft: depth * 20 }}>
      <div className="layer-node-header">
        <strong>{layer.name}</strong>
        <button type="button" onClick={() => onCreateLayer(layer.id)}>
          + Sotto-layer
        </button>
        <button type="button" onClick={() => onCreateTask(layer.id)}>
          + Task
        </button>
        <button type="button" onClick={() => setShowPermissions((v) => !v)}>
          Permessi
        </button>
      </div>

      {showPermissions && (
        <div style={{ margin: "8px 0 12px" }}>
          <PermissionsPanel resourceType="layer" resourceId={layer.id} organizationId={organizationId} />
        </div>
      )}

      {/* Kanban di default: solo le task DI QUESTO layer, escluse quelle dei
          sotto-layer (GET /tasks?layer_id= non è ricorsivo) - i sotto-layer
          hanno la propria kanban indipendente più sotto nell'albero. Le colonne
          sono quelle del progetto (condivise, gestite sopra con "Gestisci
          colonne kanban"), non colonne separate per layer. */}
      {tasks.length > 0 ? (
        <KanbanBoard columns={columns} tasks={tasks} onMoveTask={onMoveTask} />
      ) : (
        <p className="kanban-empty" style={{ margin: "4px 0 10px" }}>
          Nessuna task in questo layer.
        </p>
      )}

      {children.map((child) => (
        <LayerNode
          key={child.id}
          layer={child}
          allLayers={allLayers}
          columns={columns}
          tasksByLayer={tasksByLayer}
          organizationId={organizationId}
          onCreateLayer={onCreateLayer}
          onCreateTask={onCreateTask}
          onMoveTask={onMoveTask}
          depth={depth + 1}
        />
      ))}
    </div>
  );
}
