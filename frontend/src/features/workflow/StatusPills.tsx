import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';

const REQUEST: Record<string, StatusTone> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  cancelled: 'neutral',
};
const STEP: Record<string, StatusTone> = {
  waiting: 'neutral',
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  skipped: 'neutral',
};

export function RequestStatusPill({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <StatusPill tone={REQUEST[status] ?? 'neutral'}>{t(`workflow.status.${status}`)}</StatusPill>
  );
}

export function StepStatusPill({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <StatusPill tone={STEP[status] ?? 'neutral'}>{t(`workflow.stepStatus.${status}`)}</StatusPill>
  );
}
