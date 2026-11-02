import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export interface DocType {
  code: string;
  label: string;
  module: string;
}

export interface InboxItem {
  request_id: string;
  doc_type: string;
  doc_type_label: string;
  doc_number: string;
  title: string;
  amount: string | null;
  currency: string;
  requester_name: string;
  submitted_at: string;
  step_label: string;
  due_at: string | null;
  overdue: boolean;
  escalated: boolean;
}

export interface InboxPage {
  items: InboxItem[];
  total: number;
  page: number;
  page_size: number;
  counts: Record<string, number>;
}

export interface Step {
  seq: number;
  approver_role: string;
  approver_role_name: string;
  label: string;
  status: 'waiting' | 'pending' | 'approved' | 'rejected' | 'skipped';
  acted_by_name: string | null;
  on_behalf_of_name: string | null;
  acted_at: string | null;
  comment: string | null;
  due_at: string | null;
}

export interface RequestDetail {
  id: string;
  doc_type: string;
  doc_type_label: string;
  doc_number: string;
  title: string;
  amount: string | null;
  currency: string;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  requester_name: string;
  submitted_at: string;
  decided_at: string | null;
  rule_name: string;
  steps: Step[];
  can_act: boolean;
  can_cancel: boolean;
  changes: { label: string; before: string | null; after: string }[];
  change_reason: string | null;
}

export interface BulkResult {
  request_id: string;
  ok: boolean;
  code: string | null;
  message: string | null;
}

export interface Delegation {
  id: string;
  delegator_name: string;
  delegate_name: string;
  role_code: string | null;
  start_date: string;
  end_date: string;
  reason: string;
  active: boolean;
  can_revoke: boolean;
}

export interface RuleStep {
  seq: number;
  approver_role: string;
  label: string;
  approver_scope: 'all' | 'project';
}

export interface Rule {
  id: string;
  doc_type: string;
  doc_type_label: string;
  name: string;
  priority: number;
  condition: Record<string, unknown>;
  condition_text: string;
  escalation_hours: number;
  escalate_to_role: string | null;
  is_active: boolean;
  note: string;
  steps: RuleStep[];
  pending_change: boolean;
}

export interface RuleChange {
  id: string;
  rule_id: string | null;
  doc_type: string;
  name: string;
  reason: string;
  status: string;
  request_id: string | null;
  created_at: string;
}

export interface UserLookup {
  id: string;
  full_name: string;
  email: string;
}

export const wf = {
  inboxCount: ['workflow', 'inbox-count'] as const,
  inbox: (params: object) => ['workflow', 'inbox', params] as const,
  request: (id: string) => ['workflow', 'request', id] as const,
};

const qs = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') s.set(k, String(v));
  return s.toString();
};

export function useDocTypes() {
  return useQuery({
    queryKey: ['workflow', 'doc-types'],
    queryFn: () => api<DocType[]>('/workflow/doc-types'),
    staleTime: Infinity,
  });
}

export function useInboxCount(enabled = true) {
  return useQuery({
    queryKey: wf.inboxCount,
    queryFn: () => api<{ count: number }>('/workflow/inbox/count'),
    refetchInterval: 60_000,
    enabled,
  });
}

export function inboxQueryString(p: { doc_type?: string; q?: string; page?: number }) {
  return qs({ doc_type: p.doc_type, q: p.q, page: p.page, page_size: 25 });
}

export function useInbox(p: { doc_type?: string; q?: string; page: number }) {
  return useQuery({
    queryKey: wf.inbox(p),
    queryFn: () => api<InboxPage>(`/workflow/inbox?${inboxQueryString(p)}`),
    placeholderData: keepPreviousData,
  });
}

export function useRequest(id: string) {
  return useQuery({
    queryKey: wf.request(id),
    queryFn: () => api<RequestDetail>(`/workflow/requests/${id}`),
  });
}

function useInvalidateWorkflow() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ['workflow'] });
}

export function useDecision() {
  const invalidate = useInvalidateWorkflow();
  return useMutation({
    mutationFn: (v: { id: string; action: 'approve' | 'reject' | 'cancel'; comment?: string }) =>
      postJson<RequestDetail>(`/workflow/requests/${v.id}/${v.action}`, {
        comment: v.comment ?? null,
      }),
    onSuccess: invalidate,
  });
}

export function useBulkApprove() {
  const invalidate = useInvalidateWorkflow();
  return useMutation({
    mutationFn: (v: { doc_type: string; request_ids: string[] }) =>
      postJson<BulkResult[]>('/workflow/approvals/bulk', v),
    onSuccess: invalidate,
  });
}

export function useDelegations() {
  return useQuery({
    queryKey: ['workflow', 'delegations'],
    queryFn: () => api<Delegation[]>('/workflow/delegations'),
  });
}

export function useCreateDelegation() {
  const invalidate = useInvalidateWorkflow();
  return useMutation({
    mutationFn: (v: {
      delegate_id: string;
      role_code: string | null;
      start_date: string;
      end_date: string;
      reason: string;
    }) => postJson<{ id: string }>('/workflow/delegations', v),
    onSuccess: invalidate,
  });
}

export function useRevokeDelegation() {
  const invalidate = useInvalidateWorkflow();
  return useMutation({
    mutationFn: (id: string) => postJson<null>(`/workflow/delegations/${id}/revoke`),
    onSuccess: invalidate,
  });
}

export function useUserLookup(q: string) {
  return useQuery({
    queryKey: ['users', 'lookup', q],
    queryFn: () => api<UserLookup[]>(`/users/lookup?${qs({ q })}`),
    enabled: q.trim().length >= 2,
  });
}

export function useRules() {
  return useQuery({
    queryKey: ['workflow', 'rules'],
    queryFn: () => api<Rule[]>('/workflow/rules'),
  });
}

export function useRuleChanges() {
  return useQuery({
    queryKey: ['workflow', 'rule-changes'],
    queryFn: () => api<RuleChange[]>('/workflow/rule-changes'),
  });
}

export function useProposeRuleChange() {
  const invalidate = useInvalidateWorkflow();
  return useMutation({
    mutationFn: (v: {
      rule_id: string | null;
      rule: Omit<Rule, 'id' | 'doc_type_label' | 'condition_text' | 'pending_change'>;
      reason: string;
    }) =>
      postJson<{ change_id: string; request_id: string; doc_number: string }>(
        '/workflow/rule-changes',
        v,
      ),
    onSuccess: invalidate,
  });
}
