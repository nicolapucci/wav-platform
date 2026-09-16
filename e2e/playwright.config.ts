import { defineConfig, devices } from "@playwright/test";

// Test di sistema: girano contro lo stack già deployato (oggi il cluster k8s
// locale, nginx su localhost:80 - vedi k8s/), non contro un dev server avviato
// da Playwright stesso. Per questo qui non c'è un blocco "webServer": il
// "server" è la piattaforma intera (nginx + auth/api/ws-gateway/worker +
// postgres/redis), già in piedi prima di lanciare i test, non qualcosa che ha
// senso avviare/fermare per ogni run.
export default defineConfig({
  testDir: "./tests",
  retries: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  // il default di Playwright (5s) è tarato per app mockate/locali: qui ogni
  // assert può dipendere da più chiamate di rete reali in sequenza attraverso
  // nginx (es. loadAll() di ProjectsPage: prompt -> POST -> refetch di
  // organizzazioni e progetti), quindi serve più margine.
  expect: {
    timeout: 10_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
