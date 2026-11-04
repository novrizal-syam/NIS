/**
 * Budget lock and BCR against the REAL backend (E2E_REAL=1; see happy-path.spec.ts and README).
 *
 * draft → controller review (18 % rejected, 25 % passes) → approve → Locked
 * → test-check over budget blocked → BCR (contingency release) → approved → v1 → test-check passes.
 */
import { expect, request, test, type Page } from '@playwright/test';

const PASSWORD = 'E2e-Rahasia-2026';
const PLANNER = 'planner@e2e.gek.co.id';
const CONTROLLER = 'controller@e2e.gek.co.id';
const HOO = 'hoo@e2e.gek.co.id';
const ADMIN = 'admin@e2e.gek.co.id';

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

async function openProject(page: Page) {
  await page.goto('/proyek');
  await page.getByRole('link', { name: 'PRJ-26-900' }).click();
  await expect(page.getByRole('list', { name: 'Tahapan anggaran' })).toBeVisible();
}

async function openRequest(page: Page, number: string) {
  await page.goto('/persetujuan');
  await page.getByRole('link', { name: number }).first().click();
}

/** Admin test-check in its own request context (its session cookie must not replace the
 * browser user's). */
async function testCheck(page: Page, projectId: string, amount: number): Promise<boolean> {
  const api = await request.newContext({ baseURL: new URL(page.url()).origin });
  const login = await api.post('/api/auth/login', {
    data: { email: ADMIN, password: PASSWORD },
  });
  const token = ((await login.json()) as { access_token: string }).access_token;
  const res = await api.post('/api/budget/test-check', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      project_id: projectId,
      wbs_code: 'EXEC',
      cost_element_code: 'EQUIP-OWN',
      amount: String(amount),
    },
  });
  expect(res.status()).toBe(200);
  const ok = ((await res.json()) as { ok: boolean }).ok;
  await api.dispose();
  return ok;
}

test('budget lock, over-budget block, BCR and new version', async ({ page }) => {
  // 1. Planner submits the 18 % budget.
  await signIn(page, PLANNER);
  await openProject(page);
  const projectId = page.url().split('/proyek/')[1]!;
  await expect(page.getByRole('alert')).toContainText('18,00%');
  await page.getByRole('button', { name: /Ajukan ke Lead Controller/ }).click();
  await expect(page.getByText('Diajukan: Lead Controller → Head of Operation.')).toBeVisible();
  await signOut(page);

  // 2. Controller cannot approve below 20 %; rejects with a note.
  await signIn(page, CONTROLLER);
  await openRequest(page, 'PRJ-26-900');
  await page.getByRole('button', { name: /^Setujui$/ }).click();
  await expect(page.getByText(/di bawah batas 20%/).first()).toBeVisible();
  await page.getByRole('button', { name: /Tolak/ }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(/Alasan/).fill('Margin 18% di bawah 20%, tinjau tarif peralatan');
  await dialog.getByRole('button', { name: /Tolak/ }).click();
  await expect(page.getByText(/ditolak/i).first()).toBeVisible();
  await signOut(page);

  // 3. Planner lowers cost to reach 25 % and resubmits.
  await signIn(page, PLANNER);
  await openProject(page);
  await expect(page.getByText(/Dikembalikan dengan catatan/)).toBeVisible();
  const cell = page.getByLabel('EQUIP-OWN EXEC');
  await cell.fill('710.000.000');
  await page.getByRole('button', { name: 'Simpan & hitung ulang', exact: true }).click();
  await expect(page.getByText('25,00%').first()).toBeVisible();
  await page.getByRole('button', { name: /Ajukan ke Lead Controller/ }).click();
  await expect(page.getByText(/Diajukan: Lead Controller/)).toBeVisible();
  await signOut(page);

  // 4. Controller approves (25 %), Head of Operation approves (≤ Rp 2 M) → Locked.
  for (const approver of [CONTROLLER, HOO]) {
    await signIn(page, approver);
    await openRequest(page, 'PRJ-26-900');
    await page.getByRole('button', { name: /^Setujui$/ }).click();
    await expect(page.getByText(/disetujui/i).first()).toBeVisible();
    await signOut(page);
  }

  // 5. Locked: 750 M on EQUIP-OWN exceeds the 710 M available.
  expect(await testCheck(page, projectId, 750_000_000)).toBe(false);

  // 6. Planner releases 40 M contingency to EQUIP-OWN via a BCR.
  await signIn(page, PLANNER);
  await openProject(page);
  await expect(page.getByText(/Baseline v0/)).toBeVisible();
  await page.getByRole('tab', { name: 'BCR' }).click();
  await page.getByLabel('Elemen biaya tujuan').selectOption('EQUIP-OWN');
  await page.getByLabel(/^Nilai/).fill('40.000.000');
  await page.getByLabel(/^Justifikasi/).fill('Tambahan hari sewa peralatan sesuai jadwal klien');
  await page.getByRole('button', { name: 'Ajukan BCR', exact: true }).click();
  const submitted = page.getByText(/BCR-26-\d+ diajukan ke Head of Operation/);
  await expect(submitted).toBeVisible();
  // Specs run in parallel and share the numbering, so read this BCR's number.
  const bcrNumber = /BCR-26-\d+/.exec((await submitted.textContent()) ?? '')![0];
  await signOut(page);

  // 7. Head of Operation approves → v1.
  await signIn(page, HOO);
  await openRequest(page, bcrNumber);
  await page.getByRole('button', { name: /^Setujui$/ }).click();
  await expect(page.getByText(/disetujui/i).first()).toBeVisible();
  await signOut(page);

  await signIn(page, PLANNER);
  await openProject(page);
  await page.getByRole('tab', { name: 'Versi anggaran' }).click();
  await expect(page.getByText('Berjalan = versi v1.')).toBeVisible();
  await expect(page.getByText('+Rp 40.000.000')).toBeVisible();

  // 8. Now 750 M fits.
  expect(await testCheck(page, projectId, 750_000_000)).toBe(true);
});
