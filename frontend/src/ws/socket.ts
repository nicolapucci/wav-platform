// Wrapper minimale sul WebSocket del ws-gateway: apre la connessione con il JWT
// come query param e offre subscribe/unsubscribe per canale (task, layer, board,
// my_tasks, notifications - vedi architettura.md §6).

import { getAccessToken } from "../api/client";

type MessageHandler = (message: any) => void;

export class RealtimeSocket {
  private ws: WebSocket | null = null;
  private handlers: MessageHandler[] = [];
  private pendingSubscriptions: { resource: string; id?: string }[] = [];

  connect() {
    // idempotente: se una connessione è già aperta o in corso, non se ne apre
    // un'altra. Necessario ora che più componenti indipendenti (pagine, il
    // NotificationsProvider globale) chiamano tutti connect() sullo stesso
    // singleton: senza questo controllo si accumulerebbero WebSocket paralleli.
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const token = getAccessToken();
    if (!token) throw new Error("Nessun access token: effettuare il login prima di connettersi al socket");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${protocol}//${window.location.host}/ws?token=${token}`);

    this.ws.onopen = () => {
      // rimanda le subscribe richieste prima che la connessione fosse pronta
      this.pendingSubscriptions.forEach((sub) => this._send({ action: "subscribe", ...sub }));
      this.pendingSubscriptions = [];
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handlers.forEach((h) => h(data));
    };

    this.ws.onclose = () => {
      // TODO produzione: riconnessione con backoff esponenziale e re-invio
      // delle subscribe attive dopo la riconnessione.
    };
  }

  onMessage(handler: MessageHandler) {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter((h) => h !== handler);
    };
  }

  subscribe(resource: string, id?: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this._send({ action: "subscribe", resource, id });
    } else {
      this.pendingSubscriptions.push({ resource, id });
    }
  }

  unsubscribe(resource: string, id?: string) {
    this._send({ action: "unsubscribe", resource, id });
  }

  disconnect() {
    this.ws?.close();
    this.ws = null;
  }

  private _send(payload: object) {
    this.ws?.send(JSON.stringify(payload));
  }
}

// singleton condiviso dall'app: una sola connessione WS per client
export const realtimeSocket = new RealtimeSocket();
