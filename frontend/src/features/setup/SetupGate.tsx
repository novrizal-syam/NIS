import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useLocation } from 'react-router-dom';
import { useSetupStatus } from './api';

/** Until first-run setup is finished every route leads to /setup. */
export function SetupGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const status = useSetupStatus();
  const { pathname } = useLocation();
  if (status.isLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-surface" role="status">
        <p className="text-body text-fg-secondary">{t('auth.loading')}</p>
      </div>
    );
  }
  // If the status call fails (API down) the normal pages show their own errors.
  const needsSetup = status.data ? !status.data.setup_completed : false;
  if (needsSetup && pathname !== '/setup') return <Navigate to="/setup" replace />;
  return <>{children}</>;
}
