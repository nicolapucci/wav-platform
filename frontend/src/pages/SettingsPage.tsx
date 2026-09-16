import { useEffect, useState } from "react";

import { apiFetch } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";
import PermissionsPanel from "../components/PermissionsPanel";

type Organization = { id: string; name: string };

export default function SettingsPage() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState<string>("");
  const [loading, setLoading] = useState(true);

  async function loadOrganizations() {
    setLoading(true);
    const res = await apiFetch("/api/organizations");
    if (res.ok) {
      const orgs: Organization[] = await res.json();
      setOrganizations(orgs);
      setSelectedOrgId((current) => current || (orgs.length > 0 ? orgs[0].id : ""));
    }
    setLoading(false);
  }

  useEffect(() => {
    loadOrganizations();
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
    loadOrganizations();
  }

  return (
    <>
      <div className="page-header">
        <h1>
          Impostazioni
          <InfoTooltip text="Organizzazioni e permessi." />
        </h1>
      </div>

      <div className="toolbar">
        <button type="button" onClick={handleCreateOrganization}>
          + Organizzazione
        </button>
      </div>

      {loading && <p>Caricamento...</p>}
      {!loading && organizations.length === 0 && (
        <p style={{ color: "var(--text-secondary)" }}>Non fai ancora parte di nessuna organizzazione.</p>
      )}

      {organizations.length > 0 && (
        <>
          <div className="field" style={{ maxWidth: 280 }}>
            <label>Organizzazione</label>
            <select value={selectedOrgId} onChange={(e) => setSelectedOrgId(e.target.value)}>
              {organizations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </div>

          {selectedOrgId && (
            <PermissionsPanel resourceType="organization" resourceId={selectedOrgId} organizationId={selectedOrgId} />
          )}
        </>
      )}

      {/* TODO: invito via email (crea un utente "invitato" senza password + notifica,
          invece di poter assegnare un ruolo solo a chi si è già registrato);
          altre impostazioni (board kanban personalizzate, integrazioni, dati account). */}
    </>
  );
}
