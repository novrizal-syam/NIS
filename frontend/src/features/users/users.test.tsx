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

const admin = makeMe({
  roles: [{ code: 'admin', name: 'Admin' }],
  permissions: { users: { view: 'all', create: 'all', edit: 'all', admin: 'all', export: 'all' } },
});
const ROLES = [
  {
    id: '1',
    code: 'super_admin',
    name: 'Super Admin',
    description: '',
    is_system: true,
    is_external: false,
    requires_2fa: true,
    is_active: true,
    user_count: 1,
  },
  {
    id: '2',
    code: 'engineer',
    name: 'Engineer',
    description: '',
    is_system: true,
    is_external: false,
    requires_2fa: false,
    is_active: true,
    user_count: 3,
  },
];

it('warns about a single Super Admin and shows the temporary password once', async () => {
  const { calls } = mockApi({
    me: admin,
    handlers: {
      'GET /api/roles': () => json(ROLES),
      'GET /api/users': () =>
        json({
          items: [],
          total: 0,
          counts: { invited: 0, active: 1, locked: 0, inactive: 0 },
          active_super_admins: 1,
        }),
      'GET /api/master/departments/options': () => json([{ value: 'OPS', label: 'OPS · Operasi' }]),
      'GET /api/master/employees/options': () => json([]),
      'POST /api/users': () => json({ id: 'u9', temporary_password: 'Sementara123' }, 201),
    },
  });
  const user = userEvent.setup();
  renderApp('/pengguna');
  expect(await screen.findByRole('note')).toHaveTextContent('Hanya ada satu Super Admin aktif');

  await user.click(screen.getByRole('button', { name: /Undang pengguna/ }));
  const dialog = await screen.findByRole('dialog');
  // Only a Super Admin may grant Super Admin.
  expect(within(dialog).getByLabelText(/^Super Admin/)).toBeDisabled();
  await user.type(within(dialog).getByLabelText(/Nama lengkap/), 'Tono');
  await user.type(within(dialog).getByLabelText(/Email/), 'tono@gek.co.id');
  await user.click(within(dialog).getByLabelText(/^Engineer/));
  await user.click(within(dialog).getByLabelText(/Kata sandi sementara/));
  await user.click(within(dialog).getByRole('button', { name: /kata sandi sementara/ }));
  expect(await within(dialog).findByText('Sementara123')).toBeInTheDocument();
  const body = JSON.parse(
    String(calls.find((c) => c.key === 'POST /api/users')!.init!.body),
  ) as Record<string, unknown>;
  expect(body).toMatchObject({ roles: ['engineer'], mode: 'password', department_code: null });
});

it('asks for a reason on an SoD conflict and reports the pending approval', async () => {
  let attempts = 0;
  const { calls } = mockApi({
    me: admin,
    handlers: {
      'GET /api/roles': () => json(ROLES),
      'GET /api/users': () =>
        json({
          items: [
            {
              id: 'u1',
              email: 'ap@gek.co.id',
              full_name: 'Lina AP',
              roles: ['engineer'],
              role_names: ['Engineer'],
              department_code: null,
              employee_code: null,
              status: 'active',
              totp_enabled: true,
              last_login_at: null,
              is_demo: false,
            },
          ],
          total: 1,
          counts: { invited: 0, active: 1, locked: 0, inactive: 0 },
          active_super_admins: 2,
        }),
      'GET /api/users/u1': () =>
        json({
          id: 'u1',
          email: 'ap@gek.co.id',
          full_name: 'Lina AP',
          roles: ['engineer'],
          role_names: ['Engineer'],
          department_code: null,
          employee_code: null,
          status: 'active',
          totp_enabled: true,
          last_login_at: null,
          is_demo: false,
          sessions: [],
          assignments: [],
        }),
      'GET /api/master/departments/options': () => json([]),
      'GET /api/master/employees/options': () => json([]),
      'PATCH /api/users/u1': () => {
        attempts += 1;
        return attempts === 1
          ? json(
              {
                code: 'SOD_CONFLICT',
                message: 'Kombinasi peran melanggar pemisahan tugas: Engineer + Super Admin.',
              },
              409,
            )
          : json({ pending_approval: 'SOD-ABC12345', request_id: 'r1' }, 202);
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/pengguna');
  await user.click(await screen.findByRole('button', { name: 'Lina AP' }));
  const dialog = await screen.findByRole('dialog', { name: 'Lina AP' });
  await user.click(within(dialog).getByRole('tab', { name: 'Peran' }));
  await user.click(await within(dialog).findByRole('button', { name: 'Simpan peran' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('pemisahan tugas');
  const submit = within(dialog).getByRole('button', { name: 'Ajukan pengecualian' });
  expect(submit).toBeDisabled();
  await user.type(
    within(dialog).getAllByLabelText(/Alasan/)[0]!,
    'Kasir cuti tiga bulan, belum ada pengganti',
  );
  await user.click(submit);
  expect(
    await within(dialog).findByText(/menunggu persetujuan Direktur \(SOD-ABC12345\)/),
  ).toBeInTheDocument();
  const last = calls.filter((c) => c.key === 'PATCH /api/users/u1').at(-1)!;
  expect(JSON.parse(String(last.init!.body))).toMatchObject({
    sod_reason: 'Kasir cuti tiga bulan, belum ada pengganti',
  });
});
