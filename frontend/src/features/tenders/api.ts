import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export type PackageStatus = 'none' | 'pending' | 'approved' | 'rejected';
export type TenderResult = 'won' | 'lost' | 'disqualified' | 'cancelled';
export type Section = 'admin' | 'technical' | 'commercial';
export const SECTIONS: Section[] = ['admin', 'technical', 'commercial'];
export const METHODS = ['open', 'limited', 'selection', 'direct'] as const;
export const CHANNELS = ['eproc', 'civd', 'hardcopy', 'email'] as const;
export const RESULTS: TenderResult[] = ['won', 'lost', 'disqualified', 'cancelled'];

export interface TenderRow {
  id: string;
  opportunity_id: string;
  opportunity_number: string;
  opportunity_title: string;
  opportunity_stage: string;
  company_name: string;
  owner_name: string | null;
  tender_number: string | null;
  method: (typeof METHODS)[number];
  closing_at: string | null;
  price: string | null;
  package_status: PackageStatus;
  submitted_at: string | null;
  result: TenderResult | null;
  missing?: number;
}

export interface TenderDoc {
  id: string;
  section: Section;
  name: string;
  mandatory: boolean;
  not_applicable: boolean;
  expiry_date: string | null;
  note: string | null;
  files: number;
  status: 'present' | 'missing' | 'na';
  expired: boolean;
}

export interface TenderDetail extends TenderRow {
  aanwijzing_at: string | null;
  clarification_deadline: string | null;
  opening_at: string | null;
  bid_validity_until: string | null;
  bid_bond_required: boolean;
  bid_bond_amount: string | null;
  bid_bond_number: string | null;
  tkdn_required_pct: string | null;
  tkdn_offered_pct: string | null;
  request_id: string | null;
  submission_channel: (typeof CHANNELS)[number] | null;
  receipt_number: string | null;
  result_at: string | null;
  rank: number | null;
  winner_name: string | null;
  winning_price: string | null;
  lessons_learned: string | null;
  readiness: { ready: boolean; missing: string[]; problems: string[] };
  can_edit: boolean;
  can_submit_package: boolean;
  documents: TenderDoc[];
  clarifications: {
    id: string;
    question: string;
    asked_at: string;
    reference: string | null;
    answer: string | null;
    answered_at: string | null;
  }[];
}

type Params = Record<string, string | number | boolean | undefined>;
const qs = (p: Params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p))
    if (v !== undefined && v !== '' && v !== false) q.set(k, String(v));
  return q.toString();
};

export function useTenders(params: Params, enabled = true) {
  return useQuery({
    queryKey: ['tenders', 'list', params],
    queryFn: () => api<{ items: TenderRow[]; total: number }>(`/tenders?${qs(params)}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useClosingSoon(enabled: boolean) {
  return useQuery({
    queryKey: ['tenders', 'closing-soon'],
    queryFn: () => api<TenderRow[]>('/tenders/closing-soon'),
    enabled,
  });
}

export function useTender(id: string) {
  return useQuery({
    queryKey: ['tenders', 'detail', id],
    queryFn: () => api<TenderDetail>(`/tenders/${id}`),
  });
}

function useTenderMutation<V>(fn: (v: V) => Promise<TenderDetail>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['tenders'] });
      void qc.invalidateQueries({ queryKey: ['crm'] });
    },
  });
}

const send = (method: string, path: string, body?: unknown) =>
  api<TenderDetail>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const useCreateTender = () =>
  useTenderMutation((opportunity_id: string) =>
    postJson<TenderDetail>('/tenders', { opportunity_id }),
  );
export const useSaveTender = (id: string) =>
  useTenderMutation((body: Record<string, unknown>) => send('PUT', `/tenders/${id}`, body));
export const useAddDocument = (id: string) =>
  useTenderMutation((body: Record<string, unknown>) =>
    send('POST', `/tenders/${id}/documents`, body),
  );
export const useSaveDocument = (id: string) =>
  useTenderMutation((v: { docId: string; body: Record<string, unknown> }) =>
    send('PUT', `/tenders/${id}/documents/${v.docId}`, v.body),
  );
export const useDeleteDocument = (id: string) =>
  useTenderMutation((docId: string) => send('DELETE', `/tenders/${id}/documents/${docId}`));
export const useAddClarification = (id: string) =>
  useTenderMutation((body: Record<string, unknown>) =>
    send('POST', `/tenders/${id}/clarifications`, body),
  );
export const useSaveClarification = (id: string) =>
  useTenderMutation((v: { cid: string; body: Record<string, unknown> }) =>
    send('PUT', `/tenders/${id}/clarifications/${v.cid}`, v.body),
  );
export const useSubmitPackage = (id: string) =>
  useTenderMutation(() => send('POST', `/tenders/${id}/submit-package`));
export const useRecordSubmission = (id: string) =>
  useTenderMutation((body: Record<string, unknown>) =>
    send('POST', `/tenders/${id}/submission`, body),
  );
export const useRecordResult = (id: string) =>
  useTenderMutation((body: Record<string, unknown>) => send('POST', `/tenders/${id}/result`, body));

const JAKARTA_OFFSET = '+07:00';

/** ISO instant -> `YYYY-MM-DDTHH:mm` in Asia/Jakarta for <input type="datetime-local">. */
export function toJakartaInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(new Date(iso).getTime() + 7 * 3600_000);
  return d.toISOString().slice(0, 16);
}

/** `YYYY-MM-DDTHH:mm` typed in Jakarta time -> ISO with offset. */
export const fromJakartaInput = (v: string): string | null =>
  v ? `${v}:00${JAKARTA_OFFSET}` : null;

/** Whole days from now until the instant (negative when past). */
export const daysUntil = (iso: string, now = Date.now()): number =>
  Math.ceil((new Date(iso).getTime() - now) / 86_400_000);
