import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../api/client";
import InfoTooltip from "../components/InfoTooltip";
import { useNotifications } from "../context/NotificationsContext";
import { NOTIFICATION_TYPE_LABELS, describeNotification, notificationLink } from "../notifications/format";
import { realtimeSocket } from "../ws/socket";

type AssignedTask = {
  id: string;
  readable_id: string;
  title: string;
  project_id: string;
  project_name: string;
  column_name: string | null;
  priority: number;
  due_date: string | null;
};

const PRIORITY_LABELS = ["Bassa", "Media", "Alta", "Urgente"];
const RECENT_NOTIFICATIONS_LIMIT = 8;

export default function HomePage() {
  const [tasks, setTasks] = useState<AssignedTask[]>([]);
  const [loading, setLoading] = useState(true);
  const { notifications, unreadCount, markAsRead } = useNotifications();

  async function loadTasks() {
    setLoading(true);
    const res = await apiFetch("/api/me/tasks/assigned");
    if (res.ok) setTasks(await res.json());
    setLoading(false);
  }

  useEffect(() => {
    loadTasks();
  }, []);

  // pagina "lista" (non ancorata a una task specifica): stesso pattern delle
  // altre viste aggregate, canale generico evt:tasks (architettura.md §6.1).
  // Le notifiche arrivano già in tempo reale dal NotificationsProvider
  // globale (vedi App.tsx), non serve sottoscriverle di nuovo qui.
  useEffect(() => {
    realtimeSocket.connect();
    realtimeSocket.subscribe("tasks");

    const unsubscribe = realtimeSocket.onMessage((message) => {
      if (message.type === "task.created" || message.type === "task.updated" || message.type === "task.deleted") {
        loadTasks();
      }
    });

    return () => {
      unsubscribe();
      realtimeSocket.unsubscribe("tasks");
    };
  }, []);

  const recentNotifications = notifications.slice(0, RECENT_NOTIFICATIONS_LIMIT);

  return (
    <>
      <div className="page-header">
        <h1>
          Home
          <InfoTooltip text="Le tue task assegnate ancora aperte, e notifiche/menzioni recenti." />
        </h1>
      </div>

      <div className="home-grid">
        <section className="home-column">
          <div className="home-column-header">
            <h2>Notifiche e menzioni</h2>
            {unreadCount > 0 && <span className="sidebar-badge">{unreadCount > 9 ? "9+" : unreadCount}</span>}
          </div>

          {recentNotifications.length === 0 && (
            <p style={{ color: "var(--text-secondary)" }}>Nessuna notifica per ora.</p>
          )}

          <ul className="notification-list">
            {recentNotifications.map((n) => {
              const target = notificationLink(n);
              const body = (
                <>
                  <div className="notification-row">
                    <span className="notification-type">{NOTIFICATION_TYPE_LABELS[n.type] ?? n.type}</span>
                    <span>{new Date(n.created_at).toLocaleString()}</span>
                  </div>
                  <p>{describeNotification(n)}</p>
                </>
              );
              return (
                <li
                  key={n.id}
                  className={n.read_at ? "notification" : "notification unread"}
                  onClick={() => !n.read_at && markAsRead(n.id)}
                >
                  {target ? <Link to={target}>{body}</Link> : body}
                </li>
              );
            })}
          </ul>

          {notifications.length > RECENT_NOTIFICATIONS_LIMIT && (
            <Link to="/notifications" className="link-button">
              Vedi tutte le notifiche
            </Link>
          )}
        </section>

        <section className="home-column">
          <div className="home-column-header">
            <h2>Le tue task assegnate</h2>
          </div>

          {loading && <p>Caricamento...</p>}
          {!loading && tasks.length === 0 && (
            <p style={{ color: "var(--text-secondary)" }}>Nessuna task assegnata da completare.</p>
          )}

          <ul className="home-task-list">
            {tasks.map((task) => (
              <li key={task.id} className="home-task-item">
                <Link to={`/tasks/${task.readable_id}`}>
                  <div className="notification-row">
                    <span className="task-table-id">{task.readable_id}</span>
                    <span className={`kanban-priority priority-${task.priority}`}>
                      {PRIORITY_LABELS[task.priority] ?? task.priority}
                    </span>
                  </div>
                  <p>
                    <strong>{task.title}</strong>
                  </p>
                  <div className="notification-row">
                    <span>{task.project_name}</span>
                    <span>
                      {task.due_date ? new Date(task.due_date).toLocaleDateString() : task.column_name ?? "—"}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
