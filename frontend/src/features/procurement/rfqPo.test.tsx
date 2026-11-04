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

const officer = makeMe({
  roles: [{ code: 'procurement_officer', name: 'Procurement Officer' }],
  permissions: {
    procurement: { view: 'all', create: 'all', edit: 'all', submit: 'all', export: 'all' },
  },
});

const quote = (code: string, name: string, total: string, days: number, score: string) => ({
  id: `q-${code}`,
  vendor_code: code,
  vendor_name: name,
  rating: '4.0',
  status: 'quoted',
  total,
  delivery_days: days,
  payment_terms: '30 hari',
  valid_until: null,
  note: null,
  lines: [{ seq: 1, unit_price: total, amount: total }],
  score: { vendor_code: code, price: '0', delivery: '0', rating: '0', total: score },
});

const RFQ = {
  id: 'r1',
  number: 'RFQ-26-001',
  status: 'open',
  category: 'equipment_rental',
  due_date: null,
  pr_id: 'pr1',
  pr_number: 'PR-26-001',
  pr_total: '40000000',
  awarded_vendor_code: null,
  award_reason: null,
  pending_vendor_code: null,
  request_id: null,
  best_vendor_code: 'V-C',
  weights: { price: '60', delivery: '20', rating: '20' },
  po: null,
  can_edit: true,
  can_create_po: false,
  pr_lines: [
    {
      seq: 1,
      item_code: null,
      description: 'Sewa genset',
      qty: '1',
      uom: 'lot',
      est_price: '40000000',
    },
  ],
  quotes: [
    quote('V-A', 'PT Alfa Sewa', '40000000', 10, '80.00'),
    quote('V-B', 'PT Beta Rental', '36000000', 20, '85.00'),
    quote('V-C', 'PT Citra Genset', '38000000', 5, '88.84'),
  ],
};

it('marks the best score and requires a reason to award another vendor', async () => {
  let body: Record<string, unknown> | null = null;
  mockApi({
    me: officer,
    handlers: {
      'GET /api/procurement/rfqs/r1': () => json(RFQ),
      'POST /api/procurement/rfqs/r1/award': (init) => {
        body = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({
          ...RFQ,
          status: 'award_pending',
          pending_vendor_code: 'V-B',
          approval_needed: true,
        });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/pengadaan/rfq/r1');
  const best = (await screen.findByText('PT Citra Genset')).closest('tr')!;
  expect(within(best).getByText('Terbaik')).toBeInTheDocument();
  expect(within(best).getByText('88.84')).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText('Pemenang'), 'V-B');
  const submit = screen.getByRole('button', { name: 'Ajukan penetapan' });
  expect(submit).toBeDisabled();
  await user.type(
    screen.getByLabelText(/Alasan memilih vendor ini/),
    'Unit lebih baru dan siap kirim',
  );
  await user.click(submit);
  await vi.waitFor(() => expect(body).not.toBeNull());
  expect(body).toEqual({ vendor_code: 'V-B', reason: 'Unit lebih baru dan siap kirim' });
});

it('does not allow selecting CSMS pending or blacklisted vendors', async () => {
  mockApi({
    me: officer,
    handlers: {
      'GET /api/procurement/prs/pr1': () =>
        json({
          id: 'pr1',
          number: 'PR-26-001',
          status: 'approved',
          project_id: 'p1',
          project_number: 'PRJ-26-001',
          project_name: 'Well testing',
          wbs_code: 'EXEC',
          cost_element_code: 'EQUIP-RENT',
          total: '40000000',
          shortfall: null,
          need_date: '2026-12-01',
          requester_name: 'Budi',
          submitted_at: null,
          created_at: '2026-11-04T01:00:00Z',
          delivery_location: 'Rokan',
          purpose: 'Sewa genset',
          block_message: null,
          bcr_suggestion: null,
          reject_reason: null,
          cancel_reason: null,
          request_id: null,
          approved_at: null,
          linked_bcr: null,
          budget: {
            budget: '200000000',
            pre_commit: '40000000',
            commit: '0',
            actual: '0',
            available: '160000000',
            used_pct: '20.0',
            held_by_pr: '40000000',
          },
          approvals: [],
          can_edit: false,
          can_submit: false,
          can_cancel: false,
          can_request_bcr: false,
          can_rfq: true,
          rfq: null,
          po: null,
          lines: [
            {
              item_code: null,
              description: 'Sewa genset',
              qty: '1',
              uom: 'lot',
              est_price: '40000000',
              amount: '40000000',
            },
          ],
        }),
      'GET /api/procurement/vendor-categories': () => json(['equipment_rental']),
      'GET /api/procurement/rfq-vendors': () =>
        json([
          { code: 'V-A', name: 'PT Alfa Sewa', rating: '4.0', status: 'qualified', excluded: null },
          {
            code: 'V-P',
            name: 'PT Pending CSMS',
            rating: '4.5',
            status: 'csms_pending',
            excluded: 'CSMS belum disetujui',
          },
          {
            code: 'V-X',
            name: 'PT Daftar Hitam',
            rating: '4.0',
            status: 'blacklisted',
            excluded: 'masuk daftar hitam',
          },
        ]),
    },
  });
  const user = userEvent.setup();
  renderApp('/pengadaan/pr/pr1');
  await user.click(await screen.findByRole('button', { name: /Buat RFQ/ }));
  const dialog = await screen.findByRole('dialog');
  await user.selectOptions(within(dialog).getByLabelText(/Kategori vendor/), 'equipment_rental');
  expect(await within(dialog).findByLabelText(/PT Pending CSMS/)).toBeDisabled();
  expect(within(dialog).getByLabelText(/PT Daftar Hitam/)).toBeDisabled();
  expect(within(dialog).getByLabelText(/PT Alfa Sewa/)).toBeEnabled();
  expect(within(dialog).getByText('CSMS belum disetujui')).toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: /Kirim ke 0 vendor/ })).toBeDisabled();
});

