import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export interface BankAccount {
  id: string;
  code: string;
  name: string;
  bank_name: string;
  account_no: string;
  currency: string;
  gl_account: string;
  adapter: string;
  is_default: boolean;
  is_active: boolean;
  balance: string;
  unreconciled_statement_lines: number;
}

export interface Reconciliation {
  book_balance: string;
  statement_movement: string;
  reconciled: number;
  unmatched_statement: {
    id: string;
    value_date: string;
    amount: string;
    description: string;
    reference: string | null;
  }[];
  unmatched_book: {
    id: string;
    entry_date: string;
    number: string;
    source_number: string | null;
    description: string;
    amount: string;
  }[];
}

export interface RunItem {
  seq: number;
  kind: string;
  kind_label: string;
  vendor_invoice_id: string | null;
  vendor_code: string | null;
  payee: string;
  reference: string | null;
  amount: string;
}

export interface PaymentRun {
  id: string;
  number: string;
  pay_date: string;
  bank_account: { id: string; code: string; name: string } | null;
  description: string | null;
  total: string;
  status: string;
  request_id: string | null;
  reject_reason: string | null;
  created_by: string | null;
  released_at: string | null;
  journal_id: string | null;
  bank_file_ref: string | null;
  items: RunItem[];
  bukti_potong_vendors?: string[];
}

export interface DueItems {
  invoices: {
    vendor_invoice_id: string;
    number: string;
    invoice_no: string;
    vendor_code: string;
    vendor_name: string;
    due_date: string | null;
    outstanding: string;
    pph23: string;
  }[];
  liabilities: { kind: string; label: string; outstanding: string }[];
}

export interface ForecastWeek {
  week: number;
  start: string;
  end: string;
  opening: string;
  closing: string;
  inflow: string;
  outflow: string;
  net: string;
  negative: boolean;
  [key: string]: string | number | boolean;
}

export interface Forecast {
  as_of: string;
  opening: string;
  closing: string;
  lowest: string;
  inflows: { key: string; label: string }[];
  outflows: { key: string; label: string }[];
  weeks: ForecastWeek[];
}

export interface AdvanceLine {
  seq: number;
  spent_on: string;
  cost_element: string;
  wbs_code: string | null;
  description: string;
  amount: string;
  attachment_id: string | null;
}

export interface Advance {
  id: string;
  number: string;
  requester_id: string;
  project_id: string | null;
  purpose: string;
  amount: string;
  needed_date: string;
  status: string;
  status_label: string;
  request_id: string | null;
  reject_reason: string | null;
  disbursed_at: string | null;
  days_open: number | null;
  overdue: boolean;
  spent: string;
  difference: string | null;
  settled_at: string | null;
  lines: AdvanceLine[];
}

export interface AdvanceOptions {
  cost_elements: { code: string; name: string }[];
  projects: { id: string; number: string; name: string; wbs: string[] }[];
}

export const useBankAccounts = () =>
  useQuery({
    queryKey: ['treasury', 'accounts'],
    queryFn: () => api<BankAccount[]>('/treasury/bank-accounts'),
  });

export const useReconciliation = (id: string | null) =>
  useQuery({
    queryKey: ['treasury', 'recon', id],
    queryFn: () => api<Reconciliation>(`/treasury/bank-accounts/${id}/reconciliation`),
    enabled: !!id,
  });

export const useRuns = () =>
  useQuery({
    queryKey: ['treasury', 'runs'],
    queryFn: () => api<PaymentRun[]>('/treasury/payment-runs'),
  });

export const useRun = (id: string | null) =>
  useQuery({
    queryKey: ['treasury', 'run', id],
    queryFn: () => api<PaymentRun>(`/treasury/payment-runs/${id}`),
    enabled: !!id,
  });

export const useDueItems = (dueBy: string, enabled: boolean) =>
  useQuery({
    queryKey: ['treasury', 'due', dueBy],
    queryFn: () => api<DueItems>(`/treasury/payment-runs/due-items?due_by=${dueBy}`),
    enabled,
  });

export const useForecast = () =>
  useQuery({
    queryKey: ['treasury', 'forecast'],
    queryFn: () => api<Forecast>('/treasury/forecast'),
  });

export const useAdvances = () =>
  useQuery({
    queryKey: ['treasury', 'advances'],
    queryFn: () => api<Advance[]>('/treasury/advances'),
  });

export const useAdvance = (id: string | null) =>
  useQuery({
    queryKey: ['treasury', 'advance', id],
    queryFn: () => api<Advance>(`/treasury/advances/${id}`),
    enabled: !!id,
  });

export const useAdvanceOptions = () =>
  useQuery({
    queryKey: ['treasury', 'advance-options'],
    queryFn: () => api<AdvanceOptions>('/treasury/advance-options'),
    staleTime: 300_000,
  });

export function useTreasuryAction<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown; method?: string; form?: FormData }) =>
      v.form
        ? api<R>(v.path, { method: 'POST', body: v.form })
        : v.method
          ? api<R>(v.path, { method: v.method, body: JSON.stringify(v.body) })
          : postJson<R>(v.path, v.body ?? {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['treasury'] });
      void qc.invalidateQueries({ queryKey: ['attachments'] });
    },
  });
}
