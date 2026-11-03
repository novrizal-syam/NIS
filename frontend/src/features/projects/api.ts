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
