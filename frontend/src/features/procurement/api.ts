import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export type PrStatus =
  'draft' | 'blocked' | 'awaiting_approval' | 'approved' | 'ordered' | 'cancelled';
export const PR_STATUSES: PrStatus[] = [
  'draft',
  'blocked',
  'awaiting_approval',
  'approved',
  'ordered',
  'cancelled',
];

export interface PrRow {
  id: string;
  number: string;
  status: PrStatus;
  project_id: string;
  project_number: string;
  project_name: string;
  wbs_code: string;
  cost_element_code: string;
  total: string;
  shortfall: string | null;
  need_date: string;
  requester_name: string | null;
  submitted_at: string | null;
  created_at: string;
}

export interface PrLine {
  item_code: string | null;
  description: string;
  qty: string;
  uom: string;
  est_price: string;
  amount?: string;
}

export interface PrDetail extends PrRow {
  delivery_location: string;
  purpose: string | null;
  block_message: string | null;
  bcr_suggestion: string | null;
  reject_reason: string | null;
  cancel_reason: string | null;
  request_id: string | null;
  approved_at: string | null;
  linked_bcr: { number: string; status: string } | null;
  budget: {
    budget: string;
    pre_commit: string;
    commit: string;
    actual: string;
    available: string;
    used_pct: string;
    held_by_pr: string;
  };
  approvals: {
    approver_role: string;
    label: string | null;
    status: string;
    acted_by: string | null;
    acted_at: string | null;
    comment: string | null;
  }[];
  can_edit: boolean;
  can_submit: boolean;
  can_cancel: boolean;
  can_request_bcr: boolean;
  can_rfq: boolean;
  rfq: { id: string; number: string } | null;
  po: { id: string; number: string } | null;
  lines: PrLine[];
}

export interface PrFormOptions {
  projects: { id: string; number: string; name: string; wbs: { code: string; name: string }[] }[];
  cost_elements: { code: string; name: string }[];
}

type Params = Record<string, string | number | boolean | undefined>;
const qs = (p: Params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p))
    if (v !== undefined && v !== '' && v !== false) q.set(k, String(v));
  return q.toString();
};
export const prExportPath = (p: Params) => `/procurement/prs/export?${qs(p)}`;

export function usePrs(params: Params) {
  return useQuery({
    queryKey: ['prs', 'list', params],
    queryFn: () =>
      api<{ items: PrRow[]; total: number; counts: Record<PrStatus, number> }>(
        `/procurement/prs?${qs(params)}`,
      ),
    placeholderData: keepPreviousData,
  });
}

export function usePr(id: string) {
  return useQuery({
    queryKey: ['prs', 'detail', id],
    queryFn: () => api<PrDetail>(`/procurement/prs/${id}`),
  });
}

export function usePrFormOptions() {
  return useQuery({
    queryKey: ['prs', 'form-options'],
    queryFn: () => api<PrFormOptions>('/procurement/prs/form-options'),
    staleTime: 60_000,
  });
}

function usePrMutation<V>(fn: (v: V) => Promise<PrDetail>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['prs'] });
      void qc.invalidateQueries({ queryKey: ['projects'] });
    },
  });
}

export const useSavePr = (id: string | null) =>
  usePrMutation((body: Record<string, unknown>) =>
    id
      ? api<PrDetail>(`/procurement/prs/${id}`, { method: 'PUT', body: JSON.stringify(body) })
      : postJson<PrDetail>('/procurement/prs', body),
  );
export const useSubmitPr = (id: string) =>
  usePrMutation(() => postJson<PrDetail>(`/procurement/prs/${id}/submit`));
export const useCancelPr = (id: string) =>
  usePrMutation((reason: string) =>
    postJson<PrDetail>(`/procurement/prs/${id}/cancel`, { reason }),
  );
