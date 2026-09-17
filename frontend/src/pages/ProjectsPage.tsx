import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { apiFetch } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";

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

// Chiede nome e prefisso per un nuovo progetto (normale o demo): il prefisso è
// precompilato a partire dal nome ma resta modificabile solo qui, in fase di
// creazione (vedi il commento su ProjectCreate.prefix lato server per il perché).
// Ritorna null se l'utente annulla o il prefisso non è valido.
function promptForNameAndPrefix(namePrompt: string, defaultName?: string): { name: string; prefix: string } | null {
  const name = window.prompt(namePrompt, defaultName);
  if (!name) return null;

  const suggested = suggestPrefix(name);
  const prefixInput = window.prompt(
    `Prefisso del progetto per gli id delle task (es. "${suggested}-1"). ` +
      `Esattamente ${PROJECT_PREFIX_LENGTH} lettere maiuscole, non modificabile dopo la creazione.`,
    suggested,
  );
  if (!prefixInput) return null;

  const prefix = prefixInput.trim().toUpperCase();
  if (!/^[A-Z]+$/.test(prefix) || prefix.length !== PROJECT_PREFIX_LENGTH) {
    window.alert(`Il prefisso deve essere di esattamente ${PROJECT_PREFIX_LENGTH} lettere maiuscole.`);
    return null;
  }
  return { name, prefix };
}

export default function ProjectsPage() {
  const navigate = useNavigate();
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
    const picked = promptForNameAndPrefix("Nome del nuovo progetto?");
    if (!picked) return;

    const res = await apiFetch("/api/projects", {
      method: "POST",
      body: JSON.stringify({ organization_id: organizationId, name: picked.name, prefix: picked.prefix }),
    });
    if (res.status === 409) {
      window.alert(`Il prefisso "${picked.prefix}" è già usato da un altro progetto: riprova con uno diverso.`);
      return;
    }
    if (!res.ok) {
      window.alert("Impossibile creare il progetto.");
      return;
    }
    loadAll();
  }

  // progetto demo: stessa creazione, ma il server lo popola subito con layer,
  // task, tag, dipendenze e un commento (vedi projects.py::create_demo_project)
  // - comodo per non dover preparare a mano dei dati prima di una demo. Ci si
  // salta dentro direttamente appena creato.
  async function handleCreateDemoProject(organizationId: string) {
    const picked = promptForNameAndPrefix("Nome del progetto demo?", "Progetto Demo");
    if (!picked) return;

    const res = await apiFetch("/api/projects/demo", {
      method: "POST",
      body: JSON.stringify({ organization_id: organizationId, name: picked.name, prefix: picked.prefix }),
    });
    if (res.status === 409) {
      window.alert(`Il prefisso "${picked.prefix}" è già usato da un altro progetto: riprova con uno diverso.`);
      return;
    }
    if (!res.ok) {
      window.alert("Impossibile creare il progetto demo.");
      return;
    }
    const project = await res.json();
    navigate(`/projects/${project.id}`);
  }

  async function handleDeleteOrganization(organizationId: string, name: string) {
    if (
      !window.confirm(`Eliminare l'organizzazione "${name}"? Tutti i suoi progetti, layer e task verranno eliminati.`)
    ) {
      return;
    }
    const res = await apiFetch(`/api/organizations/${organizationId}`, { method: "DELETE" });
    if (!res.ok) {
      window.alert("Permessi insufficienti per eliminare questa organizzazione.");
      return;
    }
    loadAll();
  }

  async function handleDeleteProject(projectId: string, name: string) {
    if (!window.confirm(`Eliminare il progetto "${name}"? Tutti i suoi layer e task verranno eliminati.`)) return;
    const res = await apiFetch(`/api/projects/${projectId}`, { method: "DELETE" });
    if (!res.ok) {
      window.alert("Permessi insufficienti per eliminare questo progetto.");
      return;
    }
    loadAll();
  }

  return (
    <>
      <div className="page-header">
        <h1>
          Progetti
          <InfoTooltip text="Organizzati per organizzazione." />
        </h1>
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
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" onClick={() => handleCreateProject(org.id)}>
                Nuovo progetto
              </button>
              <button type="button" onClick={() => handleCreateDemoProject(org.id)}>
                + Progetto demo
              </button>
              <button type="button" className="link-button" onClick={() => handleDeleteOrganization(org.id, org.name)}>
                Elimina organizzazione
              </button>
            </div>
          </div>
          <ul>
            {(projectsByOrg[org.id] || []).map((project) => (
              <li key={project.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Link to={`/projects/${project.id}`}>
                  <span className="task-table-id">{project.prefix}</span> {project.name}
                </Link>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => handleDeleteProject(project.id, project.name)}
                >
                  Elimina
                </button>
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
