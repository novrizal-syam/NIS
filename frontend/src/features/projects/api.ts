import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

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

export interface ProjectDetail extends ProjectRow {
  contingency_pct: string;
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
