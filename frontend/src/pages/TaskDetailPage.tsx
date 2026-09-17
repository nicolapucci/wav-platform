import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { apiFetch } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";
import { realtimeSocket } from "../ws/socket";

type Task = {
  id: string;
  readable_id: string;
  layer_id: string;
  project_id: string;
  title: string;
  description: string | null;
  priority: number;
  due_date: string | null;
  created_by: string;
  status_column_id: string | null;
  viewer_role: string | null;
};

// un assegnatario/menzione può essere un utente o un team intero: un team è
// trattato "logicamente come un utente" (vedi permissions.py/comments.py) -
// assegnargli una task equivale ad assegnarla a ciascun membro, menzionarlo
// notifica ciascun membro.
type Assignee = { principal_type: "user" | "team"; id: string; display_name: string; email: string | null };
type Comment = { id: string; author_id: string; author_name: string; body: string; created_at: string };
type DependencyTask = { id: string; readable_id: string; title: string };
type UserResult = { id: string; email: string; display_name: string };
type Team = { id: string; name: string };
type Column = { id: string; name: string; position: number };
type Tag = { id: string; project_id: string; name: string; color: string | null };

const ROLE_ORDER = ["reader", "editor", "admin", "owner"];

function roleAtLeast(role: string | null, minimum: string) {
  if (!role) return false;
  return ROLE_ORDER.indexOf(role) >= ROLE_ORDER.indexOf(minimum);
}

