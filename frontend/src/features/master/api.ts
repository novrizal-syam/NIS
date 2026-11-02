import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export type FieldKind =
  'text' | 'int' | 'decimal' | 'idr' | 'bool' | 'date' | 'choice' | 'ref' | 'docs';

export interface FieldMeta {
  name: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  key: boolean;
  max_length: number | null;
  choices: { value: string; label: string }[];
  ref: string | null;
  in_list: boolean;
  sensitive: boolean;
  min_value: number | null;
  max_value: number | null;
  default: unknown;
}

export interface EntityMeta {
  key: string;
  label: string;
  fields: FieldMeta[];
  filters: string[];
  title_field: string;
  has_active: boolean;
  can: { create: boolean; edit: boolean; delete: boolean; export: boolean };
}

export interface ExpiringDoc {
  name: string;
  number: string | null;
  expiry_date: string | null;
}

export type Row = Record<string, unknown> & { id: string; is_active?: boolean; is_demo: boolean };

export interface RowsPage {
  items: Row[];
  total: number;
  page: number;
  page_size: number;
}

export interface ImportResult {
  ok: boolean;
  created: number;
  updated: number;
  errors: { row: number | null; field: string | null; message: string }[];
}

export const GROUPS: Record<string, string> = {
  organisasi: 'master.groups.organisasi',
  mitra: 'master.groups.mitra',
  sdm: 'master.groups.sdm',
  operasi: 'master.groups.operasi',
  komersial: 'master.groups.komersial',
  keuangan: 'master.groups.keuangan',
};

export function listQueryString(p: Record<string, string | number | undefined>) {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '') s.set(k, String(v));
  return s.toString();
}

export function useEntities() {
  return useQuery({
    queryKey: ['master', 'entities'],
    queryFn: () => api<{ key: string; label: string; group: string }[]>('/master'),
    staleTime: Infinity,
  });
}

export function useMeta(entity: string, enabled = true) {
  return useQuery({
    queryKey: ['master', entity, 'meta'],
    queryFn: () => api<EntityMeta>(`/master/${entity}/meta`),
    staleTime: 5 * 60_000,
    enabled: enabled && entity !== '',
  });
}

export function useRows(entity: string, params: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ['master', entity, 'rows', params],
    queryFn: () => api<RowsPage>(`/master/${entity}?${listQueryString(params)}`),
    placeholderData: keepPreviousData,
  });
}

export function useOptions(entity: string | null) {
  return useQuery({
    queryKey: ['master', entity, 'options'],
    queryFn: () => api<{ value: string; label: string }[]>(`/master/${entity}/options`),
    enabled: entity !== null,
    staleTime: 60_000,
  });
}

export function useSaveRow(entity: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id?: string; data: Record<string, unknown> }) =>
      v.id
        ? api<Row>(`/master/${entity}/${v.id}`, { method: 'PATCH', body: JSON.stringify(v.data) })
        : postJson<Row>(`/master/${entity}`, v.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['master', entity] }),
  });
}

export function useDeleteRow(entity: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<null>(`/master/${entity}/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['master', entity] }),
  });
}

export function useImport(entity: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append('file', file);
      return api<ImportResult>(`/master/${entity}/import`, { method: 'POST', body });
    },
    onSuccess: (r) => {
      if (r.ok) void qc.invalidateQueries({ queryKey: ['master', entity] });
    },
  });
}
