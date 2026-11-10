import { screen } from '@testing-library/react';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

it('sends external vendor users to their portal with RFQs and invoice status', async () => {
  mockApi({
    me: makeMe({
      roles: [{ code: 'vendor', name: 'Vendor' }],
      permissions: { portal: { view: 'own', create: 'own' } },
    }),
    handlers: {
      'GET /api/portal/me': () =>
        json({ client: null, vendor: { code: 'V-A', name: 'PT Alfa Sewa' } }),
      'GET /api/portal/vendor/rfqs': () =>
        json([
          {
            quote_id: 'q1',
            rfq: 'RFQ-26-004',
            due_date: '2026-11-20',
            open: true,
            status: 'invited',
            total: null,
          },
        ]),
      'GET /api/portal/vendor/invoices': () =>
        json({
          submissions: [
            {
              id: 's1',
              po_number: 'PO-26-010',
              invoice_no: 'INV/A/77',
              amount: '8000000',
              status: 'rejected',
              reject_reason: 'Faktur belum ada',
            },
          ],
          invoices: [],
        }),
    },
  });
  renderApp('/');
  expect(await screen.findByText('Undangan RFQ PT Alfa Sewa')).toBeInTheDocument();
  expect(await screen.findByText('RFQ-26-004')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Ajukan penawaran' })).toBeInTheDocument();
  expect(await screen.findByText(/Dikembalikan — Faktur belum ada/)).toBeInTheDocument();
});
