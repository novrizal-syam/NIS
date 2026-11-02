import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { formatDateTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useMarkRead, useNotifications, useUnreadCount } from './api';

const KIND_ICON: Record<string, string> = {
  approval_incoming: 'task_alt',
  approval_returned: 'undo',
  approval_approved: 'check_circle',
  approval_escalated: 'priority_high',
  expiry_alert: 'event_busy',
};

export function NotificationBell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const count = useUnreadCount();
  const list = useNotifications(open);
  const mark = useMarkRead();
  const unread = count.data?.unread ?? 0;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label={t('notifications.bell', { count: unread })}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="relative grid h-10 w-10 place-items-center rounded-control text-fg hover:bg-surface-muted"
      >
        <Icon name="notifications" />
        {unread > 0 && (
          <span className="absolute right-1 top-1 min-w-4 rounded-pill bg-brand-gold px-1 text-center text-caption font-bold text-on-gold">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          id={panelId}
          className="absolute right-0 z-30 mt-2 w-[min(24rem,calc(100vw-2rem))] rounded-card border border-border bg-surface-raised shadow-lg"
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <p className="font-heading text-card-title text-fg">{t('notifications.title')}</p>
            {unread > 0 && (
              <Button size="sm" variant="link" onClick={() => mark.mutate('all')}>
                {t('notifications.markAll')}
              </Button>
            )}
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {list.data?.items.length === 0 && (
              <li className="px-4 py-6 text-center text-small text-fg-secondary">
                {t('notifications.empty')}
              </li>
            )}
            {list.data?.items.map((n) => (
              <li key={n.id} className="border-b border-border last:border-0">
                <button
                  type="button"
                  onClick={() => {
                    if (!n.read) mark.mutate(n.id);
                    setOpen(false);
                    if (n.link) navigate(n.link);
                  }}
                  className={cn(
                    'flex w-full gap-3 px-4 py-3 text-left hover:bg-surface-muted',
                    !n.read && 'bg-surface-muted/60',
                  )}
                >
                  <Icon
                    name={KIND_ICON[n.kind] ?? 'notifications'}
                    className="mt-0.5 shrink-0 text-fg-secondary"
                  />
                  <span className="min-w-0">
                    <span className={cn('block text-small text-fg', !n.read && 'font-semibold')}>
                      {!n.read && <span className="sr-only">{t('notifications.unread')} </span>}
                      {n.title}
                    </span>
                    {n.body && (
                      <span className="block text-caption text-fg-secondary">{n.body}</span>
                    )}
                    <span className="block text-caption text-fg-muted">
                      {formatDateTime(n.created_at)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
