import react from "@vitejs/plugin-react";
// "vitest/config" ri-esporta defineConfig di vite con in più il campo "test"
// tipizzato: un solo file di config invece di vite.config.ts + vitest.config.ts.
import { defineConfig } from "vitest/config";

// In sviluppo il dev server di Vite fa da proxy verso i servizi backend,
// così il frontend può usare path relativi (/api, /auth, /ws) sia in dev
// che dietro nginx in produzione (vedi nginx/nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8001",
      "/ws": {
        target: "ws://localhost:8002",
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // ogni test riparte pulito: mock automatici ripristinati e i vi.stubGlobal
    // (fetch, WebSocket, ...) rimossi, senza doverlo scrivere in ogni file.
    restoreMocks: true,
    unstubGlobals: true,
  },
});
