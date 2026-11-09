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

const coordinator = makeMe({
  roles: [{ code: 'asset_inventory_coordinator', name: 'Asset & Inventory Coordinator' }],
  permissions: {
    maintenance: { view: 'all', create: 'all', edit: 'all' },
    inventory: { view: 'all' },
  },
});

const WO = {
  id: 'w1',
  number: 'WO-26-001',
  asset_code: 'AST-PMP',
  asset_name: 'Pump unit 600 HP',
  kind: 'preventive',
  status: 'open',
  title: 'PM Ganti oli power end — AST-PMP',
  task_code: 'PM-TRX-250',
  trigger: 'Jam operasi 252 ≥ 250',
  due_date: null,
  due_hours: '250',
  completed_date: null,
  overdue: false,
  form_code: 'FRM-MNT-07',
  project_number: 'PRJ-26-001',
  checklist: [
    { item: 'Kuras oli', result: null, note: null },
    { item: 'Ganti filter', result: null, note: null },
  ],
  labour_hours: '0',
  result: null,
  signature_name: null,
  parts_value: '0',
  parts: [],
  can_edit: true,
};

it('cannot sign off a work order until every checklist item has a result', async () => {
  let saved: Record<string, unknown> | null = null;
  let completed = false;
  mockApi({
    me: coordinator,
    handlers: {
      'GET /api/maintenance/work-orders/w1': () =>
        json(
          completed
            ? {
                ...WO,
                status: 'done',
                can_edit: false,
                signature_name: 'Rina Wijaya',
                completed_date: '2026-11-09',
              }
            : WO,
        ),
      'GET /api/inventory/warehouses': () => json([]),
      'PUT /api/maintenance/work-orders/w1': (init) => {
        saved = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({ ...WO, status: 'in_progress' });
      },
      'POST /api/maintenance/work-orders/w1/complete': () => {
        completed = true;
        return json({ ...WO, status: 'done' });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/pemeliharaan/wo/w1');
  const sign = await screen.findByRole('button', { name: /Tanda tangan & selesai/ });
  expect(sign).toBeDisabled();
  await user.selectOptions(screen.getByLabelText('Hasil Kuras oli'), 'ok');
  await user.selectOptions(screen.getByLabelText('Hasil Ganti filter'), 'na');
  expect(sign).toBeDisabled(); // result text still missing
  await user.type(screen.getByLabelText(/Hasil pekerjaan/), 'Oli diganti 20 L');
  await user.click(sign);
  await vi.waitFor(() => expect(completed).toBe(true));
  expect(saved).toMatchObject({
    checklist: [
      { item: 'Kuras oli', result: 'ok' },
      { item: 'Ganti filter', result: 'na' },
    ],
    result: 'Oli diganti 20 L',
  });
  expect(await screen.findByText(/Ditandatangani Rina Wijaya/)).toBeInTheDocument();
});

it('shows why an asset with an expired certificate cannot be allocated', async () => {
  mockApi({
    me: coordinator,
    handlers: {
      'GET /api/maintenance/assets/AST-OLD': () =>
        json({
          code: 'AST-OLD',
          name: 'Pump lama',
          equipment_type_code: 'PU-TRIPLEX',
          criticality: 'B',
          serial_no: null,
          location: 'Cilegon',
          internal_day_rate: '0',
          certificates: [
            { name: 'Sertifikat MIGAS', number: 'X', expiry_date: '2026-11-01', status: 'expired' },
          ],
          cert_blocked: 'Sertifikat MIGAS kedaluwarsa 2026-11-01',
          cert_warning: null,
          operating_hours: '0',
          allocations: [],
          schedules: [],
          work_orders: [],
          downtime: [],
        }),
      'GET /api/maintenance/projects': () =>
        json([{ id: 'p1', number: 'PRJ-26-001', name: 'Well test' }]),
      'POST /api/maintenance/assets/AST-OLD/allocate': () =>
        json(
          {
            code: 'ASSET_CERT_EXPIRED',
            message:
              'AST-OLD tidak dapat dialokasikan: Sertifikat MIGAS kedaluwarsa 2026-11-01. Perpanjang sertifikat dulu.',
          },
          422,
        ),
    },
  });
  const user = userEvent.setup();
  renderApp('/pemeliharaan/aset/AST-OLD');
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Tidak dapat dialokasikan ke proyek: Sertifikat MIGAS kedaluwarsa',
  );
  await user.selectOptions(screen.getByLabelText(/^Proyek/), 'p1');
  await user.click(screen.getByRole('button', { name: /Alokasikan ke proyek/ }));
  expect(await screen.findByText(/Perpanjang sertifikat dulu/)).toBeInTheDocument();
});
