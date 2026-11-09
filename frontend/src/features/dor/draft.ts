import type { LocalDraft } from './offlineStore';
import type { DorData, DorDetail, FormOptions } from './types';

export const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

export function newClientId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function emptyData(o: FormOptions): DorData {
  return {
    report_date: today(),
    wbs_code: o.wbs[0]?.code ?? 'EXEC',
    site_warehouse: o.default_site,
    activities: '',
    npt_hours: '0',
    npt_reason: '',
    technical: {},
    hse: { incidents: '0', near_misses: '0', unsafe_acts: '0', toolbox_talks: '0' },
    equipment: [],
    crew: [],
    consumables: [],
  };
}

export function fromServer(d: DorDetail): DorData {
  const str = (r: Record<string, unknown>) =>
    Object.fromEntries(Object.entries(r ?? {}).map(([k, v]) => [k, String(v ?? '')]));
  return {
    report_date: d.report_date,
    wbs_code: d.wbs_code,
    site_warehouse: d.site_warehouse,
    activities: d.activities ?? '',
    npt_hours: d.npt_hours,
    npt_reason: d.npt_reason ?? '',
    technical: str(d.technical),
    hse: str(d.hse),
    equipment: d.equipment.map(({ revenue: _r, internal_cost: _c, ...x }) => x),
    crew: d.crew.map(({ revenue: _r, internal_cost: _c, ...x }) => x),
    consumables: d.consumables.map(({ revenue: _r, internal_cost: _c, ...x }) => x),
  };
}

export function draftFromServer(d: DorDetail): LocalDraft {
  return {
    client_id: d.client_id,
    project_id: d.project_id,
    project_number: d.project_number,
    server_id: d.id,
    number: d.number,
    base_version: d.version,
    status: d.status,
    data: fromServer(d),
    state: 'synced',
    message: null,
    updated_at: new Date().toISOString(),
  };
}
