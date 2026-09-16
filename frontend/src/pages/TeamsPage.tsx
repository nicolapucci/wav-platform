import { useEffect, useState } from "react";

import { apiFetch } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";

type Organization = { id: string; name: string };
type Team = { id: string; name: string };
type Member = { id: string; display_name: string; email: string };

export default function TeamsPage() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [teamsByOrg, setTeamsByOrg] = useState<Record<string, Team[]>>({});
  const [loading, setLoading] = useState(true);
  const [expandedTeamId, setExpandedTeamId] = useState<string | null>(null);

  async function loadAll() {
    setLoading(true);
    const orgRes = await apiFetch("/api/organizations");
    const orgs: Organization[] = orgRes.ok ? await orgRes.json() : [];
    setOrganizations(orgs);

    const entries = await Promise.all(
      orgs.map(async (org) => {
        const res = await apiFetch(`/api/teams?organization_id=${org.id}`);
        return [org.id, res.ok ? await res.json() : []] as const;
      }),
    );
    setTeamsByOrg(Object.fromEntries(entries));
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function handleCreateTeam(organizationId: string) {
    const name = window.prompt("Nome del nuovo gruppo?");
    if (!name) return;
    const res = await apiFetch("/api/teams", {
      method: "POST",
      body: JSON.stringify({ organization_id: organizationId, name }),
    });
    if (!res.ok) window.alert("Servono permessi da admin sull'organizzazione per creare un gruppo.");
    loadAll();
  }

  return (
    <>
      <div className="page-header">
        <h1>
          Gruppi
          <InfoTooltip text="Assegna un permesso a un gruppo invece che a ogni persona singolarmente." />
        </h1>
      </div>

      {loading && <p>Caricamento...</p>}
      {!loading && organizations.length === 0 && <p>Non fai ancora parte di nessuna organizzazione.</p>}

      {organizations.map((org) => (
        <section key={org.id} style={{ marginBottom: 28 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ fontSize: 15, margin: "0 0 8px" }}>{org.name}</h2>
            <button type="button" onClick={() => handleCreateTeam(org.id)}>
              Nuovo gruppo
            </button>
          </div>
          <ul className="permissions-list">
            {(teamsByOrg[org.id] || []).map((team) => (
              <li key={team.id} style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span>{team.name}</span>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => setExpandedTeamId((current) => (current === team.id ? null : team.id))}
                  >
                    {expandedTeamId === team.id ? "Chiudi" : "Membri"}
                  </button>
                </div>
                {expandedTeamId === team.id && <TeamMembers teamId={team.id} />}
              </li>
            ))}
            {(teamsByOrg[org.id] || []).length === 0 && (
              <li style={{ color: "var(--text-secondary)" }}>Nessun gruppo</li>
            )}
          </ul>
        </section>
      ))}
    </>
  );
}

function TeamMembers({ teamId }: { teamId: string }) {
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Member[]>([]);

  async function load() {
    setLoading(true);
    const res = await apiFetch(`/api/teams/${teamId}/members`);
    if (res.ok) setMembers(await res.json());
    setLoading(false);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId]);

  useEffect(() => {
    if (query.length < 3) {
      setResults([]);
      return;
    }
    const timeout = setTimeout(async () => {
      const res = await apiFetch(`/api/users/search?q=${encodeURIComponent(query)}`);
      if (res.ok) setResults(await res.json());
    }, 250);
    return () => clearTimeout(timeout);
  }, [query]);

  async function handleAdd(user: Member) {
    const res = await apiFetch(`/api/teams/${teamId}/members`, {
      method: "POST",
      body: JSON.stringify({ user_id: user.id }),
    });
    if (!res.ok) window.alert("Servono permessi da admin sull'organizzazione per aggiungere un membro.");
    setQuery("");
    setResults([]);
    load();
  }

  async function handleRemove(userId: string) {
    const res = await apiFetch(`/api/teams/${teamId}/members/${userId}`, { method: "DELETE" });
    if (!res.ok) window.alert("Servono permessi da admin sull'organizzazione per rimuovere un membro.");
    load();
  }

  return (
    <div style={{ margin: "8px 0 4px", paddingLeft: 12, borderLeft: "2px solid var(--border)" }}>
      {loading && <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>Caricamento membri...</p>}
      {!loading && (
        <ul className="permissions-list">
          {members.map((m) => (
            <li key={m.id}>
              <span>
                {m.display_name} ({m.email})
              </span>
              <button type="button" className="link-button" onClick={() => handleRemove(m.id)}>
                Rimuovi
              </button>
            </li>
          ))}
          {members.length === 0 && <li style={{ color: "var(--text-secondary)" }}>Nessun membro ancora</li>}
        </ul>
      )}

      <input
        placeholder="Aggiungi membro per email o nome..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {results.length > 0 && (
        <ul className="permissions-suggestions">
          {results.map((u) => (
            <li key={u.id}>
              <button type="button" onClick={() => handleAdd(u)}>
                {u.display_name} ({u.email})
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
