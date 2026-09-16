import { expect, test } from "@playwright/test";

import { queueDialogResponses, registerNewUser, uniqueSuffix } from "./helpers";

test("un utente registrato crea organizzazione, progetto, layer e task, e la task compare in Kanban", async ({
  page,
}) => {
  const suffix = uniqueSuffix();
  const orgName = `Org E2E ${suffix}`;
  const projectName = `Progetto E2E ${suffix}`;
  const layerName = `Layer E2E ${suffix}`;
  const taskTitle = `Task E2E ${suffix}`;

  await registerNewUser(page, "Utente E2E");

  // prefisso univoco per run: il vincolo UNIQUE lato server è globale su tutti
  // i progetti mai creati sul DB (persistente tra run di questa suite), un
  // valore fisso avrebbe continuato a scontrarsi con quello di run precedenti.
  const prefix = Array.from({ length: 4 }, () => String.fromCharCode(65 + Math.floor(Math.random() * 26))).join("");

  queueDialogResponses(page, [
    { match: /Nome della nuova organizzazione/, value: orgName },
    // "Nome del nuovo progetto?" e "Prefisso del progetto" arrivano in sequenza
    // dalla stessa azione (promptForNameAndPrefix in ProjectsPage.tsx).
    { match: /Nome del nuovo progetto/, value: projectName },
    { match: /Prefisso del progetto/, value: prefix },
    { match: /Nome del nuovo layer/, value: layerName },
    { match: /Titolo della nuova task/, value: taskTitle },
  ]);

  await page.getByRole("link", { name: "Progetti" }).click();
  await page.getByRole("button", { name: "+ Organizzazione" }).click();
  await expect(page.getByText(orgName)).toBeVisible();

  await page.getByRole("button", { name: "Nuovo progetto" }).click();
  await expect(page.getByText(projectName)).toBeVisible();

  await page.getByText(projectName).click();
  await expect(page).toHaveURL(/\/projects\//);

  await page.getByRole("button", { name: "+ Layer" }).click();
  await expect(page.getByText(layerName)).toBeVisible();

  await page.getByRole("button", { name: "+ Task" }).click();
  await expect(page.getByText(taskTitle)).toBeVisible();

  // la stessa task deve comparire anche nella Kanban "tutte le mie task",
  // alimentata da un endpoint diverso (GET /me/tasks/board) da quello della
  // vista struttura del progetto (GET /projects/{id}/tasks) appena verificata.
  await page.getByRole("link", { name: "Kanban" }).click();
  await expect(page.getByText(taskTitle)).toBeVisible();
});
