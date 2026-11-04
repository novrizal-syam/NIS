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

const engineer = makeMe({
  id: 'e1',
  roles: [{ code: 'engineer', name: 'Engineer' }],
  permissions: {
    procurement: { view: 'own', create: 'own', edit: 'own', submit: 'own', export: 'own' },
  },
});
const planner = makeMe({
  id: 'e1',
  roles: [{ code: 'lead_engineer', name: 'Lead Engineer' }],
  permissions: {
    procurement: { view: 'project', create: 'project', edit: 'project', submit: 'project' },
    budget: { view: 'project', edit: 'project', submit: 'project' },
    project: { view: 'project' },
  },
});

const PR = {
  id: 'pr1',
  number: 'PR-26-001',
  status: 'blocked',
  project_id: 'p1',
  project_number: 'PRJ-26-001',
  project_name: 'Well testing',
  wbs_code: 'EXEC',
  cost_element_code: 'EQUIP-RENT',
  total: '150000000',
  shortfall: '95000000',
  need_date: '2026-12-01',
  requester_name: 'Budi',
  submitted_at: '2026-11-04T02:00:00Z',
  created_at: '2026-11-04T01:00:00Z',
  delivery_location: 'Lapangan Rokan',
  purpose: 'Sewa genset',
  block_message:
    'Anggaran tidak cukup: tersedia Rp 55.000.000, diminta Rp 150.000.000, kurang Rp 95.000.000.',
  bcr_suggestion: '95000000',
  reject_reason: null,
  cancel_reason: null,
  request_id: null,
  approved_at: null,
  linked_bcr: null,
  budget: {
    budget: '55000000',
    pre_commit: '0',
    commit: '0',
    actual: '0',
    available: '55000000',
    used_pct: '0.0',
    held_by_pr: '0',
  },
  approvals: [],
  can_edit: true,
  can_submit: true,
  can_cancel: true,
  can_request_bcr: true,
  lines: [
    {
      item_code: null,
      description: 'Sewa genset 500 kVA',
      qty: '1',
      uom: 'lot',
      est_price: '150000000',
      amount: '150000000',
    },
  ],
};

it('shows a blocked PR with the shortfall and asks the planner for a BCR', async () => {
  mockApi({ me: engineer, handlers: { 'GET /api/procurement/prs/pr1': () => json(PR) } });
  renderApp('/pengadaan/pr/pr1');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('kurang Rp 95.000.000');
  expect(alert).toHaveTextContent(
    'Minta planner proyek mengajukan BCR sebesar Rp 95.000.000 dengan referensi PR-26-001.',
  );
});

it('opens the BCR form prefilled for users who may request it', async () => {
  mockApi({
    me: planner,
    handlers: {
      'GET /api/procurement/prs/pr1': () => json(PR),
      'GET /api/projects/p1': () =>
        json({
          id: 'p1',
          number: 'PRJ-26-001',
          name: 'Well testing',
          company_name: 'PT KKKS',
          status: 'locked',
          status_label: 'Terkunci',
          revenue: '1000000000',
          budget_total: '105000000',
          total_cost: '105000000',
          planned_margin: '895000000',
          margin_pct: '89.50',
          min_margin_pct: '20',
          margin_warning: false,
          contract_id: null,
          contract_number: null,
          start_date: null,
          end_date: null,
          contingency_pct: '5.00',
          manager_id: 'e1',
          manager_name: 'Planner',
          budget_request_id: null,
          budget_comment: null,
          locked_at: '2026-11-03T03:00:00Z',
          baseline: {
            version: 0,
            total_cost: '105000000',
            margin_pct: '89.50',
            approved_at: '2026-11-03T03:00:00Z',
          },
          can_edit_budget: false,
          can_submit_budget: false,
          can_assign: false,
          can_bcr: true,
          wbs: [{ id: 'w1', code: 'EXEC', name: 'Execution' }],
          cells: [{ wbs_code: 'EXEC', cost_element_code: 'EQUIP-RENT', amount: '55000000' }],
          cost_elements: [
            { code: 'CONTINGENCY', name: 'Kontinjensi' },
            { code: 'EQUIP-RENT', name: 'Peralatan sewa' },
          ],
          budget: [],
        }),
      'GET /api/projects/p1/budget-status': () =>
        json({
          status: 'locked',
          lines: [],
          totals: { budget: '0', pre_commit: '0', commit: '0', actual: '0', available: '0' },
        }),
      'GET /api/projects/p1/bcrs': () => json([]),
    },
  });
  const user = userEvent.setup();
  renderApp('/pengadaan/pr/pr1');
  await user.click(await screen.findByRole('button', { name: /Ajukan BCR Rp 95\.000\.000/ }));
  expect(await screen.findByText(/BCR untuk PR-26-001/)).toBeInTheDocument();
  expect(screen.getByLabelText(/^Nilai/)).toHaveValue('95.000.000');
  expect(screen.getByLabelText('Sumber')).toHaveValue('budget_increase');
  expect(screen.getByLabelText('Elemen biaya tujuan')).toHaveValue('EQUIP-RENT');
  expect(screen.getByLabelText(/Nomor\/ID dokumen/)).toHaveValue('pr1');
});

it('creates a PR from the form', async () => {
  let body: Record<string, unknown> | null = null;
  mockApi({
    me: engineer,
    handlers: {
      'GET /api/procurement/prs/form-options': () =>
        json({
          projects: [
            {
              id: 'p1',
              number: 'PRJ-26-001',
              name: 'Well testing',
              wbs: [{ code: 'EXEC', name: 'Execution' }],
            },
          ],
          cost_elements: [{ code: 'EQUIP-RENT', name: 'Peralatan sewa' }],
        }),
      'POST /api/procurement/prs': (init) => {
        body = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({ ...PR, status: 'draft' }, 201);
      },
      'GET /api/procurement/prs/pr1': () => json({ ...PR, status: 'draft' }),
    },
  });
  const user = userEvent.setup();
  renderApp('/pengadaan/pr/baru');
  await screen.findByRole('option', { name: /PRJ-26-001/ });
  await user.selectOptions(screen.getByLabelText(/^Proyek/), 'p1');
  await user.selectOptions(screen.getByLabelText(/^Elemen biaya/), 'EQUIP-RENT');
  await user.type(screen.getByLabelText(/^Dibutuhkan/), '2026-12-01');
  await user.type(screen.getByLabelText(/^Lokasi pengiriman/), 'Lapangan Rokan');
  await user.type(screen.getByLabelText('Uraian 1'), 'Sewa genset 500 kVA');
  await user.type(screen.getByLabelText('Estimasi harga 1'), '150.000.000');
  expect(screen.getByText('Rp 150.000.000')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Simpan draf' }));
  await vi.waitFor(() => expect(body).not.toBeNull());
  expect(body).toMatchObject({
    project_id: 'p1',
    wbs_code: 'EXEC',
    cost_element_code: 'EQUIP-RENT',
    lines: [{ description: 'Sewa genset 500 kVA', qty: '1', uom: 'lot', est_price: '150000000' }],
  });
  expect(await screen.findByText(/PR-26-001/)).toBeInTheDocument();
});
