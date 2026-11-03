import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import type { ProjectStatus } from './api';

const TONE: Record<ProjectStatus, StatusTone> = {
  draft: 'neutral',
  controller_review: 'info',
  awaiting_approval: 'warning',
  locked: 'success',
  closed: 'neutral',
};

export function ProjectStatusPill({ status }: { status: ProjectStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`project.status.${status}`)}</StatusPill>;
}
