import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface AuditEntry {
  id: string;
  at: string;
  actor_name: string | null;
  action: string;
  action_label: string;
  entity_type: string;
  entity_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  changed: string[] | null;
  note: string | null;
  request_id: string | null;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

export function useHistory(entityType: string, entityId: string, page: number) {
  return useQuery({
    queryKey: ['audit', 'history', entityType, entityId, page],
    queryFn: () =>
      api<AuditPage>(`/audit/history/${entityType}/${entityId}?page=${page}&page_size=10`),
    placeholderData: keepPreviousData,
  });
}

export function useAudit(params: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== '') qs.set(k, String(v));
  return useQuery({
    queryKey: ['audit', 'search', params],
    queryFn: () => api<AuditPage>(`/audit?${qs.toString()}`),
    placeholderData: keepPreviousData,
  });
}

export function useAuditFacets() {
  return useQuery({
    queryKey: ['audit', 'facets'],
    queryFn: () =>
      api<{
        entity_types: { value: string; label: string }[];
        actions: { value: string; label: string }[];
      }>('/audit/facets'),
  });
}
