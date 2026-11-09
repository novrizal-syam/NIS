import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { useWarehouses } from '@/features/inventory/api';
import { ApiError } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import {
  useAddDowntime,
  useAllocate,
  useAsset,
  useAssets,
  useCompleteWo,
  useCreateWo,
  useDowntime,
  useImportPm,
  useIssuePart,
  useKpis,
  useMntProjects,
  usePmTasks,
  useRelease,
  useRunPm,
  useUpdateWo,
  useWo,
  useWos,
  type ChecklistItem,
  type WoRow,
} from './api';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const n = (v: string | null | undefined) => (v ?? '–').replace('.', ',');
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());
const WO_TONE: Record<WoRow['status'], StatusTone> = {
  open: 'warning',
  in_progress: 'info',
  done: 'success',
  cancelled: 'neutral',
};

export function WoStatusPill({ status }: { status: WoRow['status'] }) {
  const { t } = useTranslation();
  return <StatusPill tone={WO_TONE[status]}>{t(`mnt.woStatus.${status}`)}</StatusPill>;
}

type Tab = 'assets' | 'wos' | 'pm' | 'downtime' | 'kpi';

export function MaintenancePage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('assets');
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('nav.items.maintenance')}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'assets', label: t('mnt.tabs.assets') },
          { value: 'wos', label: t('mnt.tabs.wos') },
          { value: 'pm', label: t('mnt.tabs.pm') },
          { value: 'downtime', label: t('mnt.tabs.downtime') },
          { value: 'kpi', label: t('mnt.tabs.kpi') },
        ]}
      />
      {tab === 'assets' && <AssetsTab />}
      {tab === 'wos' && <WosTab />}
      {tab === 'pm' && <PmTab />}
      {tab === 'downtime' && <DowntimeTab />}
      {tab === 'kpi' && <KpiTab />}
    </div>
  );
}

