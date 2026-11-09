import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export interface Journal {
  number: string;
  entry_date: string;
  total: string;
  lines: {
    account_code: string;
    debit: string;
    credit: string;
    cost_element_code: string | null;
    partner_code: string | null;
  }[];
}

export interface WarehouseOption {
  code: string;
  name: string;
  kind: 'base' | 'site';
  project_code: string | null;
}

export interface StockRow {
  warehouse_code: string;
  item_code: string;
  name: string;
  uom: string;
  qty: string;
  avg_cost: string;
  value: string;
  reorder_point: string;
}

export interface ReorderRow {
  item_code: string;
  name: string;
  uom: string;
  on_hand: string;
  reorder_point: string;
  suggested_qty: string;
  last_price: string | null;
  est_value: string;
}

export interface Valuation {
  rows: StockRow[];
  total: string;
  ledger_1310: string;
  difference: string;
  reconciled: boolean;
}

export interface TransferRow {
  id: string;
  number: string;
  from_warehouse: string;
  to_warehouse: string;
  value: string;
  note: string | null;
  created_at: string;
  lines: { item_code: string; qty: string; value: string }[];
}

export type CountStatus = 'draft' | 'awaiting_approval' | 'approved' | 'rejected';

export interface CountRow {
  id: string;
  number: string;
  warehouse_code: string;
  count_date: string;
  status: CountStatus;
  variance_value: string;
}

export interface CountDetail extends CountRow {
  note: string | null;
  reject_reason: string | null;
  request_id: string | null;
  journal: Journal | null;
  can_submit: boolean;
  lines: {
    item_code: string;
    name: string;
    system_qty: string;
    counted_qty: string;
    variance_qty: string;
    unit_cost: string;
    variance_value: string;
    reason: string | null;
  }[];
}

export type GrStatus = 'draft' | 'posted' | 'cancelled';

export interface GrRow {
  id: string;
  number: string;
  kind: 'goods' | 'service';
  status: GrStatus;
  po_id: string;
  po_number: string;
  vendor_code: string;
  received_date: string;
  warehouse_code: string | null;
  amount: string;
}

export interface GrDetail extends GrRow {
  po_status: string;
  vendor_name: string;
  project_id: string;
  project_number: string;
  cost_element_code: string;
  delivery_note: string | null;
  note: string | null;
  posted_at: string | null;
  journal: Journal | null;
  can_post: boolean;
  can_cancel: boolean;
  lines: {
    seq: number;
    item_code: string | null;
    description: string;
    qty: string;
    uom: string;
    unit_price: string;
    amount: string;
    to_stock: boolean;
  }[];
}

export interface Receivable {
  po_id: string;
  po_number: string;
  po_status: string;
  vendor_name: string;
  kind: 'goods' | 'service';
  can_receive: boolean;
  lines: {
    seq: number;
    item_code: string | null;
    description: string;
    uom: string;
    ordered: string;
    received: string;
    open: string;
    unit_price: string;
  }[];
}

export type MrStatus = 'issued' | 'partial' | 'pr_created';

export interface MrRow {
  id: string;
  number: string;
  status: MrStatus;
  status_label: string;
  project_number: string;
  site_warehouse: string;
  need_date: string;
  issued_value: string;
  has_pr: boolean;
}

export interface MrDetail {
  id: string;
  number: string;
  status: MrStatus;
  status_label: string;
  project_id: string;
  project_number: string;
  project_name: string;
  wbs_code: string;
  cost_element_code: string;
  site_warehouse: string;
  base_warehouse: string;
  requester_name: string;
  need_date: string;
  purpose: string | null;
  issued_value: string;
  created_at: string;
  pr: { id: string; number: string; status: string } | null;
  journal: Journal | null;
  lines: {
    seq: number;
    item_code: string;
    name: string;
    uom: string;
    qty: string;
    from_site: string;
    from_base: string;
    shortfall: string;
    value: string;
  }[];
}

export interface MrFormOptions {
  projects: { id: string; number: string; name: string; wbs: { code: string; name: string }[] }[];
  sites: { code: string; name: string; project_code: string | null }[];
  items: { code: string; name: string; uom: string; last_price: string | null }[];
  cost_elements: { code: string; name: string }[];
}

