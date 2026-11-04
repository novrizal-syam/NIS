import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import type { PrStatus } from './api';

const TONE: Record<PrStatus, StatusTone> = {
  draft: 'neutral',
  blocked: 'danger',
  awaiting_approval: 'warning',
  approved: 'success',
  cancelled: 'neutral',
};

export function PrStatusPill({ status }: { status: PrStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`pr.status.${status}`)}</StatusPill>;
}
