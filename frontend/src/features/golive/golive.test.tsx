import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

const result = (dry: boolean) => ({
  gl_lines: 7,
  ar_items: 1,
  ap_items: 1,
  stock_rows: 1,
  assets: 1,
  total: '410000000',
  journal: dry ? null : 'JV-26-0001',
  dry_run: dry,
  errors: [],
});

it('shows the go-live checklist and checks the opening balance before posting', async () => {
  const posts: string[] = [];
  mockApi({
    me: makeMe({
      roles: [{ code: 'super_admin', name: 'Super Admin' }],
      permissions: { settings: { view: 'all' }, finance: { view: 'all', approve: 'all' } },
    }),
    handlers: {
      'GET /api/go-live/checklist': () =>
        json({
          ready: false,
          done: 1,
          total: 2,
          items: [
            { key: 'demo', label: 'Data demo dihapus', ok: true, detail: 'OK', link: null },
            {
              key: 'opening',
              label: 'Saldo awal diposting',
              ok: false,
              detail: 'Belum ada saldo awal.',
              link: '/pengaturan/go-live',
            },
            { key: 'backup', label: 'Backup harian', ok: null, detail: 'Periksa', link: null },
          ],
        }),
      'GET /api/ledger/opening': () => json({ opening_date: null }),
      'POST /api/ledger/opening': (init) => {
        const dry = (init?.body as FormData).get('dry_run') === 'true';
        posts.push(String(dry));
        return json(result(dry));
      },
    },
  });
  renderApp('/pengaturan/go-live');
  expect(await screen.findByText('1 dari 2 butir selesai.')).toBeInTheDocument();
  expect(screen.getByText('Periksa manual')).toBeInTheDocument();
  expect(screen.getAllByText('Belum').length).toBe(1);

  fireEvent.change(screen.getByLabelText('Tanggal go-live'), { target: { value: '2026-12-31' } });
  const file = new File(['x'], 'saldo-awal.xlsx');
  await userEvent.upload(screen.getByLabelText('Berkas saldo awal'), file);
  await userEvent.click(screen.getByRole('button', { name: 'Periksa' }));
  expect(await screen.findByText(/Seimbang: total Rp\s?410\.000\.000/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Posting saldo awal' }));
  expect(await screen.findByText(/Jurnal JV-26-0001 diposting/)).toBeInTheDocument();
  expect(posts).toEqual(['true', 'false']);
});
