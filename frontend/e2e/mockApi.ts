import type { Page } from '@playwright/test';

const ALL = { view: 'all', create: 'all', approve: 'all' };
const MODULES = [
  'crm',
  'quotation',
  'tender',
  'contract',
  'project',
  'budget',
  'procurement',
  'inventory',
  'operations',
  'maintenance',
  'qhse',
  'billing',
  'finance',
  'treasury',
  'payroll',
  'tax',
  'capex',
  'asset',
  'dms',
  'lms',
  'letters',
  'master',
  'users',
  'settings',
  'audit',
  'workflow',
];

export const ME = {
  id: 'u1',
  email: 'rina@gek.co.id',
  full_name: 'Rina Wijaya',
  department_id: null,
  roles: [{ code: 'super_admin', name: 'Super Admin' }],
  active_role: null,
  permissions: Object.fromEntries(MODULES.map((m) => [m, ALL])),
  pending: [],
  totp_enabled: true,
  totp_required: true,
};

/** Signed-in session without a running backend. */
export async function mockSignedIn(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}`;
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    switch (key) {
      case 'POST /api/auth/refresh':
        return json({ access_token: 'e2e', expires_in: 900 });
      case 'GET /api/auth/me':
        return json(ME);
      case 'GET /api/health':
        return json({ status: 'ok', db: 'ok', version: '0.1.0' });
      default:
        return json({ code: 'NOT_FOUND', message: 'Tidak ada mock.' }, 404);
    }
  });
}

export async function mockSignedOut(page: Page) {
  await page.route('**/api/auth/refresh', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ code: 'REFRESH_INVALID', message: 'Sesi berakhir.' }),
    }),
  );
}
