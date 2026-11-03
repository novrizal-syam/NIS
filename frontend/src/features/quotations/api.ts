import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export type QuotationStatus =
  'draft' | 'submitted' | 'approved' | 'rejected' | 'sent' | 'superseded';
export const QUOTATION_STATUSES: QuotationStatus[] = [
  'draft',
  'submitted',
  'approved',
  'rejected',
  'sent',
];

export interface QuotationRow {
  id: string;
  number: string;
  revision: number;
  label: string;
  status: QuotationStatus;
  opportunity_id: string;
  opportunity_number: string;
  opportunity_title: string;
  company_name: string;
  owner_name: string | null;
  total_price: string;
  margin_pct: string;
  margin_warning: boolean;
  valid_until: string | null;
  submitted_at: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface QuotationLine {
  id?: string;
  price_item_code: string | null;
  description: string;
  unit: string;
  qty: string;
  unit_cost: string;
  unit_price: string;
  line_cost?: string;
  line_price?: string;
}

export interface QuotationDetail extends QuotationRow {
  subtotal: string;
  discount_pct: string;
  discount_amount: string;
  total_cost: string;
  margin: string;
  notes: string | null;
  terms: string | null;
  revision_reason: string | null;
  request_id: string | null;
  decision_comment: string | null;
  opportunity_stage: string;
  contact_name: string | null;
  contact_email: string | null;
  sent_to_email: string | null;
  letter: { number: string; date: string; file_id: string | null } | null;
  is_latest: boolean;
  can_edit: boolean;
  can_submit: boolean;
  can_revise: boolean;
  can_send: boolean;
  lines: QuotationLine[];
  revisions: {
    id: string;
    revision: number;
    status: QuotationStatus;
    total_price: string;
    margin_pct: string;
    reason: string | null;
    created_at: string;
  }[];
}

export interface PriceItemOption {
  code: string;
  name: string;
  unit: string;
  unit_cost: string;
  unit_price: string;
}

type Params = Record<string, string | number | undefined>;

const qs = (params: Params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') q.set(k, String(v));
  return q.toString();
};

export const quotationExportPath = (params: Params) => `/quotations/export?${qs(params)}`;

export function useQuotations(params: Params, enabled = true) {
  return useQuery({
    queryKey: ['quotations', 'list', params],
    queryFn: () =>
      api<{
        items: QuotationRow[];
        total: number;
        counts: Record<QuotationStatus, number>;
      }>(`/quotations?${qs(params)}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useQuotation(id: string) {
  return useQuery({
    queryKey: ['quotations', 'detail', id],
    queryFn: () => api<QuotationDetail>(`/quotations/${id}`),
  });
}

export function usePriceItems() {
  return useQuery({
    queryKey: ['quotations', 'price-items'],
    queryFn: () => api<PriceItemOption[]>('/quotations/price-items'),
    staleTime: 300_000,
  });
}

export function useQuotationConfig() {
  return useQuery({
    queryKey: ['quotations', 'config'],
    queryFn: () =>
      api<{ margin_warning_pct: string; email_configured: boolean }>('/quotations/config'),
    staleTime: 300_000,
  });
}

function useQuotationMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['quotations'] });
      void qc.invalidateQueries({ queryKey: ['crm'] });
    },
  });
}

export const useCreateQuotation = () =>
  useQuotationMutation((opportunity_id: string) =>
    postJson<QuotationDetail>('/quotations', { opportunity_id }),
  );

export const useSaveQuotation = (id: string) =>
  useQuotationMutation((body: Record<string, unknown>) =>
    api<QuotationDetail>(`/quotations/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  );

export const useSubmitQuotation = (id: string) =>
  useQuotationMutation(() =>
    postJson<QuotationDetail & { approver: string | null }>(`/quotations/${id}/submit`),
  );

export const useReviseQuotation = (id: string) =>
  useQuotationMutation((reason: string) =>
    postJson<QuotationDetail>(`/quotations/${id}/revise`, { reason }),
  );

export const useSendQuotation = (id: string) =>
  useQuotationMutation((body: { send_email: boolean; to_email?: string; message?: string }) =>
    postJson<QuotationDetail & { letter_number: string; email_status: string }>(
      `/quotations/${id}/send`,
      body,
    ),
  );
