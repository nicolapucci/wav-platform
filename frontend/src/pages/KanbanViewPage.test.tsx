import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api/client";
import { realtimeSocket } from "../ws/socket";
import KanbanViewPage from "./KanbanViewPage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../ws/socket", () => ({
  realtimeSocket: { connect: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn(), onMessage: vi.fn(() => vi.fn()) },
}));

const mockApiFetch = vi.mocked(apiFetch);

function jsonResponse(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response;
}

const ORG = { id: "org-1", name: "Org", slug: "org" };
const BOARD = {
  projects: [
    {
      id: "proj-1",
      name: "Progetto Uno",
      columns: [{ id: "col-1", name: "Da fare", position: 0 }],
      tasks: [{ id: "t-1", readable_id: "QA-1", title: "Prima task", column_id: "col-1", priority: 0 }],
    },
  ],
};
const ME = { id: "user-1", email: "me@example.com", display_name: "Io Stesso" };

/** Instrada le chiamate ad apiFetch usate da KanbanViewPage in base al path,
 * ignorando la query string dove non rilevante per il singolo test. */
function setupApiFetch(overrides: Record<string, unknown> = {}) {
  mockApiFetch.mockImplementation(async (path: string) => {
    if (path === "/api/organizations") return jsonResponse(overrides.organizations ?? [ORG]);
    if (path.startsWith("/api/projects?")) return jsonResponse(overrides.projects ?? []);
    if (path.startsWith("/api/teams?")) return jsonResponse(overrides.teams ?? []);
    if (path === "/api/me") return jsonResponse(overrides.me ?? ME);
    if (path.startsWith("/api/me/tasks/board")) return jsonResponse(overrides.board ?? BOARD);
    return jsonResponse({}, false);
  });
}

beforeEach(() => {
  setupApiFetch();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <KanbanViewPage />
    </MemoryRouter>,
  );
}

describe("KanbanViewPage - caricamento iniziale", () => {
  it("carica la board (nessun filtro) e mostra le task per progetto", async () => {
    renderPage();

    expect(await screen.findByText("Prima task")).toBeInTheDocument();
    expect(screen.getByText("Progetto Uno")).toBeInTheDocument();

    const boardCall = mockApiFetch.mock.calls.find(([path]) => (path as string).startsWith("/api/me/tasks/board"));
    expect(boardCall?.[0]).toBe("/api/me/tasks/board"); // nessuna query string senza filtri attivi
  });

  it("si iscrive al canale generico 'tasks' e si disiscrive allo smontaggio", async () => {
    const { unmount } = renderPage();
    await screen.findByText("Prima task");

    expect(realtimeSocket.connect).toHaveBeenCalled();
    expect(realtimeSocket.subscribe).toHaveBeenCalledWith("tasks");

    unmount();
    expect(realtimeSocket.unsubscribe).toHaveBeenCalledWith("tasks");
  });

  it("mostra un messaggio quando nessuna task corrisponde al filtro", async () => {
    setupApiFetch({ board: { projects: [] } });
    renderPage();

    expect(await screen.findByText("Nessuna task trovata per questo filtro.")).toBeInTheDocument();
  });
});

describe("KanbanViewPage - filtro 'Assegnate a me'", () => {
  it("dopo aver caricato l'utente corrente, il toggle aggiunge se stesso come assignee_ids", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Prima task");

    await user.click(screen.getByRole("button", { name: "Assegnate a me" }));

    await waitFor(() => {
      const lastBoardCall = mockApiFetch.mock.calls
        .filter(([path]) => (path as string).startsWith("/api/me/tasks/board"))
        .at(-1);
      expect(lastBoardCall?.[0]).toBe(`/api/me/tasks/board?assignee_ids=${ME.id}`);
    });
  });
});

describe("KanbanViewPage - aggiornamento realtime", () => {
  it("ricarica la board quando arriva un evento task.updated sul canale sottoscritto", async () => {
    renderPage();
    await screen.findByText("Prima task");

    const callsBefore = mockApiFetch.mock.calls.filter(([p]) => (p as string).startsWith("/api/me/tasks/board")).length;

    const onMessageHandler = vi.mocked(realtimeSocket.onMessage).mock.calls[0][0];
    onMessageHandler({ type: "task.updated", task_id: "t-1" });

    await waitFor(() => {
      const callsAfter = mockApiFetch.mock.calls.filter(([p]) => (p as string).startsWith("/api/me/tasks/board")).length;
      expect(callsAfter).toBe(callsBefore + 1);
    });
  });
});
