import { useEffect, useState } from "react";

import { apiFetch } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";

type Profile = {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
};

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);

  useEffect(() => {
    apiFetch("/api/me").then(async (res) => {
      if (res.ok) setProfile(await res.json());
    });
  }, []);

  return (
    <>
      <div className="page-header">
        <h1>
          Profilo
          <InfoTooltip text="Le tue informazioni account." />
        </h1>
      </div>

      {!profile && <p>Caricamento...</p>}

      {profile && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div>
            <strong>Nome</strong>
            <p style={{ margin: "2px 0", color: "var(--text-secondary)" }}>{profile.display_name}</p>
          </div>
          <div>
            <strong>Email</strong>
            <p style={{ margin: "2px 0", color: "var(--text-secondary)" }}>{profile.email}</p>
          </div>
        </div>
      )}

      {/* TODO: modifica nome/avatar, cambio password, provider OAuth collegati */}
    </>
  );
}
