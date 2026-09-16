import { expect, test } from "@playwright/test";

import { getAccessToken, registerNewUser, uniqueSuffix } from "./helpers";

test("un aggiornamento della task arriva in tempo reale sulla Kanban, senza reload", async ({ page, request }) => {
  // la creazione via UI è già coperta da golden-path.spec.ts: qui l'obiettivo
  // è solo il canale realtime, quindi lo stato di partenza (org/progetto/task)
  // viene preparato per via diretta via API, con l'endpoint /projects/demo già
  // usato in questa sessione per popolare rapidamente un progetto di prova.
  await registerNewUser(page, "Utente Realtime");
  const token = await getAccessToken(page);
  const authHeaders = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  const suffix = uniqueSuffix();

  const orgRes = await request.post("/api/organizations", {
    headers: authHeaders,
    data: { name: `Org Realtime ${suffix}`, slug: `org-rt-${suffix}` },
  });
  expect(orgRes.ok()).toBeTruthy();
  const org = await orgRes.json();

  // prefisso univoco per run (4 lettere maiuscole, vincolo lato server): un
  // valore fisso avrebbe fatto scontrare un retry con i dati del tentativo
  // precedente (409, prefisso già in uso).
  const prefix = Array.from({ length: 4 }, () => String.fromCharCode(65 + Math.floor(Math.random() * 26))).join("");
  const projectRes = await request.post("/api/projects/demo", {
    headers: authHeaders,
    data: { organization_id: org.id, name: `Progetto Realtime ${suffix}`, prefix },
  });
  expect(projectRes.ok()).toBeTruthy();
  const project = await projectRes.json();

  const tasksRes = await request.get(`/api/projects/${project.id}/tasks`, { headers: authHeaders });
  const tasks: { id: string; title: string }[] = await tasksRes.json();
  const task = tasks[0];

  // niente page.goto("/board"): è una navigazione hard, e il container nginx
  // del frontend non ha un fallback SPA (try_files -> index.html) per le route
  // diverse da "/" - stesso comportamento già osservato a mano in questa
  // sessione. Va raggiunta con un click in-app (routing lato client).
  await page.getByRole("link", { name: "Kanban" }).click();
  await expect(page.getByText(task.title)).toBeVisible();

  const newTitle = `${task.title} (aggiornata realtime)`;
  const patchRes = await request.patch(`/api/tasks/${task.id}`, {
    headers: authHeaders,
    data: { title: newTitle },
  });
  expect(patchRes.ok()).toBeTruthy();

  // niente page.reload(): deve arrivare via WebSocket (publish su Redis ->
  // ws-gateway -> evt:tasks) - lo stesso percorso, dall'origine fino alla UI,
  // debuggato a mano in questa sessione quando non funzionava.
  await expect(page.getByText(newTitle)).toBeVisible({ timeout: 10000 });
});
