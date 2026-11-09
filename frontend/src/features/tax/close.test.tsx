import { screen } from '@testing-library/react';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

const check = (key: string, ok: boolean, blocking: boolean, label: string, detail: string) => ({
  key,
  ok,
  blocking,
  label,
  detail,
});

it('blocks the close while a blocking check fails and shows warnings', async () => {
  mockApi({
    me: makeMe({
      roles: [{ code: 'lead_controller', name: 'Lead Controller' }],
      permissions: { finance: { view: 'all', post: 'all', approve: 'all' } },
    }),
    handlers: {
      'GET /api/close/periods/2026/10': () =>
        json({
          year: 2026,
          month: 10,
          status: 'open',
          checks: [
            check('dors', false, true, 'Semua DOR periode disetujui', '1 DOR belum disetujui.'),
            check('trial_balance', true, true, 'Neraca saldo seimbang', 'Debit 1 / kredit 1.'),
            check('tax', false, false, 'SPT Masa dilaporkan', '0 dari 3 SPT dilaporkan.'),
          ],
          depreciation: null,
          history: [],
        }),
    },
  });
  renderApp('/keuangan/tutup-buku?year=2026&month=10');
  expect(await screen.findByText('1 DOR belum disetujui.')).toBeInTheDocument();
  expect(screen.getByText('Menghalangi')).toBeInTheDocument();
  expect(screen.getByText('Peringatan')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Tutup periode/ })).toBeDisabled();
  expect(screen.getByRole('button', { name: /Jalankan penyusutan/ })).toBeEnabled();
  expect(screen.queryByRole('button', { name: /Buka kembali/ })).toBeNull();
});
