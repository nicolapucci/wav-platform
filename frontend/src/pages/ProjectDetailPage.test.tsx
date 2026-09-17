import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api/client";
import { realtimeSocket } from "../ws/socket";
import ProjectDetailPage from "./ProjectDetailPage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../ws/socket", () => ({
  realtimeSocket: { connect: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn(), onMessage: vi.fn(() => vi.fn()) },
}));
// Isola ProjectDetailPage dai suoi 4 sotto-componenti: qui interessa solo
// l'orchestrazione della pagina (caricamento, albero layer, tab, realtime),
// non la loro logica interna (già fuori dall'ambito di questi test).
vi.mock("../components/BoardManager", () => ({ default: () => <div data-testid="board-manager" /> }));
vi.mock("../components/ColumnManager", () => ({ default: () => <div data-testid="column-manager" /> }));
vi.mock("../components/TagManager", () => ({ default: () => <div data-testid="tag-manager" /> }));
vi.mock("../components/PermissionsPanel", () => ({ default: () => <div data-testid="permissions-panel" /> }));

const mockApiFetch = vi.mocked(apiFetch);

function jsonResponse(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response;
}

const PROJECT = { id: "proj-1", organization_id: "org-1", name: "Progetto Uno", description: null, prefix: "QA" };
const ROOT_LAYER = { id: "layer-root", parent_layer_id: null, name: "Layer radice", description: null };
const CHILD_LAYER = { id: "layer-child", parent_layer_id: "layer-root", name: "Sotto-layer", description: null };

function setupApiFetch(overrides: Record<string, unknown> = {}) {
  const layers = (overrides.layers as unknown[]) ?? [ROOT_LAYER, CHILD_LAYER];
  mockApiFetch.mockImplementation(async (path: string) => {
    if (path === "/api/projects/proj-1") return jsonResponse(overrides.project ?? PROJECT);
    if (path === "/api/projects/proj-1/columns")
      return jsonResponse(overrides.columns ?? [{ id: "col-1", name: "Da fare", position: 0 }]);
    if (path === "/api/tags?project_id=proj-1") return jsonResponse(overrides.tags ?? []);
    if (path === "/api/layers?project_id=proj-1") return jsonResponse(layers);
    if (path === "/api/tasks?layer_id=layer-root")
      return jsonResponse(
        overrides.rootTasks ?? [
          { id: "t-1", readable_id: "QA-1", title: "Task nel layer radice", status_column_id: "col-1", priority: 0 },
        ],
      );
    if (path === "/api/tasks?layer_id=layer-child") return jsonResponse(overrides.childTasks ?? []);
    return jsonResponse({}, true);
  });
}

beforeEach(() => {
  setupApiFetch();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/proj-1"]}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProjectDetailPage - caricamento e albero layer", () => {
  it("carica il progetto e mostra l'albero dei layer con le rispettive task", async () => {
    renderPage();

    expect(await screen.findByText("Layer radice")).toBeInTheDocument();
    expect(screen.getByText("Sotto-layer")).toBeInTheDocument();
    expect(screen.getByText("Task nel layer radice")).toBeInTheDocument();
    expect(screen.getByText("Nessuna task in questo layer.")).toBeInTheDocument(); // il sotto-layer è vuoto
  });

  it("mostra un messaggio quando non ci sono layer", async () => {
    setupApiFetch({ layers: [] });
    renderPage();

    expect(await screen.findByText("Nessun layer ancora.")).toBeInTheDocument();
  });

  it("si iscrive al canale generico 'tasks' e si disiscrive allo smontaggio", async () => {
    const { unmount } = renderPage();
    await screen.findByText("Layer radice");

    expect(realtimeSocket.subscribe).toHaveBeenCalledWith("tasks");
    unmount();
    expect(realtimeSocket.unsubscribe).toHaveBeenCalledWith("tasks");
  });

  it("ricarica quando arriva un evento realtime su una task", async () => {
    renderPage();
    await screen.findByText("Layer radice");
    const callsBefore = mockApiFetch.mock.calls.length;

    const onMessageHandler = vi.mocked(realtimeSocket.onMessage).mock.calls[0][0];
    onMessageHandler({ type: "task.created", task_id: "t-2" });

    await waitFor(() => expect(mockApiFetch.mock.calls.length).toBeGreaterThan(callsBefore));
  });
});

describe("ProjectDetailPage - tab Struttura / Dashboard", () => {
  it("passa alla dashboard (BoardManager) quando si clicca la tab", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Layer radice");

    await user.click(screen.getByRole("button", { name: "Dashboard" }));

    expect(screen.getByTestId("board-manager")).toBeInTheDocument();
    expect(screen.queryByText("Layer radice")).not.toBeInTheDocument();
  });
});

