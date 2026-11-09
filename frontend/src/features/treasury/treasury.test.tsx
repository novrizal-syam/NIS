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

const apAccountant = makeMe({
  roles: [{ code: 'ap_accountant', name: 'AP Accountant' }],
  permissions: {
    treasury: { view: 'all', create: 'all', edit: 'all', submit: 'all' },
  },
});

const ACCOUNT = {
  id: 'ba1',
  code: 'BA-MDR-IDR',
  name: 'Mandiri Operasional IDR',
  bank_name: 'Bank Mandiri',
  account_no: '123',
  currency: 'IDR',
  gl_account: '1110',
  adapter: 'csv',
  is_default: true,
  is_active: true,
  balance: '100000000',
  unreconciled_statement_lines: 0,
};

it('builds a payment run from due invoices and liabilities', async () => {
  let body: Record<string, unknown> | null = null;
  mockApi({
    me: apAccountant,
    handlers: {
      'GET /api/treasury/payment-runs': () => json([]),
      'GET /api/treasury/bank-accounts': () => json([ACCOUNT]),
      'GET /api/treasury/payment-runs/due-items': () =>
        json({
          invoices: [
            {
              vendor_invoice_id: 'vi1',
              number: 'VI-26-001',
              invoice_no: 'INV/ALFA/12',
              vendor_code: 'V-A',
              vendor_name: 'PT Alfa Sewa',
              due_date: '2026-11-10',
              outstanding: '49000000',
              pph23: '1000000',
            },
          ],
          liabilities: [{ kind: 'bpjs', label: 'BPJS', outstanding: '3000000' }],
        }),
      'POST /api/treasury/payment-runs': (init) => {
        body = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({ id: 'run1' });
      },
      'GET /api/treasury/payment-runs/run1': () =>
        json({
          id: 'run1',
          number: 'PAY-26-001',
          pay_date: '2026-11-09',
          bank_account: { id: 'ba1', code: 'BA-MDR-IDR', name: 'Mandiri Operasional IDR' },
          description: null,
          total: '52000000',
          status: 'draft',
          request_id: null,
          reject_reason: null,
          created_by: null,
          released_at: null,
          journal_id: null,
          bank_file_ref: null,
          items: [],
          bukti_potong_vendors: [],
        }),
    },
  });
  const user = userEvent.setup();
  renderApp('/keuangan/treasury?tab=runs');
  await user.click(await screen.findByRole('button', { name: /Payment run baru/ }));
  await user.click(await screen.findByRole('checkbox', { name: 'VI-26-001' }));
  await user.click(screen.getByRole('checkbox', { name: 'BPJS' }));
  const amount = screen.getByLabelText('Dibayar VI-26-001');
  await user.clear(amount);
  await user.type(amount, '20.000.000');
  expect(screen.getByText(/Total: Rp\s*23\.000\.000/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Buat payment run' }));
  await vi.waitFor(() => expect(body).not.toBeNull());
  expect(body).toMatchObject({
    bank_account_id: 'ba1',
    items: [
      { kind: 'vendor_invoice', vendor_invoice_id: 'vi1', amount: '20000000' },
      { kind: 'bpjs', amount: '3000000' },
    ],
  });
  expect(await screen.findByText(/PAY-26-001/)).toBeInTheDocument();
});
