import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Select } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { FilterTile } from '@/features/crm/CrmPills';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDate, formatDateTime, formatIDR } from '@/lib/format';
import { useDor, useDorProjects, useDors } from './api';
import { listDrafts, type LocalDraft } from './offlineStore';
import { syncAll } from './sync';
import type { DorDetail } from './types';
import { useDorSync } from './useDorSync';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const TONE: Record<DorDetail['status'], StatusTone> = {
  draft: 'neutral',
  submitted: 'warning',
  approved: 'success',
  returned: 'danger',
};
const STATUSES: DorDetail['status'][] = ['draft', 'submitted', 'returned', 'approved'];

export function DorStatusPill({ status }: { status: DorDetail['status'] }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`dor.status.${status}`)}</StatusPill>;
}

function useLocalDrafts(): [LocalDraft[], () => void] {
  const [drafts, setDrafts] = useState<LocalDraft[]>([]);
  const reload = () => {
    void listDrafts()
      .then((all) =>
        setDrafts(
          all
            .filter((d) => d.state !== 'synced')
            .sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
        ),
      )
      .catch(() => setDrafts([]));
  };
  useEffect(() => {
    reload();
    window.addEventListener('dor-drafts-changed', reload);
    return () => window.removeEventListener('dor-drafts-changed', reload);
  }, []);
  return [drafts, reload];
}

