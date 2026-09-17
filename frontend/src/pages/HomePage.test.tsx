import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api/client";
import type { NotificationItem } from "../context/NotificationsContext";
import { useNotifications } from "../context/NotificationsContext";
import { realtimeSocket } from "../ws/socket";
import HomePage from "./HomePage";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../ws/socket", () => ({
  realtimeSocket: { connect: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn(), onMessage: vi.fn(() => vi.fn()) },
}));
vi.mock("../context/NotificationsContext", () => ({ useNotifications: vi.fn() }));

const mockApiFetch = vi.mocked(apiFetch);
const mockUseNotifications = vi.mocked(useNotifications);

function jsonResponse(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response;
}

const TASK = {
  id: "t-1",
  readable_id: "QA-7",
  title: "Task assegnata",
  project_id: "proj-1",
  project_name: "Progetto Uno",
  column_name: "In corso",
  priority: 2,
  due_date: null,
};

function notification(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: "n-1",
    type: "mention",
    entity_type: "comment",
    entity_id: "c-1",
    payload: { task_id: "t-1", comment_excerpt: "ciao @Utente" },
    read_at: null,
    created_at: "2026-01-01T10:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockApiFetch.mockResolvedValue(jsonResponse([TASK]));
  mockUseNotifications.mockReturnValue({
    notifications: [notification()],
    unreadCount: 1,
    loading: false,
    markAsRead: vi.fn(),
    markAllAsRead: vi.fn(),
  });
});

describe("HomePage - task assegnate", () => {
  it("carica e mostra le task assegnate non completate", async () => {
    renderPage();

    expect(await screen.findByText("Task assegnata")).toBeInTheDocument();
    expect(screen.getByText("QA-7")).toBeInTheDocument();
    expect(screen.getByText("Progetto Uno")).toBeInTheDocument();
    expect(mockApiFetch).toHaveBeenCalledWith("/api/me/tasks/assigned");
  });

  it("mostra un messaggio quando non ci sono task assegnate", async () => {
    mockApiFetch.mockResolvedValue(jsonResponse([]));
    renderPage();

    expect(await screen.findByText("Nessuna task assegnata da completare.")).toBeInTheDocument();
  });

  it("si iscrive al canale generico 'tasks' e si disiscrive allo smontaggio", async () => {
    const { unmount } = renderPage();
    await screen.findByText("Task assegnata");

    expect(realtimeSocket.subscribe).toHaveBeenCalledWith("tasks");
    unmount();
    expect(realtimeSocket.unsubscribe).toHaveBeenCalledWith("tasks");
  });

  it("ricarica le task quando arriva un evento realtime", async () => {
    renderPage();
    await screen.findByText("Task assegnata");
    const callsBefore = mockApiFetch.mock.calls.length;

    const onMessageHandler = vi.mocked(realtimeSocket.onMessage).mock.calls[0][0];
    onMessageHandler({ type: "task.updated", task_id: "t-1" });

    await waitFor(() => expect(mockApiFetch.mock.calls.length).toBe(callsBefore + 1));
  });
});

describe("HomePage - notifiche e menzioni", () => {
  it("mostra la menzione con etichetta e testo corretti", async () => {
    renderPage();
    await screen.findByText("Task assegnata");

    expect(screen.getByText("Menzione")).toBeInTheDocument();
    expect(screen.getByText(/Sei stato menzionato in un commento/)).toBeInTheDocument();
  });

  it("click su una notifica non letta chiama markAsRead", async () => {
    const user = userEvent.setup();
    const markAsRead = vi.fn();
    mockUseNotifications.mockReturnValue({
      notifications: [notification({ read_at: null })],
      unreadCount: 1,
      loading: false,
      markAsRead,
      markAllAsRead: vi.fn(),
    });
    renderPage();
    await screen.findByText("Task assegnata");

    await user.click(screen.getByText(/Sei stato menzionato/));

    expect(markAsRead).toHaveBeenCalledWith("n-1");
  });

  it("non mostra il link 'Vedi tutte' se le notifiche stanno tutte nell'estratto", async () => {
    renderPage();
    await screen.findByText("Task assegnata");

    expect(screen.queryByText("Vedi tutte le notifiche")).not.toBeInTheDocument();
  });

  it("mostra il link 'Vedi tutte' oltre il limite dell'estratto", async () => {
    mockUseNotifications.mockReturnValue({
      notifications: Array.from({ length: 9 }, (_, i) => notification({ id: `n-${i}` })),
      unreadCount: 9,
      loading: false,
      markAsRead: vi.fn(),
      markAllAsRead: vi.fn(),
    });
    renderPage();
    await screen.findByText("Task assegnata");

    expect(screen.getByText("Vedi tutte le notifiche")).toBeInTheDocument();
  });
});
