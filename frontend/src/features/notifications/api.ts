import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, postJson } from '@/lib/api';

export interface NotificationItem {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string | null;
  created_at: string;
  read: boolean;
}

export function useUnreadCount() {
  return useQuery({
    queryKey: ['notifications', 'count'],
    queryFn: () => api<{ unread: number }>('/notifications/count'),
    refetchInterval: 60_000,
  });
}

export function useNotifications(enabled: boolean) {
  return useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () =>
      api<{ items: NotificationItem[]; total: number; unread: number }>(
        '/notifications?page_size=15',
      ),
    enabled,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string | 'all') =>
      postJson<null>(id === 'all' ? '/notifications/read-all' : `/notifications/${id}/read`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
}
