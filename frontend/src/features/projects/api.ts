import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export type ProjectStatus =
  'draft' | 'controller_review' | 'awaiting_approval' | 'locked' | 'closed';
export const PROJECT_STATUSES: ProjectStatus[] = [
  'draft',
  'controller_review',
  'awaiting_approval',
  'locked',
  'closed',
];

export interface ProjectRow {
  id: string;
  number: string;
  name: string;
  company_name: string;
  status: ProjectStatus;
  revenue: string;
  budget_total: string;
  planned_margin: string;
  contract_id: string | null;
  contract_number: string | null;
  start_date: string | null;
  end_date: string | null;
}

export interface BudgetCell {
  wbs_code: string;
  cost_element_code: string;
  amount: string;
  locked_reserve?: boolean;
}

export interface ProjectDetail extends ProjectRow {
  contingency_pct: string;
  status_label: string;
  total_cost: string;
  margin_pct: string;
  min_margin_pct: string;
  margin_warning: boolean;
  manager_id: string | null;
  manager_name: string | null;
  budget_request_id: string | null;
  budget_comment: string | null;
  locked_at: string | null;
  baseline: { version: number; total_cost: string; margin_pct: string; approved_at: string } | null;
  can_edit_budget: boolean;
  can_submit_budget: boolean;
  can_assign: boolean;
  can_bcr: boolean;
  wbs: { id: string; code: string; name: string }[];
  cells: BudgetCell[];
  cost_elements: { code: string; name: string }[];
  budget: {
    cost_element_code: string;
    cost_element_name: string;
    amount: string;
    source: 'quotation' | 'contingency';
    share_of_revenue: string | null;
  }[];
}

type Params = Record<string, string | number | undefined>;
const qs = (p: Params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '') q.set(k, String(v));
  return q.toString();
};
export const projectExportPath = (p: Params) => `/projects/export?${qs(p)}`;

export function useProjects(params: Params) {
  return useQuery({
    queryKey: ['projects', 'list', params],
    queryFn: () =>
      api<{ items: ProjectRow[]; total: number; counts: Record<ProjectStatus, number> }>(
        `/projects?${qs(params)}`,
      ),
    placeholderData: keepPreviousData,
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: ['projects', 'detail', id],
    queryFn: () => api<ProjectDetail>(`/projects/${id}`),
  });
}

function useProjectMutation<V, R = ProjectDetail>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  });
}

export const useSaveBudget = (id: string) =>
  useProjectMutation((cells: BudgetCell[]) =>
    api<ProjectDetail>(`/projects/${id}/budget`, {
      method: 'PUT',
      body: JSON.stringify({ cells }),
    }),
  );
export const useAddWbs = (id: string) =>
  useProjectMutation((body: { code: string; name: string }) =>
    postJson<ProjectDetail>(`/projects/${id}/wbs`, body),
  );
export const useDeleteWbs = (id: string) =>
  useProjectMutation((wid: string) =>
    api<ProjectDetail>(`/projects/${id}/wbs/${wid}`, { method: 'DELETE' }),
  );
export const useSubmitBudget = (id: string) =>
  useProjectMutation(() =>
    postJson<ProjectDetail & { approvers: string[] }>(`/projects/${id}/submit-budget`),
  );
export const useSetManager = (id: string) =>
  useProjectMutation((manager_id: string | null) =>
    api<ProjectDetail>(`/projects/${id}/manager`, {
      method: 'PUT',
      body: JSON.stringify({ manager_id }),
    }),
  );

export function usePlanners(enabled: boolean) {
  return useQuery({
    queryKey: ['projects', 'planners'],
    queryFn: () => api<{ id: string; full_name: string }[]>('/projects/planners'),
    enabled,
    staleTime: 60_000,
  });
}

export interface BudgetStatusLine {
  wbs_code: string;
  cost_element_code: string;
  cost_element_name: string;
  locked_reserve: boolean;
  budget: string;
  pre_commit: string;
  commit: string;
  actual: string;
  available: string;
  used_pct: string;
  state: 'ok' | 'warning' | 'exhausted';
}

export function useBudgetStatus(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ['projects', 'budget-status', id],
    queryFn: () =>
      api<{
        status: string;
        lines: BudgetStatusLine[];
        totals: Record<'budget' | 'pre_commit' | 'commit' | 'actual' | 'available', string>;
      }>(`/projects/${id}/budget-status`),
    enabled,
  });
}

export interface BudgetVersionsView {
  versions: {
    version: number;
    kind: 'baseline' | 'bcr';
    revenue: string;
    total_cost: string;
    margin_pct: string;
    approved_at: string;
    note: string | null;
  }[];
  lines: {
    wbs_code: string;
    cost_element_code: string;
    cost_element_name: string;
    baseline: string;
    current: string;
    change: string;
  }[];
}

export type BcrSource = 'contingency_release' | 'budget_increase' | 'transfer';
export type BcrReason = 'client_variation' | 'scope_change' | 'price_escalation' | 'estimate_error';
export const BCR_SOURCES: BcrSource[] = ['contingency_release', 'budget_increase', 'transfer'];
export const BCR_REASONS: BcrReason[] = [
  'client_variation',
  'scope_change',
  'price_escalation',
  'estimate_error',
];

export interface BcrRow {
  id: string;
  number: string;
  wbs_code: string;
  cost_element_code: string;
  amount: string;
  source: BcrSource;
  from_wbs_code: string | null;
  from_cost_element_code: string | null;
  reason: BcrReason;
  justification: string;
  revenue_change: string | null;
  increase_pct: string | null;
  ref_doc_type: string | null;
  ref_doc_id: string | null;
  status: 'submitted' | 'approved' | 'rejected' | 'cancelled';
  request_id: string | null;
  decision_comment: string | null;
  version: number | null;
  created_at: string;
  created_by_name: string | null;
}

export function useBudgetVersions(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ['projects', 'versions', id],
    queryFn: () => api<BudgetVersionsView>(`/projects/${id}/versions`),
    enabled,
  });
}

export function useBcrs(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ['projects', 'bcrs', id],
    queryFn: () => api<BcrRow[]>(`/projects/${id}/bcrs`),
    enabled,
  });
}

export const useCreateBcr = (id: string) =>
  useProjectMutation((body: Record<string, unknown>) =>
    postJson<{ id: string; number: string; request_id: string; approver: string | null }>(
      `/projects/${id}/bcrs`,
      body,
    ),
  );

export interface TeamMember {
  user_id: string;
  full_name: string;
  email: string;
  added_at: string;
}

export const useTeam = (id: string) =>
  useQuery({
    queryKey: ['projects', 'team', id],
    queryFn: () => api<{ items: TeamMember[]; can_edit: boolean }>(`/projects/${id}/members`),
  });

export const useTeamCandidates = (enabled: boolean) =>
  useQuery({
    queryKey: ['projects', 'team-candidates'],
    queryFn: () => api<{ id: string; full_name: string }[]>('/projects/team-candidates'),
    enabled,
    staleTime: 60_000,
  });

export const useAddMember = (id: string) =>
  useProjectMutation((user_id: string) =>
    postJson<{ items: TeamMember[] }>(`/projects/${id}/members`, { user_id }),
  );

export const useRemoveMember = (id: string) =>
  useProjectMutation((uid: string) =>
    api<{ items: TeamMember[] }>(`/projects/${id}/members/${uid}`, { method: 'DELETE' }),
  );
