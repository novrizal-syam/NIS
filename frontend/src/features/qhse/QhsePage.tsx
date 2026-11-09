import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDate, formatDateTime } from '@/lib/format';
import {
  useCapas,
  useIncidents,
  useInspections,
  useObservations,
  usePermits,
  useQhsePost,
  useQhseProjects,
  useQhseUsers,
  useRiskAssessments,
  useStats,
  type Hazard,
} from './api';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());
const TABS = [
  'risk',
  'permits',
  'inspections',
  'observations',
  'incidents',
  'capa',
  'stats',
] as const;
type Tab = (typeof TABS)[number];
const LEVEL: Record<string, StatusTone> = {
  high: 'danger',
  medium: 'warning',
  low: 'success',
  '-': 'neutral',
};

export function QhsePage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const initial = (params.get('tab') as Tab | null) ?? 'risk';
  const [tab, setTab] = useState<Tab>(TABS.includes(initial) ? initial : 'risk');
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label="QHSE"
        value={tab}
        onChange={setTab}
        items={TABS.map((v) => ({ value: v, label: t(`qhse.tabs.${v}`) }))}
      />
      {tab === 'risk' && <RiskTab />}
      {tab === 'permits' && <PermitsTab />}
      {tab === 'inspections' && <InspectionsTab />}
      {tab === 'observations' && <ObservationsTab />}
      {tab === 'incidents' && <IncidentsTab />}
      {tab === 'capa' && <CapaTab />}
      {tab === 'stats' && <StatsTab />}
    </div>
  );
}

function ProjectSelect({
  value,
  onChange,
  optional,
}: {
  value: string;
  onChange: (v: string) => void;
  optional?: boolean;
}) {
  const { t } = useTranslation();
  const projects = useQhseProjects();
  return (
    <Field label={t('pr.project')} required={!optional} className="min-w-0 flex-1">
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{optional ? t('qhse.noProject') : t('master.choose')}</option>
        {projects.data?.map((p) => (
          <option key={p.id} value={p.id}>
            {p.number} · {p.name}
          </option>
        ))}
      </Select>
    </Field>
  );
}

// ---------------------------------------------------------------- HIRADC / JSA

const emptyHazard = (): Hazard => ({
  activity: '',
  hazard: '',
  likelihood: 3,
  severity: 3,
  controls: '',
  residual_likelihood: 1,
  residual_severity: 3,
});

function RiskTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useRiskAssessments();
  const post = useQhsePost();
  const [project, setProject] = useState('');
  const [kind, setKind] = useState<'hiradc' | 'jsa'>('hiradc');
  const [title, setTitle] = useState('');
  const [rows, setRows] = useState<Hazard[]>([emptyHazard()]);
  const set = (i: number, patch: Partial<Hazard>) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const num = (v: string) => Math.max(1, Math.min(5, Number(v) || 1));
  return (
    <>
      <p className="text-small text-fg-secondary">{t('qhse.riskHelp')}</p>
      {can('qhse', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('qhse.newRisk')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap items-end gap-2">
              <ProjectSelect value={project} onChange={setProject} />
              <Field label={t('qhse.kind')} className="w-32">
                <Select value={kind} onChange={(e) => setKind(e.target.value as 'hiradc' | 'jsa')}>
                  <option value="hiradc">HIRADC</option>
                  <option value="jsa">JSA</option>
                </Select>
              </Field>
              <Field label={t('qhse.title')} className="min-w-0 flex-1">
                <Input value={title} onChange={(e) => setTitle(e.target.value)} />
              </Field>
            </div>
            {rows.map((r, i) => (
              <div
                key={i}
                className="grid gap-2 border-b border-border pb-2 sm:grid-cols-[1fr_1fr_4rem_4rem_2fr_4rem_4rem]"
              >
                <Field label={t('qhse.activity')}>
                  <Input
                    value={r.activity}
                    onChange={(e) => set(i, { activity: e.target.value })}
                  />
                </Field>
                <Field label={t('qhse.hazard')}>
                  <Input value={r.hazard} onChange={(e) => set(i, { hazard: e.target.value })} />
                </Field>
                <Field label="L">
                  <Input
                    inputMode="numeric"
                    value={r.likelihood}
                    onChange={(e) => set(i, { likelihood: num(e.target.value) })}
                  />
                </Field>
                <Field label="S">
                  <Input
                    inputMode="numeric"
                    value={r.severity}
                    onChange={(e) => set(i, { severity: num(e.target.value) })}
                  />
                </Field>
                <Field label={t('qhse.controls')}>
                  <Input
                    value={r.controls}
                    onChange={(e) => set(i, { controls: e.target.value })}
                  />
                </Field>
                <Field label={t('qhse.residualL')}>
                  <Input
                    inputMode="numeric"
                    value={r.residual_likelihood ?? ''}
                    onChange={(e) => set(i, { residual_likelihood: num(e.target.value) })}
                  />
                </Field>
                <Field label={t('qhse.residualS')}>
                  <Input
                    inputMode="numeric"
                    value={r.residual_severity ?? ''}
                    onChange={(e) => set(i, { residual_severity: num(e.target.value) })}
                  />
                </Field>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setRows([...rows, emptyHazard()])}
              >
                <Icon name="add" /> {t('qhse.addHazard')}
              </Button>
              <Button
                variant="primary"
                disabled={!project || title.trim().length < 3 || post.isPending}
                onClick={() =>
                  post.mutate(
                    {
                      path: '/qhse/risk-assessments',
                      body: { project_id: project, kind, title, hazards: rows },
                    },
                    {
                      onSuccess: () => {
                        setTitle('');
                        setRows([emptyHazard()]);
                      },
                    },
                  )
                }
              >
                <Icon name="save" /> {t('qhse.saveDraft')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {list.data?.map((r) => (
        <Card key={r.id}>
          <CardHeader>
            <p className="eyebrow">
              {r.number} · {r.project_number} · {r.kind.toUpperCase()}
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>{r.title}</CardTitle>
              <StatusPill tone={r.status === 'approved' ? 'success' : 'warning'}>
                {t(`qhse.raStatus.${r.status}`)}
              </StatusPill>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>{t('qhse.hazard')}</TH>
                  <TH>{t('qhse.risk')}</TH>
                  <TH>{t('qhse.controls')}</TH>
                  <TH>{t('qhse.residual')}</TH>
                </TR>
              </THead>
              <TBody>
                {r.hazards.map((h, i) => (
                  <TR key={i}>
                    <TD>
                      {h.hazard}
                      <span className="block text-caption text-fg-muted">{h.activity}</span>
                    </TD>
                    <TD>
                      <StatusPill
                        tone={LEVEL[h.level ?? '-']}
                      >{`${h.score} · ${t(`qhse.level.${h.level ?? '-'}`)}`}</StatusPill>
                    </TD>
                    <TD>{h.controls || '–'}</TD>
                    <TD>
                      <StatusPill tone={LEVEL[h.residual_level ?? '-']}>
                        {t(`qhse.level.${h.residual_level ?? '-'}`)}
                      </StatusPill>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            {r.can_approve && (
              <Button
                variant="primary"
                className="self-start"
                disabled={post.isPending}
                onClick={() => post.mutate({ path: `/qhse/risk-assessments/${r.id}/approve` })}
              >
                <Icon name="task_alt" /> {t('qhse.approve')}
              </Button>
            )}
          </CardContent>
        </Card>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- permits

const PERMIT_TYPES = [
  'hot_work',
  'confined_space',
  'work_at_height',
  'electrical',
  'lifting',
  'excavation',
  'general',
];
const PERMIT_TONE: Record<string, StatusTone> = {
  requested: 'warning',
  approved: 'success',
  closed: 'neutral',
  cancelled: 'neutral',
};

function PermitsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = usePermits();
  const post = useQhsePost();
  const now = new Date();
  const local = (d: Date) =>
    new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [v, setV] = useState({
    project: '',
    type: 'hot_work',
    location: '',
    work: '',
    precautions: '',
    from: local(now),
    to: local(new Date(now.getTime() + 8 * 3600_000)),
  });
  return (
    <>
      {can('qhse', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('qhse.newPermit')}</CardTitle>
            <CardDescription>{t('qhse.permitHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap items-end gap-2">
              <ProjectSelect value={v.project} onChange={(p) => setV({ ...v, project: p })} />
              <Field label={t('qhse.permitType')} className="w-48">
                <Select value={v.type} onChange={(e) => setV({ ...v, type: e.target.value })}>
                  {PERMIT_TYPES.map((x) => (
                    <option key={x} value={x}>
                      {t(`qhse.permitTypes.${x}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('qhse.location')} className="min-w-0 flex-1">
                <Input
                  value={v.location}
                  onChange={(e) => setV({ ...v, location: e.target.value })}
                />
              </Field>
            </div>
            <Field label={t('qhse.work')}>
              <Textarea
                rows={2}
                value={v.work}
                onChange={(e) => setV({ ...v, work: e.target.value })}
              />
            </Field>
            <Field label={t('qhse.precautions')} hint={t('qhse.precautionsHint')}>
              <Textarea
                rows={2}
                value={v.precautions}
                onChange={(e) => setV({ ...v, precautions: e.target.value })}
              />
            </Field>
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('qhse.validFrom')} className="w-56">
                <Input
                  type="datetime-local"
                  value={v.from}
                  onChange={(e) => setV({ ...v, from: e.target.value })}
                />
              </Field>
              <Field label={t('qhse.validTo')} className="w-56">
                <Input
                  type="datetime-local"
                  value={v.to}
                  onChange={(e) => setV({ ...v, to: e.target.value })}
                />
              </Field>
              <Button
                variant="primary"
                disabled={
                  !v.project ||
                  v.location.trim().length < 2 ||
                  v.work.trim().length < 5 ||
                  post.isPending
                }
                onClick={() =>
                  post.mutate({
                    path: '/qhse/permits',
                    body: {
                      project_id: v.project,
                      permit_type: v.type,
                      location: v.location,
                      work_description: v.work,
                      precautions: v.precautions
                        .split('\n')
                        .map((x) => x.trim())
                        .filter(Boolean),
                      valid_from: new Date(v.from).toISOString(),
                      valid_to: new Date(v.to).toISOString(),
                    },
                  })
                }
              >
                <Icon name="send" /> {t('qhse.requestPermit')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('qhse.permitType')}</TH>
              <TH>{t('qhse.validity')}</TH>
              <TH>{t('master.status')}</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {list.data?.map((p) => (
              <TR key={p.id}>
                <TD className="whitespace-nowrap">
                  <span className="font-semibold">{p.number}</span>
                  <span className="block text-caption text-fg-muted">
                    {p.project_number} · {p.location}
                  </span>
                </TD>
                <TD>{t(`qhse.permitTypes.${p.permit_type}`)}</TD>
                <TD className="text-small">
                  {formatDateTime(p.valid_from)} – {formatDateTime(p.valid_to)}
                </TD>
                <TD>
                  <StatusPill tone={PERMIT_TONE[p.status]}>
                    {t(`qhse.permitStatus.${p.status}`)}
                  </StatusPill>
                </TD>
                <TD className="whitespace-nowrap">
                  {p.status === 'requested' && can('qhse', 'approve') && !p.is_own && (
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => post.mutate({ path: `/qhse/permits/${p.id}/approve` })}
                    >
                      {t('qhse.approve')}
                    </Button>
                  )}
                  {p.status === 'approved' && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => post.mutate({ path: `/qhse/permits/${p.id}/close` })}
                    >
                      {t('qhse.close')}
                    </Button>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- inspections, observations

function CapaFields({
  value,
  onChange,
}: {
  value: { action: string; owner: string; due: string };
  onChange: (v: { action: string; owner: string; due: string }) => void;
}) {
  const { t } = useTranslation();
  const users = useQhseUsers();
  return (
    <div className="flex flex-wrap items-end gap-2 rounded-control border border-dashed border-border p-2">
      <Field label={t('qhse.capaAction')} className="min-w-0 flex-1">
        <Input
          value={value.action}
          onChange={(e) => onChange({ ...value, action: e.target.value })}
        />
      </Field>
      <Field label={t('qhse.owner')} className="w-48">
        <Select value={value.owner} onChange={(e) => onChange({ ...value, owner: e.target.value })}>
          <option value="">–</option>
          {users.data?.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('qhse.due')} className="w-44">
        <Input
          type="date"
          min={today()}
          value={value.due}
          onChange={(e) => onChange({ ...value, due: e.target.value })}
        />
      </Field>
    </div>
  );
}

const capaList = (c: { action: string; owner: string; due: string }) =>
  c.action.trim().length >= 5 && c.owner && c.due
    ? [{ action: c.action.trim(), owner_id: c.owner, due_date: c.due }]
    : [];

function InspectionsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useInspections();
  const post = useQhsePost();
  const [v, setV] = useState({ project: '', type: '', date: today(), findings: '' });
  const [capa, setCapa] = useState({ action: '', owner: '', due: '' });
  return (
    <>
      {can('qhse', 'create') && (
        <Card>
          <CardContent className="flex flex-col gap-2 pt-4">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap items-end gap-2">
              <ProjectSelect
                optional
                value={v.project}
                onChange={(p) => setV({ ...v, project: p })}
              />
              <Field label={t('qhse.inspectionType')} className="w-56">
                <Input
                  value={v.type}
                  placeholder={t('qhse.inspectionTypeHint')}
                  onChange={(e) => setV({ ...v, type: e.target.value })}
                />
              </Field>
              <Field label={t('vi.date')} className="w-44">
                <Input
                  type="date"
                  max={today()}
                  value={v.date}
                  onChange={(e) => setV({ ...v, date: e.target.value })}
                />
              </Field>
            </div>
            <Field label={t('qhse.findings')}>
              <Textarea
                rows={2}
                value={v.findings}
                onChange={(e) => setV({ ...v, findings: e.target.value })}
              />
            </Field>
            <CapaFields value={capa} onChange={setCapa} />
            <Button
              variant="primary"
              className="self-start"
              disabled={v.type.trim().length < 2 || post.isPending}
              onClick={() =>
                post.mutate({
                  path: '/qhse/inspections',
                  body: {
                    project_id: v.project || null,
                    inspection_type: v.type,
                    inspection_date: v.date,
                    findings: v.findings || null,
                    capas: capaList(capa),
                  },
                })
              }
            >
              <Icon name="save" /> {t('qhse.record')}
            </Button>
          </CardContent>
        </Card>
      )}
      <SimpleTable
        rows={list.data ?? []}
        cols={['inspection_type', 'inspection_date', 'findings']}
      />
    </>
  );
}

function ObservationsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useObservations();
  const post = useQhsePost();
  const [v, setV] = useState({
    project: '',
    cat: 'unsafe_condition',
    date: today(),
    desc: '',
    action: '',
  });
  const [capa, setCapa] = useState({ action: '', owner: '', due: '' });
  return (
    <>
      {can('qhse', 'create') && (
        <Card>
          <CardContent className="flex flex-col gap-2 pt-4">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap items-end gap-2">
              <ProjectSelect
                optional
                value={v.project}
                onChange={(p) => setV({ ...v, project: p })}
              />
              <Field label={t('qhse.category')} className="w-52">
                <Select value={v.cat} onChange={(e) => setV({ ...v, cat: e.target.value })}>
                  {['unsafe_act', 'unsafe_condition', 'good_practice'].map((c) => (
                    <option key={c} value={c}>
                      {t(`qhse.obsCat.${c}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('vi.date')} className="w-44">
                <Input
                  type="date"
                  max={today()}
                  value={v.date}
                  onChange={(e) => setV({ ...v, date: e.target.value })}
                />
              </Field>
            </div>
            <Field label={t('qhse.description')}>
              <Textarea
                rows={2}
                value={v.desc}
                onChange={(e) => setV({ ...v, desc: e.target.value })}
              />
            </Field>
            <Field label={t('qhse.actionTaken')}>
              <Input value={v.action} onChange={(e) => setV({ ...v, action: e.target.value })} />
            </Field>
            <CapaFields value={capa} onChange={setCapa} />
            <Button
              variant="primary"
              className="self-start"
              disabled={v.desc.trim().length < 5 || post.isPending}
              onClick={() =>
                post.mutate({
                  path: '/qhse/observations',
                  body: {
                    project_id: v.project || null,
                    obs_date: v.date,
                    category: v.cat,
                    description: v.desc,
                    action_taken: v.action || null,
                    capas: capaList(capa),
                  },
                })
              }
            >
              <Icon name="save" /> {t('qhse.record')}
            </Button>
          </CardContent>
        </Card>
      )}
      <SimpleTable rows={list.data ?? []} cols={['category', 'obs_date', 'description']} />
    </>
  );
}

function SimpleTable({ rows, cols }: { rows: Record<string, unknown>[]; cols: string[] }) {
  const { t } = useTranslation();
  return (
    <Card className="overflow-x-auto">
      <Table>
        <THead>
          <TR>
            <TH>{t('crm.number')}</TH>
            {cols.map((c) => (
              <TH key={c}>{t(`qhse.cols.${c}`)}</TH>
            ))}
          </TR>
        </THead>
        <TBody>
          {rows.length === 0 && (
            <TR>
              <TD colSpan={cols.length + 1} className="py-6 text-center text-fg-secondary">
                {t('qhse.empty')}
              </TD>
            </TR>
          )}
          {rows.map((r) => (
            <TR key={String(r.id)}>
              <TD className="whitespace-nowrap">
                <span className="font-semibold">{String(r.number)}</span>
                <span className="block text-caption text-fg-muted">
                  {String(r.project_number ?? '')}
                </span>
              </TD>
              {cols.map((c) => {
                const v = r[c];
                const s =
                  typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
                    ? formatDate(v)
                    : String(v ?? '–');
                return (
                  <TD key={c} className="max-w-md">
                    {c === 'category' ? t(`qhse.obsCat.${s}`, { defaultValue: s }) : s}
                  </TD>
                );
              })}
            </TR>
          ))}
        </TBody>
      </Table>
    </Card>
  );
}

// ---------------------------------------------------------------- incidents

const CATS = [
  'near_miss',
  'first_aid',
  'medical_treatment',
  'restricted_work',
  'lost_time',
  'fatality',
  'property_damage',
  'environmental',
];

function IncidentsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useIncidents();
  const post = useQhsePost();
  const [v, setV] = useState({ project: '', cat: 'near_miss', date: today(), desc: '', lost: '0' });
  const [open, setOpen] = useState<string | null>(null);
  const [inv, setInv] = useState({ root: '', text: '' });
  const [capa, setCapa] = useState({ action: '', owner: '', due: '' });
  return (
    <>
      {can('qhse', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('qhse.reportIncident')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap items-end gap-2">
              <ProjectSelect
                optional
                value={v.project}
                onChange={(p) => setV({ ...v, project: p })}
              />
              <Field label={t('qhse.category')} className="w-52">
                <Select value={v.cat} onChange={(e) => setV({ ...v, cat: e.target.value })}>
                  {CATS.map((c) => (
                    <option key={c} value={c}>
                      {t(`qhse.incCat.${c}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('vi.date')} className="w-44">
                <Input
                  type="date"
                  max={today()}
                  value={v.date}
                  onChange={(e) => setV({ ...v, date: e.target.value })}
                />
              </Field>
              <Field label={t('qhse.lostDays')} className="w-28">
                <Input
                  inputMode="numeric"
                  value={v.lost}
                  onChange={(e) => setV({ ...v, lost: e.target.value.replace(/\D/g, '') })}
                />
              </Field>
            </div>
            <Field label={t('qhse.description')}>
              <Textarea
                rows={2}
                value={v.desc}
                onChange={(e) => setV({ ...v, desc: e.target.value })}
              />
            </Field>
            <Button
              variant="primary"
              className="self-start"
              disabled={v.desc.trim().length < 5 || post.isPending}
              onClick={() =>
                post.mutate({
                  path: '/qhse/incidents',
                  body: {
                    project_id: v.project || null,
                    occurred_on: v.date,
                    category: v.cat,
                    description: v.desc,
                    lost_days: Number(v.lost || 0),
                  },
                })
              }
            >
              <Icon name="report" /> {t('qhse.report')}
            </Button>
          </CardContent>
        </Card>
      )}
      {list.data?.map((i) => (
        <Card key={i.id}>
          <CardHeader>
            <p className="eyebrow">
              {i.number} · {i.project_number ?? '–'} · {formatDate(i.occurred_on)}
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>{t(`qhse.incCat.${i.category}`)}</CardTitle>
              <StatusPill tone={i.status === 'closed' ? 'success' : 'warning'}>
                {t(`qhse.incStatus.${i.status}`)}
              </StatusPill>
            </div>
            <CardDescription>{i.description}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-small">
            {i.root_cause && (
              <p>
                {t('qhse.rootCause')}: {i.root_cause}
              </p>
            )}
            {i.status !== 'closed' && can('qhse', 'edit') && open !== i.id && (
              <Button
                variant="secondary"
                size="sm"
                className="self-start"
                onClick={() => {
                  setOpen(i.id);
                  setInv({ root: i.root_cause ?? '', text: i.investigation ?? '' });
                }}
              >
                {t('qhse.investigate')}
              </Button>
            )}
            {open === i.id && (
              <>
                <Field label={t('qhse.investigation')}>
                  <Textarea
                    rows={2}
                    value={inv.text}
                    onChange={(e) => setInv({ ...inv, text: e.target.value })}
                  />
                </Field>
                <Field label={t('qhse.rootCause')}>
                  <Input
                    value={inv.root}
                    onChange={(e) => setInv({ ...inv, root: e.target.value })}
                  />
                </Field>
                <CapaFields value={capa} onChange={setCapa} />
                <div className="flex gap-2">
                  {[false, true].map((close) => (
                    <Button
                      key={String(close)}
                      variant={close ? 'primary' : 'secondary'}
                      onClick={() =>
                        post.mutate(
                          {
                            path: `/qhse/incidents/${i.id}/investigation`,
                            body: {
                              root_cause: inv.root,
                              investigation: inv.text,
                              close,
                              capas: capaList(capa),
                            },
                          },
                          {
                            onSuccess: () => {
                              setOpen(null);
                              setCapa({ action: '', owner: '', due: '' });
                            },
                          },
                        )
                      }
                    >
                      {close ? t('qhse.saveClose') : t('dor.save')}
                    </Button>
                  ))}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- CAPA

function CapaTab() {
  const { t } = useTranslation();
  const list = useCapas();
  const post = useQhsePost();
  const [note, setNote] = useState<Record<string, string>>({});
  return (
    <Card className="overflow-x-auto">
      <FormError message={errText(post.error, t('auth.unexpected'))} />
      <Table>
        <THead>
          <TR>
            <TH>{t('crm.number')}</TH>
            <TH>{t('qhse.capaAction')}</TH>
            <TH>{t('qhse.owner')}</TH>
            <TH>{t('qhse.due')}</TH>
            <TH>{t('master.status')}</TH>
            <TH />
          </TR>
        </THead>
        <TBody>
          {list.data?.length === 0 && (
            <TR>
              <TD colSpan={6} className="py-6 text-center text-fg-secondary">
                {t('qhse.empty')}
              </TD>
            </TR>
          )}
          {list.data?.map((c) => (
            <TR key={c.id}>
              <TD className="whitespace-nowrap">
                <span className="font-semibold">{c.number}</span>
                <span className="block text-caption text-fg-muted">
                  {t(`qhse.source.${c.source_type}`)}
                </span>
              </TD>
              <TD className="max-w-md">{c.action}</TD>
              <TD>{c.owner_name}</TD>
              <TD className="whitespace-nowrap">
                {formatDate(c.due_date)}
                {c.overdue && (
                  <span className="ml-1 text-caption font-semibold text-danger">
                    {t('mnt.overdue')}
                  </span>
                )}
              </TD>
              <TD>
                <StatusPill
                  tone={
                    c.status === 'verified'
                      ? 'success'
                      : c.status === 'done'
                        ? 'info'
                        : c.overdue
                          ? 'danger'
                          : 'warning'
                  }
                >
                  {t(`qhse.capaStatus.${c.status}`)}
                </StatusPill>
              </TD>
              <TD className="min-w-56">
                {c.can_complete && (
                  <span className="flex gap-1">
                    <Input
                      aria-label={`${t('qhse.evidence')} ${c.number}`}
                      placeholder={t('qhse.evidence')}
                      value={note[c.id] ?? ''}
                      onChange={(e) => setNote({ ...note, [c.id]: e.target.value })}
                    />
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={(note[c.id] ?? '').trim().length < 5}
                      onClick={() =>
                        post.mutate({
                          path: `/qhse/capas/${c.id}/complete`,
                          body: { note: note[c.id] },
                        })
                      }
                    >
                      {t('qhse.done')}
                    </Button>
                  </span>
                )}
                {c.can_verify && (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => post.mutate({ path: `/qhse/capas/${c.id}/verify` })}
                  >
                    {t('qhse.verify')}
                  </Button>
                )}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </Card>
  );
}

// ---------------------------------------------------------------- statistics

function StatsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [from, setFrom] = useState(`${today().slice(0, 4)}-01-01`);
  const [to, setTo] = useState(today());
  const st = useStats(from, to);
  const d = st.data;
  const tile = (label: string, value: string | number | null) => (
    <div className="rounded-control border border-border px-3 py-2">
      <dt className="text-caption text-fg-muted">{label}</dt>
      <dd className="font-heading text-card-title tabular-nums text-fg">{value ?? '–'}</dd>
    </div>
  );
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('vi.from')} className="w-44">
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label={t('vi.to')} className="w-44">
          <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
        {can('qhse', 'export') && (
          <Button
            variant="secondary"
            onClick={() =>
              void downloadFile(`/qhse/csms-export?date_from=${from}&date_to=${to}`, 'csms.xlsx')
            }
          >
            <Icon name="download" /> {t('qhse.csmsExport')}
          </Button>
        )}
      </div>
      {d && (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {tile(t('qhse.stats.manhours'), d.manhours.replace('.', ','))}
          {tile('LTI', d.lti)}
          {tile(t('qhse.stats.recordable'), d.recordable)}
          {tile('TRIR', d.trir?.replace('.', ',') ?? null)}
          {tile('LTIFR', d.ltifr?.replace('.', ',') ?? null)}
          {tile(t('qhse.incCat.near_miss'), d.near_misses)}
          {tile(t('qhse.tabs.observations'), d.observations)}
          {tile(t('qhse.tabs.inspections'), d.inspections)}
          {tile(t('qhse.stats.capaOpen'), d.capa_open)}
          {tile(t('qhse.stats.capaOverdue'), d.capa_overdue)}
        </dl>
      )}
      <p className="text-caption text-fg-muted">{t('qhse.stats.formula')}</p>
    </>
  );
}
