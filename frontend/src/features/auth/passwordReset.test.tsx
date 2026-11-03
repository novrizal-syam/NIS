import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { apiError, json, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

const GENERIC = 'Jika email terdaftar dan aktif, tautan sudah dikirim.';

it('links from the login page and shows the same message for any email', async () => {
  const { calls } = mockApi({
    signedIn: false,
    handlers: { 'POST /api/auth/forgot-password': () => json({ message: GENERIC }) },
  });
  const user = userEvent.setup();
  renderApp('/login');
  await user.click(await screen.findByRole('link', { name: 'Lupa kata sandi?' }));
  await user.type(await screen.findByLabelText(/Email/), 'siapa@gek.co.id');
  await user.click(screen.getByRole('button', { name: 'Kirim tautan' }));
  expect(await screen.findByRole('status')).toHaveTextContent(GENERIC);
  const body = JSON.parse(
    String(calls.find((c) => c.key === 'POST /api/auth/forgot-password')!.init!.body),
  ) as Record<string, unknown>;
  expect(body).toEqual({ email: 'siapa@gek.co.id' });
});

it('shows the rate-limit message from the server', async () => {
  mockApi({
    signedIn: false,
    handlers: {
      'POST /api/auth/forgot-password': () =>
        apiError(429, 'TOO_MANY_REQUESTS', 'Terlalu banyak permintaan. Coba lagi dalam 1 jam.'),
    },
  });
  const user = userEvent.setup();
  renderApp('/lupa-password');
  await user.type(await screen.findByLabelText(/Email/), 'rina@gek.co.id');
  await user.click(screen.getByRole('button', { name: 'Kirim tautan' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Terlalu banyak permintaan');
});

it('sets a new password with the token from the link', async () => {
  const { calls } = mockApi({
    signedIn: false,
    handlers: { 'POST /api/auth/reset-password': () => new Response(null, { status: 204 }) },
  });
  const user = userEvent.setup();
  renderApp('/reset-password?token=abcdefghijklmnop');
  await user.type(await screen.findByLabelText(/^Kata sandi baru/), 'SandiBaru#2026');
  await user.type(screen.getByLabelText(/Ulangi kata sandi baru/), 'SandiBaru#2026');
  await user.click(screen.getByRole('button', { name: 'Simpan kata sandi baru' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Kata sandi diperbarui');
  const body = JSON.parse(
    String(calls.find((c) => c.key === 'POST /api/auth/reset-password')!.init!.body),
  ) as Record<string, unknown>;
  expect(body).toEqual({ token: 'abcdefghijklmnop', password: 'SandiBaru#2026' });
});

it('reports an expired link', async () => {
  mockApi({
    signedIn: false,
    handlers: {
      'POST /api/auth/reset-password': () =>
        apiError(410, 'RESET_EXPIRED', 'Tautan sudah kedaluwarsa. Minta tautan baru.'),
    },
  });
  const user = userEvent.setup();
  renderApp('/reset-password?token=abcdefghijklmnop');
  await user.type(await screen.findByLabelText(/^Kata sandi baru/), 'SandiBaru#2026');
  await user.type(screen.getByLabelText(/Ulangi kata sandi baru/), 'SandiBaru#2026');
  await user.click(screen.getByRole('button', { name: 'Simpan kata sandi baru' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('kedaluwarsa');
});
