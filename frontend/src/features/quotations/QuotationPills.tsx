import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import type { QuotationStatus } from './api';

const TONE: Record<QuotationStatus, StatusTone> = {
  draft: 'neutral',
  submitted: 'warning',
  approved: 'success',
  rejected: 'danger',
  sent: 'info',
  superseded: 'neutral',
};

export function QuotationStatusPill({ status }: { status: QuotationStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`quotation.status.${status}`)}</StatusPill>;
}

/** Margin with a danger pill below the warning threshold (default 20 %). */
export function MarginPill({ pct, warning }: { pct: string; warning: boolean }) {
  const { t } = useTranslation();
  const text = `${pct.replace('.', ',')}%`;
  return warning ? (
    <StatusPill tone="danger" title={t('quotation.lowMargin')}>
      {t('quotation.marginLow', { value: text })}
    </StatusPill>
  ) : (
    <span className="tabular-nums">{text}</span>
  );
}
