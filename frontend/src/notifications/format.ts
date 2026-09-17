import type { NotificationItem } from "../context/NotificationsContext";

// Condiviso tra NotificationsPage (elenco completo) e HomePage (estratto
// recente): un solo posto per il testo/link di ogni tipo di notifica.
export const NOTIFICATION_TYPE_LABELS: Record<string, string> = {
  mention: "Menzione",
  task_assigned: "Assegnazione",
  resource_updated: "Aggiornamento",
  comment_reply: "Risposta",
};

export function describeNotification(n: NotificationItem): string {
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

export function notificationLink(n: NotificationItem): string | null {
  if (n.entity_type === "task") return `/tasks/${n.entity_id}`;
  if (typeof n.payload?.task_id === "string") return `/tasks/${n.payload.task_id}`;
  return null;
}
