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

const apAccountant = makeMe({
  roles: [{ code: 'ap_accountant', name: 'AP Accountant' }],
  permissions: {
    finance: { view: 'all', create: 'all', edit: 'all', submit: 'all', export: 'all' },
  },
});

const PREFILL = {
  po_id: 'po1',
  po_number: 'PO-26-001',
  vendor_code: 'V-A',
  vendor_name: 'PT Alfa Sewa',
  vendor_npwp: null,
  term_days: 30,
  kind: 'service',
  ppn_pct: '11',
  lines: [
    {
      seq: 1,
      description: 'Sewa genset (hari)',
      uom: 'hari',
      po_qty: '10',
      received: '4',
      invoiced: '0',
      open: '4',
      unit_price: '2000000',
    },
  ],
};

it('prefills received quantities and shows taxes before saving', async () => {
  let body: Record<string, unknown> | null = null;
  mockApi({
    me: apAccountant,
    handlers: {
      'GET /api/finance/vendor-invoices/po-options': () =>
        json([{ id: 'po1', number: 'PO-26-001', vendor_name: 'PT Alfa Sewa', status: 'issued' }]),
      'GET /api/finance/vendor-invoices/prefill/po1': () => json(PREFILL),
      'POST /api/finance/vendor-invoices': (init) => {
        body = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({ id: 'vi1' }, 201);
      },
      'GET /api/finance/vendor-invoices/vi1': () => json({}),
    },
  });
  const user = userEvent.setup();
  renderApp('/keuangan/tagihan-vendor/baru');
  await screen.findByRole('option', { name: /PO-26-001/ });
  await user.selectOptions(screen.getByLabelText(/^PO/), 'po1');
  expect(await screen.findByLabelText(/Qty Sewa genset/)).toHaveValue('4');
  // No NPWP: PPh 23 doubles to 4 %. DPP 8 jt, PPN 880 rb, PPh 320 rb -> payable 8.560.000.
  expect(screen.getByText('Vendor tanpa NPWP: tarif PPh 23 dua kali lipat (4%).')).toBeVisible();
  expect(screen.getByText('PPh 23 (4%)').nextSibling).toHaveTextContent('Rp 320.000');
  expect(screen.getByText('Rp 8.560.000')).toBeInTheDocument();
  await user.type(screen.getByLabelText(/No. invoice vendor/), 'INV/ALFA/0012');
  await user.click(screen.getByRole('button', { name: /Simpan draf/ }));
  await vi.waitFor(() => expect(body).not.toBeNull());
  expect(body).toMatchObject({
    po_id: 'po1',
    invoice_no: 'INV/ALFA/0012',
    kind: 'service',
    dpp: '8000000',
    ppn: null,
    term_days: 30,
    lines: [{ seq: 1, qty: '4', unit_price: '2000000' }],
  });
});

it('shows a match exception with the failing checks and the credit-note action', async () => {
  mockApi({
    me: apAccountant,
    handlers: {
      'GET /api/finance/vendor-invoices/vi1': () =>
        json({
          id: 'vi1',
          number: 'VI-26-001',
          status: 'exception',
          status_label: 'Selisih pencocokan',
          vendor_code: 'V-A',
          vendor_name: 'PT Alfa Sewa',
          vendor_npwp: '01.234.567.8-901.000',
          po_id: 'po1',
          po_number: 'PO-26-001',
          project_number: 'PRJ-26-001',
          invoice_no: 'INV/ALFA/0012',
          tax_invoice_no: null,
          invoice_date: '2026-11-09',
          kind: 'service',
          term_days: 30,
          due_date: null,
          dpp: '12600000',
          ppn: '1386000',
          pph23_pct: '2',
          pph23: '252000',
          payable: '13734000',
          paid_amount: '0',
          outstanding: '13734000',
          note: null,
          exception_reason:
            'Baris 1 (Sewa genset (hari)): ditagih 6, diterima belum ditagih 4 hari.',
          match_result: [
            {
              seq: 1,
              description: 'Sewa genset (hari)',
              uom: 'hari',
              po_qty: '10.00',
              received: '4.00',
              invoiced_before: '0',
              qty: '6.00',
              po_price: '2000000',
              price: '2100000',
              qty_ok: false,
              price_ok: false,
            },
          ],
          journal: null,
          credit_notes: [],
          can_edit: true,
          can_match: false,
          can_credit_note: true,
          lines: [
            {
              seq: 1,
              description: 'Sewa genset (hari)',
              qty: '6',
              unit_price: '2100000',
              amount: '12600000',
            },
          ],
        }),
      'GET /api/attachments': () => json([]),
    },
  });
  const user = userEvent.setup();
  renderApp('/keuangan/tagihan-vendor/vi1');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Tidak cocok — tidak dapat dibayar.');
  expect(alert).toHaveTextContent('diterima belum ditagih 4');
  const row = screen.getByRole('row', { name: /Sewa genset/ });
  expect(within(row).getAllByRole('img', { name: 'Tidak sesuai' })).toHaveLength(2);
  expect(screen.queryByRole('button', { name: /Cocokkan/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Nota kredit/ }));
  expect(screen.getByLabelText(/No. nota kredit/)).toBeInTheDocument();
});
