import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { formatDateTime } from '@/lib/format';

export interface LastEmail {
  kind: string;
  status: 'sent' | 'failed' | 'not_configured';
  error: string | null;
  at: string;
}

const TONE: Record<LastEmail['status'], StatusTone> = {
  sent: 'success',
  failed: 'danger',
  not_configured: 'neutral',
};

export function EmailStatus({
  value,
  withTime = false,
}: {
  value: LastEmail | null;
  withTime?: boolean;
}) {
  const { t } = useTranslation();
  if (!value) return <span className="text-fg-muted">–</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-1" title={value.error ?? undefined}>
      <StatusPill tone={TONE[value.status]}>
        {t(`email.kind.${value.kind}`, { defaultValue: value.kind })}:{' '}
        {t(`email.status.${value.status}`)}
      </StatusPill>
      {withTime && <span className="text-caption text-fg-muted">{formatDateTime(value.at)}</span>}
    </span>
  );
}
