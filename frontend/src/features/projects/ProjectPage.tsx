import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Select } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError } from '@/lib/api';
import { formatDate, formatDateTime, formatIDR } from '@/lib/format';
import { cn } from '@/lib/utils';
import {
  usePlanners,
  useProject,
  useSetManager,
  useSubmitBudget,
  type ProjectDetail,
  type ProjectStatus,
} from './api';
import { BudgetEditor } from './BudgetEditor';
import { BudgetStatusTable } from './BudgetStatusTable';
import { ProjectStatusPill } from './ProjectStatusPill';

const STEPS: ProjectStatus[] = ['draft', 'controller_review', 'awaiting_approval', 'locked'];
const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

export function Stepper({ status }: { status: ProjectStatus }) {
  const { t } = useTranslation();
  const at = status === 'closed' ? STEPS.length : STEPS.indexOf(status);
  return (
    <ol aria-label={t('project.stepper')} className="flex flex-wrap gap-2">
      {STEPS.map((s, i) => {
        const state = i < at ? 'done' : i === at ? 'current' : 'todo';
        return (
          <li
            key={s}
            aria-current={state === 'current' ? 'step' : undefined}
            className={cn(
              'flex items-center gap-2 rounded-pill border px-3 py-1 text-small',
              state === 'current' && 'border-border-strong bg-surface-raised font-semibold text-fg',
              state === 'done' && 'border-border bg-success-tint text-success',
              state === 'todo' && 'border-border text-fg-muted',
            )}
          >
            <Icon name={state === 'done' ? 'check_circle' : 'radio_button_unchecked'} />
            {i + 1}. {t(`project.status.${s}`)}
          </li>
        );
      })}
    </ol>
  );
}

export function ProjectPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const project = useProject(id);
  const [tab, setTab] = useState<'budget' | 'files' | 'history'>('budget');
  if (project.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (project.error || !project.data)
    return <FormError message={errText(project.error, t('auth.unexpected'))} />;
  const p = project.data;

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
        <CardContent className="flex flex-col gap-4">
          <Stepper status={p.status} />
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-5">
            <div>
              <dt className="text-fg-muted">{t('project.revenue')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {formatIDR(p.revenue)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('project.budget')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(p.total_cost)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('project.plannedMargin')}</dt>
              <dd className="flex flex-wrap items-center gap-2 tabular-nums text-fg-body">
                {formatIDR(p.planned_margin)}
                <StatusPill tone={p.margin_warning ? 'danger' : 'success'}>
                  {p.margin_pct.replace('.', ',')}%
                </StatusPill>
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('project.planner')}</dt>
              <dd className="text-fg-body">{p.manager_name ?? '–'}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('contract.period')}</dt>
              <dd className="text-fg-body">
                {p.start_date ? formatDate(p.start_date) : '–'} –{' '}
                {p.end_date ? formatDate(p.end_date) : '–'}
              </dd>
            </div>
          </dl>
          {p.margin_warning && (
            <p
              role="alert"
              className="flex items-start gap-2 rounded-control border border-danger bg-danger-tint px-3 py-2 text-small font-medium text-danger"
            >
              <Icon name="warning" />
              {t('project.marginBelow', {
                value: p.margin_pct.replace('.', ','),
                min: String(Number(p.min_margin_pct)),
              })}
            </p>
          )}
          {p.budget_comment && p.status === 'draft' && (
            <p className="rounded-control bg-warning-tint px-3 py-2 text-small text-warning">
              {t('project.returnedNote')}: {p.budget_comment}
            </p>
          )}
          {p.baseline && (
            <p className="text-small text-fg-secondary">
              {t('project.baselineInfo', {
                total: formatIDR(p.baseline.total_cost),
                at: formatDateTime(p.baseline.approved_at),
              })}
            </p>
          )}
          {p.contract_id && (
            <Link
              to={`/kontrak/${p.contract_id}`}
              className="text-small font-semibold text-fg-accent underline"
            >
              {t('crm.contractLink', { number: p.contract_number })}
            </Link>
          )}
        </CardContent>
      </Card>
      <Actions p={p} />
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
        <>
          {(p.status === 'locked' || p.status === 'closed') && (
            <BudgetStatusTable projectId={p.id} />
          )}
          <BudgetEditor p={p} />
        </>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="project" entityId={p.id} canWrite={p.can_edit_budget} />
      )}
      {tab === 'history' && <HistoryPanel entityType="project" entityId={p.id} />}
    </div>
  );
}

function Actions({ p }: { p: ProjectDetail }) {
  const { t } = useTranslation();
  const submit = useSubmitBudget(p.id);
  const setManager = useSetManager(p.id);
  const planners = usePlanners(p.can_assign);
  if (!p.can_submit_budget && !p.can_assign && !p.budget_request_id) return null;

  return (
    <Card>
      <CardContent className="flex flex-wrap items-end gap-3 pt-4">
        <FormError message={errText(submit.error ?? setManager.error, t('auth.unexpected'))} />
        {p.can_assign && (
          <Field label={t('project.assignPlanner')} className="w-full sm:w-72">
            <Select
              value={p.manager_id ?? ''}
              onChange={(e) => setManager.mutate(e.target.value || null)}
            >
              <option value="">–</option>
              {planners.data?.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {p.can_submit_budget && (
          <Button variant="primary" disabled={submit.isPending} onClick={() => submit.mutate()}>
            <Icon name="send" /> {t('project.submitBudget')}
          </Button>
        )}
        {submit.data && (
          <p role="status" className="text-small font-medium text-success">
            {t('project.submittedTo', {
              roles: submit.data.approvers.map((r) => t(`project.roles.${r}`)).join(' → '),
            })}
          </p>
        )}
        {p.budget_request_id && (
          <Link
            to={`/persetujuan/${p.budget_request_id}`}
            className="text-small font-semibold text-fg-accent underline"
          >
            {t('crm.openApproval')}
          </Link>
        )}
      </CardContent>
    </Card>
  );
}
