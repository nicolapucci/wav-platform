import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch, clearTokens } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";

type Profile = {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
};

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    apiFetch("/api/me").then(async (res) => {
      if (res.ok) setProfile(await res.json());
    });
  }, []);

  async function handleDeactivate() {
    if (
      !window.confirm(
        "Disattivare il tuo account? Non potrai più accedere. L'azione non è annullabile da qui.",
      )
    ) {
      return;
    }
    const res = await apiFetch("/api/me/deactivate", { method: "POST" });
    if (!res.ok) {
      window.alert("Impossibile disattivare l'account.");
      return;
    }
    clearTokens();
    navigate("/login");
  }

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

      {profile && (
        <div style={{ marginTop: 28 }}>
          <button type="button" className="link-button" onClick={handleDeactivate}>
            Disattiva account
          </button>
        </div>
      )}
    </>
  );
}
