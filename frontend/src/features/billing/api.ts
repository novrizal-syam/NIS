import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { qs } from '@/features/inventory/api';
import { api, postJson } from '@/lib/api';

export interface TicketLine {
  id: string;
  seq: number;
  work_date: string;
  kind: 'equipment' | 'personnel' | 'consumable';
  description: string;
  qty: string;
  unit: string;
  amount: string;
  disputed: boolean;
  dispute_reason: string | null;
}

export interface Ticket {
  id: string;
  number: string;
  status: 'awaiting_signature' | 'signed' | 'invoiced' | 'cancelled';
  status_label: string;
  project_id: string;
  project_number: string;
  project_name: string;
  contract_number: string;
  client_name: string;
  period_from: string;
  period_to: string;
  gross_value: string;
  disputed_value: string;
  value: string;
  signer_name: string | null;
  sign_method: string | null;
  signed_at: string | null;
  acceptance_no: string | null;
  psre_ref: string | null;
  link_email: string | null;
  link_expires_at: string | null;
  invoice: { id: string; number: string } | null;
  dors: { id: string; number: string; report_date: string }[];
  can_sign: boolean;
  lines: TicketLine[];
}

export interface TicketRow {
  id: string;
  number: string;
  status: Ticket['status'];
  status_label: string;
  project_number: string;
  period_from: string;
  period_to: string;
  value: string;
  disputed_value: string;
  acceptance_no: string | null;
}

export type InvStatus = 'draft' | 'faktur_issued' | 'sent' | 'paid' | 'cancelled';

export interface InvoiceRow {
  id: string;
  number: string;
  status: InvStatus;
  status_label: string;
  client_code: string | null;
  client_name: string | null;
  invoice_date: string;
  due_date: string;
  faktur_number: string | null;
  subtotal: string;
  total: string;
  outstanding: string;
  overdue: boolean;
}

export interface Invoice extends InvoiceRow {
  client_email: string | null;
  contract_number: string | null;
  dpp_other: string;
  ppn_rate: string;
  ppn: string;
  pph23_rate: string;
  pph23_expected: string;
  net_cash: string;
  stamp_duty: string;
  faktur_date: string | null;
  sent_at: string | null;
  sent_to: string | null;
  paid_amount: string;
  pph23_withheld: string;
  paid_at: string | null;
  pack_attachment_id: string | null;
  note: string | null;
  tickets: { id: string; number: string; value: string; acceptance_no: string | null }[];
  receipts: {
    number: string;
    receipt_date: string;
    cash: string;
    pph23: string;
    bukti_potong_no: string | null;
  }[];
}

export interface BankLineRow {
  id: string;
  value_date: string;
  amount: string;
  description: string;
  reference: string | null;
  status: string;
  suggested_invoice_id: string | null;
  suggested_invoice_number: string | null;
  match_rule: string | null;
}

type Buckets = Record<'not_due' | 'd1_30' | 'd31_60' | 'd61_90' | 'd90_plus' | 'total', string>;

const useGet = <T>(path: string, enabled = true) =>
  useQuery({ queryKey: ['billing', path], queryFn: () => api<T>(path), enabled });

export const useBillingProjects = () =>
  useGet<{ id: string; number: string; name: string; contract_number: string }[]>(
    '/billing/projects',
  );
export const useBillableDors = (projectId: string) =>
  useGet<{ id: string; number: string; report_date: string; revenue: string }[]>(
    `/billing/billable-dors?${qs({ project_id: projectId })}`,
    projectId !== '',
  );
export const useTickets = (status: string) =>
  useGet<TicketRow[]>(`/billing/tickets?${qs({ status })}`);
export const useTicket = (id: string) => useGet<Ticket>(`/billing/tickets/${id}`);
export const useTicketByToken = (token: string) => useGet<Ticket>(`/billing/sign/${token}`);
export const useSignedTickets = () =>
  useGet<
    {
      id: string;
      number: string;
      contract_id: string;
      contract_number: string;
      project_number: string;
      value: string;
      period_to: string;
    }[]
  >('/billing/signed-tickets');
export const useInvoices = (status: string, q: string) =>
  useGet<{ items: InvoiceRow[]; counts: Record<string, number> }>(
    `/billing/invoices?${qs({ status, q })}`,
  );
export const useInvoice = (id: string) => useGet<Invoice>(`/billing/invoices/${id}`);
export const useReceipts = () =>
  useGet<
    {
      id: string;
      number: string;
      client_name: string | null;
      receipt_date: string;
      cash: string;
      pph23: string;
      source: string;
      bank_ref: string | null;
    }[]
  >('/billing/receipts');
export const useBankLines = () => useGet<BankLineRow[]>('/billing/bank-lines');
export const useDisputes = () =>
  useGet<
    (TicketLine & { ticket_number: string; project_number: string; disputed_at: string | null })[]
  >('/billing/disputes');
export const useArAging = () =>
  useGet<{
    as_of: string;
    rows: (Buckets & { client_code: string; client_name: string })[];
    totals: Buckets;
  }>('/billing/ar-aging');
export const useCashKpis = () =>
  useGet<{
    ar_balance: string;
    billed_period: string;
    dso_days: string | null;
    days_to_cash: string | null;
    paid_invoices: number;
    target_days_to_cash: number;
  }>('/billing/kpis');

export function useBillingPost<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown }) => postJson<R>(v.path, v.body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['billing'] }),
  });
}

export function useBankImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append('file', file);
      return api<{ lines: number; duplicates: number; suggested: number }>('/billing/bank-import', {
        method: 'POST',
        body: form,
      });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['billing'] }),
  });
}
