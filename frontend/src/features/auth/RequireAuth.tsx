import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthProvider';

const PENDING_ROUTES = {
  change_password: '/akun/ganti-password',
  setup_totp: '/akun/2fa',
} as const;

function FullScreenStatus() {
  const { t } = useTranslation();
  return (
    <div
      className="grid min-h-screen place-items-center bg-surface"
      role="status"
      aria-live="polite"
    >
      <p className="text-body text-fg-secondary">{t('auth.loading')}</p>
    </div>
  );
}

/**
 * Guards the app. `allowPending` is for the forced first-login pages themselves.
 * Order of forced steps: change password, then 2FA setup.
 */
export function RequireAuth({
  children,
  allowPending = false,
}: {
  children: ReactNode;
  allowPending?: boolean;
}) {
  const { status, me } = useAuth();
  const location = useLocation();

  if (status === 'loading') return <FullScreenStatus />;
  if (status === 'anonymous' || !me) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  const next = me.pending[0];
  if (next && !allowPending) return <Navigate to={PENDING_ROUTES[next]} replace />;
  return <>{children}</>;
}
