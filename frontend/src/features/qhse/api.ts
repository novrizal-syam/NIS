import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { qs } from '@/features/inventory/api';
import { api, postJson } from '@/lib/api';

export interface Hazard {
  activity: string;
  hazard: string;
  likelihood: number;
  severity: number;
  score?: number;
  level?: string;
  controls: string;
  residual_likelihood?: number | null;
  residual_severity?: number | null;
  residual_level?: string;
}

export interface RiskAssessment {
  id: string;
  number: string;
  kind: 'hiradc' | 'jsa';
  title: string;
  status: 'draft' | 'approved';
  hazards: Hazard[];
  approved_at: string | null;
  project_number: string | null;
  can_approve?: boolean;
}

export interface PermitRow {
  id: string;
  number: string;
  permit_type: string;
  location: string;
  work_description: string;
  valid_from: string;
  valid_to: string;
  status: 'requested' | 'approved' | 'closed' | 'cancelled';
  project_number: string | null;
  is_own: boolean;
}

export interface IncidentRow {
  id: string;
  number: string;
  occurred_on: string;
  category: string;
  location: string | null;
  description: string;
  lost_days: number;
  status: 'reported' | 'investigating' | 'closed';
  root_cause: string | null;
  investigation: string | null;
  project_number: string | null;
}

export interface CapaRow {
  id: string;
  number: string;
  source_type: string;
  action: string;
  due_date: string;
  status: 'open' | 'done' | 'verified';
  completion_note: string | null;
  owner_name: string | null;
  overdue: boolean;
  can_complete: boolean;
  can_verify: boolean;
  project_number: string | null;
}

export interface SimpleRow {
  id: string;
  number: string;
  project_number: string | null;
  [k: string]: unknown;
}

export interface Stats {
  date_from: string;
  date_to: string;
  manhours: string;
  incidents: Record<string, number>;
  lti: number;
  recordable: number;
  trir: string | null;
  ltifr: string | null;
  near_misses: number;
  observations: number;
  inspections: number;
  capa_open: number;
  capa_overdue: number;
}

const key = (...p: unknown[]) => ['qhse', ...p];
const useGet = <T>(path: string, enabled = true) =>
  useQuery({ queryKey: key(path), queryFn: () => api<T>(path), enabled });

export const useQhseProjects = () =>
  useGet<{ id: string; number: string; name: string }[]>('/qhse/projects');
export const useQhseUsers = () => useGet<{ id: string; full_name: string }[]>('/qhse/users');
export const useRiskAssessments = () => useGet<RiskAssessment[]>('/qhse/risk-assessments');
export const usePermits = () => useGet<PermitRow[]>('/qhse/permits');
export const useInspections = () => useGet<SimpleRow[]>('/qhse/inspections');
export const useObservations = () => useGet<SimpleRow[]>('/qhse/observations');
export const useIncidents = () => useGet<IncidentRow[]>('/qhse/incidents');
export const useCapas = () => useGet<CapaRow[]>('/qhse/capas');
export const useStats = (from: string, to: string) =>
  useGet<Stats>(`/qhse/statistics?${qs({ date_from: from, date_to: to })}`);

export function useQhsePost<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown }) => postJson<R>(v.path, v.body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['qhse'] }),
  });
}
