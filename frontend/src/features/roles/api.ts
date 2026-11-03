import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';
import type { RoleRow } from '@/features/users/api';

export interface GrantRow {
  module: string;
  action: string;
  scope: string;
}

export interface Catalog {
  modules: { code: string; label: string }[];
  actions: { code: string; label: string }[];
  scopes: string[];
  sensitive: { code: string; label: string }[];
}

export type RoleDetail = RoleRow & { locked: boolean; grants: GrantRow[] };

export const useCatalog = () =>
  useQuery({
    queryKey: ['roles', 'catalog'],
    queryFn: () => api<Catalog>('/roles/catalog'),
    staleTime: Infinity,
  });

export const useRole = (id: string) =>
  useQuery({ queryKey: ['roles', 'detail', id], queryFn: () => api<RoleDetail>(`/roles/${id}`) });

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ['roles'] });
}

export function useCreateRole() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (v: {
      code: string;
      name: string;
      description: string;
      requires_2fa: boolean;
      clone_from: string | null;
    }) => postJson<RoleRow>('/roles', v),
    onSuccess: invalidate,
  });
}

export function useUpdateRole(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (
      v: Partial<{ name: string; description: string; requires_2fa: boolean; is_active: boolean }>,
    ) => api<RoleRow>(`/roles/${id}`, { method: 'PATCH', body: JSON.stringify(v) }),
    onSuccess: invalidate,
  });
}

export function useSaveGrants(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (grants: GrantRow[]) =>
      api<{ grants: GrantRow[] }>(`/roles/${id}/permissions`, {
        method: 'PUT',
        body: JSON.stringify({ grants }),
      }),
    onSuccess: invalidate,
  });
}

export const fetchPreview = (id: string) =>
  api<{ role: RoleRow; permissions: Record<string, Record<string, string>>; sensitive: string[] }>(
    `/roles/${id}/preview`,
  );
