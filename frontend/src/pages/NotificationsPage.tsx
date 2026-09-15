import { Link } from "react-router-dom";

import { NotificationItem, useNotifications } from "../context/NotificationsContext";

const TYPE_LABELS: Record<string, string> = {
  mention: "Menzione",
  task_assigned: "Assegnazione",
  resource_updated: "Aggiornamento",
  comment_reply: "Risposta",
};

function describe(n: NotificationItem): string {
  const payload = n.payload || {};
  switch (n.type) {
    case "mention":
      return `Sei stato menzionato in un commento${
        payload.comment_excerpt ? `: "${payload.comment_excerpt}"` : ""
      }`;
    case "task_assigned":
      return `Sei stato assegnato alla task "${payload.task_title ?? ""}"`;
    case "resource_updated":
      return "Una risorsa che segui è stata aggiornata";
    case "comment_reply":
      return "Hai una nuova risposta a un commento";
    default:
      return "Nuova notifica";
  }
}

function linkFor(n: NotificationItem): string | null {
  if (n.entity_type === "task") return `/tasks/${n.entity_id}`;
  if (typeof n.payload?.task_id === "string") return `/tasks/${n.payload.task_id}`;
  return null;
}

export default function NotificationsPage() {
  const { notifications, loading, unreadCount, markAsRead, markAllAsRead } = useNotifications();

  return (
    <>
      <div className="page-header">
        <h1>Notifiche</h1>
        <p>{unreadCount > 0 ? `${unreadCount} da leggere` : "Tutto letto"}</p>
      </div>

      {unreadCount > 0 && (
        <div className="toolbar">
          <button type="button" onClick={markAllAsRead}>
            Segna tutte come lette
          </button>
        </div>
      )}

      {loading && <p>Caricamento...</p>}
      {!loading && notifications.length === 0 && (
        <p style={{ color: "var(--text-secondary)" }}>Nessuna notifica per ora.</p>
      )}

      <ul className="notification-list">
        {notifications.map((n) => {
          const target = linkFor(n);
          const body = (
            <>
              <div className="notification-row">
                <span className="notification-type">{TYPE_LABELS[n.type] ?? n.type}</span>
                <span>{new Date(n.created_at).toLocaleString()}</span>
              </div>
              <p>{describe(n)}</p>
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
    </>
  );
}
