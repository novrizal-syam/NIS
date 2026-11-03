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

const row = (name: string, extra: object) => ({
  user_id: name,
  full_name: name,
  email: `${name}@gek.co.id`,
  active: true,
  roles: ['Engineer'],
  sensitive: [],
  totp_enabled: true,
  requires_2fa: false,
  last_login_at: null,
  days_since_login: null,
  inactive_90: false,
  sod_exceptions: 0,
  ...extra,
});

it('filters by the summary tiles and flags inactive users', async () => {
  mockApi({
    me: makeMe({
      roles: [{ code: 'lead_controller', name: 'Lead Controller' }],
      permissions: { audit: { view: 'all' } },
    }),
    handlers: {
      'GET /api/reports/access-review': () =>
        json({
          generated_at: '2026-11-03T01:00:00Z',
          inactive_days: 90,
          summary: {
            users: 2,
            inactive_90: 1,
            with_sensitive: 1,
            missing_2fa: 0,
            with_sod_exception: 0,
          },
          rows: [
            row('Lama', { inactive_90: true, days_since_login: 120 }),
            row('Hcbp', { sensitive: ['Gaji'] }),
          ],
        }),
    },
  });
  const user = userEvent.setup();
  renderApp('/pengaturan/tinjauan-akses');
  expect(await screen.findByText('Lama')).toBeInTheDocument();
  expect(screen.getByText('Hcbp')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Tidak aktif > 90 hari/ }));
  const table = screen.getByRole('table');
  expect(within(table).getByText('Lama')).toBeInTheDocument();
  expect(within(table).queryByText('Hcbp')).not.toBeInTheDocument();
  expect(within(table).getByText('> 90 hari')).toBeInTheDocument();
});
