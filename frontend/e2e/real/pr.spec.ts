/**
 * Purchase requisition against the REAL backend (E2E_REAL=1; see README).
 *
 * Rp 150 jt PR on Rp 55 jt remaining → Blocked → BCR (prefilled from the PR) → Director approves
 * → PR goes to approval → Head of Finance approves → available reduced.
 */
import { expect, test, type Page } from '@playwright/test';

const PASSWORD = 'E2e-Rahasia-2026';
const ENGINEER = 'engineer@e2e.gek.co.id';
const PLANNER = 'planner@e2e.gek.co.id';
const DIRECTOR = 'director@e2e.gek.co.id';
const HOF = 'hof@e2e.gek.co.id';

test.skip(!process.env.E2E_REAL, 'set E2E_REAL=1 with a seeded e2e backend on :8000');
test.setTimeout(180_000);
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
  await expect(page.getByRole('button', { name: 'Masuk', exact: true })).toBeVisible();
}

async function approve(page: Page, number: string) {
  await page.goto('/persetujuan');
  await page.getByRole('link', { name: number }).first().click();
  await page.getByRole('button', { name: /^Setujui$/ }).click();
  await expect(page.getByText(/disetujui/i).first()).toBeVisible();
}

test('blocked PR, BCR from the PR, approval reduces available', async ({ page }) => {
  // 1. Engineer raises Rp 150 jt on a line with Rp 55 jt → Blocked.
  await signIn(page, ENGINEER);
  await page.goto('/pengadaan/pr');
  await page.getByRole('link', { name: /PR baru/ }).click();
  await page.getByRole('option', { name: /PRJ-26-901/ }).waitFor({ state: 'attached' });
  await page.getByLabel(/^Proyek/).selectOption({ label: 'PRJ-26-901 · PR E2E Blok Jambi' });
  await page.getByLabel(/^Elemen biaya/).selectOption('EQUIP-RENT');
  await page.getByLabel(/^Dibutuhkan/).fill('2026-12-15');
  await page.getByLabel(/^Lokasi pengiriman/).fill('Lapangan Jambi, sumur JM-04');
  await page.getByLabel('Uraian 1').fill('Sewa genset 500 kVA 30 hari');
  await page.getByLabel('Estimasi harga 1').fill('150.000.000');
  await page.getByRole('button', { name: 'Simpan draf', exact: true }).click();
  // Specs run in parallel and share the numbering (the MR spec also raises a PR).
  const prText = page.locator('.eyebrow', { hasText: /PR-26-\d+/ }).first();
  await expect(prText).toBeVisible();
  const prNumber = /PR-26-\d+/.exec((await prText.textContent()) ?? '')![0];
  await page.getByRole('button', { name: /^Ajukan$/ }).click();
  const blocked = page.getByRole('alert');
  await expect(blocked).toContainText('kurang Rp 95.000.000');
  await expect(blocked).toContainText('Minta planner');
  const prUrl = page.url();
  await signOut(page);

  // 2. Planner opens the PR and requests the BCR, prefilled from it.
  await signIn(page, PLANNER);
  await page.goto(prUrl);
  await page.getByRole('button', { name: /Ajukan BCR Rp 95\.000\.000/ }).click();
  await expect(page.getByText(`BCR untuk ${prNumber}`)).toBeVisible();
  await expect(page.getByLabel(/^Nilai/)).toHaveValue('95.000.000');
  await page.getByLabel(/^Justifikasi/).fill('Sewa genset tambahan untuk sumur JM-04');
  await page.getByRole('button', { name: 'Ajukan BCR', exact: true }).click();
  const submitted = page.getByText(/BCR-26-\d+ diajukan ke Direktur/);
  await expect(submitted).toBeVisible();
  // Read this BCR's number for the same reason.
  const bcrNumber = /BCR-26-\d+/.exec((await submitted.textContent()) ?? '')![0];
  await signOut(page);

  // 3. Director approves the BCR → the PR goes to approval automatically.
  await signIn(page, DIRECTOR);
  await approve(page, bcrNumber);
  await signOut(page);

  // 4. Head of Finance (Rp 50 jt – 500 jt) approves the PR → pre-commitment reserved.
  await signIn(page, HOF);
  await approve(page, prNumber);
  await signOut(page);

  // 5. Engineer sees the PR approved and the line's available reduced to Rp 0.
  await signIn(page, ENGINEER);
  await page.goto(prUrl);
  await expect(page.getByText('Disetujui').first()).toBeVisible();
  await expect(page.getByText(bcrNumber).first()).toBeVisible();
  const held = page
    .locator('dt', { hasText: 'Dicadangkan PR ini' })
    .locator('xpath=following-sibling::dd');
  await expect(held).toHaveText('Rp 150.000.000');
  const available = page
    .locator('dt', { hasText: 'Tersedia' })
    .locator('xpath=following-sibling::dd');
  await expect(available).toHaveText('Rp 0');
});
