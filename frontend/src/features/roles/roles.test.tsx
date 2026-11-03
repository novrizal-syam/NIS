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

const CATALOG = {
  modules: [
    { code: 'procurement', label: 'Pengadaan' },
    { code: 'finance', label: 'Keuangan' },
  ],
  actions: [
    { code: 'view', label: 'melihat' },
    { code: 'approve', label: 'menyetujui' },
  ],
  scopes: ['own', 'department', 'project', 'all'],
  sensitive: [{ code: 'salary', label: 'Gaji' }],
};

it('edits the permission matrix and saves only granted cells', async () => {
  const { calls } = mockApi({
    me: makeMe({
      roles: [{ code: 'admin', name: 'Admin' }],
      permissions: { users: { view: 'all', admin: 'all' } },
    }),
    handlers: {
      'GET /api/roles/catalog': () => json(CATALOG),
      'GET /api/roles/r1': () =>
        json({
          id: 'r1',
          code: 'site_clerk',
          name: 'Site Clerk',
          description: '',
          is_system: false,
          is_external: false,
          requires_2fa: false,
          is_active: true,
          user_count: 2,
          locked: false,
          grants: [{ module: 'procurement', action: 'view', scope: 'own' }],
        }),
      'PUT /api/roles/r1/permissions': () => json({ grants: [] }),
    },
  });
  const user = userEvent.setup();
  renderApp('/pengaturan/peran/r1');
  const save = await screen.findByRole('button', { name: 'Simpan izin' });
  expect(save).toBeDisabled();
  await user.selectOptions(screen.getByLabelText('Pengadaan – menyetujui'), 'all');
  await user.selectOptions(screen.getByLabelText('Pengadaan – melihat'), '');
  await user.click(screen.getByLabelText('Gaji'));
  await user.click(save);
  expect(await screen.findByText(/Izin disimpan/)).toBeInTheDocument();
  const body = JSON.parse(
    String(calls.find((c) => c.key === 'PUT /api/roles/r1/permissions')!.init!.body),
  ) as {
    grants: unknown[];
  };
  expect(body.grants).toEqual([
    { module: 'procurement', action: 'approve', scope: 'all' },
    { module: 'sensitive', action: 'salary', scope: 'all' },
  ]);
});
