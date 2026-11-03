import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';
import { daysUntil, fromJakartaInput, toJakartaInput } from './api';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

const ts = makeMe({
  roles: [{ code: 'tender_specialist', name: 'Tender Specialist' }],
  permissions: {
    tender: { view: 'all', create: 'all', edit: 'all', submit: 'all', export: 'all' },
    crm: { view: 'all' },
  },
});

const DOC = {
  id: 'd1',
  section: 'admin',
  name: 'Sertifikat CSMS',
  mandatory: true,
  not_applicable: false,
  expiry_date: '2026-10-01',
  note: null,
  files: 1,
  status: 'missing',
  expired: true,
};

const TENDER = {
  id: 't1',
  opportunity_id: 'o1',
  opportunity_number: 'OPP-26-001',
  opportunity_title: 'Tender well testing',
  opportunity_stage: 'quotation',
  company_name: 'PT KKKS',
  owner_name: 'Citra',
  tender_number: 'TND-2026-0042',
  method: 'open',
  closing_at: '2026-11-08T07:00:00Z',
  price: null,
  package_status: 'none',
  submitted_at: null,
  result: null,
  aanwijzing_at: null,
  clarification_deadline: null,
  opening_at: null,
  bid_validity_until: null,
  bid_bond_required: false,
  bid_bond_amount: null,
  bid_bond_number: null,
  tkdn_required_pct: null,
  tkdn_offered_pct: null,
  request_id: null,
  submission_channel: null,
  receipt_number: null,
  result_at: null,
  rank: null,
  winner_name: null,
  winning_price: null,
  lessons_learned: null,
  readiness: {
    ready: false,
    missing: ['Sertifikat CSMS'],
    problems: ['1 dokumen wajib belum ada atau kedaluwarsa', 'harga penawaran belum diisi'],
  },
  can_edit: true,
  can_submit_package: true,
  documents: [DOC],
  clarifications: [],
};

it('converts Jakarta wall-clock time for datetime inputs', () => {
  expect(toJakartaInput('2026-11-08T07:00:00Z')).toBe('2026-11-08T14:00');
  expect(fromJakartaInput('2026-11-08T14:00')).toBe('2026-11-08T14:00:00+07:00');
  expect(fromJakartaInput('')).toBeNull();
  expect(daysUntil('2026-11-10T00:00:00Z', Date.parse('2026-11-08T00:00:00Z'))).toBe(2);
});

it('keeps the package button disabled and lists what is missing', async () => {
  mockApi({ me: ts, handlers: { 'GET /api/tenders/t1': () => json(TENDER) } });
  const user = userEvent.setup();
  renderApp('/tender/t1');
  await user.click(await screen.findByRole('tab', { name: /Dokumen/ }));
  expect(screen.getByText('Kedaluwarsa')).toBeInTheDocument();
  await user.click(screen.getByRole('tab', { name: 'Pengajuan & hasil' }));
  expect(screen.getByRole('button', { name: /Ajukan paket/ })).toBeDisabled();
  const problems = screen.getByRole('list', { name: 'Belum siap diajukan' });
  expect(within(problems).getByText(/harga penawaran belum diisi/)).toBeInTheDocument();
});

it('submits the package when ready', async () => {
  const ready = {
    ...TENDER,
    price: '950000000',
    documents: [{ ...DOC, status: 'present', expired: false, expiry_date: null }],
    readiness: { ready: true, missing: [], problems: [] },
  };
  const { calls } = mockApi({
    me: ts,
    handlers: {
      'GET /api/tenders/t1': () => json(ready),
      'POST /api/tenders/t1/submit-package': () =>
        json({ ...ready, package_status: 'pending', can_submit_package: false, request_id: 'r1' }),
    },
  });
  const user = userEvent.setup();
  renderApp('/tender/t1');
  await user.click(await screen.findByRole('tab', { name: 'Pengajuan & hasil' }));
  await user.click(screen.getByRole('button', { name: /Ajukan paket/ }));
  await vi.waitFor(() =>
    expect(calls.some((c) => c.key === 'POST /api/tenders/t1/submit-package')).toBe(true),
  );
});

it('lists tenders closing within 7 days on the dashboard', async () => {
  mockApi({
    me: ts,
    handlers: {
      'GET /api/tenders/closing-soon': () =>
        json([
          {
            ...TENDER,
            closing_at: new Date(Date.now() + 2 * 86_400_000).toISOString(),
            missing: 3,
          },
        ]),
    },
  });
  renderApp('/');
  expect(await screen.findByText('Tender tutup ≤ 7 hari')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'TND-2026-0042' })).toHaveAttribute('href', '/tender/t1');
  expect(screen.getByText('3 dokumen kurang')).toBeInTheDocument();
  expect(screen.getByText('2 hari lagi')).toBeInTheDocument();
});
