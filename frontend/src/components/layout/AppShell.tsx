import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Outlet, useLocation } from 'react-router-dom';
import { Icon } from '@/components/ui/icon';
import { useInboxCount } from '@/features/workflow/api';
import { cn } from '@/lib/utils';
import { ErrorBoundary } from './ErrorBoundary';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

const COLLAPSE_KEY = 'nustrad.sidebarCollapsed';

export function AppShell() {
  const { t } = useTranslation();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch {
      return false;
    }
  });
  const inboxCount = useInboxCount();
  const approvalsCount = inboxCount.data?.count ?? 0;

  useEffect(() => setDrawerOpen(false), [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawerOpen(false);
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [drawerOpen]);

  const toggleCollapsed = () =>
    setCollapsed((v) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, v ? '0' : '1');
      } catch {
        /* storage unavailable */
      }
      return !v;
    });

  return (
    <div className="flex min-h-screen">
      <a
        href="#main"
        className="sr-only z-50 rounded-control bg-brand-gold px-3 py-2 text-on-gold focus:not-sr-only focus:fixed focus:left-2 focus:top-2"
      >
        {t('app.skipToContent')}
      </a>

      {/* Desktop sidebar */}
      <aside
        className={cn(
          'sticky top-0 hidden h-screen shrink-0 lg:block',
          collapsed ? 'w-16' : 'w-sidebar',
        )}
      >
        <Sidebar
          collapsed={collapsed}
          onToggleCollapsed={toggleCollapsed}
          approvalsCount={approvalsCount}
        />
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label={t('nav.label')}
        >
          <button
            type="button"
            aria-label={t('nav.close')}
            className="absolute inset-0 bg-brand-ink/60"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="relative h-full w-sidebar max-w-[85vw]">
            <Sidebar
              collapsed={false}
              onNavigate={() => setDrawerOpen(false)}
              approvalsCount={approvalsCount}
            />
            <button
              type="button"
              onClick={() => setDrawerOpen(false)}
              aria-label={t('nav.close')}
              className="absolute right-2 top-3 grid h-10 w-10 place-items-center rounded-control text-sidebar-fg hover:bg-sidebar-hover [&:focus-visible]:outline-brand-gold"
            >
              <Icon name="close" />
            </button>
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onOpenMenu={() => setDrawerOpen(true)} approvalsCount={approvalsCount} />
        <main id="main" tabIndex={-1} className="flex-1 p-4 md:p-6">
          <ErrorBoundary resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
