import { session } from '@/lib/api';
import { json } from '@/test/mockApi';
import { listDrafts, putDraft, type LocalDraft } from './offlineStore';
import { checks, price } from './pricing';
import { syncAll, syncDraft } from './sync';
import type { DorData, FormOptions } from './types';

const OPTIONS: FormOptions = {
  project: {
    id: 'p1',
    number: 'PRJ-26-001',
    name: 'Well testing',
    service_line: 'ofs',
    service_type: 'well_test',
    contract_number: 'CTR-26-001',
  },
  template: null,
  wbs: [{ code: 'EXEC', name: 'Execution' }],
  sites: [{ code: 'WH-RKN', name: 'Site Rokan', project_code: 'PRJ-26-001' }],
  default_site: 'WH-RKN',
  rates: [
    {
      id: 'pump',
      kind: 'equipment',
      description: 'Pump',
      unit: 'hari',
      rate: '14000000',
      standby_rate: '7000000',
      breakdown_rate: '0',
      unit_cost: null,
      markup_pct: null,
      internal_cost: null,
    },
    {
      id: 'fe',
      kind: 'personnel',
      description: 'FE',
      unit: 'hari',
      rate: '3000000',
      standby_rate: null,
      breakdown_rate: null,
      unit_cost: null,
      markup_pct: null,
      internal_cost: '1800000',
    },
    {
      id: 'chem',
      kind: 'consumable',
      description: 'Demulsifier',
      unit: 'drum',
      rate: '6600000',
      standby_rate: null,
      breakdown_rate: null,
      unit_cost: '6000000',
      markup_pct: '10.00',
      internal_cost: null,
    },
  ],
  assets: [
    { code: 'AST-PMP', name: 'Pump', internal_day_rate: '9500000', blocked: null, warning: null },
  ],
  crew: [{ code: 'E-1', full_name: 'Andi', position: 'FE', blocked: null, warning: null }],
  stock: [
    {
      warehouse_code: 'WH-RKN',
      item_code: 'ITM-1',
      name: 'Demulsifier',
      uom: 'drum',
      qty: '4',
      avg_cost: '6000000.00',
    },
  ],
};

const DATA: DorData = {
  report_date: '2026-11-09',
  wbs_code: 'EXEC',
  site_warehouse: 'WH-RKN',
  activities: 'Flowing',
  npt_hours: '0',
  npt_reason: '',
  technical: {},
  hse: {},
  equipment: [
    {
      asset_code: 'AST-PMP',
      rate_id: 'pump',
      operating: '18',
      standby: '4',
      breakdown: '0',
      rig: '2',
    },
  ],
  crew: [{ employee_code: 'E-1', rate_id: 'fe', hours: '12', overtime_hours: '0' }],
  consumables: [{ item_code: 'ITM-1', rate_id: 'chem', qty: '2' }],
};

it('prices like the backend (equipment hours/24, person-day, cost + markup)', () => {
  const p = price(DATA, OPTIONS);
  expect(p.equipment[0]).toEqual({ revenue: 12_833_333, cost: 9_500_000, hours: 24 });
  expect(p.crew[0]).toEqual({ revenue: 3_000_000, cost: 1_800_000 });
  expect(p.consumables[0]).toMatchObject({ revenue: 13_200_000, cost: 12_000_000 });
  expect([p.revenue, p.cost]).toEqual([29_033_333, 23_300_000]);
  expect(checks(DATA, OPTIONS, p)).toEqual([]);
  const bad = {
    ...DATA,
    equipment: [{ ...DATA.equipment[0]!, standby: '3' }],
    consumables: [{ item_code: 'ITM-1', rate_id: 'chem', qty: '5' }],
  };
  expect(checks(bad, OPTIONS, price(bad, OPTIONS))).toEqual([
    'AST-PMP: total jam 23, harus 24.',
    'ITM-1: 5 melebihi stok site (4).',
  ]);
});

const draft = (id: string): LocalDraft => ({
  client_id: id,
  project_id: 'p1',
  project_number: 'PRJ-26-001',
  server_id: null,
  number: null,
  base_version: null,
  status: 'local',
  data: DATA,
  state: 'dirty',
  message: null,
  updated_at: new Date().toISOString(),
});

describe('offline queue', () => {
  beforeEach(() => session.setToken('t'));
  afterEach(() => vi.unstubAllGlobals());

  it('keeps a draft dirty while offline and syncs it when the network is back', async () => {
    await putDraft(draft('c-offline'));
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    expect((await syncDraft(draft('c-offline'))).state).toBe('dirty');

    const body: unknown[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        body.push(JSON.parse(String(init?.body)));
        return Promise.resolve(
          json({ id: 's1', number: 'DOR-26-001', version: 1, status: 'draft' }),
        );
      }),
    );
    expect(await syncAll()).toBe(1);
    const stored = (await listDrafts()).find((d) => d.client_id === 'c-offline')!;
    expect(stored).toMatchObject({ state: 'synced', number: 'DOR-26-001', base_version: 1 });
    expect(body[0]).toMatchObject({ client_id: 'c-offline', base_version: null, project_id: 'p1' });
  });

  it('marks a version clash as a conflict instead of overwriting', async () => {
    await putDraft({ ...draft('c-conflict'), base_version: 1, server_id: 's2' });
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          json(
            { code: 'VERSION_CONFLICT', message: 'DOR-26-002 sudah diubah di perangkat lain' },
            409,
          ),
        ),
    );
    const res = await syncDraft({ ...draft('c-conflict'), base_version: 1 });
    expect(res.state).toBe('conflict');
    expect(res.message).toMatch(/perangkat lain/);
  });
});
