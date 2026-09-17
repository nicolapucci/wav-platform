import { Link } from "react-router-dom";

import InfoTooltip from "../components/InfoTooltip";
import { useNotifications } from "../context/NotificationsContext";
import { NOTIFICATION_TYPE_LABELS, describeNotification, notificationLink } from "../notifications/format";

export default function NotificationsPage() {
  const { notifications, loading, unreadCount, markAsRead, markAllAsRead } = useNotifications();

  return (
    <>
      <div className="page-header">
        <h1>
          Notifiche
          <InfoTooltip text={unreadCount > 0 ? `${unreadCount} da leggere` : "Tutto letto"} />
        </h1>
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
    </>
  );
}
