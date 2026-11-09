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

it('previews the business case while the proposal is typed', async () => {
  let body: Record<string, unknown> | null = null;
  mockApi({
    me: makeMe({
      roles: [{ code: 'head_of_operation', name: 'Head of Operation' }],
      permissions: { capex: { view: 'all', create: 'all', edit: 'all', submit: 'all' } },
    }),
    handlers: {
      'GET /api/capex/settings': () => json({ discount_rate: '12', rental_spend_12m: '900000000' }),
      'POST /api/capex/calculate': (init) => {
        body = JSON.parse(String(init!.body)) as Record<string, unknown>;
        return json({
          revenue_annual: '5018750000',
          opex_annual: '360000000',
          cash_flow_annual: '4658750000',
          npv: '17143000000',
          irr: '77.10',
          payback_years: '1.29',
          pv_buy: '7600000000',
          pv_rent: '4470000000',
          pv_lease: null,
          best_option: 'rent',
          priority_score: '82.5',
        });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/capex/baru');
  expect(await screen.findByText(/Rp\s*900\.000\.000/)).toBeInTheDocument();
  await user.type(screen.getByLabelText(/^Judul/), 'Separator 3 fasa');
  await user.type(screen.getByLabelText('Kelas aset'), 'Well testing');
  await user.type(screen.getByLabelText('Nilai investasi'), '6.000.000.000');
  expect(await screen.findByText('77.10%', {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByText('Sewa')).toBeInTheDocument();
  expect(body).toMatchObject({ amount: '6000000000', life_years: 8, funding: 'equity' });
});
