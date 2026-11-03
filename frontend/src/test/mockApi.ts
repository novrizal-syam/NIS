import type { Me } from '@/lib/api';

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;

export const json = (body: unknown, status = 200) =>
  new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

export const apiError = (status: number, code: string, message: string) =>
  json({ code, message }, status);

export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    id: 'u1',
    email: 'rina@gek.co.id',
    full_name: 'Rina Wijaya',
    department_id: null,
    roles: [{ code: 'head_of_operation', name: 'Head of Operation' }],
    active_role: null,
    permissions: {
      procurement: { view: 'all', approve: 'all' },
      crm: { view: 'all' },
      operations: { view: 'all' },
    },
    pending: [],
    totp_enabled: false,
    totp_required: false,
    ...overrides,
  };
}

/**
 * Replace global fetch with a router keyed by "METHOD /api/path".
 * `signedIn: false` makes the startup refresh fail (anonymous visitor).
 */
export function mockApi(
  options: { me?: Me; signedIn?: boolean; handlers?: Record<string, Handler> } = {},
) {
  const { me = makeMe(), signedIn = true, handlers = {} } = options;
  const calls: { key: string; init?: RequestInit }[] = [];
  const defaults: Record<string, Handler> = {
    'POST /api/auth/refresh': () =>
      signedIn
        ? json({ access_token: 'tok', expires_in: 900 })
        : apiError(401, 'REFRESH_INVALID', 'Sesi berakhir.'),
    'GET /api/auth/me': () => json(me),
    'POST /api/auth/logout': () => new Response(null, { status: 204 }),
    'GET /api/health': () => json({ status: 'ok', db: 'ok', version: '0.1.0' }),
    'GET /api/workflow/inbox/count': () => json({ count: 0 }),
    'GET /api/setup/status': () =>
      json({ setup_completed: true, token_configured: true, steps: {} }),
    'GET /api/notifications/count': () => json({ unread: 0 }),
    'GET /api/workflow/doc-types': () =>
      json([
        { code: 'purchase_requisition', label: 'Purchase Requisition', module: 'procurement' },
        { code: 'cash_advance', label: 'Uang muka kerja', module: 'treasury' },
      ]),
  };
  const routes = { ...defaults, ...handlers };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const key = `${(init?.method ?? 'GET').toUpperCase()} ${new URL(url, 'http://x').pathname}`;
    calls.push({ key, init });
    const handler = routes[key];
    if (!handler) return apiError(404, 'NOT_FOUND', `no mock for ${key}`);
    return handler(init);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}
