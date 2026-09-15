import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../api/client";

type Organization = { id: string; name: string };
type Project = { id: string; name: string; description: string | null; prefix: string };

// Lunghezza fissa dei prefissi progetto (stessa costante lato server, vedi
// PROJECT_PREFIX_LENGTH in projects.py): tutti gli id leggibili delle task
// (<PREFISSO>-<numero>) hanno quindi un prefisso della stessa lunghezza.
const PROJECT_PREFIX_LENGTH = 4;

function suggestPrefix(name: string): string {
  const letters = name.toUpperCase().replace(/[^A-Z]/g, "");
  return (letters + "XXXX").slice(0, PROJECT_PREFIX_LENGTH);
}

export default function ProjectsPage() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [projectsByOrg, setProjectsByOrg] = useState<Record<string, Project[]>>({});
  const [loading, setLoading] = useState(true);

  async function loadAll() {
    setLoading(true);
    const orgRes = await apiFetch("/api/organizations");
    const orgs: Organization[] = orgRes.ok ? await orgRes.json() : [];
    setOrganizations(orgs);

    const entries = await Promise.all(
      orgs.map(async (org) => {
        const res = await apiFetch(`/api/projects?organization_id=${org.id}`);
        return [org.id, res.ok ? await res.json() : []] as const;
      }),
    );
    setProjectsByOrg(Object.fromEntries(entries));
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function handleCreateOrganization() {
    const name = window.prompt("Nome della nuova organizzazione?");
    if (!name) return;
    const slug = name
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "");

    await apiFetch("/api/organizations", {
      method: "POST",
      body: JSON.stringify({ name, slug }),
    });
    loadAll();
  }

  async function handleCreateProject(organizationId: string) {
    const name = window.prompt("Nome del nuovo progetto?");
    if (!name) return;

    // Il prefisso identifica le task del progetto negli id leggibili
    // (<PREFISSO>-<numero>, es. "QA-1"): si può modificare solo qui, in fase di
    // creazione, non è più editabile dopo (cambierebbe l'id di ogni task esistente).
    const suggested = suggestPrefix(name);
    const prefixInput = window.prompt(
      `Prefisso del progetto per gli id delle task (es. "${suggested}-1"). ` +
        `Esattamente ${PROJECT_PREFIX_LENGTH} lettere maiuscole, non modificabile dopo la creazione.`,
      suggested,
    );
    if (!prefixInput) return;
    const prefix = prefixInput.trim().toUpperCase();
    if (!/^[A-Z]+$/.test(prefix) || prefix.length !== PROJECT_PREFIX_LENGTH) {
      window.alert(`Il prefisso deve essere di esattamente ${PROJECT_PREFIX_LENGTH} lettere maiuscole.`);
      return;
    }

    const res = await apiFetch("/api/projects", {
      method: "POST",
      body: JSON.stringify({ organization_id: organizationId, name, prefix }),
    });
    if (res.status === 409) {
      window.alert(`Il prefisso "${prefix}" è già usato da un altro progetto: riprova con uno diverso.`);
      return;
    }
    if (!res.ok) {
      window.alert("Impossibile creare il progetto.");
      return;
    }
    loadAll();
  }

  return (
    <>
      <div className="page-header">
        <h1>Progetti</h1>
        <p>Organizzati per organizzazione.</p>
      </div>

      <div className="toolbar">
        <button type="button" onClick={handleCreateOrganization}>
          + Organizzazione
        </button>
      </div>

      {loading && <p>Caricamento...</p>}
      {!loading && organizations.length === 0 && (
        <p style={{ color: "var(--text-secondary)" }}>
          Non fai ancora parte di nessuna organizzazione: creane una per iniziare a creare progetti.
        </p>
      )}

      {organizations.map((org) => (
        <section key={org.id} style={{ marginBottom: 28 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ fontSize: 15, margin: "0 0 8px" }}>{org.name}</h2>
            <button type="button" onClick={() => handleCreateProject(org.id)}>
              Nuovo progetto
            </button>
          </div>
          <ul>
            {(projectsByOrg[org.id] || []).map((project) => (
              <li key={project.id}>
                <Link to={`/projects/${project.id}`}>
                  <span className="task-table-id">{project.prefix}</span> {project.name}
                </Link>
              </li>
            ))}
            {(projectsByOrg[org.id] || []).length === 0 && (
              <li style={{ color: "var(--text-secondary)" }}>Nessun progetto</li>
            )}
          </ul>
        </section>
      ))}

      {/* TODO: click su un progetto -> pagina di dettaglio con l'albero dei layer */}
    </>
  );
}
