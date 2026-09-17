import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, clearTokens } from "../api/client";
import ProfilePage from "./ProfilePage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn(), clearTokens: vi.fn() }));

const mockApiFetch = vi.mocked(apiFetch);
const mockClearTokens = vi.mocked(clearTokens);

function jsonResponse(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response;
}

const PROFILE = { id: "user-1", email: "me@example.com", display_name: "Utente Test", avatar_url: null };

function renderPage() {
  return render(
    <MemoryRouter>
      <ProfilePage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockApiFetch.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path === "/api/me" && (!options || !options.method)) return jsonResponse(PROFILE);
    return jsonResponse({ status: "ok" });
  });
});

describe("ProfilePage - disattivazione account", () => {
  it("mostra il profilo caricato", async () => {
    renderPage();
    expect(await screen.findByText("Utente Test")).toBeInTheDocument();
    expect(screen.getByText("me@example.com")).toBeInTheDocument();
  });

  it("chiede conferma, poi chiama POST /me/deactivate e pulisce i token", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await screen.findByText("Utente Test");

    await user.click(screen.getByRole("button", { name: "Disattiva account" }));

    await waitFor(() => {
      const deactivateCall = mockApiFetch.mock.calls.find(
        ([path, options]) => path === "/api/me/deactivate" && (options as RequestInit)?.method === "POST",
      );
      expect(deactivateCall).toBeDefined();
    });
    expect(mockClearTokens).toHaveBeenCalled();
  });

  it("annullare la conferma non chiama l'API né pulisce i token", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await screen.findByText("Utente Test");

    await user.click(screen.getByRole("button", { name: "Disattiva account" }));

    const deactivateCall = mockApiFetch.mock.calls.find(([path]) => path === "/api/me/deactivate");
    expect(deactivateCall).toBeUndefined();
    expect(mockClearTokens).not.toHaveBeenCalled();
  });
});
