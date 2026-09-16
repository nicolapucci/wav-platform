import type { Page } from "@playwright/test";

export function uniqueSuffix(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Registra un handler per i window.prompt/alert nativi che l'app usa per
 * creare organizzazioni/progetti/layer/task (vedi ProjectsPage.tsx,
 * ProjectDetailPage.tsx): ogni prompt viene fatto corrispondere al primo
 * "match" sul suo testo, e accettato con il valore associato. A differenza
 * del browser pane usato in questa sessione per i test manuali (dove
 * window.prompt() non è supportato), Playwright gestisce i dialog nativi
 * nativamente tramite l'evento "dialog". */
export function queueDialogResponses(page: Page, responses: { match: RegExp; value: string }[]) {
  page.on("dialog", async (dialog) => {
    const entry = responses.find((r) => r.match.test(dialog.message()));
    if (entry) {
      await dialog.accept(entry.value);
    } else {
      await dialog.dismiss();
    }
  });
}

/** Registra un nuovo utente (email sempre univoca) tramite la vera UI e
 * ritorna alla pagina "Le mie task", loggato. */
export async function registerNewUser(page: Page, displayName: string): Promise<string> {
  const email = `e2e-${uniqueSuffix()}@example.com`;

  await page.goto("/");
  await page.getByRole("button", { name: "Registrati" }).click(); // passa dal login alla modalità registrazione
  await page.locator('input[type="text"]').fill(displayName);
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill("e2e-supersegreto-123");
  await page.getByRole("button", { name: "Registrati" }).click(); // submit del form

  await page.waitForURL("**/my-tasks");
  return email;
}

/** Estrae l'access token JWT salvato dal client dopo il login/registrazione,
 * per fare chiamate dirette alle API (bypassando la UI) nella stessa identità
 * con cui gira `page`. */
export async function getAccessToken(page: Page): Promise<string> {
  const token = await page.evaluate(() => localStorage.getItem("wav_access_token"));
  if (!token) throw new Error("Nessun access token in localStorage: l'utente è loggato?");
  return token;
}
