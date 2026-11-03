import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

export function TempPassword({ value }: { value: string }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="flex flex-col gap-2 rounded-control border border-border bg-warning-tint p-3"
    >
      <p className="text-small font-semibold text-warning">{t('users.tempOnce')}</p>
      <div className="flex items-center gap-2">
        <code className="rounded-control bg-surface-raised px-2 py-1 font-mono text-body text-fg">
          {value}
        </code>
        <Button
          size="sm"
          variant="ghost"
          aria-label={t('recovery.copy')}
          onClick={() => void navigator.clipboard?.writeText(value)}
        >
          <Icon name="content_copy" />
        </Button>
      </div>
    </div>
  );
}
