/**
 * Lead to contract against the REAL backend (no mocks). Runs only with E2E_REAL=1 and an API on
 * :8000 backed by a throw-away database seeded with `python -m tests.e2e_seed` (see README).
 *
 * lead → qualify → bid (Director) → quotation 34 % → Head of Sales approves → send → won
 * → contract + draft project.
 */
import { expect, test, type Page } from '@playwright/test';

const PASSWORD = 'E2e-Rahasia-2026';
const AE = 'ae@e2e.gek.co.id';
const HOS = 'hos@e2e.gek.co.id';
const DIRECTOR = 'director@e2e.gek.co.id';

test.skip(!process.env.E2E_REAL, 'set E2E_REAL=1 with a seeded e2e backend on :8000');
test.describe.configure({ mode: 'serial' });
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
  await expect(page.getByRole('button', { name: 'Masuk', exact: true })).toBeVisible({
    timeout: 15_000,
  });
}

async function approve(page: Page, docNumber: string) {
  await page.goto('/persetujuan');
  await page.getByRole('link', { name: docNumber }).first().click();
  await page.getByRole('button', { name: /^Setujui$/ }).click();
  await expect(page.getByText(/disetujui/i).first()).toBeVisible();
}

test('lead to contract and draft project', async ({ page }) => {
  // 1. Account Executive: lead → qualify → opportunity → bid proposal.
  await signIn(page, AE);
  await page.goto('/lead');
  await page.getByRole('button', { name: /Lead baru/ }).click();
  const create = page.getByRole('dialog');
  await create.getByLabel(/^Perusahaan/).fill('PT Migas Hulu E2E');
  await create.getByLabel(/^Nama kontak/).fill('Bapak Andi');
  await create.getByLabel(/^Kebutuhan/).fill('Well testing 3 sumur, Q1 2027');
  await create.getByRole('button', { name: 'Simpan lead', exact: true }).click();
  await expect(create).toBeHidden();

  await page.getByRole('button', { name: 'LD-26-001', exact: true }).click();
  const lead = page.getByRole('dialog');
  await lead.getByRole('button', { name: 'Tandai sudah dihubungi', exact: true }).click();
  for (const c of [
    'Klien punya anggaran/AFE',
    'Sesuai kemampuan teknis kita',
    'Mulai dalam 6 bulan',
  ])
    await lead.getByLabel(c).check();
  await lead.getByRole('button', { name: 'Kualifikasi', exact: true }).click();
  await lead.getByRole('button', { name: 'Jadikan Opportunity', exact: true }).click();
  await lead.getByLabel(/^Judul peluang/).fill('Well testing Blok E2E');
  await lead.getByRole('button', { name: 'Buat opportunity', exact: true }).click();
  await lead.getByRole('status').getByRole('link', { name: 'OPP-26-001' }).click();

  await expect(page.getByText('Keputusan bid/no-bid').first()).toBeVisible();
  for (const s of [
    'Kesesuaian strategis (RJPP)',
    'Kemampuan teknis',
    'Ketersediaan aset & kru',
    'CSMS & kepatuhan',
    'Margin',
    'Risiko komersial & hukum',
  ])
    await page.getByLabel(s, { exact: false }).first().selectOption('5');
  await page.getByLabel('Bid', { exact: true }).check();
  await page.getByRole('button', { name: 'Ajukan ke Direktur', exact: true }).click();
  await expect(page.getByText('Menunggu Direktur').first()).toBeVisible();
  await signOut(page);

  // 2. Director approves the bid.
  await signIn(page, DIRECTOR);
  await approve(page, 'OPP-26-001');
  await signOut(page);

  // 3. AE: quotation at 34 % margin, submitted → Head of Sales.
  await signIn(page, AE);
  await page.goto('/peluang');
  await page
    .getByRole('link', { name: /OPP-26-001/ })
    .first()
    .click();
  await page.getByRole('button', { name: 'Buat penawaran', exact: true }).click();
  await page.getByLabel('Tambah dari database harga').selectOption('SRV-E2E');
  await page.getByLabel('Qty 1').fill('10');
  await page.getByRole('button', { name: 'Simpan & hitung ulang', exact: true }).click();
  await expect(page.getByText('Rp 100.000.000').first()).toBeVisible();
  await expect(page.getByText('34,00%').first()).toBeVisible();
  await page.getByRole('button', { name: /Ajukan persetujuan/ }).click();
  await expect(page.getByText('Diajukan ke Head of Sales.').first()).toBeVisible();
  await signOut(page);

  // 4. Head of Sales approves the quotation.
  await signIn(page, HOS);
  await approve(page, 'QT-26-001 Rev.0');
  await signOut(page);

  // 5. AE sends it to the client and marks the opportunity won.
  await signIn(page, AE);
  await page.goto('/penawaran');
  await page.getByRole('link', { name: 'QT-26-001 Rev.0' }).click();
  await page.getByRole('button', { name: /Kirim ke klien/ }).click();
  const send = page.getByRole('dialog');
  await send.getByLabel(/Kirim juga lewat email/).uncheck();
  await send.getByRole('button', { name: 'Buat surat & kirim', exact: true }).click();
  await expect(send.getByText(/Surat 001\/GEK-SLS\/.+ dibuat dan disimpan/).first()).toBeVisible();
  await send.getByRole('button', { name: 'Tutup', exact: true }).first().click();

  await page
    .getByRole('link', { name: /OPP-26-001/ })
    .first()
    .click();
  await page.getByRole('button', { name: /Tandai Menang/ }).click();
  await page.getByLabel('No. PO/SPK klien').fill('PO-E2E-0001');
  await page.getByRole('button', { name: 'Buat kontrak & proyek', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Kontrak CTR-26-001' })).toBeVisible();
  await signOut(page);

  // 6. Head of Sales sees the contract and the draft project budget.
  await signIn(page, HOS);
  await page.goto('/kontrak');
  await page.getByRole('link', { name: 'CTR-26-001' }).click();
  await expect(page.getByText('Rp 100.000.000').first()).toBeVisible();
  await expect(page.getByText('PO-E2E-0001').first()).toBeVisible();
  await page.getByRole('link', { name: 'Proyek PRJ-26-001' }).click();
  await expect(page.getByText('Draf').first()).toBeVisible();
  // Budget: quoted cost 66 M + contingency 5 % (3.3 M).
  await expect(page.getByText('Rp 66.000.000').first()).toBeVisible();
  await expect(page.getByText('Rp 3.300.000').first()).toBeVisible();
  await expect(page.getByText('Rp 69.300.000').first()).toBeVisible();
});
