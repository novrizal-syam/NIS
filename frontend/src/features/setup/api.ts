import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface SetupStatus {
  setup_completed: boolean;
  token_configured: boolean;
  steps: Partial<Record<'admin' | 'totp' | 'company' | 'departments' | 'demo', boolean>>;
}

const TOKEN_KEY = 'nustrad.setupToken';

export const setupToken = {
  get: () => {
    try {
      return sessionStorage.getItem(TOKEN_KEY) ?? '';
    } catch {
      return '';
    }
  },
  set: (v: string) => {
    try {
      if (v) sessionStorage.setItem(TOKEN_KEY, v);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable */
    }
  },
};

/** Setup endpoints always carry the one-time token (and the session once the admin exists). */
export function setupCall<T>(path: string, method = 'POST', body?: unknown) {
  return api<T>(`/setup${path}`, {
    method,
    headers: { 'X-Setup-Token': setupToken.get() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function useSetupStatus() {
  return useQuery({
    queryKey: ['setup', 'status'],
    queryFn: () => api<SetupStatus>('/setup/status'),
    staleTime: Infinity,
    retry: false,
  });
}
