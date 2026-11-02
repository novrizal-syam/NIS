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
      case 'GET /api/workflow/inbox/count':
        return json({ count: 2 });
      case 'GET /api/workflow/doc-types':
        return json([
          { code: 'purchase_requisition', label: 'Purchase Requisition', module: 'procurement' },
        ]);
      case 'GET /api/workflow/inbox':
        return json({
          items: [1, 2].map((n) => ({
            request_id: `r${n}`,
            doc_type: 'purchase_requisition',
            doc_type_label: 'Purchase Requisition',
            doc_number: `PR-26-03${n}`,
            title: 'Booster pump seal kit',
            amount: '12500000',
            currency: 'IDR',
            requester_name: 'Budi Engineer',
            submitted_at: '2026-10-07T01:00:00Z',
            step_label: 'Head of Operation',
            due_at: '2026-10-09T01:00:00Z',
            overdue: n === 2,
            escalated: false,
          })),
          total: 2,
          page: 1,
          page_size: 25,
          counts: { purchase_requisition: 2 },
        });
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
