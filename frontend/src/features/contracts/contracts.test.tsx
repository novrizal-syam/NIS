import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

const hos = makeMe({
  roles: [{ code: 'head_of_sales', name: 'Head of Sales' }],
  permissions: {
    crm: { view: 'all', create: 'all', edit: 'all', submit: 'all', export: 'all' },
    quotation: { view: 'all' },
    contract: { view: 'all', edit: 'all', export: 'all' },
    project: { view: 'all', export: 'all' },
  },
});

const OPP = {
  id: 'o1',
  number: 'OPP-26-001',
  lead_id: null,
  lead_number: null,
  client_code: null,
  company_name: 'PT Migas Contoh',
  title: 'Well testing Blok X',
  owner_id: 'u1',
  owner_name: 'Citra',
  value: '132750000',
  weighted_value: '92925000',
  probability: 70,
  expected_close: null,
  is_tender: false,
  stage: 'submitted',
  bid_status: 'bid',
  lost_reason: null,
  winner_price: null,
  won_at: null,
  lost_at: null,
  is_demo: false,
  contract: null,
  project: null,
  can_edit: true,
  can_submit: true,
  bid_decisions: [],
};

it('marks an opportunity won with the client PO and links contract and project', async () => {
  let won = false;
  const { calls } = mockApi({
    me: hos,
    handlers: {
      'GET /api/crm/opportunities/o1': () =>
        json(
          won
            ? {
                ...OPP,
                stage: 'won',
                contract: { id: 'c1', number: 'CTR-26-001' },
                project: { id: 'p1', number: 'PRJ-26-001' },
              }
            : OPP,
        ),
      'GET /api/quotations': () => json({ items: [], total: 0, counts: {} }),
      'POST /api/crm/opportunities/o1/won': () => {
        won = true;
        return json({
          contract_id: 'c1',
          contract_number: 'CTR-26-001',
          project_id: 'p1',
          project_number: 'PRJ-26-001',
        });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/peluang/o1');
  await user.click(await screen.findByRole('button', { name: /Tandai Menang/ }));
  await user.type(screen.getByLabelText('No. PO/SPK klien'), 'PO-4500012345');
  await user.type(screen.getByLabelText(/Termin pembayaran/), '45');
  await user.click(screen.getByRole('button', { name: 'Buat kontrak & proyek' }));
  expect(await screen.findByRole('link', { name: 'Kontrak CTR-26-001' })).toHaveAttribute(
    'href',
    '/kontrak/c1',
  );
  expect(screen.getByRole('link', { name: 'Proyek PRJ-26-001' })).toHaveAttribute(
    'href',
    '/proyek/p1',
  );
  const body = JSON.parse(
    String(calls.find((c) => c.key === 'POST /api/crm/opportunities/o1/won')!.init!.body),
  ) as Record<string, unknown>;
  expect(body).toEqual({
    po_number: 'PO-4500012345',
    start_date: null,
    end_date: null,
    payment_term_days: 45,
  });
});

it('records the winner price when marking lost', async () => {
  const { calls } = mockApi({
    me: hos,
    handlers: {
      'GET /api/crm/opportunities/o1': () => json(OPP),
      'GET /api/quotations': () => json({ items: [], total: 0, counts: {} }),
      'POST /api/crm/opportunities/o1/stage': () => json({ ...OPP, stage: 'lost' }),
    },
  });
  const user = userEvent.setup();
  renderApp('/peluang/o1');
  await user.click(await screen.findByRole('button', { name: 'Tandai kalah/batal' }));
  await user.type(screen.getByLabelText(/Alasan kalah/), 'Kalah harga 8%');
  await user.type(screen.getByLabelText(/Harga pemenang/), '120.000.000');
  await user.click(screen.getByRole('button', { name: 'Simpan sebagai Lost' }));
  await vi.waitFor(() =>
    expect(calls.some((c) => c.key === 'POST /api/crm/opportunities/o1/stage')).toBe(true),
  );
  const body = JSON.parse(
    String(calls.find((c) => c.key === 'POST /api/crm/opportunities/o1/stage')!.init!.body),
  ) as Record<string, unknown>;
  expect(body).toEqual({ to: 'lost', reason: 'Kalah harga 8%', winner_price: '120000000' });
});

const CONTRACT = {
  id: 'c1',
  number: 'CTR-26-001',
  title: 'Well testing Blok X',
  company_name: 'PT Migas Contoh',
  status: 'active',
  value: '132750000',
  used_value: '0',
  usage_pct: '0.0',
  po_number: 'PO-1',
  start_date: '2027-01-05',
  end_date: '2027-03-31',
  payment_term_days: 45,
  owner_name: 'Citra',
  project_id: 'p1',
  project_number: 'PRJ-26-001',
  opportunity_id: 'o1',
  opportunity_number: 'OPP-26-001',
  quotation_id: 'q1',
  quotation_label: 'QT-26-001 Rev.0',
  can_edit: true,
  rates: [
    {
      id: 'r1',
      kind: 'equipment',
      price_item_code: 'SRV-PUMP',
      cost_element_code: 'EQUIP-OWN',
      description: 'Pump unit (operating)',
      unit: 'hari',
      rate: '12600000',
      standby_rate: null,
      breakdown_rate: '0',
      unit_cost: null,
      markup_pct: null,
      quoted_qty: '10',
    },
  ],
};

it('edits the rate schedule: standby rate and a consumable with markup', async () => {
  let sent: { rates: Record<string, unknown>[] } | null = null;
  mockApi({
    me: hos,
    handlers: {
      'GET /api/contracts/c1': () => json(CONTRACT),
      'PUT /api/contracts/c1/rates': (init) => {
        sent = JSON.parse(String(init!.body)) as { rates: Record<string, unknown>[] };
        return json(CONTRACT);
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/kontrak/c1');
  expect(await screen.findByText('Rp 132.750.000')).toBeInTheDocument();
  await user.type(screen.getByLabelText('Standby 1'), '6.300.000');
  await user.click(screen.getByRole('button', { name: /Tambah tarif/ }));
  await user.selectOptions(screen.getByLabelText('Jenis 2'), 'consumable');
  await user.type(screen.getByLabelText('Uraian 2'), 'Nitrogen');
  await user.clear(screen.getByLabelText('Satuan 2'));
  await user.type(screen.getByLabelText('Satuan 2'), 'm3');
  await user.type(screen.getByLabelText('Biaya satuan 2'), '1.000.000');
  await user.type(screen.getByLabelText('Markup % 2'), '15');
  await user.click(screen.getByRole('button', { name: 'Simpan rate schedule' }));
  await vi.waitFor(() => expect(sent).not.toBeNull());
  expect(sent!.rates[0]).toMatchObject({ kind: 'equipment', standby_rate: '6300000' });
  expect(sent!.rates[1]).toMatchObject({
    kind: 'consumable',
    description: 'Nitrogen',
    unit: 'm3',
    unit_cost: '1000000',
    markup_pct: '15',
  });
});
