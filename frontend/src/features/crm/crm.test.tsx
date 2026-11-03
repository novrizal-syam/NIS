import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';
import { scorePercent } from './api';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

const ae = makeMe({
  id: 'ae1',
  roles: [{ code: 'account_executive', name: 'Account Executive' }],
  permissions: {
    crm: { view: 'own', create: 'own', edit: 'own', submit: 'own', export: 'own' },
  },
});

const CONFIG = {
  sources: [],
  qualification: [],
  min_qualified: 3,
  scores: [],
  bid_threshold: '60',
  win_rate_target: '45',
  contract_target: '80000000000',
};

const LEAD = {
  id: 'l1',
  number: 'LD-26-001',
  client_code: null,
  company_name: 'PT Migas Contoh',
  contact_name: 'Bapak Andi',
  contact_email: null,
  contact_phone: null,
  source: 'civd',
  need: 'Well testing 3 sumur',
  estimated_value: '4500000000',
  status: 'contacted',
  disqualify_reason: null,
  qualification: { budget: true, technical_fit: true },
  qualification_count: 2,
  owner_id: 'ae1',
  owner_name: 'Citra',
  opportunity_id: null,
  opportunity_number: null,
  created_at: '2026-11-01T02:00:00Z',
  status_changed_at: null,
  is_demo: false,
};

const OPP = {
  id: 'o1',
  number: 'OPP-26-001',
  lead_id: 'l1',
  lead_number: 'LD-26-001',
  client_code: null,
  company_name: 'PT Migas Contoh',
  title: 'Well testing Blok X',
  owner_id: 'ae1',
  owner_name: 'Citra',
  value: '4500000000',
  weighted_value: '1800000000',
  probability: 40,
  expected_close: null,
  is_tender: false,
  stage: 'qualified',
  bid_status: 'none',
  lost_reason: null,
  won_at: null,
  lost_at: null,
  is_demo: false,
};

const SUMMARY = {
  qualified: { count: 1, value: '4500000000' },
  quotation: { count: 0, value: '0' },
  submitted: { count: 0, value: '0' },
  won: { count: 0, value: '0' },
  lost: { count: 0, value: '0' },
};

it('computes the bid score like the backend', () => {
  const s = (v: number[]) =>
    Object.fromEntries(
      ['strategic_fit', 'technical', 'availability', 'csms', 'margin', 'risk'].map((k, i) => [
        k,
        v[i]!,
      ]),
    );
  expect(scorePercent(s([3, 3, 3, 3, 3, 3]))).toBe(60);
  expect(scorePercent(s([3, 3, 3, 3, 3, 2]))).toBe(56.67);
  expect(scorePercent({ strategic_fit: 5 })).toBeNull();
});

it('lists leads and qualifies only with at least 3 of 5 criteria', async () => {
  const { calls } = mockApi({
    me: ae,
    handlers: {
      'GET /api/crm/config': () => json(CONFIG),
      'GET /api/crm/leads': () =>
        json({
          items: [LEAD],
          total: 1,
          counts: { new: 0, contacted: 1, qualified: 0, disqualified: 0 },
        }),
      'GET /api/crm/leads/l1': () => json(LEAD),
      'GET /api/master/clients/options': () => json([]),
      'PATCH /api/crm/leads/l1': () =>
        json({ ...LEAD, qualification: { ...LEAD.qualification, start_6m: true } }),
      'POST /api/crm/leads/l1/status': () => json({ ...LEAD, status: 'qualified' }),
    },
  });
  const user = userEvent.setup();
  renderApp('/lead');
  expect(await screen.findByRole('heading', { level: 1, name: 'Lead' })).toBeInTheDocument();
  expect(await screen.findByText('Rp 4.500.000.000')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'LD-26-001' }));
  const dialog = await screen.findByRole('dialog');
  expect(await within(dialog).findByText(/2 dari 5 terpenuhi/)).toBeInTheDocument();
  const qualify = within(dialog).getByRole('button', { name: 'Kualifikasi' });
  expect(qualify).toBeDisabled();
  await user.click(within(dialog).getByLabelText('Mulai dalam 6 bulan'));
  expect(within(dialog).getByText(/3 dari 5 terpenuhi/)).toBeInTheDocument();
  await user.click(qualify);
  await vi.waitFor(() =>
    expect(calls.some((c) => c.key === 'POST /api/crm/leads/l1/status')).toBe(true),
  );
  const patch = JSON.parse(
    String(calls.find((c) => c.key === 'PATCH /api/crm/leads/l1')!.init!.body),
  ) as { qualification: Record<string, boolean> };
  expect(patch.qualification).toMatchObject({ budget: true, technical_fit: true, start_6m: true });
  const status = JSON.parse(
    String(calls.find((c) => c.key === 'POST /api/crm/leads/l1/status')!.init!.body),
  ) as Record<string, unknown>;
  expect(status).toEqual({ to: 'qualified' });
});

