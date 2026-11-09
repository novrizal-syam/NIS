import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

const PNG = 'data:image/png;base64,iVBORw0KGgo=';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
  // jsdom has no canvas: give the signature pad a no-op 2D context.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    fillRect: () => undefined,
    fillText: () => undefined,
    beginPath: () => undefined,
    moveTo: () => undefined,
    lineTo: () => undefined,
    stroke: () => undefined,
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(PNG);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const billing = makeMe({
  roles: [{ code: 'billing_admin', name: 'Billing Admin' }],
  permissions: { billing: { view: 'all', create: 'all', edit: 'all', export: 'all' } },
});

const TICKET = {
  id: 't1',
  number: 'TK-26-001',
  status: 'awaiting_signature',
  status_label: 'Menunggu tanda tangan klien',
  project_id: 'p1',
  project_number: 'PRJ-26-001',
  project_name: 'Well test',
  contract_number: 'CTR-26-001',
  client_name: 'PT KKKS',
  period_from: '2026-11-08',
  period_to: '2026-11-08',
  gross_value: '29033333',
  disputed_value: '0',
  value: '29033333',
  signer_name: null,
  sign_method: null,
  signed_at: null,
  acceptance_no: null,
  psre_ref: null,
  link_email: null,
  link_expires_at: null,
  invoice: null,
  dors: [{ id: 'd1', number: 'DOR-26-001', report_date: '2026-11-08' }],
  can_sign: true,
  lines: [
    {
      id: 'l1',
      seq: 1,
      work_date: '2026-11-08',
      kind: 'equipment',
      description: 'Pump unit AST-PMP',
      qty: '1',
      unit: 'hari',
      amount: '15833333',
      disputed: false,
      dispute_reason: null,
    },
    {
      id: 'l2',
      seq: 2,
      work_date: '2026-11-08',
      kind: 'consumable',
      description: 'Demulsifier',
      qty: '2',
      unit: 'drum',
      amount: '13200000',
      disputed: false,
      dispute_reason: null,
    },
  ],
};

it('signs on the tablet with a disputed line and a reason', async () => {
  let body: Record<string, unknown> | null = null;
  mockApi({
    me: billing,
    handlers: {
      'GET /api/billing/tickets/t1': () => json(TICKET),
      'POST /api/billing/tickets/t1/sign': (init) => {
        body = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({ ...TICKET, status: 'signed', can_sign: false });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/tagihan/tiket/t1');
  await user.click(await screen.findByRole('button', { name: /Tanda tangan di tablet/ }));
  const sign = screen.getByRole('button', { name: /^Tanda tangani$/ });
  expect(sign).toBeDisabled();
  await user.click(screen.getByLabelText('Dispute Demulsifier'));
  expect(screen.getByText(/Nilai disetujui/).parentElement).toHaveTextContent('Rp 15.833.333');
  await user.type(screen.getByLabelText(/Nama penanda tangan/), 'Pak Rep');
  await user.type(screen.getByLabelText(/Atau ketik nama/), 'Pak Rep');
  expect(sign).toBeDisabled(); // dispute reason still empty
  await user.type(screen.getByLabelText('Alasan dispute Demulsifier'), 'Belum disepakati');
  await user.type(screen.getByLabelText(/No. BAST\/SES/), 'SES-1');
  await user.click(sign);
  await vi.waitFor(() => expect(body).not.toBeNull());
  expect(body).toEqual({
    signer_name: 'Pak Rep',
    signature: PNG,
    acceptance_no: 'SES-1',
    disputes: [{ line_id: 'l2', reason: 'Belum disepakati' }],
  });
});

it('shows invoice tax amounts and requires a faktur number to issue', async () => {
  mockApi({
    me: billing,
    handlers: {
      'GET /api/billing/invoices/i1': () =>
        json({
          id: 'i1',
          number: 'INV-26-001',
          status: 'draft',
          status_label: 'Draf',
          client_code: 'C-1',
          client_name: 'PT KKKS',
          invoice_date: '2026-11-09',
          due_date: '2026-12-09',
          faktur_number: null,
          subtotal: '15833333',
          total: '17575000',
          outstanding: '17575000',
          overdue: false,
          client_email: 'ap@kkks.co.id',
          contract_number: 'CTR-26-001',
          dpp_other: '14513889',
          ppn_rate: '12',
          ppn: '1741667',
          pph23_rate: '2',
          pph23_expected: '316667',
          net_cash: '17258333',
          stamp_duty: '10000',
          faktur_date: null,
          sent_at: null,
          sent_to: null,
          paid_amount: '0',
          pph23_withheld: '0',
          paid_at: null,
          pack_attachment_id: null,
          note: null,
          tickets: [{ id: 't1', number: 'TK-26-001', value: '15833333', acceptance_no: 'SES-1' }],
          receipts: [],
        }),
    },
  });
  renderApp('/tagihan/invoice/i1');
  expect(await screen.findByText('DPP nilai lain (11/12)')).toBeInTheDocument();
  expect(screen.getByText('Rp 14.513.889')).toBeInTheDocument();
  expect(screen.getByText('Rp 1.741.667')).toBeInTheDocument();
  expect(screen.getByText('Rp 17.258.333')).toBeInTheDocument();
  expect(screen.getByText(/Bea meterai Rp 10.000/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Terbitkan faktur/ })).toBeDisabled();
});
