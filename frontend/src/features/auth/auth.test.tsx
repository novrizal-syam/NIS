import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { apiError, json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
  session.setActiveRole(null);
});

afterEach(() => vi.unstubAllGlobals());

describe('auth flow', () => {
  it('redirects anonymous visitors to the login page', async () => {
    mockApi({ signedIn: false });
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Masuk' })).toBeInTheDocument();
    expect(screen.getByText('PT Global Energi KITA', { exact: false })).toBeInTheDocument();
  });

  it('shows Indonesian validation errors', async () => {
    mockApi({ signedIn: false });
    const user = userEvent.setup();
    renderApp('/login');
    await user.type(await screen.findByLabelText(/Email/), 'bukan-email');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));
    expect(await screen.findByText(/Format email tidak valid/)).toBeInTheDocument();
    expect(screen.getByText('Kata sandi wajib diisi.')).toBeInTheDocument();
  });

  it('shows the backend message on wrong credentials', async () => {
    mockApi({
      signedIn: false,
      handlers: {
        'POST /api/auth/login': () =>
          apiError(401, 'INVALID_CREDENTIALS', 'Email atau kata sandi salah.'),
      },
    });
    const user = userEvent.setup();
    renderApp('/login');
    await user.type(await screen.findByLabelText(/Email/), 'rina@gek.co.id');
    await user.type(screen.getByLabelText(/Kata sandi/), 'salah');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Email atau kata sandi salah.');
  });

  it('asks for the 2FA code when required, then signs in', async () => {
    let attempts = 0;
    mockApi({
      signedIn: false,
      handlers: {
        'POST /api/auth/login': (init) => {
          attempts += 1;
          const body = JSON.parse(String(init?.body)) as { totp_code: string | null };
          if (!body.totp_code) return apiError(401, 'TOTP_REQUIRED', 'Masukkan kode 2FA.');
          return json({ access_token: 'tok', expires_in: 900 });
        },
      },
    });
    const user = userEvent.setup();
    renderApp('/login');
    await user.type(await screen.findByLabelText(/Email/), 'rina@gek.co.id');
    await user.type(screen.getByLabelText(/Kata sandi/), 'Rahasia-Kuat-2026');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));
    await user.type(await screen.findByLabelText(/Kode 2FA/), '123456');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Dasbor' })).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it('forces a password change on first login', async () => {
    const pending = makeMe({ pending: ['change_password'] });
    const done = makeMe();
    let changed = false;
    mockApi({
      handlers: {
        'GET /api/auth/me': () => json(changed ? done : pending),
        'POST /api/auth/change-password': () => {
          changed = true;
          return json({ access_token: 'tok2', expires_in: 900 });
        },
      },
    });
    const user = userEvent.setup();
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Ganti kata sandi' })).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Kata sandi saat ini/), 'Sementara123');
    await user.type(screen.getByLabelText(/^Kata sandi baru/), 'pendek');
    await user.type(screen.getByLabelText(/Ulangi/), 'pendek');
    await user.click(screen.getByRole('button', { name: 'Simpan kata sandi' }));
    expect(await screen.findByText('Kata sandi minimal 10 karakter.')).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/^Kata sandi baru/));
    await user.type(screen.getByLabelText(/^Kata sandi baru/), 'KataSandiBaru2026');
    await user.clear(screen.getByLabelText(/Ulangi/));
    await user.type(screen.getByLabelText(/Ulangi/), 'KataSandiBaru2026');
    await user.click(screen.getByRole('button', { name: 'Simpan kata sandi' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Dasbor' })).toBeInTheDocument();
  });

  it('forces 2FA setup when the role requires it', async () => {
    mockApi({
      me: makeMe({ pending: ['setup_totp'] }),
      handlers: {
        'POST /api/auth/totp/setup': () =>
          json({ secret: 'ABCDEF', otpauth_uri: 'otpauth://totp/x', qr_svg: '<svg></svg>' }),
      },
    });
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Aktifkan 2FA' })).toBeInTheDocument();
    expect(await screen.findByText('ABCDEF')).toBeInTheDocument();
  });

  it('refreshes the access token once on 401 and retries', async () => {
    let healthCalls = 0;
    const { calls } = mockApi({
      handlers: {
        'GET /api/health': () => {
          healthCalls += 1;
          return healthCalls === 1
            ? apiError(401, 'TOKEN_EXPIRED', 'Sesi berakhir.')
            : json({ status: 'ok', db: 'ok', version: '0.1.0' });
        },
      },
    });
    renderApp('/');
    expect(await screen.findByText('API dan database terhubung')).toBeInTheDocument();
    expect(calls.filter((c) => c.key === 'POST /api/auth/refresh')).toHaveLength(2);
  });
});