type Params = Record<string, string | number | undefined>;
export const qs = (p: Params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '') q.set(k, String(v));
  return q.toString();
};
type Page<T> = { items: T[]; total: number };

export const useWarehouses = () =>
  useQuery({
    queryKey: ['inventory', 'warehouses'],
    queryFn: () => api<WarehouseOption[]>('/inventory/warehouses'),
    staleTime: 300_000,
  });

export const useStock = (params: Params) =>
  useQuery({
    queryKey: ['inventory', 'stock', params],
    queryFn: () => api<Page<StockRow> & { total_value: string }>(`/inventory/stock?${qs(params)}`),
    placeholderData: keepPreviousData,
  });

export const stockExportPath = (params: Params) => `/inventory/stock/export?${qs(params)}`;

export const useReorder = (enabled: boolean) =>
  useQuery({
    queryKey: ['inventory', 'reorder'],
    queryFn: () => api<ReorderRow[]>('/inventory/reorder'),
    enabled,
  });

export const useValuation = (enabled: boolean) =>
  useQuery({
    queryKey: ['inventory', 'valuation'],
    queryFn: () => api<Valuation>('/inventory/valuation'),
    enabled,
  });

export const useTransfers = (page: number, enabled: boolean) =>
  useQuery({
    queryKey: ['inventory', 'transfers', page],
    queryFn: () => api<Page<TransferRow>>(`/inventory/transfers?${qs({ page })}`),
    enabled,
  });

export const useCounts = (page: number, enabled: boolean) =>
  useQuery({
    queryKey: ['inventory', 'counts', page],
    queryFn: () => api<Page<CountRow>>(`/inventory/counts?${qs({ page })}`),
    enabled,
  });

export const useCount = (id: string) =>
  useQuery({
    queryKey: ['inventory', 'count', id],
    queryFn: () => api<CountDetail>(`/inventory/counts/${id}`),
  });

export const useGrs = (params: Params) =>
  useQuery({
    queryKey: ['grs', 'list', params],
    queryFn: () => api<Page<GrRow>>(`/inventory/grs?${qs(params)}`),
    placeholderData: keepPreviousData,
  });

export const useGr = (id: string) =>
  useQuery({
    queryKey: ['grs', 'detail', id],
    queryFn: () => api<GrDetail>(`/inventory/grs/${id}`),
  });

export const useReceivable = (poId: string) =>
  useQuery({
    queryKey: ['grs', 'receivable', poId],
    queryFn: () => api<Receivable>(`/inventory/receivable/${poId}`),
    enabled: poId !== '',
  });

export const useMrs = (params: Params) =>
  useQuery({
    queryKey: ['mrs', 'list', params],
    queryFn: () => api<Page<MrRow>>(`/inventory/mrs?${qs(params)}`),
    placeholderData: keepPreviousData,
  });

export const useMr = (id: string) =>
  useQuery({
    queryKey: ['mrs', 'detail', id],
    queryFn: () => api<MrDetail>(`/inventory/mrs/${id}`),
  });

export const useMrFormOptions = () =>
  useQuery({
    queryKey: ['mrs', 'form-options'],
    queryFn: () => api<MrFormOptions>('/inventory/mrs/form-options'),
  });

function useInvMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const k of ['inventory', 'grs', 'mrs', 'pos', 'prs', 'projects'])
        void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}

export const useCreateGr = () =>
  useInvMutation((body: Record<string, unknown>) => postJson<GrDetail>('/inventory/grs', body));
export const usePostGr = (id: string) =>
  useInvMutation(() => postJson<GrDetail>(`/inventory/grs/${id}/post`));
export const useCancelGr = (id: string) =>
  useInvMutation(() => postJson<GrDetail>(`/inventory/grs/${id}/cancel`));
export const useCreateMr = () =>
  useInvMutation((body: Record<string, unknown>) => postJson<MrDetail>('/inventory/mrs', body));
export const useCreateTransfer = () =>
  useInvMutation((body: Record<string, unknown>) =>
    postJson<{ id: string; number: string; value: string }>('/inventory/transfers', body),
  );
export const useCreateCount = () =>
  useInvMutation((body: Record<string, unknown>) =>
    postJson<CountDetail>('/inventory/counts', body),
  );
export const useSubmitCount = (id: string) =>
  useInvMutation(() => postJson<CountDetail>(`/inventory/counts/${id}/submit`));
