import { describe, expect, it, vi } from "vitest";

import { apiFetch, clearTokens, getAccessToken, setTokens } from "./client";

describe("apiFetch", () => {
  it("attacca l'Authorization header quando c'è un access token", async () => {
    setTokens("access-1", "refresh-1");
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/tasks");

    const options = fetchMock.mock.calls[0][1] as RequestInit;
    expect((options.headers as Record<string, string>).Authorization).toBe("Bearer access-1");
  });

  it("non manda Authorization se non c'è un token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/tasks");

    const options = fetchMock.mock.calls[0][1] as RequestInit;
    expect((options.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("su 401 prova il refresh e ripete la richiesta originale con il nuovo token", async () => {
    setTokens("expired-access", "valid-refresh");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 401 })) // richiesta originale
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "new-access", refresh_token: "new-refresh" }), {
          status: 200,
        }),
      ) // POST /auth/refresh
      .mockResolvedValueOnce(new Response("{}", { status: 200 })); // richiesta originale ripetuta
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiFetch("/api/tasks");

    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe("/auth/refresh");
    const retryOptions = fetchMock.mock.calls[2][1] as RequestInit;
    expect((retryOptions.headers as Record<string, string>).Authorization).toBe("Bearer new-access");
    expect(getAccessToken()).toBe("new-access");
  });

  it("su 401 con refresh fallito pulisce i token e ritorna la risposta 401 originale, senza ritentare", async () => {
    setTokens("expired-access", "expired-refresh");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockResolvedValueOnce(new Response("{}", { status: 401 })); // anche il refresh fallisce
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiFetch("/api/tasks");

    expect(res.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getAccessToken()).toBeNull();
  });

  it("senza refresh token salvato non tenta nemmeno /auth/refresh su un 401", async () => {
    clearTokens();
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/tasks");

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
