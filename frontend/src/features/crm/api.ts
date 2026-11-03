import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export type LeadStatus = 'new' | 'contacted' | 'qualified' | 'disqualified';
export type Stage = 'qualified' | 'quotation' | 'submitted' | 'won' | 'lost';
export const LEAD_STATUSES: LeadStatus[] = ['new', 'contacted', 'qualified', 'disqualified'];
export const STAGES: Stage[] = ['qualified', 'quotation', 'submitted', 'won', 'lost'];
export const SOURCES = [
  'civd',
  'eproc',
  'invitation',
  'visit',
  'referral',
  'website',
  'exhibition',
] as const;
export const CRITERIA = ['budget', 'technical_fit', 'start_6m', 'decision_maker', 'csms'] as const;
export const SCORES = [
  'strategic_fit',
  'technical',
  'availability',
  'csms',
  'margin',
  'risk',
] as const;

export interface Lead {
  id: string;
  number: string;
  client_code: string | null;
  company_name: string;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  source: string;
  need: string;
  estimated_value: string | null;
  status: LeadStatus;
  disqualify_reason: string | null;
  qualification: Record<string, boolean>;
  qualification_count: number;
  owner_id: string;
  owner_name: string | null;
  opportunity_id: string | null;
  opportunity_number: string | null;
  created_at: string;
  is_demo: boolean;
}

export interface Opportunity {
  id: string;
  number: string;
  lead_id: string | null;
  lead_number: string | null;
  client_code: string | null;
  company_name: string;
  title: string;
  owner_id: string;
  owner_name: string | null;
  value: string;
  weighted_value: string;
  probability: number;
  expected_close: string | null;
  is_tender: boolean;
  stage: Stage;
  bid_status: 'none' | 'pending' | 'bid' | 'no_bid';
  lost_reason: string | null;
  won_at: string | null;
  lost_at: string | null;
  is_demo: boolean;
}

export interface BidDecisionRow {
  id: string;
  scores: Record<string, number>;
  percent: string;
  threshold: string;
  recommendation: 'bid' | 'no_bid';
  proposal: 'bid' | 'no_bid';
  note: string | null;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  request_id: string | null;
  decision_comment: string | null;
  decided_at: string | null;
  created_at: string;
  created_by_name: string | null;
}

export interface OpportunityDetail extends Opportunity {
  can_edit: boolean;
  can_submit: boolean;
  bid_decisions: BidDecisionRow[];
}

export interface CrmConfig {
  bid_threshold: string;
  win_rate_target: string;
  contract_target: string;
  min_qualified: number;
}

export interface SalesDashboard {
  year: number;
  open_count: number;
  open_pipeline: string;
  weighted_pipeline: string;
  won_count: number;
  lost_count: number;
  win_rate: string | null;
  win_rate_target: string;
  new_contract_value: string;
  contract_target: string;
  scope: 'all' | 'own';
}

type Params = Record<string, string | number | boolean | undefined>;

function qs(params: Params): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== '' && v !== false) q.set(k, String(v));
  return q.toString();
}

export const exportPath = (kind: 'leads' | 'opportunities', params: Params) =>
  `/crm/${kind}/export?${qs(params)}`;

export function useCrmConfig() {
  return useQuery({
    queryKey: ['crm', 'config'],
    queryFn: () => api<CrmConfig>('/crm/config'),
    staleTime: 300_000,
  });
}

export function useOwners(enabled: boolean) {
  return useQuery({
    queryKey: ['crm', 'owners'],
    queryFn: () => api<{ id: string; full_name: string }[]>('/crm/owners'),
    enabled,
    staleTime: 60_000,
  });
}

export function useLeads(params: Params) {
  return useQuery({
    queryKey: ['crm', 'leads', params],
    queryFn: () =>
      api<{ items: Lead[]; total: number; counts: Record<LeadStatus, number> }>(
        `/crm/leads?${qs(params)}`,
      ),
    placeholderData: keepPreviousData,
  });
}

export function useLead(id: string | null) {
  return useQuery({
    queryKey: ['crm', 'lead', id],
    queryFn: () => api<Lead>(`/crm/leads/${id}`),
    enabled: id !== null,
  });
}

export function useOpportunities(params: Params) {
  return useQuery({
    queryKey: ['crm', 'opportunities', params],
    queryFn: () =>
      api<{
        items: Opportunity[];
        total: number;
        summary: Record<Stage, { count: number; value: string }>;
      }>(`/crm/opportunities?${qs(params)}`),
    placeholderData: keepPreviousData,
  });
}

export function useOpportunity(id: string) {
  return useQuery({
    queryKey: ['crm', 'opportunity', id],
    queryFn: () => api<OpportunityDetail>(`/crm/opportunities/${id}`),
  });
}

export function useSalesDashboard(enabled: boolean) {
  return useQuery({
    queryKey: ['crm', 'dashboard'],
    queryFn: () => api<SalesDashboard>('/crm/dashboard'),
    enabled,
  });
}

function useCrmMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['crm'] }),
  });
}

export const useSaveLead = (id: string | null) =>
  useCrmMutation((body: Record<string, unknown>) =>
    id
      ? api<Lead>(`/crm/leads/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
      : postJson<Lead>('/crm/leads', body),
  );

export const useLeadStatus = (id: string) =>
  useCrmMutation((body: { to: LeadStatus; reason?: string }) =>
    postJson<Lead>(`/crm/leads/${id}/status`, body),
  );

export const useConvertLead = (id: string) =>
  useCrmMutation((body: Record<string, unknown>) =>
    postJson<Opportunity>(`/crm/leads/${id}/convert`, body),
  );

export const useSaveOpportunity = (id: string) =>
  useCrmMutation((body: Record<string, unknown>) =>
    api<Opportunity>(`/crm/opportunities/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  );

export const useMoveStage = (id: string) =>
  useCrmMutation((body: { to: Stage; reason?: string }) =>
    postJson<Opportunity>(`/crm/opportunities/${id}/stage`, body),
  );

export const useBidDecision = (id: string) =>
  useCrmMutation(
    (body: { scores: Record<string, number>; proposal: 'bid' | 'no_bid'; note?: string }) =>
      postJson<{ request_id: string; percent: string; recommendation: string }>(
        `/crm/opportunities/${id}/bid-decision`,
        body,
      ),
  );

/** Same rule as the backend: average of six 1–5 scores / 5, two decimals. */
export function scorePercent(scores: Record<string, number>): number | null {
  const values = SCORES.map((k) => scores[k]);
  if (values.some((v) => !v)) return null;
  const total = values.reduce<number>((a, b) => a + (b ?? 0), 0);
  return Math.round((total / (SCORES.length * 5)) * 10000) / 100;
}

/** Form money input: accepts `4.500.000.000` or `4500000000`. */
export const moneyToApi = (s: string): string | null => {
  const digits = s.replace(/[^\d]/g, '');
  return digits === '' ? null : digits;
};
