// Fetch wrapper. Adds the in-memory access token and the active role, refreshes the
// access token once on 401 (refresh token lives in an httpOnly cookie), and turns
// backend errors ({code, message}) into ApiError.

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

let accessToken: string | null = null;
let activeRole: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionLost: (() => void) | null = null;

export const session = {
  setToken(token: string | null) {
    accessToken = token;
  },
  hasToken: () => accessToken !== null,
  setActiveRole(role: string | null) {
    activeRole = role;
  },
  getActiveRole: () => activeRole,
  /** Called when the session cannot be refreshed (AuthProvider signs the user out). */
  onLost(cb: (() => void) | null) {
    onSessionLost = cb;
  },
};

interface TokenOut {
  access_token: string;
  expires_in: number;
}

async function parse(res: Response): Promise<unknown> {
  return res.status === 204 ? null : res.json().catch(() => null);
}

function toError(status: number, body: unknown): ApiError {
  const b = (body ?? {}) as { code?: string; message?: string; details?: unknown };
  return new ApiError(
    status,
    b.code ?? 'HTTP_ERROR',
    b.message ?? 'Permintaan gagal. Coba lagi.',
    b.details,
  );
}

async function send(path: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  if (activeRole) headers.set('X-Active-Role', activeRole);
  try {
    return await fetch(`${BASE}${path}`, { credentials: 'include', ...init, headers });
  } catch {
    throw new ApiError(
      0,
      'NETWORK_ERROR',
      'Tidak dapat terhubung ke server. Periksa koneksi Anda.',
    );
  }
}

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshAccessToken(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await send('/auth/refresh', { method: 'POST' });
      if (!res.ok) {
        accessToken = null;
        return false;
      }
      accessToken = ((await res.json()) as TokenOut).access_token;
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await send(path, init);
  if (res.status === 401 && !path.startsWith('/auth/')) {
    if (await refreshAccessToken()) res = await send(path, init);
    else onSessionLost?.();
  }
  const body = await parse(res);
  if (!res.ok) throw toError(res.status, body);
  return body as T;
}

/** Fetch a protected file as a Blob (previews). */
export async function fetchBlob(path: string): Promise<Blob> {
  let res = await send(path, {});
  if (res.status === 401 && (await refreshAccessToken())) res = await send(path, {});
  if (!res.ok) throw toError(res.status, await parse(res));
  return res.blob();
}

/** Download a file (e.g. Excel export) with the user's session. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  let res = await send(path, {});
  if (res.status === 401 && (await refreshAccessToken())) res = await send(path, {});
  if (!res.ok) throw toError(res.status, await parse(res));
  const name =
    /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export const postJson = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) });

export interface Health {
  status: 'ok' | 'degraded';
  db: 'ok' | 'error';
  version: string;
}

export const getHealth = () => api<Health>('/health');

// --- auth -----------------------------------------------------------------------------------

export type PendingStep = 'change_password' | 'setup_totp';

export interface Me {
  id: string;
  email: string;
  full_name: string;
  department_id: string | null;
  roles: { code: string; name: string }[];
  active_role: string | null;
  permissions: Record<string, Record<string, string>>;
  pending: PendingStep[];
  totp_enabled: boolean;
  totp_required: boolean;
}

export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

export const authApi = {
  login: (email: string, password: string, totp_code?: string, recovery_code?: string) =>
    postJson<TokenOut>('/auth/login', {
      email,
      password,
      totp_code: totp_code || null,
      recovery_code: recovery_code || null,
    }),
  logout: () => postJson<null>('/auth/logout'),
  me: () => api<Me>('/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    postJson<TokenOut>('/auth/change-password', { current_password, new_password }),
  totpSetup: () => postJson<TotpSetup>('/auth/totp/setup'),
  totpVerify: (code: string) =>
    postJson<{ recovery_codes: string[] }>('/auth/totp/verify', { code }),
};
