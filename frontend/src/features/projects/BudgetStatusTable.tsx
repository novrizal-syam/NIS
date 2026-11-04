import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { formatIDR } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useBudgetStatus, type BudgetStatusLine } from './api';

const BAR: Record<BudgetStatusLine['state'], string> = {
  ok: 'bg-brand-gold',
  warning: 'bg-warning',
  exhausted: 'bg-danger',
};

export function UsageBar({ line }: { line: BudgetStatusLine }) {
  const { t } = useTranslation();
  const pct = Math.min(Number(line.used_pct), 100);
  return (
    <span className="flex items-center gap-2">
      <span
        role="progressbar"
        aria-label={`${t('project.used')} ${line.wbs_code} ${line.cost_element_code}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        className="h-2 w-24 overflow-hidden rounded-pill bg-surface-muted"
      >
        <span className={cn('block h-full', BAR[line.state])} style={{ width: `${pct}%` }} />
      </span>
      <span
        className={cn(
          'text-caption tabular-nums',
          line.state === 'exhausted'
            ? 'font-semibold text-danger'
            : line.state === 'warning'
              ? 'font-semibold text-warning'
              : 'text-fg-secondary',
        )}
      >
        {line.used_pct.replace('.', ',')}%
      </span>
    </span>
  );
}

/** Budget, pre-commitment, commitment, actual and available per line (budget_control). */
export function BudgetStatusTable({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useBudgetStatus(projectId, true);
  if (!q.data) return null;
  const { lines, totals } = q.data;
  const money = (v: string) => formatIDR(v);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('project.controlTitle')}</CardTitle>
        <CardDescription>{t('project.controlHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>WBS</TH>
              <TH>{t('project.costElement')}</TH>
              <TH className="text-right">{t('project.budget')}</TH>
              <TH className="text-right">{t('project.preCommit')}</TH>
              <TH className="text-right">{t('project.commit')}</TH>
              <TH className="text-right">{t('project.actual')}</TH>
              <TH className="text-right">{t('project.available')}</TH>
              <TH>{t('project.used')}</TH>
            </TR>
          </THead>
          <TBody>
            {lines.map((l) => (
              <TR key={`${l.wbs_code}|${l.cost_element_code}`}>
                <TD>{l.wbs_code}</TD>
                <TD className="min-w-44">
                  {l.cost_element_name}
                  {l.locked_reserve && (
                    <StatusPill tone="info" className="ml-2">
                      {t('project.lockedReserve')}
                    </StatusPill>
                  )}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{money(l.budget)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{money(l.pre_commit)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{money(l.commit)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{money(l.actual)}</TD>
                <TD
                  className={cn(
                    'whitespace-nowrap text-right font-semibold tabular-nums',
                    l.state === 'exhausted' ? 'text-danger' : 'text-fg',
                  )}
                >
                  {money(l.available)}
                </TD>
                <TD>{l.locked_reserve ? '–' : <UsageBar line={l} />}</TD>
              </TR>
            ))}
            <TR>
              <TD className="font-semibold text-fg" colSpan={2}>
                {t('project.total')}
              </TD>
              {(['budget', 'pre_commit', 'commit', 'actual', 'available'] as const).map((k) => (
                <TD
                  key={k}
                  className="whitespace-nowrap text-right font-semibold tabular-nums text-fg"
                >
                  {money(totals[k])}
                </TD>
              ))}
              <TD>{''}</TD>
            </TR>
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}
