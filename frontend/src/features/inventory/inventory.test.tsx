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

const warehouseHead = makeMe({
  roles: [{ code: 'warehouse_head', name: 'Warehouse Head' }],
  permissions: {
    inventory: { view: 'all', create: 'all', edit: 'all', submit: 'all', export: 'all' },
    procurement: { view: 'all' },
  },
});

const RECEIVABLE = {
  po_id: 'po1',
  po_number: 'PO-26-001',
  po_status: 'issued',
  vendor_name: 'PT Kimia Jaya',
  kind: 'goods',
  can_receive: true,
  lines: [
    {
      seq: 1,
      item_code: 'ITM-004',
      description: 'Demulsifier',
      uom: 'drum',
      ordered: '10',
      received: '4',
      open: '6',
      unit_price: '6000000',
    },
  ],
};

it('receives a partial quantity and refuses more than is open', async () => {
  let body: Record<string, unknown> | null = null;
  mockApi({
    me: warehouseHead,
    handlers: {
      'GET /api/inventory/receivable/po1': () => json(RECEIVABLE),
      'GET /api/inventory/warehouses': () =>
        json([{ code: 'WH-CLG', name: 'Base Cilegon', kind: 'base', project_code: null }]),
      'POST /api/inventory/grs': (init) => {
        body = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({ id: 'gr1' }, 201);
      },
      'GET /api/inventory/grs/gr1': () => json({}),
    },
  });
  const user = userEvent.setup();
  renderApp('/gudang/gr/baru?po=po1');
  const qty = await screen.findByLabelText(/Terima sekarang Demulsifier/);
  expect(qty).toHaveValue('6'); // defaults to the open quantity (full receipt)
  const save = screen.getByRole('button', { name: /Simpan draf GR/ });
  await user.clear(qty);
  await user.type(qty, '7');
  expect(screen.getByText('Jumlah melebihi sisa yang belum diterima.')).toBeInTheDocument();
  expect(save).toBeDisabled();
  await user.clear(qty);
  await user.type(qty, '4');
  await user.selectOptions(screen.getByLabelText(/Masuk ke gudang/), 'WH-CLG');
  expect(screen.getByText('Rp 24.000.000')).toBeInTheDocument();
  await user.click(save);
  await vi.waitFor(() => expect(body).not.toBeNull());
  expect(body).toMatchObject({
    po_id: 'po1',
    warehouse_code: 'WH-CLG',
    lines: [{ seq: 1, qty: '4' }],
  });
});

it('shows how an MR was split between site, base and a PR', async () => {
  mockApi({
    me: warehouseHead,
    handlers: {
      'GET /api/inventory/mrs/m1': () =>
        json({
          id: 'm1',
          number: 'MR-26-001',
          status: 'partial',
          status_label: 'Sebagian dikeluarkan, sisanya PR',
          project_id: 'p1',
          project_number: 'PRJ-26-001',
          project_name: 'Well testing',
          wbs_code: 'EXEC',
          cost_element_code: 'CONSUMABLE',
          site_warehouse: 'WH-RKN',
          base_warehouse: 'WH-CLG',
          requester_name: 'Field Engineer',
          need_date: '2026-12-01',
          purpose: 'Treatment sumur RK-12',
          issued_value: '30000000',
          created_at: '2026-11-09T01:00:00Z',
          pr: { id: 'pr9', number: 'PR-26-009', status: 'awaiting_approval' },
          journal: {
            number: 'JV-26-0001',
            entry_date: '2026-11-09',
            total: '30000000',
            lines: [
              {
                account_code: '5300',
                debit: '30000000',
                credit: '0',
                cost_element_code: 'CONSUMABLE',
                partner_code: null,
              },
              {
                account_code: '1310',
                debit: '0',
                credit: '30000000',
                cost_element_code: null,
                partner_code: null,
              },
            ],
          },
          lines: [
            {
              seq: 1,
              item_code: 'ITM-004',
              name: 'Demulsifier',
              uom: 'drum',
              qty: '8',
              from_site: '2',
              from_base: '3',
              shortfall: '3',
              value: '30000000',
            },
          ],
        }),
    },
  });
  renderApp('/gudang/mr/m1');
  const row = (await screen.findByText('Demulsifier')).closest('tr')!;
  expect(
    within(row)
      .getAllByRole('cell')
      .map((c) => c.textContent),
  ).toEqual(['DemulsifierITM-004 · drum', '8', '2', '3', '3', 'Rp 30.000.000']);
  expect(screen.getByRole('link', { name: 'PR-26-009' })).toHaveAttribute(
    'href',
    '/pengadaan/pr/pr9',
  );
  expect(screen.getByText(/JV-26-0001/)).toBeInTheDocument();
  expect(screen.getByText(/5300 · Bahan habis pakai/)).toBeInTheDocument();
});

it('flags a valuation that does not reconcile to account 1310', async () => {
  mockApi({
    me: warehouseHead,
    handlers: {
      'GET /api/inventory/stock': () => json({ items: [], total: 0, total_value: '0' }),
      'GET /api/inventory/valuation': () =>
        json({
          rows: [],
          total: '60000000',
          ledger_1310: '59000000',
          difference: '1000000',
          reconciled: false,
        }),
    },
  });
  const user = userEvent.setup();
  renderApp('/gudang/stok');
  await user.click(await screen.findByRole('tab', { name: 'Valuasi' }));
  expect(await screen.findByRole('status')).toHaveTextContent(/berbeda Rp 1.000.000/);
});