it('shows the pipeline as a kanban board by stage', async () => {
  mockApi({
    me: ae,
    handlers: {
      'GET /api/crm/opportunities': () => json({ items: [OPP], total: 1, summary: SUMMARY }),
    },
  });
  renderApp('/peluang');
  const column = await screen.findByRole('region', { name: 'Qualified' });
  expect(await within(column).findByText('Well testing Blok X')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Won' })).getByText('Kosong')).toBeVisible();
});

it('recommends from the scores and asks for a reason when the proposal differs', async () => {
  const { calls } = mockApi({
    me: ae,
    handlers: {
      'GET /api/crm/config': () => json(CONFIG),
      'GET /api/crm/opportunities/o1': () =>
        json({ ...OPP, can_edit: true, can_submit: true, bid_decisions: [] }),
      'POST /api/crm/opportunities/o1/bid-decision': () =>
        json({ request_id: 'r1', percent: '56.67', recommendation: 'no_bid' }, 201),
    },
  });
  const user = userEvent.setup();
  renderApp('/peluang/o1');
  expect(await screen.findByText('Keputusan bid/no-bid')).toBeInTheDocument();
  const labels = [
    'Kesesuaian strategis (RJPP)',
    'Kemampuan teknis',
    'Ketersediaan aset & kru',
    'CSMS & kepatuhan',
    'Margin',
    'Risiko komersial & hukum',
  ];
  for (const [i, label] of labels.entries())
    await user.selectOptions(
      screen.getByLabelText(new RegExp(`^${label.replace(/[()&]/g, '\\$&')}`)),
      i === 5 ? '2' : '3',
    );
  expect(screen.getByText('56,67%')).toBeInTheDocument();
  expect(screen.getByText('Rekomendasi: no-bid')).toBeInTheDocument();

  await user.click(screen.getByLabelText('Bid'));
  const submit = screen.getByRole('button', { name: 'Ajukan ke Direktur' });
  expect(submit).toBeDisabled();
  await user.type(screen.getByLabelText(/Catatan/), 'Klien strategis untuk RJPP');
  expect(submit).toBeEnabled();
  await user.click(submit);
  await vi.waitFor(() =>
    expect(calls.some((c) => c.key === 'POST /api/crm/opportunities/o1/bid-decision')).toBe(true),
  );
  const body = JSON.parse(
    String(calls.find((c) => c.key === 'POST /api/crm/opportunities/o1/bid-decision')!.init!.body),
  ) as { scores: Record<string, number>; proposal: string; note: string };
  expect(body.proposal).toBe('bid');
  expect(body.scores.risk).toBe(2);
  expect(body.note).toBe('Klien strategis untuk RJPP');
});

it('shows sales tiles on the dashboard', async () => {
  mockApi({
    me: ae,
    handlers: {
      'GET /api/crm/dashboard': () =>
        json({
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
          scope: 'own',
        }),
    },
  });
  renderApp('/');
  expect(await screen.findByText('Rp 12.000.000.000')).toBeInTheDocument();
  expect(screen.getByText('40,0%')).toBeInTheDocument();
  expect(screen.getByText('Target 45%')).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '25');
  expect(screen.getByText('dari target Rp 80.000.000.000')).toBeInTheDocument();
});
