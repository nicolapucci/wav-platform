import { useState } from "react";

import { apiFetch } from "../api/client";

type Tag = { id: string; project_id: string; name: string; color: string | null };

export default function TagManager({
  projectId,
  tags,
  onChange,
}: {
  projectId: string;
  tags: Tag[];
  onChange: () => void;
}) {
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState("#4c6fe0");

  async function handleCreate() {
    if (!newName.trim()) return;
    const res = await apiFetch("/api/tags", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, name: newName.trim(), color: newColor }),
    });
    if (!res.ok) window.alert("Servono permessi da editor sul progetto per creare tag.");
    setNewName("");
    onChange();
  }

  async function handleDelete(tagId: string) {
    const res = await apiFetch(`/api/tags/${tagId}`, { method: "DELETE" });
    if (!res.ok) window.alert("Servono permessi da admin sul progetto per eliminare un tag.");
    onChange();
  }

  return (
    <div className="tag-manager">
      {tags.length > 0 ? (
        <div className="chip-list">
          {tags.map((t) => (
            <span key={t.id} className="chip" style={t.color ? { background: t.color } : undefined}>
              {t.name}
              <button type="button" onClick={() => handleDelete(t.id)} aria-label={`Elimina tag "${t.name}"`}>
                ×
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="kanban-empty">Nessun tag ancora in questo progetto.</p>
      )}

      <div className="tag-manager-add">
        <input
          type="text"
          placeholder="Nome nuovo tag..."
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
        />
        <input
          type="color"
          value={newColor}
          onChange={(e) => setNewColor(e.target.value)}
          aria-label="Colore del tag"
        />
        <button type="button" onClick={handleCreate}>
          + Tag
        </button>
      </div>
    </div>
  );
}
