import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router-dom';
import { NAV, visibleNav } from '@/app/nav';
import { useAuth } from '@/features/auth/AuthProvider';
import { Icon } from '@/components/ui/icon';
import { cn } from '@/lib/utils';

interface SidebarProps {
  collapsed: boolean;
  onNavigate?: () => void;
  onToggleCollapsed?: () => void;
  approvalsCount: number;
}

export function Sidebar({
  collapsed,
  onNavigate,
  onToggleCollapsed,
  approvalsCount,
}: SidebarProps) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const groups = visibleNav(import.meta.env.DEV, (m) => can(m, 'view'));
  // A path with another menu item below it (/, /pengaturan) must match exactly.
  const allPaths = NAV.flatMap((g) => g.items.map((i) => i.path));
  const exactPaths = new Set(
    allPaths.filter((p) => p === '/' || allPaths.some((o) => o !== p && o.startsWith(`${p}/`))),
  );

  return (
    <div className="sidebar flex h-full flex-col border-r border-border bg-sidebar text-sidebar-fg">
      <div
        className={cn(
          'flex h-16 shrink-0 items-center',
          collapsed ? 'justify-center px-2' : 'px-5',
        )}
      >
        {collapsed ? (
          <img src="/brand/nustrad-monogram-gold.svg" alt="Nustrad" className="h-8 w-8" />
        ) : (
          <img src="/brand/nustrad-logo-reverse.svg" alt="Nustrad" className="h-9 w-auto" />
        )}
      </div>

      <nav aria-label={t('nav.label')} className="flex-1 overflow-y-auto pb-4">
        {groups.map((group) => (
          <div key={group.key} className="mt-4 first:mt-1">
            {collapsed ? (
              <hr className="mx-3 mb-2 border-sidebar-hover" />
            ) : (
              <p className="px-5 pb-1 text-eyebrow uppercase text-sidebar-muted">
                {t(`nav.groups.${group.key}`)}
              </p>
            )}
            <ul>
              {group.items.map((item) => {
                const label = t(`nav.items.${item.key}`);
                return (
                  <li key={item.key}>
                    <NavLink
                      to={item.path}
                      end={exactPaths.has(item.path)}
                      onClick={onNavigate}
                      title={collapsed ? label : undefined}
                      aria-label={collapsed ? label : undefined}
                      className={({ isActive }) =>
                        cn(
                          'relative flex min-h-9 items-center gap-3 text-small font-medium transition-colors hover:bg-sidebar-hover',
                          collapsed ? 'justify-center px-2' : 'px-5',
                          isActive
                            ? 'bg-sidebar-hover text-sidebar-fg before:absolute before:inset-y-1 before:left-0 before:w-[3px] before:bg-brand-gold'
                            : 'text-sidebar-fg/85',
                        )
                      }
                    >
                      <Icon name={item.icon} className="shrink-0 text-[20px]" />
                      {!collapsed && (
                        <>
                          <span className="min-w-0 flex-1 py-1.5 leading-tight">{label}</span>
                          {!item.ready && (
                            <span className="rounded-pill border border-sidebar-muted/60 px-1.5 text-caption text-sidebar-muted">
                              {t('nav.soon')}
                            </span>
                          )}
                          {item.key === 'approvals' && approvalsCount > 0 && (
                            <span className="rounded-pill bg-brand-gold px-1.5 text-caption font-bold text-on-gold">
                              {approvalsCount}
                            </span>
                          )}
                        </>
                      )}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div
        className={cn('shrink-0 border-t border-sidebar-hover py-3', collapsed ? 'px-2' : 'px-5')}
      >
        {!collapsed && (
          <p className="mb-2 text-caption text-sidebar-muted">{t('app.clientLabel')}</p>
        )}
        {onToggleCollapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
            className={cn(
              'flex h-8 items-center gap-2 rounded-control text-small text-sidebar-fg/85 hover:bg-sidebar-hover',
              collapsed ? 'w-full justify-center' : 'px-2',
            )}
          >
            <Icon name={collapsed ? 'left_panel_open' : 'left_panel_close'} />
            {!collapsed && <span>{t('nav.collapse')}</span>}
          </button>
        )}
      </div>
    </div>
  );
}
