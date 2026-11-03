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
  phone: '0812000000',
  photo_attachment_id: null,
  signature_attachment_id: null,
  tour_done: true,
  employee_code: null,
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
      case 'GET /api/crm/dashboard':
        return json({
          year: 2026,
          open_count: 3,
          open_pipeline: '12000000000',
          weighted_pipeline: '5000000000',
          won_count: 2,
          lost_count: 3,
          win_rate: '40.0',
          win_rate_target: '45',
          new_contract_value: '20000000000',
          contract_target: '80000000000',
          scope: 'all',
        });
      case 'GET /api/crm/leads':
        return json({
          items: [
            {
              id: 'l1',
              number: 'LD-26-001',
              client_code: null,
              company_name: 'PT Migas Hulu Contoh',
              contact_name: 'Bapak Andi',
              contact_email: null,
              contact_phone: null,
              source: 'civd',
              need: 'Well testing 3 sumur, Q1 2027',
              estimated_value: '4500000000',
              status: 'contacted',
              disqualify_reason: null,
              qualification: {},
              qualification_count: 0,
              owner_id: 'u1',
              owner_name: 'Rina Wijaya',
              opportunity_id: null,
              opportunity_number: null,
              created_at: '2026-11-01T02:00:00Z',
              is_demo: false,
            },
          ],
          total: 1,
          counts: { new: 0, contacted: 1, qualified: 0, disqualified: 0 },
        });
      case 'GET /api/crm/opportunities': {
        const stages = ['qualified', 'quotation', 'submitted', 'won', 'lost'] as const;
        return json({
          items: stages.map((stage, i) => ({
            id: `o${i}`,
            number: `OPP-26-00${i + 1}`,
            lead_id: null,
            lead_number: null,
            client_code: null,
            company_name: 'PT Energi Rokan Hulu',
            title: 'Well clean-up 4 sumur Rokan',
            owner_id: 'u1',
            owner_name: 'Rina Wijaya',
            value: '6800000000',
            weighted_value: '2720000000',
            probability: 40,
            expected_close: null,
            is_tender: i === 1,
            stage,
            bid_status: i === 0 ? 'pending' : 'bid',
            lost_reason: null,
            won_at: null,
            lost_at: null,
            is_demo: false,
          })),
          total: 5,
          summary: Object.fromEntries(stages.map((s) => [s, { count: 1, value: '6800000000' }])),
        });
      }
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
