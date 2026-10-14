import { test, expect, request } from '@playwright/test';

/** Happy path: login -> project -> run -> dossier -> export.
 * Uses the seeded SYNTHETIC demo project (full evidence, gate sufficient).
 * Asserts no invented numbers: every value comes from the app's own API.
 */
test('login → project → run → dossier → export', async ({ page }) => {
  // login (DEMO_MODE pre-fills credentials; fill explicitly to be sure)
  await page.goto('/login');
  const inputs = page.locator('form.card input.input');
  await inputs.nth(0).fill('admin@mwamba.local');
  await inputs.nth(1).fill('Mwamba123!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/login/, { timeout: 15_000 });

  // project: Workspace lists the SYNTHETIC demo project; its card selects it
  await page.goto('/');
  const card = page.locator('button.card', { hasText: 'Synthetic demo' }).first();
  await expect(card).toBeVisible({ timeout: 15_000 });
  await card.click();

  // run: Models page -> launch weighted analysis
  await page.getByRole('navigation').getByRole('link', { name: 'Models' }).click();
  await expect(page.getByText(/evidence available/i)).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: /run analysis/i }).click();
  await expect(page.getByText(/run queued/i)).toBeVisible({ timeout: 15_000 });
  const runId = (await page.getByText(/run queued/i).textContent())?.replace('Run queued: ', '').trim();
  expect(runId, 'run id from app response').toBeTruthy();

  // wait for the run to finish (poll the run-history row)
  const doneRow = page.locator('div', { hasText: new RegExp(`${runId!.slice(0, 8)}.*done`) }).first();
  await expect(doneRow).toBeVisible({ timeout: 110_000 });

  // targets: page auto-selects the latest done run; open the first dossier
  await page.getByRole('navigation').getByRole('link', { name: 'Targets' }).click();
  await expect(page.getByRole('link', { name: /dossier/i }).first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole('link', { name: /dossier/i }).first().click();
  await expect(page.getByText(/score breakdown/i)).toBeVisible({ timeout: 15_000 });

  // export: geojson + csv + kml + pdf straight from the backend
  const token = await page.evaluate(() => localStorage.getItem('mwamba_token'));
  const ctx = await request.newContext({
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
  for (const ext of ['geojson', 'csv', 'kml']) {
    const r = await ctx.get(`http://127.0.0.1:8000/runs/${runId}/export.${ext}`);
    expect(r.status(), `export.${ext}`).toBe(200);
  }
  const m = page.url().match(/targets\/([a-z0-9]+)/);
  expect(m, 'target id in dossier url').toBeTruthy();
  const pdf = await ctx.get(`http://127.0.0.1:8000/targets/${m![1]}/dossier.pdf`);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 4).toString()).toBe('%PDF');
  await ctx.dispose();
});
