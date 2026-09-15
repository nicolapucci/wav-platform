import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

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
});
