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
