import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { qs } from '@/features/inventory/api';
import { api, postJson } from '@/lib/api';
import { getOptions, putOptions } from './offlineStore';
import type { DorDetail, DorRow, FormOptions } from './types';

export const useDorProjects = () =>
  useQuery({
    queryKey: ['dors', 'projects'],
    queryFn: () =>
      api<{ id: string; number: string; name: string; service_type: string | null }[]>(
        '/operations/projects',
      ),
    staleTime: 300_000,
  });

/** Form options from the server, cached in IndexedDB so the form opens offline. */
export const useDorOptions = (projectId: string) =>
  useQuery({
    queryKey: ['dors', 'options', projectId],
    queryFn: async () => {
      try {
        const o = await api<FormOptions>(
          `/operations/dors/form-options?${qs({ project_id: projectId })}`,
        );
        await putOptions(projectId, o).catch(() => undefined);
        return o;
      } catch (e) {
        const cached = await getOptions(projectId).catch(() => undefined);
        if (cached) return cached;
        throw e;
      }
    },
    enabled: projectId !== '',
    staleTime: 60_000,
    retry: false,
  });

export const useDors = (params: Record<string, string | number | undefined>) =>
  useQuery({
    queryKey: ['dors', 'list', params],
    queryFn: () =>
      api<{ items: DorRow[]; total: number; counts: Record<DorRow['status'], number> }>(
        `/operations/dors?${qs(params)}`,
      ),
    placeholderData: keepPreviousData,
    retry: false,
  });

export const useDor = (id: string) =>
  useQuery({
    queryKey: ['dors', 'detail', id],
    queryFn: () => api<DorDetail>(`/operations/dors/${id}`),
  });

export const fetchByClient = (clientId: string) =>
  api<DorDetail>(`/operations/dors/by-client/${clientId}`);

export const useSubmitDor = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => postJson<DorDetail>(`/operations/dors/${id}/submit`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['dors'] }),
  });
};
