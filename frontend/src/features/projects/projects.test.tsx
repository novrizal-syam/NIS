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

const planner = makeMe({
  id: 'le1',
  roles: [{ code: 'lead_engineer', name: 'Lead Engineer' }],
  permissions: {
    project: { view: 'project', create: 'project', edit: 'project', submit: 'project' },
    budget: { view: 'project', create: 'project', edit: 'project', submit: 'project' },
  },
});

const BASE = {
  id: 'p1',
  number: 'PRJ-26-001',
  name: 'Well testing Blok X',
  company_name: 'PT KKKS',
  status: 'draft',
  status_label: 'Draf',
  revenue: '1000000000',
  budget_total: '525000000',
  total_cost: '525000000',
  planned_margin: '475000000',
  margin_pct: '47.50',
  min_margin_pct: '20',
  margin_warning: false,
  contract_id: null,
  contract_number: null,
  start_date: null,
  end_date: null,
  contingency_pct: '5.00',
  manager_id: 'le1',
  manager_name: 'Planner',
  budget_request_id: null,
  budget_comment: null,
  locked_at: null,
  baseline: null,
  can_edit_budget: true,
  can_submit_budget: true,
  can_assign: false,
  wbs: [
    { id: 'w1', code: 'EXEC', name: 'Execution' },
    { id: 'w2', code: 'MOB', name: 'Mobilisasi' },
  ],
  cells: [
    {
      wbs_code: 'EXEC',
      cost_element_code: 'EQUIP-OWN',
      amount: '500000000',
      locked_reserve: false,
    },
    {
      wbs_code: 'EXEC',
      cost_element_code: 'CONTINGENCY',
      amount: '25000000',
      locked_reserve: true,
    },
  ],
  cost_elements: [
    { code: 'CONTINGENCY', name: 'Kontinjensi' },
    { code: 'EQUIP-OWN', name: 'Peralatan milik (tarif internal)' },
    { code: 'LOGISTICS', name: 'Logistik & transport' },
  ],
  budget: [],
};

it('edits cost element x WBS and submits to the Lead Controller', async () => {
  let saved: { cells: Record<string, string>[] } | null = null;
  mockApi({
    me: planner,
    handlers: {
      'GET /api/projects/p1': () => json(BASE),
      'PUT /api/projects/p1/budget': (init) => {
        saved = JSON.parse(String(init!.body)) as { cells: Record<string, string>[] };
        return json(BASE);
      },
      'POST /api/projects/p1/submit-budget': () =>
        json({
          ...BASE,
          status: 'controller_review',
          approvers: ['lead_controller', 'head_of_operation'],
        }),
    },
  });
  const user = userEvent.setup();
  renderApp('/proyek/p1');
  const steps = await screen.findByRole('list', { name: 'Tahapan anggaran' });
  expect(
    within(steps)
      .getByText(/1\. Draf/)
      .closest('li'),
  ).toHaveAttribute('aria-current', 'step');
  expect(screen.getByText('Cadangan terkunci')).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText('Tambah elemen biaya'), 'LOGISTICS');
  await user.click(screen.getByRole('button', { name: /Tambah baris/ }));
  await user.type(screen.getByLabelText('LOGISTICS MOB'), '75.000.000');
  await user.click(screen.getByRole('button', { name: 'Simpan & hitung ulang' }));
  await vi.waitFor(() => expect(saved).not.toBeNull());
  expect(saved!.cells).toEqual(
    expect.arrayContaining([
      { wbs_code: 'EXEC', cost_element_code: 'EQUIP-OWN', amount: '500000000' },
      { wbs_code: 'EXEC', cost_element_code: 'CONTINGENCY', amount: '25000000' },
      { wbs_code: 'MOB', cost_element_code: 'LOGISTICS', amount: '75000000' },
    ]),
  );
  await user.click(screen.getByRole('button', { name: /Ajukan ke Lead Controller/ }));
  expect(
    await screen.findByText('Diajukan: Lead Controller → Head of Operation.'),
  ).toBeInTheDocument();
});

it('shows a locked budget read-only with the baseline', async () => {
  mockApi({
    me: planner,
    handlers: {
      'GET /api/projects/p1': () =>
        json({
          ...BASE,
          status: 'locked',
          can_edit_budget: false,
          can_submit_budget: false,
          locked_at: '2026-11-03T03:00:00Z',
          baseline: {
            version: 0,
            total_cost: '525000000',
            margin_pct: '47.50',
            approved_at: '2026-11-03T03:00:00Z',
          },
        }),
    },
  });
  renderApp('/proyek/p1');
  expect(await screen.findByText(/Baseline v0: Rp 525\.000\.000/)).toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Ajukan/ })).not.toBeInTheDocument();
  const steps = screen.getByRole('list', { name: 'Tahapan anggaran' });
  expect(
    within(steps)
      .getByText(/4\. Terkunci/)
      .closest('li'),
  ).toHaveAttribute('aria-current', 'step');
});

it('warns when the planned margin is below the threshold', async () => {
  mockApi({
    me: planner,
    handlers: {
      'GET /api/projects/p1': () =>
        json({
          ...BASE,
          margin_pct: '15.00',
          margin_warning: true,
          budget_comment: 'Tinjau harga sewa',
        }),
    },
  });
  renderApp('/proyek/p1');
  expect(await screen.findByRole('alert')).toHaveTextContent('Margin rencana 15,00% di bawah 20%');
  expect(screen.getByText(/Dikembalikan dengan catatan: Tinjau harga sewa/)).toBeInTheDocument();
});