export function DorListPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const online = useDorSync();
  const [drafts, reload] = useLocalDrafts();
  const [status, setStatus] = useState<DorDetail['status'] | ''>('');
  const [page, setPage] = useState(1);
  const [project, setProject] = useState('');
  const list = useDors({ status, page });
  const projects = useDorProjects();
  const canCreate = can('operations', 'create');
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill tone={online ? 'success' : 'warning'}>
          {online ? t('dor.online') : t('dor.offline')}
        </StatusPill>
        {drafts.length > 0 && (
          <span className="text-small text-fg-secondary">
            {t('dor.pending', { count: drafts.length })}
          </span>
        )}
      </div>
      {canCreate && (
        <Card>
          <CardContent className="flex flex-wrap items-end gap-2 pt-4">
            <Field label={t('pr.project')} className="min-w-0 flex-1">
              <Select value={project} onChange={(e) => setProject(e.target.value)}>
                <option value="">{t('master.choose')}</option>
                {projects.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.number} · {p.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Button
              variant="primary"
              disabled={!project}
              onClick={() => navigate(`/operasi/dor/baru?project=${project}`)}
            >
              <Icon name="add" /> {t('dor.new')}
            </Button>
          </CardContent>
        </Card>
      )}
      {drafts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('dor.onDevice')}</CardTitle>
            <CardDescription>{t('dor.onDeviceHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {drafts.map((d) => (
              <Link
                key={d.client_id}
                to={`/operasi/dor/isi/${d.client_id}`}
                className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-border px-3 py-2 text-small hover:bg-surface-muted"
              >
                <span>
                  <span className="font-semibold text-fg">
                    {d.number ?? t('dor.newTitle')} · {d.project_number}
                  </span>{' '}
                  · {formatDate(d.data.report_date)}
                </span>
                <StatusPill tone={d.state === 'dirty' ? 'warning' : 'danger'}>
                  {t(`dor.state.${d.state}`)}
                </StatusPill>
              </Link>
            ))}
            <Button
              variant="secondary"
              size="sm"
              className="self-start"
              disabled={!online}
              onClick={() => void syncAll().then(reload)}
            >
              <Icon name="sync" /> {t('dor.syncNow')}
            </Button>
          </CardContent>
        </Card>
      )}
      <div className="flex flex-wrap gap-2">
        {STATUSES.map((s) => (
          <FilterTile
            key={s}
            label={t(`dor.status.${s}`)}
            value={list.data?.counts[s] ?? '–'}
            active={status === s}
            onClick={() => {
              setStatus(status === s ? '' : s);
              setPage(1);
            }}
          />
        ))}
        {can('operations', 'export') && (
          <Button
            variant="secondary"
            className="ml-auto self-end"
            onClick={() => void downloadFile(`/operations/dors/export`, 'dor.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
      </div>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('pr.project')}</TH>
              <TH>{t('dor.reportDate')}</TH>
              <TH className="text-right">{t('dor.revenue')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.error && (
              <TR>
                <TD colSpan={5} className="py-6 text-center text-fg-secondary">
                  {t('dor.listOffline')}
                </TD>
              </TR>
            )}
            {list.data?.items.length === 0 && (
              <TR>
                <TD colSpan={5} className="py-8 text-center text-fg-secondary">
                  {t('dor.empty')}
                </TD>
              </TR>
            )}
            {list.data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/operasi/dor/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.number}
                  </Link>
                </TD>
                <TD>{r.project_number}</TD>
                <TD className="whitespace-nowrap">
                  {formatDate(r.report_date)}
                  {r.late && (
                    <span className="ml-2 text-caption font-semibold text-danger">
                      {t('dor.late')}
                    </span>
                  )}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(r.revenue)}
                </TD>
                <TD>
                  <DorStatusPill status={r.status} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}

export function DorPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const dor = useDor(id);
  const [tab, setTab] = useState<'detail' | 'photos' | 'history'>('detail');
  if (dor.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (dor.error || !dor.data)
    return <FormError message={errText(dor.error, t('auth.unexpected'))} />;
  const d = dor.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/operasi/dor"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('dor.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {d.project_number} · {d.wbs_code}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">
              {t('dor.titleFor', { date: formatDate(d.report_date) })}
            </CardTitle>
            <DorStatusPill status={d.status} />
          </div>
          <CardDescription>
            {d.project_name} · {d.created_by_name} · {t('dor.deadline')}:{' '}
            {formatDateTime(d.deadline)}
            {d.late && <span className="ml-2 font-semibold text-danger">{t('dor.late')}</span>}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <dl className="grid gap-x-6 gap-y-2 text-small sm:grid-cols-3">
            <div>
              <dt className="text-fg-muted">{t('dor.revenue')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {formatIDR(d.revenue)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('dor.internalCost')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.internal_cost)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">NPT</dt>
              <dd className="text-fg-body">
                {d.npt_hours.replace('.', ',')} {t('dor.hoursShort')}
                {d.npt_reason ? ` · ${d.npt_reason}` : ''}
              </dd>
            </div>
          </dl>
          {d.return_reason && d.status === 'returned' && (
            <p className="rounded-control bg-warning-tint px-3 py-2 text-small text-warning">
              {t('dor.returned')}: {d.return_reason}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {d.can_edit && (
              <Link
                to={`/operasi/dor/isi/${d.client_id}`}
                className="inline-flex h-10 items-center gap-2 rounded-control bg-brand-gold px-4 font-semibold text-on-gold"
              >
                <Icon name="edit" /> {t('dor.edit')}
              </Link>
            )}
            {d.request_id && (
              <Link
                to={`/persetujuan/${d.request_id}`}
                className="inline-flex h-10 items-center text-small font-semibold text-fg-accent underline"
              >
                {t('crm.openApproval')}
              </Link>
            )}
          </div>
        </CardContent>
      </Card>
      <Tabs
        label={d.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'photos', label: t('dor.photos') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && <DorDetailView d={d} />}
      {tab === 'photos' && (
        <AttachmentsPanel entityType="dor" entityId={d.id} canWrite={d.can_edit} />
      )}
      {tab === 'history' && <HistoryPanel entityType="dor" entityId={d.id} />}
    </div>
  );
}

function DorDetailView({ d }: { d: DorDetail }) {
  const { t } = useTranslation();
  const n = (v: string) => v.replace('.', ',');
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('dor.sections.activities')}</CardTitle>
        </CardHeader>
        <CardContent className="whitespace-pre-line text-small text-fg-body">
          {d.activities || '–'}
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('dor.sections.equipment')}</CardTitle>
        </CardHeader>
        <Table>
          <THead>
            <TR>
              <TH>{t('dor.unit')}</TH>
              <TH className="text-right">{t('dor.hours.operating')}</TH>
              <TH className="text-right">{t('dor.hours.standby')}</TH>
              <TH className="text-right">{t('dor.hours.breakdown')}</TH>
              <TH className="text-right">{t('dor.hours.rig')}</TH>
              <TH className="text-right">{t('dor.revenue')}</TH>
            </TR>
          </THead>
          <TBody>
            {d.equipment.map((x) => (
              <TR key={x.asset_code}>
                <TD>{x.asset_code}</TD>
                <TD className="text-right tabular-nums">{n(x.operating)}</TD>
                <TD className="text-right tabular-nums">{n(x.standby)}</TD>
                <TD className="text-right tabular-nums">{n(x.breakdown)}</TD>
                <TD className="text-right tabular-nums">{n(x.rig)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(x.revenue)}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="overflow-x-auto">
          <CardHeader>
            <CardTitle>{t('dor.sections.crew')}</CardTitle>
          </CardHeader>
          <Table>
            <TBody>
              {d.crew.map((c) => (
                <TR key={c.employee_code}>
                  <TD>{c.employee_code}</TD>
                  <TD className="text-right tabular-nums">
                    {n(c.hours)} + {n(c.overtime_hours)} {t('dor.hoursShort')}
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(c.revenue)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
        <Card className="overflow-x-auto">
          <CardHeader>
            <CardTitle>{t('dor.sections.consumables')}</CardTitle>
          </CardHeader>
          <Table>
            <TBody>
              {d.consumables.map((k) => (
                <TR key={k.item_code}>
                  <TD>{k.item_code}</TD>
                  <TD className="text-right tabular-nums">{n(k.qty)}</TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(k.revenue)}
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums text-fg-secondary">
                    {formatIDR(k.internal_cost)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      </div>
      {Object.keys(d.technical).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('dor.technical')}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-2 text-small sm:grid-cols-3">
              {Object.entries(d.technical).map(([k, v]) => (
                <div key={k}>
                  <dt className="text-fg-muted">{k}</dt>
                  <dd className="text-fg-body">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
