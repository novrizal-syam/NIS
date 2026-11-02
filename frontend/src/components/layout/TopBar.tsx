import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { usePageMeta } from '@/app/pageMeta';
import { Icon } from '@/components/ui/icon';
import { UserMenu } from './UserMenu';

export function TopBar({
  onOpenMenu,
  approvalsCount,
}: {
  onOpenMenu: () => void;
  approvalsCount: number;
}) {
  const { t } = useTranslation();
  const meta = usePageMeta();

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-surface">
      <div className="flex min-h-16 items-center gap-3 px-4 py-2 md:px-6">
        <button
          type="button"
          onClick={onOpenMenu}
          aria-label={t('nav.open')}
          className="grid h-10 w-10 place-items-center rounded-control text-fg hover:bg-surface-muted lg:hidden"
        >
          <Icon name="menu" />
        </button>

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-section-title md:text-page-title">{meta.title}</h1>
          <p className="hidden truncate text-small text-fg-secondary sm:block">
            {meta.description}
          </p>
        </div>

        <form role="search" className="hidden w-72 xl:block" onSubmit={(e) => e.preventDefault()}>
          <label className="relative block">
            <span className="sr-only">{t('topbar.searchLabel')}</span>
            <Icon
              name="search"
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted"
            />
            <input
              type="search"
              placeholder={t('topbar.search')}
              className="h-10 w-full rounded-control border border-border bg-surface-muted pl-10 pr-3 text-small text-fg placeholder:text-fg-muted"
            />
          </label>
        </form>

        <Link
          to="/persetujuan"
          aria-label={t('topbar.approvalsCount', { count: approvalsCount })}
          title={t('topbar.approvals')}
          className="relative grid h-10 w-10 place-items-center rounded-control text-fg hover:bg-surface-muted"
        >
          <Icon name="notifications" />
          {approvalsCount > 0 && (
            <span className="absolute right-1 top-1 min-w-4 rounded-pill bg-brand-gold px-1 text-center text-caption font-bold text-on-gold">
              {approvalsCount}
            </span>
          )}
        </Link>

        <UserMenu />
      </div>
    </header>
  );
}
