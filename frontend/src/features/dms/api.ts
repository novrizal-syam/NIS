import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export interface Attachment {
  id: string;
  group_id: string;
  version: number;
  versions: number;
  filename: string;
  content_type: string;
  size: number;
  uploaded_by: string;
  uploaded_at: string;
  note: string | null;
}

const key = (t: string, id: string) => ['attachments', t, id] as const;

export function useAttachments(entityType: string, entityId: string) {
  return useQuery({
    queryKey: key(entityType, entityId),
    queryFn: () =>
      api<Attachment[]>(`/attachments?entity_type=${entityType}&entity_id=${entityId}`),
  });
}

export function useVersions(id: string | null) {
  return useQuery({
    queryKey: ['attachments', 'versions', id],
    queryFn: () => api<Attachment[]>(`/attachments/${id}/versions`),
    enabled: id !== null,
  });
}

export function useUpload(entityType: string, entityId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { file: File; replaces?: string }) => {
      const body = new FormData();
      body.append('entity_type', entityType);
      body.append('entity_id', entityId);
      body.append('file', v.file);
      if (v.replaces) body.append('replaces', v.replaces);
      return api<Attachment>('/attachments', { method: 'POST', body });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['attachments'] }),
  });
}

export function useArchive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => postJson<null>(`/attachments/${id}/archive`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['attachments'] }),
  });
}

export const MAX_BYTES = 20 * 1024 * 1024;
export const ACCEPT = '.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png';
