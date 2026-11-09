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

it('registers an incoming letter and searches inside letters', async () => {
  let posted: Record<string, unknown> | null = null;
  const { fetchMock } = mockApi({
    me: makeMe({
      roles: [{ code: 'legal_liaison', name: 'Legal & Liaison' }],
      permissions: { letters: { view: 'all', create: 'all', edit: 'all', submit: 'all' } },
    }),
    handlers: {
      'GET /api/letters/incoming': () =>
        json([
          {
            id: 'l1',
            number: 'SM-26-001',
            received_on: '2026-11-09',
            sender: 'PT KKKS Rokan',
            sender_ref: null,
            subject: 'Undangan rapat kick-off',
            status: 'registered',
            file_id: null,
            confidential: false,
          },
        ]),
      'POST /api/letters/incoming': (init) => {
        posted = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({ id: 'l2' });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/surat');
  expect(await screen.findByRole('link', { name: 'SM-26-001' })).toHaveAttribute(
    'href',
    '/surat/masuk/l1',
  );
  await user.type(screen.getByLabelText('Pengirim'), 'PT Mitra');
  await user.type(screen.getByLabelText('Perihal'), 'Penawaran kerja sama');
  await user.click(screen.getByRole('button', { name: 'Daftarkan' }));
  await vi.waitFor(() => expect(posted).toMatchObject({ sender: 'PT Mitra', sender_ref: null }));
  await user.type(screen.getByLabelText('Cari'), 'RKN');
  await vi.waitFor(() =>
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('q=RKN'))).toBe(true),
  );
});
