import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { setTokens } from "../api/client";

type Mode = "login" | "register";

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const endpoint = mode === "login" ? "/auth/login" : "/auth/register";
    const body = mode === "login" ? { email, password } : { email, password, display_name: displayName };

    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      if (res.status === 409) {
        setError("Esiste già un utente con questa email");
      } else if (res.status === 401) {
        setError("Credenziali non valide");
      } else {
        setError("Si è verificato un errore, riprova");
      }
      return;
    }

    const data = await res.json();
    setTokens(data.access_token, data.refresh_token);
    navigate("/");
  }

  function toggleMode() {
    setError(null);
    setMode((m) => (m === "login" ? "register" : "login"));
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">WAV</div>
        <h1>{mode === "login" ? "Accedi al tuo spazio" : "Crea un account"}</h1>

        <form onSubmit={handleSubmit}>
          {mode === "register" && (
            <div className="field">
              <label>Nome visualizzato</label>
              <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} type="text" required />
            </div>
          )}

          <div className="field">
            <label>Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
          </div>

          <div className="field">
            <label>Password</label>
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              required
              minLength={8}
            />
          </div>

          {error && <p className="auth-error">{error}</p>}

          <button type="submit" className="btn-primary">
            {mode === "login" ? "Accedi" : "Registrati"}
          </button>
        </form>

        <p className="auth-switch">
          {mode === "login" ? "Non hai un account? " : "Hai già un account? "}
          <button type="button" onClick={toggleMode} className="link-button">
            {mode === "login" ? "Registrati" : "Accedi"}
          </button>
        </p>

        {/* TODO: bottoni "Accedi con Google/GitHub" -> redirect a /auth/oauth/{provider}/login */}
      </div>
    </div>
  );
}
