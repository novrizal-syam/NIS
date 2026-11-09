/**
 * Offline storage for DOR drafts (IndexedDB). Every draft is saved here first; the sync queue
 * pushes dirty drafts to `/operations/dors/sync` when online. `client_id` makes the server save
 * idempotent and `base_version` lets the server detect edits made on another device.
 */
import type { DorData, FormOptions } from './types';

const DB = 'nustrad-dor';
const DRAFTS = 'drafts';
const OPTIONS = 'options';

export type SyncState = 'dirty' | 'synced' | 'conflict' | 'error';

export interface LocalDraft {
  client_id: string;
  project_id: string;
  project_number: string;
  server_id: string | null;
  number: string | null;
  base_version: number | null;
  status: string; // server status (draft | returned | submitted | approved) or 'local'
  data: DorData;
  state: SyncState;
  message: string | null;
  updated_at: string;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(DRAFTS))
        db.createObjectStore(DRAFTS, { keyPath: 'client_id' });
      if (!db.objectStoreNames.contains(OPTIONS)) db.createObjectStore(OPTIONS);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run<T>(
  store: string,
  mode: IDBTransactionMode,
  fn: (s: IDBObjectStore) => IDBRequest,
): Promise<T> {
  const db = await open();
  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const req = fn(tx.objectStore(store));
    req.onsuccess = () => resolve(req.result as T);
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
  });
}

export const putDraft = (d: LocalDraft) => run<IDBValidKey>(DRAFTS, 'readwrite', (s) => s.put(d));
export const getDraft = (clientId: string) =>
  run<LocalDraft | undefined>(DRAFTS, 'readonly', (s) => s.get(clientId));
export const listDrafts = () => run<LocalDraft[]>(DRAFTS, 'readonly', (s) => s.getAll());
export const deleteDraft = (clientId: string) =>
  run<undefined>(DRAFTS, 'readwrite', (s) => s.delete(clientId));
export const putOptions = (projectId: string, o: FormOptions) =>
  run<IDBValidKey>(OPTIONS, 'readwrite', (s) => s.put(o, projectId));
export const getOptions = (projectId: string) =>
  run<FormOptions | undefined>(OPTIONS, 'readonly', (s) => s.get(projectId));
