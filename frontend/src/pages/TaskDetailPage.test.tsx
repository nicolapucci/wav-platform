import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api/client";
import { realtimeSocket } from "../ws/socket";
import TaskDetailPage from "./TaskDetailPage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../ws/socket", () => ({
  realtimeSocket: { connect: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn(), onMessage: vi.fn(() => vi.fn()) },
}));

const mockApiFetch = vi.mocked(apiFetch);

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 400) {
  return { ok, status, json: async () => body } as Response;
}

function makeTask(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "uuid-task-1",
    readable_id: "QA-1",
    layer_id: "layer-1",
    project_id: "proj-1",
    title: "Titolo originale",
    description: "Una descrizione",
    priority: 1,
    due_date: null,
    created_by: "user-1",
    status_column_id: "col-1",
    viewer_role: "editor",
    ...overrides,
  };
}

function setupApiFetch(overrides: Record<string, unknown> = {}) {
  const task = (overrides.task as ReturnType<typeof makeTask>) ?? makeTask();
  mockApiFetch.mockImplementation(async (path: string) => {
    if (path === "/api/tasks/QA-1") return jsonResponse(task, overrides.taskOk !== false);
    if (path === "/api/tasks/QA-1/assignees") return jsonResponse(overrides.assignees ?? []);
    if (path === "/api/tasks/QA-1/dependencies") return jsonResponse(overrides.dependencies ?? { blocked_by: [], blocks: [] });
    if (path === "/api/comments?task_id=QA-1") return jsonResponse(overrides.comments ?? []);
    if (path === "/api/tasks/QA-1/tags") return jsonResponse(overrides.taskTags ?? []);
    if (path === "/api/projects/proj-1") return jsonResponse({ organization_id: "org-1" });
    if (path === "/api/projects/proj-1/columns")
      return jsonResponse(overrides.columns ?? [{ id: "col-1", name: "Da fare", position: 0 }]);
    if (path === "/api/tags?project_id=proj-1") return jsonResponse(overrides.projectTags ?? []);
    if (path.startsWith("/api/teams?")) return jsonResponse(overrides.teams ?? []);
    if (path.startsWith("/api/users/search")) return jsonResponse(overrides.userSearch ?? []);
    return jsonResponse({}, true);
  });
}

beforeEach(() => {
  setupApiFetch();
});

function renderPage(initialPath = "/tasks/QA-1") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TaskDetailPage - caricamento", () => {
  it("carica e mostra i campi della task", async () => {
    renderPage();

    expect(await screen.findByDisplayValue("Titolo originale")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Una descrizione")).toBeInTheDocument();
    expect(screen.getByText("QA-1")).toBeInTheDocument();
  });

  it("mostra un messaggio se la task non esiste o non è visibile", async () => {
    setupApiFetch({ taskOk: false });
    renderPage();

    expect(await screen.findByText("Task non trovata, oppure non hai i permessi per vederla.")).toBeInTheDocument();
  });

  it("si iscrive al canale specifico evt:task:{uuid interno}, non all'id leggibile della route", async () => {
    renderPage();
    await screen.findByDisplayValue("Titolo originale");

    // regressione: deve usare task.id (lo UUID), non taskId dalla route (QA-1,
    // l'id leggibile) - bug corretto in questa sessione.
    expect(realtimeSocket.subscribe).toHaveBeenCalledWith("task", "uuid-task-1");
    expect(realtimeSocket.subscribe).not.toHaveBeenCalledWith("task", "QA-1");
  });
});

describe("TaskDetailPage - permessi (canEdit)", () => {
  it("con ruolo editor i campi sono modificabili e compare 'Salva'", async () => {
    renderPage();
    await screen.findByDisplayValue("Titolo originale");

    expect(screen.getByDisplayValue("Titolo originale")).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Salva" })).toBeInTheDocument();
  });

  it("con ruolo reader i campi sono disabilitati e 'Salva' non compare", async () => {
    setupApiFetch({ task: makeTask({ viewer_role: "reader" }) });
    renderPage();
    await screen.findByDisplayValue("Titolo originale");

    expect(screen.getByDisplayValue("Titolo originale")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Salva" })).not.toBeInTheDocument();
  });
});

describe("TaskDetailPage - salvataggio", () => {
  it("Salva fa la PATCH con i campi correnti del form", async () => {
    const user = userEvent.setup();
    renderPage();
    const titleInput = await screen.findByDisplayValue("Titolo originale");

    await user.clear(titleInput);
    await user.type(titleInput, "Titolo modificato");
    await user.click(screen.getByRole("button", { name: "Salva" }));

    await waitFor(() => {
      const patchCall = mockApiFetch.mock.calls.find(
        ([path, options]) => path === "/api/tasks/QA-1" && (options as RequestInit)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
      const body = JSON.parse((patchCall![1] as RequestInit).body as string);
      expect(body.title).toBe("Titolo modificato");
    });
  });
});

describe("TaskDetailPage - commenti", () => {
  it("invia un commento e pulisce il campo dopo l'invio", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByDisplayValue("Titolo originale");

    const textarea = screen.getByPlaceholderText("Scrivi un commento... digita @ per menzionare qualcuno");
    await user.type(textarea, "Un commento di prova");
    await user.click(screen.getByRole("button", { name: "Invia" }));

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(([path]) => path === "/api/comments");
      expect(postCall).toBeDefined();
      const body = JSON.parse((postCall![1] as RequestInit).body as string);
      expect(body).toMatchObject({ task_id: "QA-1", body: "Un commento di prova" });
    });

    // l'invio innesca loadAll(), che rimonta il form mentre ricarica (loading=true
    // fa tornare "Caricamento...") - va ri-interrogato il DOM live, non riusato
    // il riferimento al textarea precedente, ormai smontato.
    await waitFor(() => expect(screen.getByPlaceholderText(/Scrivi un commento/)).toHaveValue(""));
  });
});
