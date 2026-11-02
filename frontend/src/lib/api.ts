// Thin fetch wrapper. The backend always answers errors as {code, message}.

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const BASE = '/api';

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      credentials: 'include',
      ...init,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    });
  } catch {
    throw new ApiError(
      0,
      'NETWORK_ERROR',
      'Tidak dapat terhubung ke server. Periksa koneksi Anda.',
    );
  }
  const body: unknown = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const b = (body ?? {}) as { code?: string; message?: string; details?: unknown };
    throw new ApiError(
      res.status,
      b.code ?? 'HTTP_ERROR',
      b.message ?? 'Permintaan gagal. Coba lagi.',
      b.details,
    );
  }
  return body as T;
}

export interface Health {
  status: 'ok' | 'degraded';
  db: 'ok' | 'error';
  version: string;
}

export const getHealth = () => api<Health>('/health');
