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

const superAdmin = makeMe({
  roles: [{ code: 'super_admin', name: 'Super Admin' }],
  permissions: { settings: { view: 'all' } },
});

describe('Pengaturan · data demo', () => {
  it('requires typing HAPUS before removing demo data', async () => {
    let present = true;
    const { calls } = mockApi({
      me: superAdmin,
      handlers: {
        'GET /api/admin/demo': () =>
          json({ present, counts: present ? { vendors: 15, users: 29 } : {} }),
        'POST /api/admin/demo/remove': () => {
          present = false;
          return json({ removed: { vendors: 15, users: 29 } });
        },
      },
    });
    const user = userEvent.setup();
    renderApp('/pengaturan');
    expect(await screen.findByText('Ada 44 baris data demo.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Hapus semua data demo/ }));
    const dialog = await screen.findByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: /Hapus semua data demo/ });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Ketik HAPUS/), 'HAPUS');
    await user.click(confirm);
    expect(await screen.findByText('44 baris data demo dihapus.')).toBeInTheDocument();
    expect(calls.some((c) => c.key === 'POST /api/admin/demo/remove')).toBe(true);
  });

  it('is not offered to non Super Admin users', async () => {
    const { calls } = mockApi({
      me: makeMe({
        roles: [{ code: 'admin', name: 'Admin' }],
        permissions: { settings: { view: 'all' } },
      }),
    });
    renderApp('/pengaturan');
    expect(await screen.findByText(/dibangun di fase 01a/)).toBeInTheDocument();
    expect(calls.some((c) => c.key === 'GET /api/admin/demo')).toBe(false);
  });
});
