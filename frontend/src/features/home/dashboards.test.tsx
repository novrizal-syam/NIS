import { screen, within } from '@testing-library/react';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

it('shows the live process map and the role dashboard tiles', async () => {
  mockApi({
    me: makeMe({
      roles: [{ code: 'finance_officer', name: 'Finance Officer' }],
      permissions: { finance: { view: 'all' } },
    }),
    handlers: {
      'GET /api/dashboard/process-map': () =>
        json({
          lanes: ['revenue', 'spend', 'people', 'finance'],
          phases: ['plan', 'commit', 'execute', 'record', 'settle', 'review'],
          cells: [
            {
              lane: 'finance',
              phase: 'record',
              key: 'journals_month',
              count: 12,
              link: '/keuangan/buku-besar?tab=journals',
              attention: false,
            },
            {
              lane: 'spend',
              phase: 'record',
              key: 'vi_exception',
              count: 2,
              link: '/keuangan/tagihan-vendor',
              attention: true,
            },
          ],
        }),
      'GET /api/dashboard/roles': () => json(['finance']),
      'GET /api/dashboard/roles/finance': () =>
        json({
          kind: 'finance',
          tiles: [
            {
              key: 'cash',
              value: '1000000000',
              unit: 'idr',
              link: '/keuangan/treasury',
              tone: 'neutral',
            },
            { key: 'dso', value: '27.5', unit: 'days', link: null, tone: 'neutral' },
          ],
        }),
    },
  });
  renderApp('/');
  const journals = await screen.findByRole('link', { name: /Jurnal bulan ini\s*12/ });
  expect(journals).toHaveAttribute('href', '/keuangan/buku-besar?tab=journals');
  expect(screen.getByRole('link', { name: /Invoice vendor exception\s*2/ })).toBeInTheDocument();
  expect(await screen.findByText('Dasbor Keuangan')).toBeInTheDocument();
  const cash = screen.getByRole('link', { name: /Saldo kas/ });
  expect(within(cash).getByText(/Rp\s*1\.000\.000\.000/)).toBeInTheDocument();
  expect(screen.getByText('27,5 hari')).toBeInTheDocument();
  // No reporting right: no OKR card.
  expect(screen.queryByText(/^OKR /)).toBeNull();
});
