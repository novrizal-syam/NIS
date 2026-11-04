import { useQueryClient } from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { authApi, refreshAccessToken, session, type Me } from '@/lib/api';

type Status = 'loading' | 'anonymous' | 'authenticated';
const ROLE_KEY = 'nustrad.activeRole';

interface AuthContextValue {
  status: Status;
  me: Me | null;
  login: (
    email: string,
    password: string,
    totpCode?: string,
    recoveryCode?: string,
  ) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
  /** Called with a fresh access token, e.g. after a password change. */
  acceptToken: (token: string) => Promise<void>;
  setActiveRole: (code: string | null) => Promise<void>;
  can: (module: string, action?: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function savedRole(): string | null {
  try {
    return localStorage.getItem(ROLE_KEY);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>('loading');
  const [me, setMe] = useState<Me | null>(null);

  const signOutLocally = useCallback(() => {
    session.setToken(null);
    setMe(null);
    setStatus('anonymous');
    // Drop the previous user's data, but keep the public setup status: the always-mounted
    // SetupGate observes it, and removing it under an active observer could leave the app
    // on "Memuat sesi…" after sign-out.
    void queryClient.cancelQueries();
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'setup' });
  }, [queryClient]);

  const reload = useCallback(async () => {
    try {
      setMe(await authApi.me());
      setStatus('authenticated');
    } catch (err) {
      // A remembered role that was since removed: fall back to all roles.
      if (session.getActiveRole()) {
        session.setActiveRole(null);
        setMe(await authApi.me());
        setStatus('authenticated');
        return;
      }
      throw err;
    }
  }, []);

  useEffect(() => {
    session.onLost(signOutLocally);
    session.setActiveRole(savedRole());
    let cancelled = false;
    void (async () => {
      const ok = await refreshAccessToken();
      if (cancelled) return;
      if (!ok) return setStatus('anonymous');
      try {
        await reload();
      } catch {
        signOutLocally();
      }
    })();
    return () => {
      cancelled = true;
      session.onLost(null);
    };
  }, [reload, signOutLocally]);

  const acceptToken = useCallback(
    async (token: string) => {
      session.setToken(token);
      await reload();
    },
    [reload],
  );

  const login = useCallback(
    async (email: string, password: string, totpCode?: string, recoveryCode?: string) => {
      const out = await authApi.login(email, password, totpCode, recoveryCode);
      await acceptToken(out.access_token);
    },
    [acceptToken],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      signOutLocally();
    }
  }, [signOutLocally]);

  const setActiveRole = useCallback(
    async (code: string | null) => {
      session.setActiveRole(code);
      try {
        if (code) localStorage.setItem(ROLE_KEY, code);
        else localStorage.removeItem(ROLE_KEY);
      } catch {
        /* storage unavailable */
      }
      await reload();
      await queryClient.invalidateQueries();
    },
    [queryClient, reload],
  );

  const can = useCallback(
    (module: string, action = 'view') => Boolean(me?.permissions[module]?.[action]),
    [me],
  );

  const value = useMemo(
    () => ({ status, me, login, logout, reload, acceptToken, setActiveRole, can }),
    [status, me, login, logout, reload, acceptToken, setActiveRole, can],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
