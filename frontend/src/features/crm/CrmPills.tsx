import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { cn } from '@/lib/utils';
import type { LeadStatus, Stage } from './api';

const LEAD_TONE: Record<LeadStatus, StatusTone> = {
  new: 'info',
  contacted: 'warning',
  qualified: 'success',
  disqualified: 'neutral',
};

const STAGE_TONE: Record<Stage, StatusTone> = {
  qualified: 'info',
  quotation: 'warning',
  submitted: 'warning',
  won: 'success',
  lost: 'danger',
};

export function LeadStatusPill({ status }: { status: LeadStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={LEAD_TONE[status]}>{t(`crm.leadStatus.${status}`)}</StatusPill>;
}

export function StagePill({ stage }: { stage: Stage }) {
  const { t } = useTranslation();
  return <StatusPill tone={STAGE_TONE[stage]}>{t(`crm.stage.${stage}`)}</StatusPill>;
}

/** Summary tile that doubles as a filter toggle (same look as the users screen). */
export function FilterTile({
  label,
  value,
  sub,
  active,
  onClick,
}: {
  label: string;
  value: string | number;
  sub?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'min-w-32 rounded-card border bg-surface-raised px-3 py-2 text-left',
        active ? 'border-border-strong' : 'border-border',
      )}
    >
      <span className="block text-caption uppercase text-fg-muted">{label}</span>
      <span className="font-heading text-section-title tabular-nums text-fg">{value}</span>
      {sub && <span className="block text-caption tabular-nums text-fg-secondary">{sub}</span>}
    </button>
  );
}
