import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { apiFetch } from "../api/client";
import { realtimeSocket } from "../ws/socket";

export type NotificationItem = {
  id: string;
  type: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
};

type NotificationsContextValue = {
  notifications: NotificationItem[];
  unreadCount: number;
  loading: boolean;
  markAsRead: (id: string) => Promise<void>;
  markAllAsRead: () => Promise<void>;
};

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const res = await apiFetch("/api/me/notifications");
    if (res.ok) setNotifications(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Sottoscrizione globale: questo provider vive per tutta la sessione
  // autenticata (è montato una volta sola attorno al Layout, non per singola
  // pagina - vedi App.tsx), quindi il badge nella sidebar si aggiorna anche
  // se l'utente non ha la pagina Notifiche aperta (architettura.md §6.4).
  useEffect(() => {
    realtimeSocket.connect();
    realtimeSocket.subscribe("notifications");

    const unsubscribe = realtimeSocket.onMessage((message) => {
      if (message.type === "notification.created") {
        refresh();
      }
    });

    return () => {
      unsubscribe();
      realtimeSocket.unsubscribe("notifications");
    };
  }, [refresh]);

  async function markAsRead(id: string) {
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)));
    await apiFetch(`/api/me/notifications/${id}/read`, { method: "POST" });
  }

  async function markAllAsRead() {
    const unread = notifications.filter((n) => !n.read_at);
    setNotifications((prev) => prev.map((n) => (n.read_at ? n : { ...n, read_at: new Date().toISOString() })));
    // TODO produzione: un endpoint POST /me/notifications/read-all evita N round-trip.
    await Promise.all(unread.map((n) => apiFetch(`/api/me/notifications/${n.id}/read`, { method: "POST" })));
  }

  const unreadCount = notifications.filter((n) => !n.read_at).length;

  return (
    <NotificationsContext.Provider value={{ notifications, unreadCount, loading, markAsRead, markAllAsRead }}>
      {children}
    </NotificationsContext.Provider>
  );
}

export function useNotifications() {
  const ctx = useContext(NotificationsContext);
  if (!ctx) throw new Error("useNotifications deve essere usato dentro <NotificationsProvider>");
  return ctx;
}