it('issues a draft PO', async () => {
  let issued = false;
  const PO = {
    id: 'po1',
    number: 'PO-26-001',
    revision: 0,
    status: 'draft',
    vendor_code: 'V-C',
    vendor_name: 'PT Citra Genset',
    project_id: 'p1',
    project_number: 'PRJ-26-001',
    wbs_code: 'EXEC',
    cost_element_code: 'EQUIP-RENT',
    pr_id: 'pr1',
    pr_number: 'PR-26-001',
    rfq_id: 'r1',
    rfq_number: 'RFQ-26-001',
    subtotal: '38000000',
    ppn_pct: '11.00',
    ppn_amount: '4180000',
    total: '42180000',
    delivery_date: '2026-12-01',
    delivery_location: 'Rokan',
    payment_terms: '30 hari',
    terms: 'Denda keterlambatan',
    issued_at: null,
    revision_reason: null,
    pending_revision: null,
    request_id: null,
    budget: { available: '160000000', commit_by_po: '0', budget: '200000000', used_pct: '20.0' },
    can_edit: true,
    can_issue: true,
    can_revise: false,
    lines: [
      {
        seq: 1,
        item_code: null,
        description: 'Sewa genset',
        qty: '1',
        uom: 'lot',
        unit_price: '38000000',
        amount: '38000000',
      },
    ],
  };
  mockApi({
    me: officer,
    handlers: {
      'GET /api/procurement/pos/po1': () =>
        json(issued ? { ...PO, status: 'issued', can_edit: false, can_revise: true } : PO),
      'PUT /api/procurement/pos/po1': () => json(PO),
      'POST /api/procurement/pos/po1/issue': () => {
        issued = true;
        return json({ ...PO, status: 'issued' });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/pengadaan/po/po1');
  expect(await screen.findByText('Rp 42.180.000')).toBeInTheDocument();
  expect(screen.getByText('Rp 4.180.000')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Terbitkan PO/ }));
  expect(await screen.findByText('Diterbitkan')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Revisi PO/ })).toBeInTheDocument();
});