function AssetsTab() {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const assets = useAssets(q);
  return (
    <>
      <Field label={t('master.search')} className="max-w-md">
        <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </Field>
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('mnt.asset')}</TH>
              <TH>{t('mnt.type')}</TH>
              <TH>{t('mnt.criticality')}</TH>
              <TH>{t('mnt.certificates')}</TH>
              <TH>{t('mnt.allocatedTo')}</TH>
              <TH className="text-right">{t('mnt.hours')}</TH>
              <TH className="text-right">{t('mnt.openWo')}</TH>
            </TR>
          </THead>
          <TBody>
            {assets.data?.map((a) => (
              <TR key={a.code}>
                <TD className="min-w-48">
                  <Link
                    to={`/pemeliharaan/aset/${a.code}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {a.code}
                  </Link>
                  <span className="block text-caption text-fg-muted">{a.name}</span>
                </TD>
                <TD>{a.equipment_type ?? '–'}</TD>
                <TD>{a.criticality}</TD>
                <TD>
                  {a.cert_blocked ? (
                    <StatusPill tone="danger">{t('mnt.certExpired')}</StatusPill>
                  ) : a.cert_warning ? (
                    <StatusPill tone="warning">{t('mnt.certSoon')}</StatusPill>
                  ) : (
                    <StatusPill tone="success">{t('mnt.certOk')}</StatusPill>
                  )}
                </TD>
                <TD>{a.allocated_to ?? '–'}</TD>
                <TD className="text-right tabular-nums">{n(a.operating_hours)}</TD>
                <TD className="text-right tabular-nums">{a.open_work_orders}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

const KINDS: WoRow['kind'][] = ['preventive', 'corrective', 'inspection_pre', 'inspection_post'];

function WosTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [status, setStatus] = useState('open');
  const [kind, setKind] = useState('');
  const [page, setPage] = useState(1);
  const wos = useWos({ status, kind, page });
  const run = useRunPm();
  const create = useCreateWo();
  const [asset, setAsset] = useState('');
  const [title, setTitle] = useState('');
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.status')} className="w-44">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t('mnt.all')}</option>
            <option value="open">{t('mnt.openOnly')}</option>
            <option value="done">{t('mnt.woStatus.done')}</option>
            <option value="cancelled">{t('mnt.woStatus.cancelled')}</option>
          </Select>
        </Field>
        <Field label={t('mnt.kind')} className="w-52">
          <Select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">{t('mnt.all')}</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`mnt.kinds.${k}`)}
              </option>
            ))}
          </Select>
        </Field>
        {can('maintenance', 'edit') && (
          <Button variant="secondary" disabled={run.isPending} onClick={() => run.mutate()}>
            <Icon name="event_repeat" /> {t('mnt.runPm')}
          </Button>
        )}
        {run.data && (
          <span role="status" className="text-small text-fg-secondary">
            {t('mnt.pmCreated', { count: run.data.created })}
          </span>
        )}
      </div>
      {can('maintenance', 'create') && (
        <Card>
          <CardContent className="flex flex-wrap items-end gap-2 pt-4">
            <FormError message={errText(create.error, t('auth.unexpected'))} />
            <Field label={t('mnt.asset')} className="w-40">
              <Input value={asset} onChange={(e) => setAsset(e.target.value.toUpperCase())} />
            </Field>
            <Field label={t('mnt.corrTitle')} className="min-w-0 flex-1">
              <Input value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Button
              variant="primary"
              disabled={!asset || title.trim().length < 5 || create.isPending}
              onClick={() =>
                create.mutate(
                  { asset_code: asset, title: title.trim(), checklist: [] },
                  { onSuccess: () => setTitle('') },
                )
              }
            >
              <Icon name="build" /> {t('mnt.newCorrective')}
            </Button>
          </CardContent>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('mnt.asset')}</TH>
              <TH>{t('mnt.kind')}</TH>
              <TH>{t('mnt.trigger')}</TH>
              <TH>{t('mnt.due')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {wos.data?.items.length === 0 && (
              <TR>
                <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                  {t('mnt.noWo')}
                </TD>
              </TR>
            )}
            {wos.data?.items.map((w) => (
              <TR key={w.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/pemeliharaan/wo/${w.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {w.number}
                  </Link>
                  <span className="block max-w-xs truncate text-caption text-fg-muted">
                    {w.title}
                  </span>
                </TD>
                <TD>{w.asset_code}</TD>
                <TD>{t(`mnt.kinds.${w.kind}`)}</TD>
                <TD className="text-small text-fg-secondary">{w.trigger}</TD>
                <TD className="whitespace-nowrap">
                  {w.due_date
                    ? formatDate(w.due_date)
                    : w.due_hours
                      ? `${n(w.due_hours)} ${t('mnt.h')}`
                      : '–'}
                  {w.overdue && (
                    <span className="ml-1 text-caption font-semibold text-danger">
                      {t('mnt.overdue')}
                    </span>
                  )}
                </TD>
                <TD>
                  <WoStatusPill status={w.status} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={wos.data?.total ?? 0} onPage={setPage} />
      </Card>
    </>
  );
}

function PmTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const tasks = usePmTasks(true);
  const imp = useImportPm();
  const details =
    imp.error instanceof ApiError
      ? (imp.error.details as { errors?: string[] } | undefined)
      : undefined;
  return (
    <>
      {can('maintenance', 'edit') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('mnt.importTitle')}</CardTitle>
            <CardDescription>{t('mnt.importHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <input
              type="file"
              accept=".xlsx"
              aria-label={t('mnt.importFile')}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) imp.mutate(f);
                e.target.value = '';
              }}
            />
            <FormError message={errText(imp.error, t('auth.unexpected'))} />
            {details?.errors && (
              <ul className="list-disc pl-6 text-small text-danger">
                {details.errors.slice(0, 20).map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            )}
            {imp.data && (
              <p role="status" className="text-small text-success">
                {t('mnt.imported', imp.data)}
              </p>
            )}
          </CardContent>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('mnt.type')}</TH>
              <TH>{t('mnt.task')}</TH>
              <TH>{t('mnt.frequency')}</TH>
              <TH>{t('mnt.form')}</TH>
              <TH className="text-right">{t('mnt.items')}</TH>
            </TR>
          </THead>
          <TBody>
            {tasks.data?.length === 0 && (
              <TR>
                <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                  {t('mnt.noTasks')}
                </TD>
              </TR>
            )}
            {tasks.data?.map((x) => (
              <TR key={x.code}>
                <TD className="whitespace-nowrap font-semibold">{x.code}</TD>
                <TD>{x.equipment_type_code}</TD>
                <TD className="min-w-48">{x.title}</TD>
                <TD>
                  {x.frequency === 'hours'
                    ? t('mnt.everyHours', { hours: x.interval_hours })
                    : t(`mnt.freq.${x.frequency}`)}
                </TD>
                <TD>{x.form_code ?? '–'}</TD>
                <TD className="text-right">{x.checklist.length}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

function DowntimeTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const rows = useDowntime(true);
  const add = useAddDowntime();
  const [v, setV] = useState({ asset: '', start: today(), hours: '', reason: '' });
  return (
    <>
      {can('maintenance', 'create') && (
        <Card>
          <CardContent className="flex flex-wrap items-end gap-2 pt-4">
            <FormError message={errText(add.error, t('auth.unexpected'))} />
            <Field label={t('mnt.asset')} className="w-36">
              <Input
                value={v.asset}
                onChange={(e) => setV({ ...v, asset: e.target.value.toUpperCase() })}
              />
            </Field>
            <Field label={t('mnt.start')} className="w-44">
              <Input
                type="date"
                value={v.start}
                onChange={(e) => setV({ ...v, start: e.target.value })}
              />
            </Field>
            <Field label={t('mnt.hours')} className="w-24">
              <Input
                inputMode="decimal"
                value={v.hours}
                onChange={(e) => setV({ ...v, hours: e.target.value })}
              />
            </Field>
            <Field label={t('mnt.reason')} className="min-w-0 flex-1">
              <Input value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />
            </Field>
            <Button
              variant="primary"
              disabled={
                !v.asset ||
                !Number(v.hours.replace(',', '.')) ||
                v.reason.trim().length < 3 ||
                add.isPending
              }
              onClick={() =>
                add.mutate(
                  {
                    asset_code: v.asset,
                    start_date: v.start,
                    hours: v.hours.replace(',', '.'),
                    reason: v.reason.trim(),
                  },
                  { onSuccess: () => setV({ ...v, hours: '', reason: '' }) },
                )
              }
            >
              <Icon name="add" /> {t('mnt.logDowntime')}
            </Button>
          </CardContent>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('mnt.asset')}</TH>
              <TH>{t('mnt.start')}</TH>
              <TH className="text-right">{t('mnt.hours')}</TH>
              <TH>{t('mnt.reason')}</TH>
            </TR>
          </THead>
          <TBody>
            {rows.data?.map((d, i) => (
              <TR key={i}>
                <TD>{d.asset_code}</TD>
                <TD className="whitespace-nowrap">{formatDate(d.start_date)}</TD>
                <TD className="text-right tabular-nums">{n(d.hours)}</TD>
                <TD>
                  {d.reason}
                  {d.from_dor && <span className="ml-1 text-caption text-fg-muted">(DOR)</span>}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

function Kpi({
  label,
  value,
  target,
  good,
}: {
  label: string;
  value: string | null;
  target?: string;
  good?: boolean;
}) {
  return (
    <div className="rounded-control border border-border px-3 py-2">
      <dt className="text-caption text-fg-muted">{label}</dt>
      <dd
        className={
          good === undefined || value === null
            ? 'font-heading text-card-title tabular-nums text-fg'
            : good
              ? 'font-heading text-card-title tabular-nums text-success'
              : 'font-heading text-card-title tabular-nums text-danger'
        }
      >
        {value === null ? '–' : value}
      </dd>
      {target && <dd className="text-caption text-fg-muted">{target}</dd>}
    </div>
  );
}

function KpiTab() {
  const { t } = useTranslation();
  const [to, setTo] = useState(today());
  const [from, setFrom] = useState(() => {
    const d = new Date(`${today()}T00:00:00`);
    d.setDate(d.getDate() - 29);
    return d.toISOString().slice(0, 10);
  });
  const k = useKpis(from, to, true);
  const tot = k.data?.totals;
  const pct = (v: string | null | undefined) => (v == null ? null : `${n(v)}%`);
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('vi.from')} className="w-44">
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label={t('vi.to')} className="w-44">
          <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
      </div>
      {tot && (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Kpi
            label={t('mnt.kpi.utilisation')}
            value={pct(tot.utilisation_pct)}
            target="≥ 85%"
            good={tot.utilisation_pct !== null && Number(tot.utilisation_pct) >= 85}
          />
          <Kpi
            label={t('mnt.kpi.downtime')}
            value={pct(tot.downtime_pct)}
            target="< 3%"
            good={tot.downtime_pct !== null && Number(tot.downtime_pct) < 3}
          />
          <Kpi
            label={t('mnt.kpi.pmCompliance')}
            value={pct(tot.pm_compliance_pct)}
            target={t('mnt.kpi.pmOnTime', { done: tot.pm_on_time, due: tot.pm_due })}
          />
          <Kpi label="MTBF" value={tot.mtbf_hours ? `${n(tot.mtbf_hours)} ${t('mnt.h')}` : null} />
          <Kpi label="MTTR" value={tot.mttr_hours ? `${n(tot.mttr_hours)} ${t('mnt.h')}` : null} />
          <Kpi label={t('mnt.kpi.failures')} value={String(tot.failures)} />
        </dl>
      )}
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('mnt.asset')}</TH>
              <TH className="text-right">{t('mnt.kpi.utilisation')}</TH>
              <TH className="text-right">{t('mnt.kpi.downtime')}</TH>
              <TH className="text-right">{t('mnt.hours')}</TH>
              <TH className="text-right">MTBF</TH>
              <TH className="text-right">MTTR</TH>
            </TR>
          </THead>
          <TBody>
            {k.data?.rows.map((r) => (
              <TR key={r.asset_code}>
                <TD>
                  {r.asset_code}
                  <span className="block text-caption text-fg-muted">{r.name}</span>
                </TD>
                <TD className="text-right tabular-nums">{pct(r.utilisation_pct) ?? '–'}</TD>
                <TD className="text-right tabular-nums">{pct(r.downtime_pct) ?? '–'}</TD>
                <TD className="text-right tabular-nums">{n(r.operating_hours)}</TD>
                <TD className="text-right tabular-nums">{r.mtbf_hours ? n(r.mtbf_hours) : '–'}</TD>
                <TD className="text-right tabular-nums">{r.mttr_hours ? n(r.mttr_hours) : '–'}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- asset detail

export function AssetPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { code = '' } = useParams();
  const a = useAsset(code);
  const projects = useMntProjects();
  const allocate = useAllocate(code);
  const release = useRelease(code);
  const [project, setProject] = useState('');
  const [start, setStart] = useState(today());
  if (a.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (a.error || !a.data) return <FormError message={errText(a.error, t('auth.unexpected'))} />;
  const d = a.data;
  const current = d.allocations.find((x) => !x.released_at);
  const mayAllocate = can('maintenance', 'edit') || can('maintenance', 'approve');
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/pemeliharaan"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('mnt.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.code} · {d.equipment_type_code ?? '–'} · {t('mnt.criticality')} {d.criticality}
          </p>
          <CardTitle className="text-section-title">{d.name}</CardTitle>
          <CardDescription>
            {t('mnt.hours')}: {n(d.operating_hours)} · {d.location ?? '–'} · {t('mnt.dayRate')}{' '}
            {formatIDR(d.internal_day_rate)}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {d.cert_blocked && (
            <p
              role="alert"
              className="rounded-control border border-danger bg-danger-tint px-3 py-2 text-small text-danger"
            >
              {t('mnt.blockedAllocation', { reason: d.cert_blocked })}
            </p>
          )}
          {d.cert_warning && !d.cert_blocked && (
            <p className="rounded-control bg-warning-tint px-3 py-2 text-small text-warning">
              {d.cert_warning}
            </p>
          )}
          <ul className="flex flex-col gap-1 text-small">
            {d.certificates.map((c) => (
              <li key={c.name} className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{c.name}</span>
                <span className="text-fg-secondary">
                  {c.expiry_date ? formatDate(c.expiry_date) : '–'}
                </span>
                <StatusPill
                  tone={
                    c.status === 'expired'
                      ? 'danger'
                      : c.status === 'warning'
                        ? 'warning'
                        : 'success'
                  }
                >
                  {t(`mnt.certStatus.${c.status}`)}
                </StatusPill>
              </li>
            ))}
          </ul>
          <FormError message={errText(allocate.error ?? release.error, t('auth.unexpected'))} />
          {mayAllocate && !current && (
            <div className="flex flex-wrap items-end gap-2">
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
              <Field label={t('mnt.start')} className="w-44">
                <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              </Field>
              <Button
                variant="primary"
                disabled={!project || allocate.isPending}
                onClick={() => allocate.mutate({ project_id: project, start_date: start })}
              >
                <Icon name="local_shipping" /> {t('mnt.allocate')}
              </Button>
            </div>
          )}
          {current && (
            <div className="flex flex-wrap items-center gap-2 text-small">
              {t('mnt.allocatedSince', {
                project: current.project_number,
                date: formatDate(current.start_date),
              })}
              {mayAllocate && (
                <Button variant="secondary" size="sm" onClick={() => release.mutate(today())}>
                  {t('mnt.release')}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('mnt.schedules')}</CardTitle>
        </CardHeader>
        <Table>
          <THead>
            <TR>
              <TH>{t('mnt.task')}</TH>
              <TH>{t('mnt.frequency')}</TH>
              <TH>{t('mnt.lastDone')}</TH>
              <TH>{t('mnt.nextDue')}</TH>
            </TR>
          </THead>
          <TBody>
            {d.schedules.map((s) => (
              <TR key={s.task_code}>
                <TD>{s.title}</TD>
                <TD>
                  {s.frequency === 'hours'
                    ? t('mnt.everyHours', { hours: s.interval_hours })
                    : t(`mnt.freq.${s.frequency}`)}
                </TD>
                <TD className="whitespace-nowrap">
                  {formatDate(s.last_done_date)} · {n(s.last_done_hours)} {t('mnt.h')}
                </TD>
                <TD className="whitespace-nowrap">
                  {s.next_due_date
                    ? formatDate(s.next_due_date)
                    : s.next_due_hours
                      ? `${n(s.next_due_hours)} ${t('mnt.h')}`
                      : '–'}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('mnt.tabs.wos')}</CardTitle>
        </CardHeader>
        <Table>
          <TBody>
            {d.work_orders.map((w) => (
              <TR key={w.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/pemeliharaan/wo/${w.id}`}
                    className="font-semibold underline-offset-2 hover:underline"
                  >
                    {w.number}
                  </Link>
                </TD>
                <TD>{w.title}</TD>
                <TD>
                  <WoStatusPill status={w.status} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- work order

export function WorkOrderPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const wo = useWo(id);
  const [tab, setTab] = useState<'detail' | 'photos' | 'history'>('detail');
  if (wo.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (wo.error || !wo.data) return <FormError message={errText(wo.error, t('auth.unexpected'))} />;
  const d = wo.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/pemeliharaan"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('mnt.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {d.asset_code} · {t(`mnt.kinds.${d.kind}`)}
            {d.form_code ? ` · ${d.form_code}` : ''}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{d.title}</CardTitle>
            <WoStatusPill status={d.status} />
          </div>
          <CardDescription>
            {d.asset_name}
            {d.project_number ? ` · ${d.project_number}` : ''}
            {d.trigger ? ` · ${d.trigger}` : ''}
          </CardDescription>
        </CardHeader>
        {d.signature_name && (
          <CardContent className="text-small text-fg-secondary">
            {t('mnt.signed', {
              name: d.signature_name,
              date: d.completed_date ? formatDate(d.completed_date) : '',
            })}
          </CardContent>
        )}
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
      {tab === 'detail' && <WoEditor key={d.status + d.labour_hours} d={d} />}
      {tab === 'photos' && (
        <AttachmentsPanel entityType="work_order" entityId={d.id} canWrite={d.can_edit} />
      )}
      {tab === 'history' && <HistoryPanel entityType="work_order" entityId={d.id} />}
    </div>
  );
}

function WoEditor({ d }: { d: NonNullable<ReturnType<typeof useWo>['data']> }) {
  const { t } = useTranslation();
  const save = useUpdateWo(d.id);
  const complete = useCompleteWo(d.id);
  const part = useIssuePart(d.id);
  const warehouses = useWarehouses();
  const [list, setList] = useState<ChecklistItem[]>(d.checklist);
  const [hours, setHours] = useState(d.labour_hours);
  const [result, setResult] = useState(d.result ?? '');
  const [p, setP] = useState({ item: '', wh: '', qty: '1' });
  const ed = d.can_edit;
  const setItem = (i: number, patch: Partial<ChecklistItem>) =>
    setList(list.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const body = {
    checklist: list,
    labour_hours: hours.replace(',', '.') || '0',
    result: result.trim() || null,
  };
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('mnt.checklist')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {list.map((x, i) => (
            <div
              key={x.item}
              className="flex flex-wrap items-end gap-2 border-b border-border pb-2"
            >
              <span className="min-w-48 flex-1 text-small text-fg">{x.item}</span>
              <Field label={t('mnt.resultLabel')} className="w-32">
                <Select
                  aria-label={`${t('mnt.resultLabel')} ${x.item}`}
                  value={x.result ?? ''}
                  disabled={!ed}
                  onChange={(e) =>
                    setItem(i, { result: (e.target.value || null) as ChecklistItem['result'] })
                  }
                >
                  <option value="">–</option>
                  <option value="ok">OK</option>
                  <option value="nok">{t('mnt.nok')}</option>
                  <option value="na">N/A</option>
                </Select>
              </Field>
              <Field label={t('mnt.note')} className="min-w-0 flex-1">
                <Input
                  value={x.note ?? ''}
                  disabled={!ed}
                  onChange={(e) => setItem(i, { note: e.target.value })}
                />
              </Field>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Field label={t('mnt.labour')} className="w-32">
              <Input
                inputMode="decimal"
                value={hours}
                disabled={!ed}
                onChange={(e) => setHours(e.target.value)}
              />
            </Field>
            <Field label={t('mnt.result')} className="min-w-0 flex-1">
              <Textarea
                rows={2}
                value={result}
                disabled={!ed}
                onChange={(e) => setResult(e.target.value)}
              />
            </Field>
          </div>
          <FormError message={errText(save.error ?? complete.error, t('auth.unexpected'))} />
          {ed && (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                disabled={save.isPending}
                onClick={() => save.mutate(body)}
              >
                <Icon name="save" /> {t('dor.save')}
              </Button>
              <Button
                variant="primary"
                disabled={complete.isPending || list.some((x) => !x.result) || !result.trim()}
                onClick={() => save.mutate(body, { onSuccess: () => complete.mutate() })}
              >
                <Icon name="draw" /> {t('mnt.signComplete')}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t('mnt.parts')}</CardTitle>
          <CardDescription>
            {t('mnt.partsHelp', { value: formatIDR(d.parts_value) })}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {d.parts.map((x, i) => (
            <p key={i} className="text-small">
              {x.item_code} × {n(x.qty)} ({x.warehouse_code}) · {formatIDR(x.value)}
            </p>
          ))}
          <FormError message={errText(part.error, t('auth.unexpected'))} />
          {ed && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('stock.itemCode')} className="w-36">
                <Input
                  value={p.item}
                  onChange={(e) => setP({ ...p, item: e.target.value.toUpperCase() })}
                />
              </Field>
              <Field label={t('stock.warehouse')} className="w-48">
                <Select value={p.wh} onChange={(e) => setP({ ...p, wh: e.target.value })}>
                  <option value="">{t('master.choose')}</option>
                  {warehouses.data?.map((w) => (
                    <option key={w.code} value={w.code}>
                      {w.code} · {w.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('quotation.qty')} className="w-24">
                <Input
                  inputMode="decimal"
                  value={p.qty}
                  onChange={(e) => setP({ ...p, qty: e.target.value })}
                />
              </Field>
              <Button
                variant="secondary"
                disabled={!p.item || !p.wh || part.isPending}
                onClick={() =>
                  part.mutate(
                    { item_code: p.item, warehouse_code: p.wh, qty: p.qty.replace(',', '.') },
                    { onSuccess: () => setP({ ...p, item: '', qty: '1' }) },
                  )
                }
              >
                <Icon name="inventory_2" /> {t('mnt.issuePart')}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