export default function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();

  const [task, setTask] = useState<Task | null>(null);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [dependencies, setDependencies] = useState<{ blocked_by: DependencyTask[]; blocks: DependencyTask[] }>({
    blocked_by: [],
    blocks: [],
  });
  const [comments, setComments] = useState<Comment[]>([]);
  const [columns, setColumns] = useState<Column[]>([]);
  const [taskTags, setTaskTags] = useState<Tag[]>([]);
  const [projectTags, setProjectTags] = useState<Tag[]>([]);
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(0);
  const [dueDate, setDueDate] = useState("");

  const [assigneeQuery, setAssigneeQuery] = useState("");
  const [assigneeResults, setAssigneeResults] = useState<UserResult[]>([]);
  const [assigneeTeamResults, setAssigneeTeamResults] = useState<Team[]>([]);

  // autocomplete dipendenze: cerca tra le task esistenti per titolo
  const [dependencyQuery, setDependencyQuery] = useState("");
  const [dependencyResults, setDependencyResults] = useState<DependencyTask[]>([]);

  // tag: ricerca/creazione al volo tra i tag del progetto
  const [tagQuery, setTagQuery] = useState("");

  // chat + menzioni
  const [newComment, setNewComment] = useState("");
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionResults, setMentionResults] = useState<UserResult[]>([]);
  const [mentionTeamResults, setMentionTeamResults] = useState<Team[]>([]);
  const [mentionedUsers, setMentionedUsers] = useState<Record<string, UserResult>>({});
  const [mentionedTeams, setMentionedTeams] = useState<Record<string, Team>>({});
  const commentInputRef = useRef<HTMLTextAreaElement>(null);

  const canEdit = roleAtLeast(task?.viewer_role ?? null, "editor");

  async function loadAll() {
    if (!taskId) return;
    setLoading(true);

    const [taskRes, assigneesRes, depsRes, commentsRes, taskTagsRes] = await Promise.all([
      apiFetch(`/api/tasks/${taskId}`),
      apiFetch(`/api/tasks/${taskId}/assignees`),
      apiFetch(`/api/tasks/${taskId}/dependencies`),
      apiFetch(`/api/comments?task_id=${taskId}`),
      apiFetch(`/api/tasks/${taskId}/tags`),
    ]);

    let projectId: string | null = null;
    if (taskRes.ok) {
      const t: Task = await taskRes.json();
      setTask(t);
      setTitle(t.title);
      setDescription(t.description || "");
      setPriority(t.priority);
      setDueDate(t.due_date || "");
      projectId = t.project_id;
    } else {
      setTask(null);
    }

    if (assigneesRes.ok) setAssignees(await assigneesRes.json());
    if (depsRes.ok) setDependencies(await depsRes.json());
    if (commentsRes.ok) setComments(await commentsRes.json());
    if (taskTagsRes.ok) setTaskTags(await taskTagsRes.json());

    if (projectId) {
      const [projectRes, columnsRes, projectTagsRes] = await Promise.all([
        apiFetch(`/api/projects/${projectId}`),
        apiFetch(`/api/projects/${projectId}/columns`),
        apiFetch(`/api/tags?project_id=${projectId}`),
      ]);
      if (projectRes.ok) setOrganizationId((await projectRes.json()).organization_id);
      if (columnsRes.ok) setColumns(await columnsRes.json());
      if (projectTagsRes.ok) setProjectTags(await projectTagsRes.json());
    }

    setLoading(false);
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  // gruppi dell'organizzazione del progetto: usati sia per assegnare la task a
  // un gruppo sia per menzionarlo nei commenti (autocomplete filtrato lato
  // client, coerente con BoardManager che fa lo stesso per il filtro "Gruppo").
  useEffect(() => {
    if (!organizationId) return;
    apiFetch(`/api/teams?organization_id=${organizationId}`).then(async (res) => {
      if (res.ok) setTeams(await res.json());
    });
  }, [organizationId]);

  // realtime: la pagina è ancorata a questa risorsa, quindi si sottoscrive
  // direttamente a evt:task:{id} (architettura.md §6.2) e ricarica su ogni evento
  // (aggiornamento campi, spostamento kanban, nuovo commento, tag). Il canale è
  // sempre keyed sullo UUID interno lato server (vedi tasks.py/comments.py),
  // mai sull'id leggibile: si sottoscrive con task.id (disponibile solo dopo il
  // primo caricamento), non con taskId dalla route (che ora è l'id leggibile).
  useEffect(() => {
    if (!task) return;
    const resourceId = task.id;
    realtimeSocket.connect();
    realtimeSocket.subscribe("task", resourceId);

    const unsubscribe = realtimeSocket.onMessage((message) => {
      if (message.channel === `evt:task:${resourceId}`) {
        loadAll();
      }
    });

    return () => {
      unsubscribe();
      realtimeSocket.unsubscribe("task", resourceId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  useEffect(() => {
    if (assigneeQuery.length < 3) {
      setAssigneeResults([]);
      setAssigneeTeamResults([]);
      return;
    }
    const timeout = setTimeout(async () => {
      const res = await apiFetch(`/api/users/search?q=${encodeURIComponent(assigneeQuery)}`);
      if (res.ok) setAssigneeResults(await res.json());
      setAssigneeTeamResults(teams.filter((t) => t.name.toLowerCase().includes(assigneeQuery.toLowerCase())));
    }, 250);
    return () => clearTimeout(timeout);
  }, [assigneeQuery, teams]);

  // autocomplete dipendenze: cerca task per titolo, escludendo questa stessa task
  useEffect(() => {
    if (dependencyQuery.length < 2 || !taskId) {
      setDependencyResults([]);
      return;
    }
    const timeout = setTimeout(async () => {
      const res = await apiFetch(
        `/api/tasks/search?q=${encodeURIComponent(dependencyQuery)}&exclude_task_id=${taskId}`,
      );
      if (res.ok) setDependencyResults(await res.json());
    }, 250);
    return () => clearTimeout(timeout);
  }, [dependencyQuery, taskId]);

  // autocomplete menzioni: si attiva sull'ultimo "@parola" prima del cursore
  useEffect(() => {
    if (mentionQuery === null) {
      setMentionResults([]);
      setMentionTeamResults([]);
      return;
    }
    const timeout = setTimeout(async () => {
      const res = await apiFetch(`/api/users/search?q=${encodeURIComponent(mentionQuery)}`);
      if (res.ok) setMentionResults(await res.json());
      setMentionTeamResults(teams.filter((t) => t.name.toLowerCase().includes(mentionQuery.toLowerCase())));
    }, 200);
    return () => clearTimeout(timeout);
  }, [mentionQuery, teams]);

  async function handleSave() {
    if (!taskId) return;
    const res = await apiFetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ title, description: description || null, priority, due_date: dueDate || null }),
    });
    if (!res.ok) window.alert("Impossibile salvare: permessi insufficienti.");
    loadAll();
  }

  async function handleDelete() {
    if (!taskId || !task) return;
    if (!window.confirm(`Eliminare la task "${task.title}"? L'azione non è annullabile da qui.`)) return;

    const res = await apiFetch(`/api/tasks/${taskId}`, { method: "DELETE" });
    if (!res.ok) {
      window.alert("Impossibile eliminare: permessi insufficienti.");
      return;
    }
    navigate("/my-tasks");
  }

  async function handleColumnChange(columnId: string) {
    if (!taskId) return;
    const res = await apiFetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status_column_id: columnId }),
    });
    if (!res.ok) window.alert("Impossibile cambiare stato: permessi insufficienti.");
    loadAll();
  }

  async function handleAddAssignee(principalType: "user" | "team", principalId: string) {
    if (!taskId) return;
    await apiFetch(`/api/tasks/${taskId}/assignees`, {
      method: "POST",
      body: JSON.stringify({ principal_type: principalType, principal_id: principalId }),
    });
    setAssigneeQuery("");
    setAssigneeResults([]);
    setAssigneeTeamResults([]);
    loadAll();
  }

  async function handleRemoveAssignee(principalType: "user" | "team", principalId: string) {
    if (!taskId) return;
    await apiFetch(`/api/tasks/${taskId}/assignees/${principalId}?principal_type=${principalType}`, {
      method: "DELETE",
    });
    loadAll();
  }

  async function handleSelectDependency(candidate: DependencyTask) {
    if (!taskId) return;
    const res = await apiFetch(`/api/tasks/${taskId}/dependencies/${candidate.id}`, { method: "POST" });
    if (!res.ok) window.alert("Impossibile aggiungere la dipendenza (permessi insufficienti o ciclo rilevato).");
    setDependencyQuery("");
    setDependencyResults([]);
    loadAll();
  }

  async function handleRemoveDependency(dependsOnId: string) {
    if (!taskId) return;
    await apiFetch(`/api/tasks/${taskId}/dependencies/${dependsOnId}`, { method: "DELETE" });
    loadAll();
  }

  async function handleAttachTag(tag: Tag) {
    if (!taskId) return;
    const res = await apiFetch(`/api/tasks/${taskId}/tags/${tag.id}`, { method: "POST" });
    if (!res.ok) window.alert("Impossibile aggiungere il tag: permessi insufficienti.");
    setTagQuery("");
    loadAll();
  }

  async function handleCreateAndAttachTag(name: string) {
    if (!task) return;
    const createRes = await apiFetch("/api/tags", {
      method: "POST",
      body: JSON.stringify({ project_id: task.project_id, name }),
    });
    if (!createRes.ok) {
      window.alert("Impossibile creare il tag: servono permessi da editor sul progetto.");
      return;
    }
    const newTag: Tag = await createRes.json();
    await handleAttachTag(newTag);
  }

  async function handleRemoveTag(tagId: string) {
    if (!taskId) return;
    await apiFetch(`/api/tasks/${taskId}/tags/${tagId}`, { method: "DELETE" });
    loadAll();
  }

  function handleCommentChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const value = e.target.value;
    const cursor = e.target.selectionStart;
    setNewComment(value);

    // testo fino al cursore: se termina con "@" seguito da caratteri senza spazi,
    // quella è la query di menzione attiva
    const beforeCursor = value.slice(0, cursor);
    const match = beforeCursor.match(/@([a-zA-Z0-9_]*)$/);
    setMentionQuery(match ? match[1] : null);
  }

  function insertMentionText(name: string) {
    const textarea = commentInputRef.current;
    if (!textarea) return;

    const cursor = textarea.selectionStart;
    const beforeCursor = newComment.slice(0, cursor);
    const afterCursor = newComment.slice(cursor);
    const updatedBefore = beforeCursor.replace(/@([a-zA-Z0-9_]*)$/, `@${name} `);

    setNewComment(updatedBefore + afterCursor);
    setMentionQuery(null);
    setMentionResults([]);
    setMentionTeamResults([]);

    requestAnimationFrame(() => textarea.focus());
  }

  function handleSelectMentionUser(user: UserResult) {
    insertMentionText(user.display_name);
    setMentionedUsers((prev) => ({ ...prev, [user.display_name]: user }));
  }

  function handleSelectMentionTeam(team: Team) {
    insertMentionText(team.name);
    setMentionedTeams((prev) => ({ ...prev, [team.name]: team }));
  }

  async function handleAddComment() {
    if (!taskId || !newComment.trim()) return;

    // solo le menzioni ancora presenti nel testo (l'utente potrebbe aver cancellato
    // un "@nome" dopo averlo selezionato dall'autocomplete)
    const mentionedIds = Object.values(mentionedUsers)
      .filter((u) => newComment.includes(`@${u.display_name}`))
      .map((u) => u.id);
    const mentionedTeamIds = Object.values(mentionedTeams)
      .filter((t) => newComment.includes(`@${t.name}`))
      .map((t) => t.id);

    const res = await apiFetch("/api/comments", {
      method: "POST",
      body: JSON.stringify({
        task_id: taskId,
        body: newComment,
        mentioned_user_ids: mentionedIds,
        mentioned_team_ids: mentionedTeamIds,
      }),
    });
    if (res.ok) {
      setNewComment("");
      setMentionedUsers({});
      setMentionedTeams({});
      loadAll();
    } else if (res.status === 403) {
      window.alert("Non hai i permessi per commentare questa task.");
    }
  }

  if (loading) return <p>Caricamento...</p>;
  if (!task) return <p>Task non trovata, oppure non hai i permessi per vederla.</p>;

  const attachedTagIds = new Set(taskTags.map((t) => t.id));
  const tagSuggestions = projectTags.filter(
    (t) => !attachedTagIds.has(t.id) && t.name.toLowerCase().includes(tagQuery.toLowerCase()),
  );
  const exactMatchExists = projectTags.some((t) => t.name.toLowerCase() === tagQuery.trim().toLowerCase());

  return (
    <>
      <div className="page-header">
        <h1>
          <span className="task-detail-readable-id">{task.readable_id}</span> {task.title}
          <InfoTooltip text={`Il tuo ruolo qui: ${task.viewer_role ?? "nessuno"}`} />
        </h1>
      </div>

      <div className="task-detail-grid">
        <section className="task-fields">
          <div className="field">
            <label>Titolo</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!canEdit} />
          </div>

          <div className="field">
            <label>Descrizione</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={!canEdit}
              rows={4}
            />
          </div>

          <div className="field">
            <label>Stato (kanban)</label>
            <select
              value={task.status_column_id ?? ""}
              onChange={(e) => handleColumnChange(e.target.value)}
              disabled={!canEdit}
            >
              {columns
                .slice()
                .sort((a, b) => a.position - b.position)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
          </div>

          <div className="field">
            <label>Priorità</label>
            <select value={priority} onChange={(e) => setPriority(Number(e.target.value))} disabled={!canEdit}>
              <option value={0}>Bassa</option>
              <option value={1}>Media</option>
              <option value={2}>Alta</option>
              <option value={3}>Urgente</option>
            </select>
          </div>

          <div className="field">
            <label>Scadenza</label>
            <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} disabled={!canEdit} />
          </div>

          {canEdit && (
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="btn-primary" onClick={handleSave}>
                Salva
              </button>
              <button type="button" className="link-button" onClick={handleDelete}>
                Elimina task
              </button>
            </div>
          )}

          <div className="field" style={{ marginTop: 22 }}>
            <label>Tag</label>
            {taskTags.length > 0 && (
              <div className="chip-list">
                {taskTags.map((t) => (
                  <span key={t.id} className="chip">
                    {t.name}
                    {canEdit && <button type="button" onClick={() => handleRemoveTag(t.id)}>×</button>}
                  </span>
                ))}
              </div>
            )}

            {canEdit && (
              <>
                <input
                  placeholder="Cerca o crea un tag..."
                  value={tagQuery}
                  onChange={(e) => setTagQuery(e.target.value)}
                />
                {tagQuery.trim().length > 0 && (
                  <ul className="permissions-suggestions">
                    {tagSuggestions.map((t) => (
                      <li key={t.id}>
                        <button type="button" onClick={() => handleAttachTag(t)}>
                          {t.name}
                        </button>
                      </li>
                    ))}
                    {!exactMatchExists && (
                      <li>
                        <button type="button" onClick={() => handleCreateAndAttachTag(tagQuery.trim())}>
                          + Crea tag &quot;{tagQuery.trim()}&quot;
                        </button>
                      </li>
                    )}
                  </ul>
                )}
              </>
            )}
          </div>

          <div className="field" style={{ marginTop: 22 }}>
            <label>Assegnatari</label>
            <ul className="permissions-list">
              {assignees.map((a) => (
                <li key={`${a.principal_type}-${a.id}`}>
                  <span>
                    {a.principal_type === "team" ? "Gruppo: " : ""}
                    {a.display_name}
                    {a.email && ` (${a.email})`}
                  </span>
                  {canEdit && (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => handleRemoveAssignee(a.principal_type, a.id)}
                    >
                      Rimuovi
                    </button>
                  )}
                </li>
              ))}
              {assignees.length === 0 && <li style={{ color: "var(--text-secondary)" }}>Nessun assegnatario</li>}
            </ul>

            {canEdit && (
              <>
                <input
                  placeholder="Cerca utente o gruppo..."
                  value={assigneeQuery}
                  onChange={(e) => setAssigneeQuery(e.target.value)}
                />
                {(assigneeResults.length > 0 || assigneeTeamResults.length > 0) && (
                  <ul className="permissions-suggestions">
                    {assigneeResults.map((u) => (
                      <li key={u.id}>
                        <button type="button" onClick={() => handleAddAssignee("user", u.id)}>
                          {u.display_name} ({u.email})
                        </button>
                      </li>
                    ))}
                    {assigneeTeamResults.map((t) => (
                      <li key={t.id}>
                        <button type="button" onClick={() => handleAddAssignee("team", t.id)}>
                          Gruppo: {t.name}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>

          <div className="field" style={{ marginTop: 22 }}>
            <label>Dipendenze</label>
            <p className="dependency-label">Bloccata da:</p>
            <ul className="permissions-list">
              {dependencies.blocked_by.map((d) => (
                <li key={d.id}>
                  <Link to={`/tasks/${d.readable_id}`}>
                    <span className="task-table-id">{d.readable_id}</span> {d.title}
                  </Link>
                  {canEdit && (
                    <button type="button" className="link-button" onClick={() => handleRemoveDependency(d.id)}>
                      Rimuovi
                    </button>
                  )}
                </li>
              ))}
              {dependencies.blocked_by.length === 0 && <li style={{ color: "var(--text-secondary)" }}>Nessuna</li>}
            </ul>

            <p className="dependency-label">Blocca:</p>
            <ul className="permissions-list">
              {dependencies.blocks.map((d) => (
                <li key={d.id}>
                  <Link to={`/tasks/${d.readable_id}`}>
                    <span className="task-table-id">{d.readable_id}</span> {d.title}
                  </Link>
                </li>
              ))}
              {dependencies.blocks.length === 0 && <li style={{ color: "var(--text-secondary)" }}>Nessuna</li>}
            </ul>

            {canEdit && (
              <>
                <input
                  placeholder="Cerca una task da cui dipendere..."
                  value={dependencyQuery}
                  onChange={(e) => setDependencyQuery(e.target.value)}
                />
                {dependencyResults.length > 0 && (
                  <ul className="permissions-suggestions">
                    {dependencyResults.map((t) => (
                      <li key={t.id}>
                        <button type="button" onClick={() => handleSelectDependency(t)}>
                          <span className="task-table-id">{t.readable_id}</span> {t.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        </section>

        <section className="task-chat">
          <h2 className="task-chat-title">Commenti</h2>

          <div className="comment-list">
            {comments.map((c) => (
              <div key={c.id} className="comment">
                <div className="comment-header">
                  <strong>{c.author_name}</strong>
                  <span>{new Date(c.created_at).toLocaleString()}</span>
                </div>
                <p>{c.body}</p>
              </div>
            ))}
            {comments.length === 0 && <p style={{ color: "var(--text-secondary)" }}>Nessun commento ancora.</p>}
          </div>

          <div className="comment-composer">
            <div className="mention-anchor">
              <textarea
                ref={commentInputRef}
                placeholder="Scrivi un commento... digita @ per menzionare qualcuno"
                value={newComment}
                onChange={handleCommentChange}
                rows={3}
              />
              {(mentionResults.length > 0 || mentionTeamResults.length > 0) && (
                <ul className="mention-suggestions">
                  {mentionResults.map((u) => (
                    <li key={`user-${u.id}`}>
                      <button type="button" onClick={() => handleSelectMentionUser(u)}>
                        {u.display_name} <span className="mention-email">{u.email}</span>
                      </button>
                    </li>
                  ))}
                  {mentionTeamResults.map((t) => (
                    <li key={`team-${t.id}`}>
                      <button type="button" onClick={() => handleSelectMentionTeam(t)}>
                        Gruppo: {t.name}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <button type="button" className="btn-primary" onClick={handleAddComment}>
              Invia
            </button>
          </div>

          {/* TODO: allegati (richiede endpoint presigned URL verso MinIO/S3, vedi
              architettura.md §4.3). Le menzioni si basano sul display_name presente
              nel testo: se due utenti hanno lo stesso nome visualizzato, la
              menzione selezionata per ultima "vince" nel matching in handleAddComment. */}
        </section>
      </div>
    </>
  );
}
