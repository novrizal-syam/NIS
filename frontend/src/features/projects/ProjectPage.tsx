import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import { useProject } from './api';
import { ProjectStatusPill } from './ProjectStatusPill';

export function ProjectPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const project = useProject(id);
  const [tab, setTab] = useState<'budget' | 'files' | 'history'>('budget');
  if (project.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (project.error || !project.data)
    return (
      <FormError
        message={project.error instanceof ApiError ? project.error.message : t('auth.unexpected')}
      />
    );
  const p = project.data;
  const total = p.budget.reduce((a, b) => a + Number(b.amount), 0);

  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/proyek"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('project.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {p.number}
            {p.contract_number && ` · ${p.contract_number}`}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{p.name}</CardTitle>
            <ProjectStatusPill status={p.status} />
          </div>
          <CardDescription>{p.company_name}</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-fg-muted">{t('project.revenue')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {formatIDR(p.revenue)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('project.budget')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(p.budget_total)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('project.plannedMargin')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(p.planned_margin)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('contract.period')}</dt>
              <dd className="text-fg-body">
                {p.start_date ? formatDate(p.start_date) : '–'} –{' '}
                {p.end_date ? formatDate(p.end_date) : '–'}
              </dd>
            </div>
          </dl>
          {p.contract_id && (
            <Link
              to={`/kontrak/${p.contract_id}`}
              className="mt-3 inline-block text-small font-semibold text-fg-accent underline"
            >
              {t('crm.contractLink', { number: p.contract_number })}
            </Link>
          )}
        </CardContent>
      </Card>
      <Tabs
        label={p.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'budget', label: t('project.budgetTab') },
          { value: 'files', label: t('project.documents') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'budget' && (
        <Card>
          <CardHeader>
            <CardTitle>{t('project.budgetTitle')}</CardTitle>
            <CardDescription>
              {t('project.budgetHelp', {
                pct: String(Number(p.contingency_pct)).replace('.', ','),
              })}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <THead>
                <TR>
                  <TH>{t('project.costElement')}</TH>
                  <TH>{t('project.source')}</TH>
                  <TH className="text-right">{t('project.amount')}</TH>
                  <TH className="text-right">{t('project.ofRevenue')}</TH>
                </TR>
              </THead>
              <TBody>
                {p.budget.map((b) => (
                  <TR key={b.cost_element_code}>
                    <TD>
                      {b.cost_element_name}
                      <span className="block text-caption text-fg-muted">
                        {b.cost_element_code}
                      </span>
                    </TD>
                    <TD>{t(`project.sources.${b.source}`)}</TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(b.amount)}
                    </TD>
                    <TD className="text-right tabular-nums">
                      {b.share_of_revenue ? `${b.share_of_revenue.replace('.', ',')}%` : '–'}
                    </TD>
                  </TR>
                ))}
                <TR>
                  <TD className="font-semibold text-fg">{t('project.total')}</TD>
                  <TD>{''}</TD>
                  <TD className="whitespace-nowrap text-right font-semibold tabular-nums text-fg">
                    {formatIDR(total)}
                  </TD>
                  <TD>{''}</TD>
                </TR>
              </TBody>
            </Table>
          </CardContent>
        </Card>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="project" entityId={p.id} canWrite={false} />
      )}
      {tab === 'history' && <HistoryPanel entityType="project" entityId={p.id} />}
    </div>
  );
}
