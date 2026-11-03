import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { cn } from '@/lib/utils';
import type { ContractRow } from './api';

const TONE: Record<ContractRow['status'], StatusTone> = {
  active: 'success',
  completed: 'neutral',
  terminated: 'danger',
};

export function ContractStatusPill({ status }: { status: ContractRow['status'] }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`contract.status.${status}`)}</StatusPill>;
}

/** Contract usage (approved DOR value / contract value); amber from 80 %. */
export function UsageBar({ pct }: { pct: string | null }) {
  const { t } = useTranslation();
  const value = pct === null ? 0 : Number(pct);
  return (
    <span className="flex items-center gap-2">
      <span
        role="progressbar"
        aria-label={t('contract.usage')}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(value, 100))}
        className="h-2 w-20 overflow-hidden rounded-pill bg-surface-muted"
      >
        <span
          className={cn('block h-full', value >= 80 ? 'bg-warning' : 'bg-brand-gold')}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </span>
      <span className="text-caption tabular-nums text-fg-secondary">
        {pct === null ? '–' : `${pct.replace('.', ',')}%`}
      </span>
    </span>
  );
}
