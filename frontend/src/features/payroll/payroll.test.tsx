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

const RUN = {
  id: 'r1',
  year: 2026,
  month: 11,
  label: 'Gaji 11/2026',
  period_start: '2026-10-26',
  period_end: '2026-11-25',
  pay_date: '2026-11-25',
  status: 'awaiting_approval',
  status_label: 'Menunggu persetujuan',
  request_id: 'q1',
  reject_reason: null,
  journal_id: null,
  employees: 1,
  gross: '13000000',
  employer_bpjs: '1500000',
  employee_bpjs: '480000',
  pph21: '400000',
  deductions: '0',
  net: '12120000',
  employer_cost: '14500000',
};

it('shows run totals but masks per-employee amounts without the salary permission', async () => {
  mockApi({
    me: makeMe({
      roles: [{ code: 'x', name: 'Reviewer' }],
      permissions: { payroll: { view: 'all' } },
    }),
    handlers: {
      'GET /api/payroll/runs': () => json([RUN]),
      'GET /api/payroll/runs/r1': () =>
        json({
          ...RUN,
          allocation: [{ project_id: 'p1', project: 'PRJ-26-001', amount: '14500000' }],
          office_cost: '0',
          payslips: [
            {
              id: 's1',
              employee_code: 'E-1',
              employee_name: 'Andi Operator',
              position: 'FE',
              is_field: true,
              ptkp_status: 'TK/0',
              ter_category: 'A',
              site_days: 2,
              overtime_hours: '3.00',
            },
          ],
        }),
    },
  });
  const user = userEvent.setup();
  renderApp('/keuangan/penggajian');
  await user.click(await screen.findByRole('button', { name: 'Gaji 11/2026' }));
  expect(await screen.findByText('PRJ-26-001')).toBeInTheDocument();
  expect(screen.getByText('Andi Operator')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Andi Operator' })).toBeNull();
  expect(screen.getAllByText('•••')).toHaveLength(3);
  expect(screen.queryByRole('button', { name: /Hitung penggajian/ })).toBeNull();
});

it('lists my approved payslips', async () => {
  mockApi({
    me: makeMe({ roles: [{ code: 'field_engineer', name: 'Field Engineer' }], permissions: {} }),
    handlers: {
      'GET /api/payroll/my-payslips': () =>
        json([{ id: 's1', label: 'Gaji 11/2026', year: 2026, month: 11, net: '12120000' }]),
    },
  });
  renderApp('/slip-gaji');
  expect(await screen.findByText('Gaji 11/2026')).toBeInTheDocument();
  expect(screen.getByText(/Rp\s*12\.120\.000/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /1721-A1 2026/ })).toBeInTheDocument();
});
