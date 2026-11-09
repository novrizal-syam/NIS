import { ApiError, api } from '@/lib/api';
import { listDrafts, putDraft, type LocalDraft } from './offlineStore';
import type { DorData, DorDetail } from './types';

const toApi = (d: DorData) => ({
  ...d,
  site_warehouse: d.site_warehouse || null,
  npt_hours: d.npt_hours.replace(',', '.') || '0',
  equipment: d.equipment.map((x) => ({
    ...x,
    operating: x.operating.replace(',', '.') || '0',
    standby: x.standby.replace(',', '.') || '0',
    breakdown: x.breakdown.replace(',', '.') || '0',
    rig: x.rig.replace(',', '.') || '0',
  })),
  crew: d.crew.map((c) => ({
    ...c,
    hours: c.hours.replace(',', '.') || '0',
    overtime_hours: c.overtime_hours.replace(',', '.') || '0',
  })),
  consumables: d.consumables.map((k) => ({ ...k, qty: k.qty.replace(',', '.') || '0' })),
});

/** Push one draft. Network failure keeps it dirty; a version clash marks it as a conflict. */
export async function syncDraft(d: LocalDraft): Promise<LocalDraft> {
  try {
    const res = await api<DorDetail>('/operations/dors/sync', {
      method: 'POST',
      body: JSON.stringify({
        project_id: d.project_id,
        client_id: d.client_id,
        base_version: d.base_version,
        dor: toApi(d.data),
      }),
    });
    const next: LocalDraft = {
      ...d,
      server_id: res.id,
      number: res.number,
      base_version: res.version,
      status: res.status,
      state: 'synced',
      message: null,
    };
    await putDraft(next);
    return next;
  } catch (e) {
    // Offline, timeouts and server hiccups: stays dirty and is retried later.
    if (!(e instanceof ApiError) || e.status === 0 || e.status >= 500) return d;
    const next: LocalDraft = {
      ...d,
      state: e.code === 'VERSION_CONFLICT' ? 'conflict' : 'error',
      message: e.message,
    };
    await putDraft(next);
    return next;
  }
}

let running: Promise<number> | null = null;

/** Push every dirty draft; returns how many synced. Calls never overlap. */
export function syncAll(): Promise<number> {
  running ??= (async () => {
    let n = 0;
    try {
      for (const d of await listDrafts()) {
        if (d.state !== 'dirty') continue;
        if ((await syncDraft(d)).state === 'synced') n += 1;
      }
    } finally {
      running = null;
    }
    return n;
  })();
  return running;
}

/** Ask the service worker to fire a background sync once the connection is back. */
export function requestBackgroundSync(): void {
  if (!('serviceWorker' in navigator)) return;
  void navigator.serviceWorker.ready
    .then((reg) =>
      (
        reg as ServiceWorkerRegistration & { sync?: { register(t: string): Promise<void> } }
      ).sync?.register('dor-sync'),
    )
    .catch(() => undefined);
}
