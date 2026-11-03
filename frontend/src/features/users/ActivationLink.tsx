import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

/** Shown when email is not configured: the admin passes the link on personally. */
export function ActivationLink({ link }: { link: string }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="flex flex-col gap-2 rounded-control border border-border bg-warning-tint p-3"
    >
      <p className="text-small font-semibold text-warning">{t('users.linkNotEmailed')}</p>
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 break-all rounded-control bg-surface-raised px-2 py-1 text-small text-fg">
          {link}
        </code>
        <Button
          size="sm"
          variant="ghost"
          aria-label={t('recovery.copy')}
          onClick={() => void navigator.clipboard?.writeText(link)}
        >
          <Icon name="content_copy" />
        </Button>
      </div>
    </div>
  );
}
