import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api/client";
import ProjectsPage from "./ProjectsPage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));

const mockApiFetch = vi.mocked(apiFetch);

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 400) {
  return { ok, status, json: async () => body } as Response;
}

const ORG = { id: "org-1", name: "Org Uno" };
const PROJECT = { id: "proj-1", name: "Progetto Uno", description: null, prefix: "QATT" };

function setupApiFetch(overrides: Record<string, unknown> = {}) {
  mockApiFetch.mockImplementation(async (path: string) => {
    if (path === "/api/organizations") return jsonResponse(overrides.organizations ?? [ORG]);
    if (path.startsWith("/api/projects?organization_id=")) return jsonResponse(overrides.projects ?? [PROJECT]);
    return jsonResponse({}, true);
  });
}

beforeEach(() => {
  setupApiFetch();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <ProjectsPage />
    </MemoryRouter>,
  );
}

describe("ProjectsPage - eliminazione organizzazione", () => {
  it("chiede conferma e chiama DELETE /organizations/{id}", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await screen.findByText("Org Uno");

    await user.click(screen.getByRole("button", { name: "Elimina organizzazione" }));

    await waitFor(() => {
      const deleteCall = mockApiFetch.mock.calls.find(
        ([path, options]) => path === "/api/organizations/org-1" && (options as RequestInit)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
    });
  });

  it("annullare la conferma non chiama DELETE", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await screen.findByText("Org Uno");

    await user.click(screen.getByRole("button", { name: "Elimina organizzazione" }));

    const deleteCall = mockApiFetch.mock.calls.find(
      ([path, options]) => path === "/api/organizations/org-1" && (options as RequestInit)?.method === "DELETE",
    );
    expect(deleteCall).toBeUndefined();
  });
});

describe("ProjectsPage - eliminazione progetto", () => {
  it("chiede conferma e chiama DELETE /projects/{id}", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await screen.findByText("Progetto Uno");

    await user.click(screen.getByRole("button", { name: "Elimina" }));

    await waitFor(() => {
      const deleteCall = mockApiFetch.mock.calls.find(
        ([path, options]) => path === "/api/projects/proj-1" && (options as RequestInit)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
    });
  });
});
