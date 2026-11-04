import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
  session.setActiveRole(null);
  delete document.documentElement.dataset.theme;
});

afterEach(() => vi.unstubAllGlobals());

describe('AppShell', () => {
  it('shows only the menu items the user may view, with "Segera" on unbuilt ones', async () => {
    mockApi();
    renderApp('/');
    const nav = (await screen.findAllByRole('navigation', { name: 'Menu utama' }))[0]!;
    expect(within(nav).getByText('Procure to Pay')).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Lead' })).toHaveAttribute('href', '/lead');
    const dor = within(nav).getByRole('link', { name: /Daily Operation Report\s*Segera/ });
    expect(dor).toHaveAttribute('href', '/segera/dor');
    // No finance/payroll permission -> Keuangan group hidden entirely.
    expect(within(nav).queryByText('Keuangan')).not.toBeInTheDocument();
    expect(within(nav).queryByText('Penggajian')).not.toBeInTheDocument();
  });

  it('shows the page title in the top bar and API status', async () => {
    mockApi();
    renderApp('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Dasbor' })).toBeInTheDocument();
    expect(await screen.findByText('API dan database terhubung')).toBeInTheDocument();
  });

  it('renders the coming-soon page for unbuilt modules', async () => {
    mockApi();
    renderApp('/segera/purchaseOrders');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Purchase Order' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/belum tersedia/)).toBeInTheDocument();
  });

  it('switches theme from the user menu and remembers it', async () => {
    mockApi();
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Menu pengguna' }));
    await user.click(screen.getByRole('button', { name: /Gelap/ }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('nustrad.theme')).toBe('dark');
    await user.click(screen.getByRole('button', { name: /Sistem/ }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it('switches language to English', async () => {
    mockApi();
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Menu pengguna' }));
    await user.click(screen.getByRole('button', { name: 'EN' }));
    expect(screen.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'ID' }));
  });

  it('switches active role and sends it with every request', async () => {
    const me = makeMe({
      roles: [
        { code: 'engineer', name: 'Engineer' },
        { code: 'procurement_officer', name: 'Procurement Officer' },
      ],
    });
    const { calls } = mockApi({ me });
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Menu pengguna' }));
    await user.selectOptions(screen.getByLabelText('Peran aktif'), 'engineer');
    const lastMe = calls.filter((c) => c.key === 'GET /api/auth/me').at(-1)!;
    expect(new Headers(lastMe.init?.headers).get('X-Active-Role')).toBe('engineer');
    expect(localStorage.getItem('nustrad.activeRole')).toBe('engineer');
  });

  it('signs out and returns to the login page', async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Menu pengguna' }));
    await user.click(screen.getByRole('button', { name: /Keluar/ }));
    expect(await screen.findByRole('heading', { name: 'Masuk' })).toBeInTheDocument();
    expect(calls.some((c) => c.key === 'POST /api/auth/logout')).toBe(true);
  });
});

describe('sign out', () => {
  it('does not send the next user back to the previous page', async () => {
    mockApi({
      handlers: {
        'POST /api/auth/login': () =>
          new Response(JSON.stringify({ access_token: 't', expires_in: 900 }), { status: 200 }),
      },
    });
    const user = userEvent.setup();
    renderApp('/segera/purchaseOrders');
    await user.click(await screen.findByRole('button', { name: 'Menu pengguna' }));
    await user.click(screen.getByRole('button', { name: /Keluar/ }));
    await user.type(await screen.findByLabelText(/Email/), 'budi@gek.co.id');
    await user.type(screen.getByLabelText(/Kata sandi/), 'BukitDuri-2026');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Dasbor' })).toBeInTheDocument();
  });
});

describe('active menu item', () => {
  it('highlights only the deepest matching item', async () => {
    mockApi({
      me: makeMe({ permissions: { settings: { view: 'all' }, users: { view: 'all' } } }),
      handlers: { 'GET /api/roles': () => new Response('[]', { status: 200 }) },
    });
    renderApp('/pengaturan/peran');
    const nav = (await screen.findAllByRole('navigation', { name: 'Menu utama' }))[0]!;
    expect(within(nav).getByRole('link', { name: /Peran & Izin/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(within(nav).getByRole('link', { name: /^Pengaturan$/ })).not.toHaveAttribute(
      'aria-current',
    );
  });
});
