import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Journal } from '@/features/inventory/api';
import { qs } from '@/features/inventory/api';
import { api, postJson } from '@/lib/api';

export type ViStatus = 'draft' | 'approved' | 'exception' | 'paid' | 'cancelled';
export const VI_STATUSES: ViStatus[] = ['draft', 'exception', 'approved', 'paid', 'cancelled'];

export interface ViRow {
  id: string;
  number: string;
  status: ViStatus;
  status_label: string;
  vendor_code: string;
  vendor_name: string;
  po_number: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  dpp: string;
  payable: string;
  outstanding: string;
}

export interface MatchRow {
  seq: number;
  description: string;
  uom: string;
  po_qty: string;
  received: string;
  invoiced_before: string;
  qty: string;
  po_price: string;
  price: string;
  qty_ok: boolean;
  price_ok: boolean;
}

export interface ViLine {
  seq: number;
  description: string;
  qty: string;
  unit_price: string;
  amount?: string;
}

export interface ViDetail extends ViRow {
  vendor_npwp: string | null;
  po_id: string;
  project_number: string | null;
  tax_invoice_no: string | null;
  kind: 'goods' | 'service';
  term_days: number;
  ppn: string;
  pph23_pct: string;
  pph23: string;
  paid_amount: string;
  note: string | null;
  exception_reason: string | null;
  match_result: MatchRow[] | null;
  journal: Journal | null;
  credit_notes: {
    credit_note_no: string;
    note_date: string;
    dpp: string;
    ppn: string;
    reason: string;
  }[];
  can_edit: boolean;
  can_match: boolean;
  can_credit_note: boolean;
  lines: ViLine[];
}

export interface Prefill {
  po_id: string;
  po_number: string;
  vendor_code: string;
  vendor_name: string;
  vendor_npwp: string | null;
  term_days: number;
  kind: 'goods' | 'service';
  ppn_pct: string;
  lines: {
    seq: number;
    description: string;
    uom: string;
    po_qty: string;
    received: string;
    invoiced: string;
    open: string;
    unit_price: string;
  }[];
}

type Buckets = Record<'not_due' | 'd1_30' | 'd31_60' | 'd61_90' | 'd90_plus' | 'total', string>;
export interface Aging {
  as_of: string;
  rows: (Buckets & { vendor_code: string; vendor_name: string })[];
  totals: Buckets;
}

export interface Statement {
  vendor_code: string;
  vendor_name: string;
  date_from: string;
  date_to: string;
  opening: string;
  closing: string;
  rows: {
    date: string;
    journal: string;
    document: string | null;
    description: string;
    debit: string;
    credit: string;
    balance: string;
  }[];
}

type Params = Record<string, string | number | undefined>;

export const viExportPath = (p: Params) => `/finance/vendor-invoices/export?${qs(p)}`;

export const useVendorInvoices = (params: Params) =>
  useQuery({
    queryKey: ['vendor-invoices', 'list', params],
    queryFn: () =>
      api<{ items: ViRow[]; total: number; counts: Record<ViStatus, number> }>(
        `/finance/vendor-invoices?${qs(params)}`,
      ),
    placeholderData: keepPreviousData,
  });

export const useVendorInvoice = (id: string) =>
  useQuery({
    queryKey: ['vendor-invoices', 'detail', id],
    queryFn: () => api<ViDetail>(`/finance/vendor-invoices/${id}`),
  });

export const usePoOptions = (q: string) =>
  useQuery({
    queryKey: ['vendor-invoices', 'po-options', q],
    queryFn: () =>
      api<{ id: string; number: string; vendor_name: string; status: string }[]>(
        `/finance/vendor-invoices/po-options?${qs({ q })}`,
      ),
  });

export const usePrefill = (poId: string) =>
  useQuery({
    queryKey: ['vendor-invoices', 'prefill', poId],
    queryFn: () => api<Prefill>(`/finance/vendor-invoices/prefill/${poId}`),
    enabled: poId !== '',
  });

export const useAging = (enabled: boolean) =>
  useQuery({
    queryKey: ['vendor-invoices', 'aging'],
    queryFn: () => api<Aging>('/finance/ap-aging'),
    enabled,
  });

export const useFinanceVendors = (enabled: boolean) =>
  useQuery({
    queryKey: ['vendor-invoices', 'vendors'],
    queryFn: () => api<{ code: string; name: string }[]>('/finance/vendors'),
    enabled,
    staleTime: 300_000,
  });

export const useStatement = (vendor: string, from: string, to: string) =>
  useQuery({
    queryKey: ['vendor-invoices', 'statement', vendor, from, to],
    queryFn: () =>
      api<Statement>(`/finance/vendor-statement?${qs({ vendor, date_from: from, date_to: to })}`),
    enabled: vendor !== '' && from !== '' && to !== '',
  });

function useViMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['vendor-invoices'] }),
  });
}

export const useCreateVendorInvoice = () =>
  useViMutation((body: Record<string, unknown>) =>
    postJson<ViDetail>('/finance/vendor-invoices', body),
  );
export const useCorrectVendorInvoice = (id: string) =>
  useViMutation((body: Record<string, unknown>) =>
    api<ViDetail>(`/finance/vendor-invoices/${id}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  );
export const useMatchVendorInvoice = (id: string) =>
  useViMutation(() => postJson<ViDetail>(`/finance/vendor-invoices/${id}/match`));
export const useCreditNote = (id: string) =>
  useViMutation((body: Record<string, unknown>) =>
    postJson<ViDetail>(`/finance/vendor-invoices/${id}/credit-note`, body),
  );
export const useCancelVendorInvoice = (id: string) =>
  useViMutation((reason: string) =>
    postJson<ViDetail>(`/finance/vendor-invoices/${id}/cancel`, { reason }),
  );
