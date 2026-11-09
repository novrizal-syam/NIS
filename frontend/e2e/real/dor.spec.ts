/**
 * DOR against the REAL backend (E2E_REAL=1; see README): the field engineer fills a DOR while
 * OFFLINE (saved in IndexedDB), the connection comes back and the draft syncs on its own; the
 * DOR is submitted and the project's OFS Superintendent approves it.
 */
import { expect, test, type Page } from '@playwright/test';

const PASSWORD = 'E2e-Rahasia-2026';
const FIELD_ENGINEER = 'fe@e2e.gek.co.id';
const SUPERINTENDENT = 'sup@e2e.gek.co.id';

test.skip(!process.env.E2E_REAL, 'set E2E_REAL=1 with a seeded e2e backend on :8000');
test.setTimeout(120_000);
test.use({ actionTimeout: 15_000 });
expect.configure({ timeout: 15_000 });

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

test('offline DOR draft syncs when back online, then approval', async ({ page, context }) => {
  await signIn(page, FIELD_ENGINEER);
  await page.getByRole('link', { name: 'Daily Operation Report' }).click();
  await page.getByRole('option', { name: /PRJ-26-902/ }).waitFor({ state: 'attached' });
  await page.getByLabel(/^Proyek/).selectOption({ label: 'PRJ-26-902 · MR E2E Blok Rokan' });
  await page.getByRole('button', { name: /DOR baru/ }).click();
  // Form options (rates, units, crew, stock) are loaded once while online and cached.
  await expect(page.getByText('Data teknis — Well testing')).toBeVisible();

  await context.setOffline(true);
  await expect(page.getByText('Offline', { exact: true })).toBeVisible();
  await page.getByLabel('Tambah unit').selectOption('AST-E2E');
  await page.getByLabel('Rig-up/down').fill('2');
  await page.getByLabel('Operasi').fill('22');
  await expect(page.getByText(/Total 24 jam · Rp 14\.000\.000/)).toBeVisible();
  await page.getByLabel('Tambah kru').selectOption('E-E2E');
  await page.getByLabel(/^Ringkasan aktivitas/).fill('Flowing sumur RK-12, sampling tiap 2 jam.');
  await page.getByLabel(/^Laju minyak/).fill('850');
  await expect(page.getByText('Rp 17.000.000')).toBeVisible(); // live preview, offline
  await page.getByRole('button', { name: /^Simpan$/ }).click();
  await expect(page.getByRole('status')).toHaveText(
    'Tersimpan di perangkat. Akan dikirim otomatis saat online.',
  );
  await expect(page.getByText('Belum tersinkron')).toBeVisible();
  await expect(page.getByRole('button', { name: /Ajukan/ })).toBeDisabled();

  // Connection back: the queue pushes the draft by itself.
  await context.setOffline(false);
  await expect(page.getByText('Tersinkron', { exact: true })).toBeVisible();
  const heading = page.getByRole('heading', { name: /DOR-26-\d+/ });
  await expect(heading).toBeVisible();
  const number = /DOR-26-\d+/.exec((await heading.textContent()) ?? '')![0];

  await page.getByRole('button', { name: /Ajukan/ }).click();
  await expect(page.getByText('Menunggu persetujuan').first()).toBeVisible();
  await signOut(page);

  await signIn(page, SUPERINTENDENT);
  await page.goto('/persetujuan');
  await page.getByRole('link', { name: number }).first().click();
  await page.getByRole('button', { name: /^Setujui$/ }).click();
  await expect(page.getByText(/disetujui/i).first()).toBeVisible();
});
