import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useAuth } from '@/features/auth/AuthProvider';
import { downloadFile } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import { cn } from '@/lib/utils';
import { STAGES, exportPath, useOpportunities, type Opportunity, type Stage } from './api';
import { FilterTile, StagePill } from './CrmPills';

type View = 'board' | 'table';
const VIEW_KEY = 'crm.oppView';

function readView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'board';
  } catch {
    return 'board';
  }
}

export function OpportunitiesPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [view, setViewState] = useState<View>(readView);
  const [q, setQ] = useState('');
  const [stage, setStage] = useState<Stage | ''>('');
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const setView = (v: View) => {
    setViewState(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* per-viewer convenience only */
    }
  };
  const filters = { q, stage, mine };
  // The board shows every stage at once (up to 200 cards); the table pages.
  const opps = useOpportunities(
    view === 'board' ? { q, mine, page: 1, page_size: 200 } : { ...filters, page },
  );
  const data = opps.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {STAGES.map((s) => (
          <FilterTile
            key={s}
            label={t(`crm.stage.${s}`)}
            value={data?.summary[s].count ?? '–'}
            sub={data ? formatIDR(data.summary[s].value) : undefined}
            active={view === 'table' && stage === s}
            onClick={() => {
              setView('table');
              setStage(stage === s ? '' : s);
              setPage(1);
            }}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('crm.searchOpps')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        <label className="flex h-10 items-center gap-2 text-small text-fg-body">
          <input
            type="checkbox"
            checked={mine}
            onChange={(e) => {
              setMine(e.target.checked);
              setPage(1);
            }}
          />
          {t('crm.mineOnly')}
        </label>
        <div role="group" aria-label={t('crm.view')} className="flex gap-1">
          {(['board', 'table'] as const).map((v) => (
            <Button
              key={v}
              variant={view === v ? 'primary' : 'secondary'}
              aria-pressed={view === v}
              onClick={() => setView(v)}
            >
              <Icon name={v === 'board' ? 'view_kanban' : 'table_rows'} /> {t(`crm.views.${v}`)}
            </Button>
          ))}
        </div>
        {can('crm', 'export') && (
          <Button
            variant="secondary"
            onClick={() =>
              void downloadFile(exportPath('opportunities', filters), 'opportunity.xlsx')
            }
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
      </div>
      <p className="text-caption text-fg-muted">{t('crm.fromLeadHint')}</p>

      {view === 'board' ? (
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
          {STAGES.map((s) => {
            const cards = data?.items.filter((o) => o.stage === s) ?? [];
            return (
              <section
                key={s}
                aria-label={t(`crm.stage.${s}`)}
                className="flex min-w-0 flex-col gap-2 rounded-card bg-surface-muted p-2"
              >
                <header className="flex items-center justify-between px-1">
                  <StagePill stage={s} />
                  <span className="text-caption tabular-nums text-fg-secondary">
                    {cards.length}
                  </span>
                </header>
                {cards.length === 0 && (
                  <p className="px-1 py-4 text-center text-caption text-fg-muted">
                    {t('crm.emptyColumn')}
                  </p>
                )}
                {cards.map((o) => (
                  <OppCard key={o.id} o={o} />
                ))}
              </section>
            );
          })}
        </div>
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <THead>
              <TR>
                <TH>{t('crm.number')}</TH>
                <TH>{t('crm.oppTitle')}</TH>
                <TH>{t('crm.stageLabel')}</TH>
                <TH className="text-right">{t('crm.value')}</TH>
                <TH className="text-right">{t('crm.probability')}</TH>
                <TH className="text-right">{t('crm.weighted')}</TH>
                <TH>{t('crm.expectedClose')}</TH>
                <TH>{t('crm.owner')}</TH>
              </TR>
            </THead>
            <TBody>
              {data?.items.length === 0 && (
                <TR>
                  <TD colSpan={8} className="py-8 text-center text-fg-secondary">
                    {t('crm.noOpps')}
                  </TD>
                </TR>
              )}
              {data?.items.map((o) => (
                <TR key={o.id}>
                  <TD className="whitespace-nowrap">
                    <Link
                      to={`/peluang/${o.id}`}
                      className="font-semibold text-fg underline-offset-2 hover:underline"
                    >
                      {o.number}
                    </Link>
                  </TD>
                  <TD className="min-w-56">
                    {o.title}
                    <span className="block text-caption text-fg-muted">{o.company_name}</span>
                  </TD>
                  <TD>
                    <StagePill stage={o.stage} />
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(o.value)}
                  </TD>
                  <TD className="text-right tabular-nums">{o.probability}%</TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(o.weighted_value)}
                  </TD>
                  <TD className="whitespace-nowrap">
                    {o.expected_close ? formatDate(o.expected_close) : '–'}
                  </TD>
                  <TD>{o.owner_name ?? '–'}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
        </Card>
      )}
    </div>
  );
}

function OppCard({ o }: { o: Opportunity }) {
  const { t } = useTranslation();
  return (
    <Link
      to={`/peluang/${o.id}`}
      className={cn(
        'flex flex-col gap-1 rounded-card border border-border bg-surface-raised p-3',
        'hover:border-border-strong',
      )}
    >
      <span className="text-caption text-fg-muted">
        {o.number}
        {o.is_tender && ` · ${t('crm.tender')}`}
      </span>
      <span className="text-small font-semibold text-fg">{o.title}</span>
      <span className="text-caption text-fg-secondary">{o.company_name}</span>
      <span className="flex items-center justify-between gap-2 text-small tabular-nums text-fg">
        {formatIDR(o.value)}
        <span className="text-caption text-fg-secondary">{o.probability}%</span>
      </span>
      {o.bid_status === 'pending' && (
        <StatusPill tone="warning" className="self-start">
          {t('crm.bidPending')}
        </StatusPill>
      )}
      <span className="text-caption text-fg-muted">{o.owner_name}</span>
    </Link>
  );
}
