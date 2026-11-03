import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { apiError, json, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

it('sends every route to /setup until setup is finished', async () => {
  mockApi({
    signedIn: false,
    handlers: {
      'GET /api/setup/status': () =>
        json({ setup_completed: false, token_configured: true, steps: {} }),
    },
  });
  renderApp('/master');
  expect(await screen.findByRole('heading', { name: 'Token penyiapan' })).toBeInTheDocument();
});

it('rejects a wrong setup token with the server message', async () => {
  const { calls } = mockApi({
    signedIn: false,
    handlers: {
      'GET /api/setup/status': () =>
        json({ setup_completed: false, token_configured: true, steps: {} }),
      'POST /api/setup/verify-token': () =>
        apiError(403, 'SETUP_TOKEN_INVALID', 'Token penyiapan salah.'),
    },
  });
  const user = userEvent.setup();
  renderApp('/setup');
  await user.type(await screen.findByLabelText(/Token penyiapan/), 'salah');
  await user.click(screen.getByRole('button', { name: 'Lanjut' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Token penyiapan salah.');
  const sent = calls.find((c) => c.key === 'POST /api/setup/verify-token')!;
  expect(new Headers(sent.init?.headers).get('X-Setup-Token')).toBe('salah');
});

it('shows a closed page after setup is complete', async () => {
  mockApi({ signedIn: false });
  renderApp('/setup');
  expect(
    await screen.findByRole('heading', { name: 'Penyiapan sudah selesai' }),
  ).toBeInTheDocument();
});

it('offers a recovery code when 2FA is asked at sign-in', async () => {
  const bodies: Record<string, unknown>[] = [];
  mockApi({
    signedIn: false,
    handlers: {
      'POST /api/auth/login': (init) => {
        const b = JSON.parse(String(init?.body)) as Record<string, unknown>;
        bodies.push(b);
        return b.recovery_code
          ? json({ access_token: 't', expires_in: 900 })
          : apiError(401, 'TOTP_REQUIRED', 'Masukkan kode 2FA.');
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/login');
  await user.type(await screen.findByLabelText(/Email/), 'kasir@gek.co.id');
  await user.type(screen.getByLabelText(/Kata sandi/), 'Rahasia-Kuat-2026');
  await user.click(screen.getByRole('button', { name: 'Masuk' }));
  await user.click(await screen.findByRole('button', { name: /Pakai kode pemulihan/ }));
  await user.type(screen.getByLabelText(/Kode pemulihan/), 'ABCD-EFGH');
  await user.click(screen.getByRole('button', { name: 'Masuk' }));
  expect(await screen.findByRole('heading', { level: 1, name: 'Dasbor' })).toBeInTheDocument();
  expect(bodies.at(-1)).toMatchObject({ recovery_code: 'ABCD-EFGH', totp_code: null });
});
