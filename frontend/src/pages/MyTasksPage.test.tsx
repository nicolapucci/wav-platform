import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api/client";
import { realtimeSocket } from "../ws/socket";
import MyTasksPage from "./MyTasksPage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../ws/socket", () => ({
  realtimeSocket: { connect: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn(), onMessage: vi.fn(() => vi.fn()) },
}));

const mockApiFetch = vi.mocked(apiFetch);

function jsonResponse(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response;
}

const TASK = {
  id: "t-1",
  readable_id: "QA-1",
  title: "Task di esempio",
  layer_id: "layer-1",
  updated_at: "2026-01-01T10:00:00Z",
  project_id: "proj-1",
  project_name: "Progetto Uno",
  status_column_id: "col-1",
  column_name: "In corso",
  priority: 1,
  due_date: null,
  assignees: [],
  tags: [],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <MyTasksPage />
    </MemoryRouter>,
  );
}

describe("MyTasksPage - caricamento iniziale", () => {
  beforeEach(() => {
    mockApiFetch.mockResolvedValue(jsonResponse([TASK]));
  });

  it("carica e mostra le task in tabella", async () => {
    renderPage();

    expect(await screen.findByText("Task di esempio")).toBeInTheDocument();
    expect(screen.getByText("QA-1")).toBeInTheDocument();
    expect(screen.getByText("Progetto Uno")).toBeInTheDocument();
  });

  it("mostra un messaggio quando non ci sono task", async () => {
    mockApiFetch.mockResolvedValue(jsonResponse([]));
    renderPage();

    expect(await screen.findByText("Nessuna task trovata.")).toBeInTheDocument();
  });

  it("si iscrive al canale generico 'tasks' e si disiscrive allo smontaggio", async () => {
    const { unmount } = renderPage();
    await screen.findByText("Task di esempio");

    expect(realtimeSocket.subscribe).toHaveBeenCalledWith("tasks");
    unmount();
    expect(realtimeSocket.unsubscribe).toHaveBeenCalledWith("tasks");
  });
});

describe("MyTasksPage - ricerca con debounce", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    mockApiFetch.mockResolvedValue(jsonResponse([TASK]));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("aspetta 300ms dall'ultima digitazione prima di rifare la fetch con 'search'", async () => {
    renderPage();
    await vi.advanceTimersByTimeAsync(300); // fetch iniziale (search vuota)
    mockApiFetch.mockClear();

    const input = screen.getByPlaceholderText("Cerca per titolo...");
    fireEvent.change(input, { target: { value: "bug" } });
    await vi.advanceTimersByTimeAsync(100);
    expect(mockApiFetch).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(200); // completa i 300ms
    expect(mockApiFetch).toHaveBeenCalledWith("/api/me/tasks?search=bug");
  });
});

describe("MyTasksPage - aggiornamento realtime", () => {
  beforeEach(() => {
    mockApiFetch.mockResolvedValue(jsonResponse([TASK]));
  });

  it("ricarica quando arriva un evento task.created/updated/deleted", async () => {
    renderPage();
    await screen.findByText("Task di esempio");
    const callsBefore = mockApiFetch.mock.calls.length;

    const onMessageHandler = vi.mocked(realtimeSocket.onMessage).mock.calls[0][0];
    onMessageHandler({ type: "task.deleted", task_id: "t-1" });

    await waitFor(() => expect(mockApiFetch.mock.calls.length).toBe(callsBefore + 1));
  });
});
