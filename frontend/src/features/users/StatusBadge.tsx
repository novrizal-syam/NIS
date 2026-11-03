import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import type { UserStatus } from './api';

const TONE: Record<UserStatus, StatusTone> = {
  invited: 'info',
  active: 'success',
  locked: 'danger',
  inactive: 'neutral',
};

export function StatusBadge({ status }: { status: UserStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`users.status.${status}`)}</StatusPill>;
}
