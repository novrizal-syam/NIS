import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { formatDateTime, formatIDR } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useBudgetVersions } from './api';

/** Baseline v0 vs current (latest version) per line, plus the version history. */
export function BudgetVersionsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useBudgetVersions(projectId, true);
  if (!q.data) return null;
  const { versions, lines } = q.data;
  if (versions.length === 0)
    return <p className="text-small text-fg-secondary">{t('project.noVersions')}</p>;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('project.baselineVsCurrent')}</CardTitle>
          <CardDescription>
            {t('project.currentVersion', { version: versions[versions.length - 1]!.version })}
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>WBS</TH>
                <TH>{t('project.costElement')}</TH>
                <TH className="text-right">{t('project.baselineCol')}</TH>
                <TH className="text-right">{t('project.currentCol')}</TH>
                <TH className="text-right">{t('project.changeCol')}</TH>
              </TR>
            </THead>
            <TBody>
              {lines.map((l) => {
                const change = Number(l.change);
                return (
                  <TR key={`${l.wbs_code}|${l.cost_element_code}`}>
                    <TD>{l.wbs_code}</TD>
                    <TD>{l.cost_element_name}</TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(l.baseline)}
                    </TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(l.current)}
                    </TD>
                    <TD
                      className={cn(
                        'whitespace-nowrap text-right tabular-nums',
                        change > 0 && 'font-semibold text-fg',
                        change < 0 && 'text-fg-secondary',
                      )}
                    >
                      {change === 0 ? '–' : `${change > 0 ? '+' : ''}${formatIDR(l.change)}`}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t('project.versionHistory')}</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="flex flex-col gap-3">
            {[...versions].reverse().map((v) => (
              <li
                key={v.version}
                className="flex flex-col gap-1 border-b border-border pb-3 last:border-0"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-fg">v{v.version}</span>
                  <StatusPill tone={v.kind === 'baseline' ? 'info' : 'neutral'}>
                    {t(`project.versionKind.${v.kind}`)}
                  </StatusPill>
                  <span className="text-small tabular-nums text-fg-body">
                    {formatIDR(v.total_cost)} · {v.margin_pct.replace('.', ',')}%
                  </span>
                  <span className="text-caption text-fg-muted">
                    {formatDateTime(v.approved_at)}
                  </span>
                </span>
                {v.note && <span className="text-small text-fg-secondary">{v.note}</span>}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}
