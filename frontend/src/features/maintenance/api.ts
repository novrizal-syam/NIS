import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { qs } from '@/features/inventory/api';
import { api, postJson } from '@/lib/api';

export interface AssetRow {
  code: string;
  name: string;
  equipment_type_code: string | null;
  equipment_type: string | null;
  category: string | null;
  criticality: string;
  location: string | null;
  is_active: boolean;
  cert_blocked: string | null;
  cert_warning: string | null;
  allocated_to: string | null;
  open_work_orders: number;
  operating_hours: string;
}

export interface WoRow {
  id: string;
  number: string;
  asset_code: string;
  kind: 'preventive' | 'corrective' | 'inspection_pre' | 'inspection_post';
  status: 'open' | 'in_progress' | 'done' | 'cancelled';
  title: string;
  task_code: string | null;
  trigger: string | null;
  due_date: string | null;
  due_hours: string | null;
  completed_date: string | null;
  overdue: boolean;
}

export interface ChecklistItem {
  item: string;
  result: 'ok' | 'nok' | 'na' | null;
  note: string | null;
}

export interface WoDetail extends WoRow {
  asset_name: string;
  form_code: string | null;
  project_number: string | null;
  checklist: ChecklistItem[];
  labour_hours: string;
  result: string | null;
  signature_name: string | null;
  parts_value: string;
  parts: { item_code: string; warehouse_code: string; qty: string; value: string }[];
  can_edit: boolean;
}

export interface AssetDetail {
  code: string;
  name: string;
  equipment_type_code: string | null;
  criticality: string;
  serial_no: string | null;
  location: string | null;
  internal_day_rate: string;
  certificates: {
    name: string;
    number: string | null;
    expiry_date: string | null;
    mandatory?: boolean;
    status: string;
  }[];
  cert_blocked: string | null;
  cert_warning: string | null;
  operating_hours: string;
  allocations: { project_number: string; start_date: string; released_at: string | null }[];
  schedules: {
    task_code: string;
    title: string;
    frequency: string;
    interval_hours: number | null;
    last_done_date: string;
    last_done_hours: string;
    next_due_date: string | null;
    next_due_hours: string | null;
  }[];
  work_orders: WoRow[];
  downtime: { start_date: string; hours: string; reason: string }[];
}

export interface PmTask {
  code: string;
  equipment_type_code: string;
  title: string;
  frequency: string;
  interval_hours: number | null;
  form_code: string | null;
  checklist: string[];
  est_hours: string | null;
  is_active: boolean;
}

export interface Kpis {
  date_from: string;
  date_to: string;
  rows: {
    asset_code: string;
    name: string;
    criticality: string;
    days_used: string;
    operating_hours: string;
    downtime_hours: string;
    failures: number;
    utilisation_pct: string | null;
    downtime_pct: string | null;
    mtbf_hours: string | null;
    mttr_hours: string | null;
  }[];
  totals: {
    utilisation_pct: string | null;
    downtime_pct: string | null;
    pm_due: number;
    pm_on_time: number;
    pm_compliance_pct: string | null;
    mtbf_hours: string | null;
    mttr_hours: string | null;
    failures: number;
  };
  targets: { utilisation_pct: number; downtime_pct: number };
}

const k = (...p: unknown[]) => ['maintenance', ...p];

export const useAssets = (q: string) =>
  useQuery({
    queryKey: k('assets', q),
    queryFn: () => api<AssetRow[]>(`/maintenance/assets?${qs({ q })}`),
    placeholderData: keepPreviousData,
  });
export const useAsset = (code: string) =>
  useQuery({
    queryKey: k('asset', code),
    queryFn: () => api<AssetDetail>(`/maintenance/assets/${code}`),
  });
export const useWos = (params: Record<string, string | number | undefined>) =>
  useQuery({
    queryKey: k('wos', params),
    queryFn: () =>
      api<{ items: WoRow[]; total: number; counts: Record<string, number> }>(
        `/maintenance/work-orders?${qs(params)}`,
      ),
    placeholderData: keepPreviousData,
  });
export const useWo = (id: string) =>
  useQuery({
    queryKey: k('wo', id),
    queryFn: () => api<WoDetail>(`/maintenance/work-orders/${id}`),
  });
export const usePmTasks = (enabled: boolean) =>
  useQuery({
    queryKey: k('pm-tasks'),
    queryFn: () => api<PmTask[]>('/maintenance/pm-tasks'),
    enabled,
  });
export const useDowntime = (enabled: boolean) =>
  useQuery({
    queryKey: k('downtime'),
    queryFn: () =>
      api<
        {
          asset_code: string;
          start_date: string;
          end_date: string | null;
          hours: string;
          reason: string;
          from_dor: boolean;
        }[]
      >('/maintenance/downtime'),
    enabled,
  });
export const useKpis = (from: string, to: string, enabled: boolean) =>
  useQuery({
    queryKey: k('kpis', from, to),
    queryFn: () => api<Kpis>(`/maintenance/kpis?${qs({ date_from: from, date_to: to })}`),
    enabled,
  });
export const useMntProjects = () =>
  useQuery({
    queryKey: k('projects'),
    queryFn: () => api<{ id: string; number: string; name: string }[]>('/maintenance/projects'),
    staleTime: 60_000,
  });

function useMnt<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['maintenance'] }),
  });
}

export const useAllocate = (code: string) =>
  useMnt((body: { project_id: string; start_date: string; note?: string }) =>
    postJson<unknown>(`/maintenance/assets/${code}/allocate`, body),
  );
export const useRelease = (code: string) =>
  useMnt((release_date: string) =>
    postJson<unknown>(`/maintenance/assets/${code}/release`, { release_date }),
  );
export const useUpdateWo = (id: string) =>
  useMnt((body: { checklist: ChecklistItem[]; labour_hours: string; result: string | null }) =>
    api<WoDetail>(`/maintenance/work-orders/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  );
export const useIssuePart = (id: string) =>
  useMnt((body: { item_code: string; warehouse_code: string; qty: string }) =>
    postJson<WoDetail>(`/maintenance/work-orders/${id}/parts`, body),
  );
export const useCompleteWo = (id: string) =>
  useMnt(() => postJson<WoDetail>(`/maintenance/work-orders/${id}/complete`, {}));
export const useCreateWo = () =>
  useMnt((body: { asset_code: string; title: string; checklist: string[] }) =>
    postJson<WoDetail>('/maintenance/work-orders', body),
  );
export const useAddDowntime = () =>
  useMnt((body: Record<string, unknown>) => postJson<unknown>('/maintenance/downtime', body));
export const useRunPm = () => useMnt(() => postJson<{ created: number }>('/maintenance/pm-run'));

/** Multipart upload of the GEK PM plan workbook. */
export const useImportPm = () =>
  useMnt(async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api<{
      tasks_created: number;
      tasks_updated: number;
      assets_created: number;
      assets_updated: number;
    }>('/maintenance/pm-import', { method: 'POST', body: form });
  });
