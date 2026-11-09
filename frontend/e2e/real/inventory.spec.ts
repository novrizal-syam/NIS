/**
 * Material request against the REAL backend (E2E_REAL=1; see README).
 *
 * Field engineer asks 8 drums on PRJ-26-902: 2 come from the site, 3 from Base, the 3 short
 * become a PR at the last price; the Warehouse Head sees stock valuation still equal to 1310.
 */
import { expect, test, type Page } from '@playwright/test';

const PASSWORD = 'E2e-Rahasia-2026';
const FIELD_ENGINEER = 'fe@e2e.gek.co.id';
const WAREHOUSE_HEAD = 'wh@e2e.gek.co.id';

test.skip(!process.env.E2E_REAL, 'set E2E_REAL=1 with a seeded e2e backend on :8000');
test.setTimeout(120_000);
test.use({ actionTimeout: 15_000 });
expect.configure({ timeout: 10_000 });

async function signIn(page: Page, email: string) {
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByRole('textbox', { name: 'Kata sandi' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Masuk', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Dasbor' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Menu pengguna', exact: true }).click();
  await page.getByRole('button', { name: /Keluar/ }).click();
  await page.waitForURL(/\/login/, { timeout: 15_000 });
}

test('MR issues site then base stock and turns the shortfall into a PR', async ({ page }) => {
  await signIn(page, FIELD_ENGINEER);
  await page.getByRole('link', { name: 'Permintaan Material' }).click();
  await page.getByRole('link', { name: /Permintaan material baru/ }).click();
  await page.getByRole('option', { name: /PRJ-26-902/ }).waitFor({ state: 'attached' });
  await page.getByLabel(/^Proyek/).selectOption({ label: 'PRJ-26-902 · MR E2E Blok Rokan' });
  // The project's site warehouse is preselected.
  await expect(page.getByLabel(/^Gudang site/)).toHaveValue('WH-902');
  await page.getByLabel(/^Dibutuhkan/).fill('2026-12-15');
  await page.getByLabel('Item 1').selectOption('ITM-E2E');
  await page.getByLabel('Qty 1').fill('8');
  await page.getByRole('button', { name: /Ajukan & keluarkan/ }).click();

  const row = page.getByRole('row', { name: /Demulsifier E2E/ });
  await expect(row.getByRole('cell')).toHaveText([
    /Demulsifier E2E/,
    '8',
    '2',
    '3',
    '3',
    'Rp 30.000.000',
  ]);
  await expect(page.getByText('Sebagian + PR')).toBeVisible();
  await expect(page.getByText(/5300 · Bahan habis pakai/)).toBeVisible();
  await page.getByRole('link', { name: /PR-26-\d+/ }).click();
  await expect(page.getByText('Rp 19.200.000').first()).toBeVisible(); // 3 x 6.400.000
  await signOut(page);

  await signIn(page, WAREHOUSE_HEAD);
  await page.getByRole('link', { name: 'Persediaan' }).click();
  await page.getByRole('tab', { name: 'Valuasi' }).click();
  await expect(page.getByRole('status')).toHaveText(
    'Valuasi stok sama dengan saldo akun 1310 Persediaan.',
  );
});
