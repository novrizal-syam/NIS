import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export interface RfqVendorOption {
  code: string;
  name: string;
  rating: string | null;
  status: string;
  excluded: string | null;
}

export interface Score {
  vendor_code: string;
  price: string;
  delivery: string;
  rating: string;
  total: string;
}

export interface RfqQuote {
  id: string;
  vendor_code: string;
  vendor_name: string;
  rating: string | null;
  status: 'invited' | 'quoted' | 'declined';
  total: string | null;
  delivery_days: number | null;
  payment_terms: string | null;
  valid_until: string | null;
  note: string | null;
  lines: { seq: number; unit_price: string; amount: string }[];
  score: Score | null;
}

export interface RfqDetail {
  id: string;
  number: string;
  status: 'open' | 'award_pending' | 'awarded' | 'cancelled';
  category: string;
  due_date: string | null;
  pr_id: string;
  pr_number: string;
  pr_total: string;
  awarded_vendor_code: string | null;
  award_reason: string | null;
  pending_vendor_code: string | null;
  request_id: string | null;
  best_vendor_code: string | null;
  weights: Record<'price' | 'delivery' | 'rating', string>;
  po: { id: string; number: string } | null;
  can_edit: boolean;
  can_create_po: boolean;
  pr_lines: {
    seq: number;
    item_code: string | null;
    description: string;
    qty: string;
    uom: string;
    est_price: string;
  }[];
  quotes: RfqQuote[];
}

export interface RfqRow {
  id: string;
  number: string;
  status: RfqDetail['status'];
  category: string;
  pr_id: string;
  pr_number: string;
  pr_total: string;
  awarded_vendor_code: string | null;
  due_date: string | null;
  created_at: string;
}

export interface PoLine {
  seq: number;
  item_code: string | null;
  description: string;
  qty: string;
  uom: string;
  unit_price: string;
  amount?: string;
}

export interface PoDetail {
  id: string;
  number: string;
  revision: number;
  status: 'draft' | 'issued' | 'revision_pending' | 'cancelled' | 'closed';
  vendor_code: string;
  vendor_name: string;
  project_id: string;
  project_number: string;
  wbs_code: string;
  cost_element_code: string;
  pr_id: string;
  pr_number: string;
  rfq_id: string | null;
  rfq_number: string | null;
  subtotal: string;
  ppn_pct: string;
  ppn_amount: string;
  total: string;
  delivery_date: string | null;
  delivery_location: string;
  payment_terms: string | null;
  terms: string | null;
  issued_at: string | null;
  revision_reason: string | null;
  pending_revision: { lines: PoLine[]; reason: string } | null;
  request_id: string | null;
  budget: { available: string; commit_by_po: string; budget: string; used_pct: string };
  can_edit: boolean;
  can_issue: boolean;
  can_revise: boolean;
  lines: PoLine[];
}

export interface PoRow {
  id: string;
  number: string;
  revision: number;
  status: PoDetail['status'];
  vendor_name: string;
  subtotal: string;
  total: string;
  delivery_date: string | null;
  issued_at: string | null;
}

export interface PriceHistoryRow {
  item_code: string | null;
  description: string;
  vendor_code: string;
  vendor_name: string;
  uom: string;
  unit_price: string;
  source: 'rfq_quote' | 'po';
  doc_number: string;
  at: string;
}

type Params = Record<string, string | number | undefined>;
const qs = (p: Params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '') q.set(k, String(v));
  return q.toString();
};

export const useVendorCategories = () =>
  useQuery({
    queryKey: ['procurement', 'categories'],
    queryFn: () => api<string[]>('/procurement/vendor-categories'),
    staleTime: 300_000,
  });

export const useRfqVendors = (category: string) =>
  useQuery({
    queryKey: ['procurement', 'rfq-vendors', category],
    queryFn: () => api<RfqVendorOption[]>(`/procurement/rfq-vendors?${qs({ category })}`),
    enabled: category !== '',
  });

export const usePriceHistory = (params: Params, enabled: boolean) =>
  useQuery({
    queryKey: ['procurement', 'price-history', params],
    queryFn: () => api<PriceHistoryRow[]>(`/procurement/price-history?${qs(params)}`),
    enabled,
  });

export const useRfqs = (params: Params) =>
  useQuery({
    queryKey: ['rfqs', 'list', params],
    queryFn: () => api<{ items: RfqRow[]; total: number }>(`/procurement/rfqs?${qs(params)}`),
    placeholderData: keepPreviousData,
  });

export const useRfq = (id: string) =>
  useQuery({
    queryKey: ['rfqs', 'detail', id],
    queryFn: () => api<RfqDetail>(`/procurement/rfqs/${id}`),
  });

export const usePos = (params: Params) =>
  useQuery({
    queryKey: ['pos', 'list', params],
    queryFn: () => api<{ items: PoRow[]; total: number }>(`/procurement/pos?${qs(params)}`),
    placeholderData: keepPreviousData,
  });

export const usePo = (id: string) =>
  useQuery({
    queryKey: ['pos', 'detail', id],
    queryFn: () => api<PoDetail>(`/procurement/pos/${id}`),
  });

function useProcMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const k of ['rfqs', 'pos', 'prs', 'procurement', 'projects'])
        void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}

export const useCreateRfq = () =>
  useProcMutation((body: Record<string, unknown>) =>
    postJson<RfqDetail>('/procurement/rfqs', body),
  );
export const useRecordQuote = (rfqId: string) =>
  useProcMutation((v: { quoteId: string; body: Record<string, unknown> }) =>
    api<RfqDetail>(`/procurement/rfqs/${rfqId}/quotes/${v.quoteId}`, {
      method: 'PUT',
      body: JSON.stringify(v.body),
    }),
  );
export const useAward = (rfqId: string) =>
  useProcMutation((body: { vendor_code: string; reason?: string }) =>
    postJson<RfqDetail & { approval_needed: boolean }>(`/procurement/rfqs/${rfqId}/award`, body),
  );
export const useCreatePo = (rfqId: string) =>
  useProcMutation(() => postJson<PoDetail>(`/procurement/rfqs/${rfqId}/po`));
export const useSavePo = (id: string) =>
  useProcMutation((body: Record<string, unknown>) =>
    api<PoDetail>(`/procurement/pos/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  );
export const useIssuePo = (id: string) =>
  useProcMutation(() => postJson<PoDetail>(`/procurement/pos/${id}/issue`));
export const useRevisePo = (id: string) =>
  useProcMutation((body: Record<string, unknown>) =>
    postJson<PoDetail & { approval_needed: boolean }>(`/procurement/pos/${id}/revise`, body),
  );