describe("ProjectDetailPage - creazione layer", () => {
  it("+ Layer chiede il nome via prompt e POSTa il nuovo layer radice", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "prompt").mockReturnValue("Nuovo Layer");
    renderPage();
    await screen.findByText("Layer radice");

    await user.click(screen.getByRole("button", { name: "+ Layer" }));

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([path, options]) => path === "/api/layers" && (options as RequestInit)?.method === "POST",
      );
      expect(postCall).toBeDefined();
      const body = JSON.parse((postCall![1] as RequestInit).body as string);
      expect(body).toEqual({ project_id: "proj-1", parent_layer_id: null, name: "Nuovo Layer" });
    });
  });

  it("annullare il prompt non fa nessuna richiesta", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "prompt").mockReturnValue(null);
    renderPage();
    await screen.findByText("Layer radice");
    const callsBefore = mockApiFetch.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "+ Layer" }));

    expect(mockApiFetch.mock.calls.length).toBe(callsBefore);
  });
});

describe("ProjectDetailPage - pannelli a comparsa", () => {
  it("i pulsanti toolbar mostrano/nascondono i rispettivi pannelli", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Layer radice");

    expect(screen.queryByTestId("column-manager")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Gestisci colonne kanban" }));
    expect(screen.getByTestId("column-manager")).toBeInTheDocument();

    expect(screen.queryByTestId("tag-manager")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Gestisci tag" }));
    expect(screen.getByTestId("tag-manager")).toBeInTheDocument();

    expect(screen.queryByTestId("permissions-panel")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Permessi progetto" }));
    expect(screen.getByTestId("permissions-panel")).toBeInTheDocument();
  });
});

describe("ProjectDetailPage - eliminazione", () => {
  it("Elimina su un layer chiede conferma e chiama DELETE /layers/{id}", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await screen.findByText("Layer radice");

    // .layer-node del layer radice contiene anche l'intero sotto-albero (il
    // .layer-node del figlio, con il SUO "Elimina"): serve scoparsi al solo
    // .layer-node-header, che ha solo i pulsanti di QUESTO layer.
    const layerHeader = screen.getByText("Layer radice").closest(".layer-node-header")!;
    await user.click(within(layerHeader).getByRole("button", { name: "Elimina" }));

    await waitFor(() => {
      const deleteCall = mockApiFetch.mock.calls.find(
        ([path, options]) => path === "/api/layers/layer-root" && (options as RequestInit)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
    });
  });

  it("annullare la conferma non chiama DELETE sul layer", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await screen.findByText("Layer radice");

    const layerHeader = screen.getByText("Layer radice").closest(".layer-node-header")!;
    await user.click(within(layerHeader).getByRole("button", { name: "Elimina" }));

    const deleteCall = mockApiFetch.mock.calls.find(
      ([path, options]) => path === "/api/layers/layer-root" && (options as RequestInit)?.method === "DELETE",
    );
    expect(deleteCall).toBeUndefined();
  });

  it("Elimina progetto chiede conferma e chiama DELETE /projects/{id}", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await screen.findByText("Layer radice");

    await user.click(screen.getByRole("button", { name: "Elimina progetto" }));

    await waitFor(() => {
      const deleteCall = mockApiFetch.mock.calls.find(
        ([path, options]) => path === "/api/projects/proj-1" && (options as RequestInit)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
    });
  });
});
