import { useState } from "react";

import { apiFetch } from "../api/client";

type Column = { id: string; name: string; position: number };

export default function ColumnManager({
  projectId,
  columns,
  onChange,
}: {
  projectId: string;
  columns: Column[];
  onChange: () => void;
}) {
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");

  const sorted = [...columns].sort((a, b) => a.position - b.position);

  async function handleCreate() {
    if (!newName.trim()) return;
    const res = await apiFetch(`/api/projects/${projectId}/columns`, {
      method: "POST",
      body: JSON.stringify({ name: newName }),
    });
    if (!res.ok) window.alert("Servono permessi da admin sul progetto per gestire le colonne.");
    setNewName("");
    onChange();
  }

  async function handleRename(columnId: string) {
    if (!editingName.trim()) {
      setEditingId(null);
      return;
    }
    const res = await apiFetch(`/api/projects/${projectId}/columns/${columnId}`, {
      method: "PATCH",
      body: JSON.stringify({ name: editingName }),
    });
    if (!res.ok) window.alert("Servono permessi da admin sul progetto per gestire le colonne.");
    setEditingId(null);
    onChange();
  }

  async function handleDelete(columnId: string) {
    const res = await apiFetch(`/api/projects/${projectId}/columns/${columnId}`, { method: "DELETE" });
    if (!res.ok) {
      if (res.status === 409) window.alert("Sposta prima tutte le task fuori da questa colonna.");
      else window.alert("Servono permessi da admin sul progetto per gestire le colonne.");
    }
    onChange();
  }

  async function handleMove(index: number, direction: -1 | 1) {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= sorted.length) return;
    const a = sorted[index];
    const b = sorted[targetIndex];

    // scambio semplice delle posizioni: due PATCH, nessun endpoint di riordino
    // bulk dedicato (con poche colonne per progetto è un compromesso ragionevole)
    await Promise.all([
      apiFetch(`/api/projects/${projectId}/columns/${a.id}`, {
        method: "PATCH",
        body: JSON.stringify({ position: b.position }),
      }),
      apiFetch(`/api/projects/${projectId}/columns/${b.id}`, {
        method: "PATCH",
        body: JSON.stringify({ position: a.position }),
      }),
    ]);
    onChange();
  }

  return (
    <div className="column-manager">
      <ul className="column-manager-list">
        {sorted.map((col, index) => (
          <li key={col.id}>
            <div className="column-manager-order">
              <button type="button" disabled={index === 0} onClick={() => handleMove(index, -1)} aria-label="Sposta a sinistra">
                ←
              </button>
              <button
                type="button"
                disabled={index === sorted.length - 1}
                onClick={() => handleMove(index, 1)}
                aria-label="Sposta a destra"
              >
                →
              </button>
            </div>

            {editingId === col.id ? (
              <input
                value={editingName}
                onChange={(e) => setEditingName(e.target.value)}
                onBlur={() => handleRename(col.id)}
                onKeyDown={(e) => e.key === "Enter" && handleRename(col.id)}
                autoFocus
              />
            ) : (
              <span
                className="column-manager-name"
                onClick={() => {
                  setEditingId(col.id);
                  setEditingName(col.name);
                }}
                title="Clicca per rinominare"
              >
                {col.name}
              </span>
            )}

            <button type="button" className="link-button" onClick={() => handleDelete(col.id)}>
              Elimina
            </button>
          </li>
        ))}
      </ul>

      <div className="column-manager-add">
        <input placeholder="Nome nuova colonna..." value={newName} onChange={(e) => setNewName(e.target.value)} />
        <button type="button" onClick={handleCreate}>
          + Colonna
        </button>
      </div>
    </div>
  );
}
