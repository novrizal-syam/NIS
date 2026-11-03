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

it('walks privacy then profile before the app', async () => {
  let pending: string[] = ['accept_privacy', 'complete_profile'];
  const { calls } = mockApi({
    handlers: {
      'GET /api/auth/me': () => json(makeMe({ pending: pending as never, phone: null })),
      'GET /api/auth/privacy': () =>
        json({ version: '2026-1', text: 'Pemberitahuan UU 27 Tahun 2022' }),
      'POST /api/auth/privacy/accept': () => {
        pending = ['complete_profile'];
        return new Response(null, { status: 204 });
      },
      'PUT /api/auth/profile': () => {
        pending = [];
        return json({ phone: '08123456789' });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/');
  expect(await screen.findByRole('heading', { name: 'Pemberitahuan privasi' })).toBeInTheDocument();
  const agree = screen.getByRole('button', { name: 'Saya setuju' });
  expect(agree).toBeDisabled();
  await user.click(screen.getByLabelText(/Saya telah membaca/));
  await user.click(agree);
  expect(await screen.findByRole('heading', { name: 'Lengkapi profil' })).toBeInTheDocument();
  await user.type(screen.getByLabelText(/Telepon/), '08123456789');
  await user.click(screen.getByRole('button', { name: 'Simpan profil' }));
  expect(await screen.findByRole('heading', { level: 1, name: 'Dasbor' })).toBeInTheDocument();
  expect(
    JSON.parse(String(calls.find((c) => c.key === 'POST /api/auth/privacy/accept')!.init!.body)),
  ).toEqual({
    version: '2026-1',
  });
});

it('shows the role tour once and lets the user skip it', async () => {
  let done = false;
  mockApi({
    handlers: {
      'GET /api/auth/me': () => json(makeMe({ tour_done: done })),
      'POST /api/auth/tour/done': () => {
        done = true;
        return new Response(null, { status: 204 });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/');
  const dialog = await screen.findByRole('dialog', { name: /Selamat datang, Rina/ });
  expect(dialog).toHaveTextContent('Head of Operation');
  await user.click(screen.getByRole('button', { name: 'Berikutnya' }));
  expect(await screen.findByRole('dialog', { name: 'Menu Anda' })).toHaveTextContent(
    'Procure to Pay',
  );
  await user.click(screen.getByRole('button', { name: 'Lewati' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
