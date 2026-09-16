import { beforeEach, describe, expect, it, vi } from "vitest";

import { setTokens } from "../api/client";
import { RealtimeSocket } from "./socket";

/** jsdom non implementa un WebSocket funzionante (nessuna vera connessione di
 * rete): un fake minimale che il test pilota a mano (triggerOpen/triggerMessage)
 * al posto di un vero server. */
class FakeWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  triggerOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  triggerMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

describe("RealtimeSocket.connect", () => {
  it("lancia se non c'è un access token salvato", () => {
    const socket = new RealtimeSocket();
    expect(() => socket.connect()).toThrow(/access token/i);
  });

  it("apre un WebSocket verso /ws con il token in query string", () => {
    setTokens("il-mio-token", "refresh");
    const socket = new RealtimeSocket();

    socket.connect();

    expect(FakeWebSocket.instances).toHaveLength(1);
    const url = new URL(FakeWebSocket.instances[0].url, window.location.origin);
    expect(url.pathname).toBe("/ws");
    expect(url.searchParams.get("token")).toBe("il-mio-token");
  });

  it("è idempotente: non apre una seconda connessione se una è già aperta", () => {
    setTokens("token", "refresh");
    const socket = new RealtimeSocket();

    socket.connect();
    FakeWebSocket.instances[0].triggerOpen();
    socket.connect();

    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe("RealtimeSocket.subscribe/unsubscribe", () => {
  it("mette in coda le subscribe fatte prima dell'apertura e le invia tutte all'onopen", () => {
    setTokens("token", "refresh");
    const socket = new RealtimeSocket();
    socket.connect();

    socket.subscribe("tasks");
    socket.subscribe("task", "pg-123");
    const ws = FakeWebSocket.instances[0];
    expect(ws.sent).toHaveLength(0); // non ancora open: nessun invio

    ws.triggerOpen();

    expect(ws.sent.map((s) => JSON.parse(s))).toEqual([
      { action: "subscribe", resource: "tasks", id: undefined },
      { action: "subscribe", resource: "task", id: "pg-123" },
    ]);
  });

  it("invia subito la subscribe se la connessione è già aperta", () => {
    setTokens("token", "refresh");
    const socket = new RealtimeSocket();
    socket.connect();
    const ws = FakeWebSocket.instances[0];
    ws.triggerOpen();

    socket.subscribe("tasks");

    expect(ws.sent.map((s) => JSON.parse(s))).toEqual([{ action: "subscribe", resource: "tasks", id: undefined }]);
  });

  it("unsubscribe invia il messaggio corrispondente", () => {
    setTokens("token", "refresh");
    const socket = new RealtimeSocket();
    socket.connect();
    const ws = FakeWebSocket.instances[0];
    ws.triggerOpen();

    socket.unsubscribe("task", "pg-123");

    expect(ws.sent.map((s) => JSON.parse(s))).toEqual([
      { action: "unsubscribe", resource: "task", id: "pg-123" },
    ]);
  });
});

describe("RealtimeSocket.onMessage", () => {
  it("passa i messaggi ricevuti (JSON-parsati) a tutti gli handler registrati", () => {
    setTokens("token", "refresh");
    const socket = new RealtimeSocket();
    socket.connect();
    const ws = FakeWebSocket.instances[0];

    const received: unknown[] = [];
    socket.onMessage((msg) => received.push(msg));

    ws.triggerMessage({ channel: "evt:tasks", type: "task.updated" });

    expect(received).toEqual([{ channel: "evt:tasks", type: "task.updated" }]);
  });

  it("la funzione di cleanup ritornata rimuove l'handler", () => {
    setTokens("token", "refresh");
    const socket = new RealtimeSocket();
    socket.connect();
    const ws = FakeWebSocket.instances[0];

    const received: unknown[] = [];
    const stop = socket.onMessage((msg) => received.push(msg));
    stop();

    ws.triggerMessage({ type: "task.updated" });

    expect(received).toEqual([]);
  });
});

describe("RealtimeSocket.disconnect", () => {
  it("chiude il socket sottostante e permette una nuova connect()", () => {
    setTokens("token", "refresh");
    const socket = new RealtimeSocket();
    socket.connect();
    const first = FakeWebSocket.instances[0];

    socket.disconnect();
    expect(first.readyState).toBe(FakeWebSocket.CLOSED);

    socket.connect();
    expect(FakeWebSocket.instances).toHaveLength(2);
  });
});
