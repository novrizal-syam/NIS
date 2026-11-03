import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

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
    quotation: { view: 'own', create: 'own', edit: 'own', submit: 'own', export: 'own' },
  },
});

const BASE = {
  id: 'q1',
  number: 'QT-26-001',
  revision: 0,
  label: 'QT-26-001 Rev.0',
  status: 'draft',
  opportunity_id: 'o1',
  opportunity_number: 'OPP-26-001',
  opportunity_title: 'Well testing Blok X',
  company_name: 'PT Migas Contoh',
  owner_name: 'Citra',
  total_price: '0',
  margin_pct: '0.00',
  margin_warning: false,
  valid_until: null,
  submitted_at: null,
  sent_at: null,
  created_at: '2026-11-01T02:00:00Z',
  subtotal: '0',
  discount_pct: '0',
  discount_amount: '0',
  total_cost: '0',
  margin: '0',
  notes: null,
  terms: 'Harga belum termasuk PPN.',
  revision_reason: null,
  request_id: null,
  decision_comment: null,
  opportunity_stage: 'quotation',
  contact_name: 'Bapak Andi',
  contact_email: 'andi@klien.co.id',
  sent_to_email: null,
  letter: null,
  is_latest: true,
  can_edit: true,
  can_submit: true,
  can_revise: false,
  can_send: false,
  lines: [],
  revisions: [
    {
      id: 'q1',
      revision: 0,
      status: 'draft',
      total_price: '0',
      margin_pct: '0.00',
      reason: null,
      created_at: '2026-11-01T02:00:00Z',
    },
  ],
};

const PRICES = [
  {
    code: 'SRV-PUMP',
    name: 'Pump unit (operating)',
    unit: 'hari',
    unit_cost: '9500000',
    unit_price: '14000000',
  },
];

it('adds lines from the price database and lets the server compute totals', async () => {
  let saved: Record<string, unknown> | null = null;
  const { calls } = mockApi({
    me: ae,
    handlers: {
      'GET /api/quotations/q1': () =>
        json(
          saved
            ? {
                ...BASE,
                subtotal: '35000000',
                total_price: '31500000',
                discount_pct: '10',
                discount_amount: '3500000',
                total_cost: '23750000',
                margin: '7750000',
                margin_pct: '24.60',
                lines: [
                  {
                    price_item_code: 'SRV-PUMP',
                    description: 'Pump unit (operating)',
                    unit: 'hari',
                    qty: '2.5',
                    unit_cost: '9500000',
                    unit_price: '14000000',
                    line_cost: '23750000',
                    line_price: '35000000',
                  },
                ],
              }
            : BASE,
        ),
      'GET /api/quotations/price-items': () => json(PRICES),
      'GET /api/quotations/config': () =>
        json({ margin_warning_pct: '20', email_configured: true }),
      'PUT /api/quotations/q1': (init) => {
        saved = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({ ...BASE });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/penawaran/q1');
  expect(await screen.findByRole('heading', { level: 1, name: 'Penawaran' })).toBeInTheDocument();
  await user.selectOptions(await screen.findByLabelText('Tambah dari database harga'), 'SRV-PUMP');
  const qty = screen.getByLabelText('Qty 1');
  await user.clear(qty);
  await user.type(qty, '2,5');
  expect(screen.getByLabelText('Harga satuan 1')).toHaveValue('14.000.000');
  await user.clear(screen.getByLabelText('Diskon'));
  await user.type(screen.getByLabelText('Diskon'), '10');
  expect(screen.getByText(/belum disimpan/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Simpan & hitung ulang' }));
  await vi.waitFor(() => expect(saved).not.toBeNull());
  expect(saved).toMatchObject({
    discount_pct: '10',
    lines: [
      {
        price_item_code: 'SRV-PUMP',
        qty: '2.5',
        unit_cost: '9500000',
        unit_price: '14000000',
      },
    ],
  });
  expect(await screen.findByText('Rp 31.500.000')).toBeInTheDocument();
  expect(calls.filter((c) => c.key === 'PUT /api/quotations/q1')).toHaveLength(1);
});

it('warns in red when the margin is below 20 %', async () => {
  mockApi({
    me: ae,
    handlers: {
      'GET /api/quotations/q1': () =>
        json({ ...BASE, total_price: '100', margin_pct: '12.50', margin_warning: true }),
      'GET /api/quotations/price-items': () => json(PRICES),
      'GET /api/quotations/config': () =>
        json({ margin_warning_pct: '20', email_configured: true }),
    },
  });
  renderApp('/penawaran/q1');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Margin 12,50% di bawah 20%');
  expect(alert.className).toContain('text-danger');
});

it('sends an approved quotation to the client', async () => {
  const { calls } = mockApi({
    me: ae,
    handlers: {
      'GET /api/quotations/q1': () =>
        json({
          ...BASE,
          status: 'approved',
          can_edit: false,
          can_submit: false,
          can_send: true,
          can_revise: true,
          total_price: '147500000',
          margin_pct: '32.54',
        }),
      'GET /api/quotations/price-items': () => json(PRICES),
      'GET /api/quotations/config': () =>
        json({ margin_warning_pct: '20', email_configured: true }),
      'POST /api/quotations/q1/send': () =>
        json({
          ...BASE,
          status: 'sent',
          letter_number: '001/GEK-SLS/XI/2026',
          email_status: 'queued',
        }),
    },
  });
  const user = userEvent.setup();
  renderApp('/penawaran/q1');
  await user.click(await screen.findByRole('button', { name: /Kirim ke klien/ }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByLabelText(/Email kontak/)).toHaveValue('andi@klien.co.id');
  await user.click(within(dialog).getByRole('button', { name: 'Buat surat & kirim' }));
  expect(
    await within(dialog).findByText(/Surat 001\/GEK-SLS\/XI\/2026 dibuat dan disimpan/),
  ).toBeInTheDocument();
  const body = JSON.parse(
    String(calls.find((c) => c.key === 'POST /api/quotations/q1/send')!.init!.body),
  ) as Record<string, unknown>;
  expect(body).toEqual({ send_email: true, to_email: 'andi@klien.co.id' });
});
