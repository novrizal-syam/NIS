import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export type UserStatus = 'invited' | 'active' | 'locked' | 'inactive';

export interface UserRow {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  role_names: string[];
  department_code: string | null;
  employee_code: string | null;
  status: UserStatus;
  totp_enabled: boolean;
  last_login_at: string | null;
  is_demo: boolean;
}

export interface SessionRow {
  family_id: string;
  signed_in_at: string;
  last_active_at: string;
  user_agent: string | null;
  ip: string | null;
}

export interface Assignment {
  code: string;
  name: string;
  valid_from: string | null;
  valid_until: string | null;
  reason: string | null;
}

export interface RoleRow {
  id: string;
  code: string;
  name: string;
  description: string;
  is_system: boolean;
  is_external: boolean;
  requires_2fa: boolean;
  is_active: boolean;
  user_count: number;
}

export function useRoles() {
  return useQuery({
    queryKey: ['roles'],
    queryFn: () => api<RoleRow[]>('/roles'),
    staleTime: 60_000,
  });
}

export function useUsers(params: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== '') qs.set(k, String(v));
  return useQuery({
    queryKey: ['users', 'list', params],
    queryFn: () =>
      api<{
        items: UserRow[];
        total: number;
        counts: Record<UserStatus, number>;
        active_super_admins: number;
      }>(`/users?${qs.toString()}`),
    placeholderData: keepPreviousData,
  });
}

export function useUser(id: string | null) {
  return useQuery({
    queryKey: ['users', 'detail', id],
    queryFn: () =>
      api<UserRow & { sessions: SessionRow[]; assignments: Assignment[] }>(`/users/${id}`),
    enabled: id !== null,
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ['users'] });
}

export function useCreateUser() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (v: {
      email: string;
      full_name: string;
      roles: string[];
      department_code: string | null;
      employee_code: string | null;
      mode: 'invite' | 'password';
    }) => postJson<{ id: string; temporary_password: string | null }>('/users', v),
    onSuccess: invalidate,
  });
}

export function useUpdateUser(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (
      v: Partial<{
        full_name: string;
        department_code: string | null;
        employee_code: string | null;
        roles: string[];
      }>,
    ) => api<UserRow>(`/users/${id}`, { method: 'PATCH', body: JSON.stringify(v) }),
    onSuccess: invalidate,
  });
}

export type UserAction =
  'deactivate' | 'activate' | 'reset-password' | 'unlock' | 'reset-2fa' | 'force-logout' | 'invite';

export function useUserAction(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (action: UserAction | { revoke: string }) =>
      typeof action === 'string'
        ? postJson<{ temporary_password?: string } | null>(`/users/${id}/${action}`)
        : postJson<null>(`/users/${id}/sessions/${action.revoke}/revoke`),
    onSuccess: invalidate,
  });
}

export function useImportUsers() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append('file', file);
      return api<{
        ok: boolean;
        created: number;
        errors: { row: number | null; field: string | null; message: string }[];
      }>('/users/import', { method: 'POST', body });
    },
    onSuccess: (r) => {
      if (r.ok) void invalidate();
    },
  });
}

export function useAddTemporaryRole(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (v: {
      role: string;
      valid_from: string | null;
      valid_until: string;
      reason: string;
    }) => postJson<{ status: string }>(`/users/${id}/roles/temporary`, v),
    onSuccess: invalidate,
  });
}
