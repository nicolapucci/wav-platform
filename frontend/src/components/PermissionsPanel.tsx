import { useEffect, useState } from "react";

import { apiFetch } from "../api/client";

type Assignment = {
  id: string;
  principal_type: "user" | "team";
  principal_id: string;
  principal_label: string;
  principal_email: string;
  role: string;
};

type UserResult = { id: string; email: string; display_name: string };
type Team = { id: string; name: string };

const ROLES = ["reader", "editor", "admin", "owner"];

type Props = {
  resourceType: "organization" | "project" | "layer";
  resourceId: string;
  organizationId: string;
};

export default function PermissionsPanel({ resourceType, resourceId, organizationId }: Props) {
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // a chi si assegna il ruolo: un utente singolo (ricerca per email, come prima)
  // o un gruppo intero (select tra i gruppi dell'organizzazione) - il ruolo
  // finale dell'utente sarà il più alto tra quello personale e quello ereditato
  // dai suoi gruppi (calcolato da wav_core.permissions.candidate_role_at_resource,
  // già lato server: qui serve solo la UI per assegnare al gruppo).
  const [principalKind, setPrincipalKind] = useState<"user" | "team">("user");
  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState("");

  const [emailQuery, setEmailQuery] = useState("");
  const [userResults, setUserResults] = useState<UserResult[]>([]);
  const [selectedUser, setSelectedUser] = useState<UserResult | null>(null);
  const [role, setRole] = useState("editor");

  async function load() {
    setLoading(true);
    setError(null);
    const res = await apiFetch(`/api/permissions?resource_type=${resourceType}&resource_id=${resourceId}`);
    if (res.ok) {
      setAssignments(await res.json());
    } else if (res.status === 403) {
      setError("Servono permessi da admin su questa risorsa per gestirne i permessi.");
    } else {
      setError("Impossibile caricare i permessi.");
    }
    setLoading(false);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceType, resourceId]);

  useEffect(() => {
    apiFetch(`/api/teams?organization_id=${organizationId}`).then(async (res) => {
      if (res.ok) setTeams(await res.json());
    });
  }, [organizationId]);

  // autocomplete utenti per email, con piccolo debounce
  useEffect(() => {
    if (emailQuery.length < 3 || selectedUser) {
      setUserResults([]);
      return;
    }
    const timeout = setTimeout(async () => {
      const res = await apiFetch(`/api/users/search?q=${encodeURIComponent(emailQuery)}`);
      if (res.ok) setUserResults(await res.json());
    }, 250);
    return () => clearTimeout(timeout);
  }, [emailQuery, selectedUser]);

  async function handleGrant() {
    const principalId = principalKind === "team" ? selectedTeamId : selectedUser?.id;
    if (!principalId) return;
    await apiFetch("/api/permissions", {
      method: "POST",
      body: JSON.stringify({
        resource_type: resourceType,
        resource_id: resourceId,
        principal_type: principalKind,
        principal_id: principalId,
        role,
      }),
    });
    setSelectedUser(null);
    setEmailQuery("");
    setUserResults([]);
    setSelectedTeamId("");
    load();
  }

  async function handleRevoke(assignmentId: string) {
    await apiFetch(`/api/permissions/${assignmentId}`, { method: "DELETE" });
    load();
  }

  return (
    <div className="permissions-panel">
      {loading && <p>Caricamento permessi...</p>}
      {error && <p className="auth-error">{error}</p>}

      {!loading && !error && (
        <>
          <ul className="permissions-list">
            {assignments.map((a) => (
              <li key={a.id}>
                <span>
                  {a.principal_type === "team" ? "Gruppo: " : ""}
                  {a.principal_label}
                  {a.principal_email && ` (${a.principal_email})`} — <strong>{a.role}</strong>
                </span>
                <button type="button" className="link-button" onClick={() => handleRevoke(a.id)}>
                  Rimuovi
                </button>
              </li>
            ))}
            {assignments.length === 0 && <li style={{ color: "var(--text-secondary)" }}>Nessun permesso diretto qui.</li>}
          </ul>

          <div className="permissions-form" style={{ marginBottom: 8 }}>
            <div className="view-toggle">
              <button
                type="button"
                className={principalKind === "user" ? "active" : ""}
                onClick={() => setPrincipalKind("user")}
              >
                Utente
              </button>
              <button
                type="button"
                className={principalKind === "team" ? "active" : ""}
                onClick={() => setPrincipalKind("team")}
              >
                Gruppo
              </button>
            </div>
          </div>

          <div className="permissions-form">
            {principalKind === "user" ? (
              <input
                placeholder="Cerca utente per email..."
                value={emailQuery}
                onChange={(e) => {
                  setEmailQuery(e.target.value);
                  setSelectedUser(null);
                }}
              />
            ) : (
              <select value={selectedTeamId} onChange={(e) => setSelectedTeamId(e.target.value)}>
                <option value="">Scegli un gruppo...</option>
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            )}
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={handleGrant}
              disabled={principalKind === "team" ? !selectedTeamId : !selectedUser}
            >
              Aggiungi
            </button>
          </div>

          {principalKind === "user" && userResults.length > 0 && (
            <ul className="permissions-suggestions">
              {userResults.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedUser(u);
                      setEmailQuery(`${u.display_name} <${u.email}>`);
                      setUserResults([]);
                    }}
                  >
                    {u.display_name} ({u.email})
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
