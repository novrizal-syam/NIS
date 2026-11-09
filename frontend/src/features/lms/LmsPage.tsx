import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { moneyToApi } from '@/features/crm/api';
import { ApiError, api, downloadFile, postJson } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

interface Course {
  code: string;
  title: string;
  kind: string;
  validity_months: number | null;
  certificate_name: string | null;
  cost: string;
  pass_score: number;
  questions: { q: string; options: string[] }[];
}
interface Task {
  id: string;
  kind: 'course' | 'acknowledge';
  reason: string;
  course: Course | null;
  document: {
    code: string;
    revision: number;
    title: string;
    document_id: string;
    revision_id: string;
  } | null;
  due_date: string | null;
  overdue: boolean;
  status: string;
  score: number | null;
}
interface ComplianceRow {
  employee_code: string;
  name: string;
  position_code: string | null;
  department: string | null;
  mobilisation_blocked: string | null;
  compliance_pct: number;
  items: { kind: string; name: string; status: string; valid_until: string | null }[];
}

const TONES: Record<string, StatusTone> = {
  valid: 'success',
  expiring: 'warning',
  expired: 'danger',
  missing: 'danger',
};

function useLmsAction<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown; method?: string }) =>
      v.method
        ? api<R>(v.path, { method: v.method, body: JSON.stringify(v.body) })
        : postJson<R>(v.path, v.body ?? {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['lms'] }),
  });
}

export function LmsPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const manager = me?.permissions.lms?.edit === 'all';
  const [params, setParams] = useSearchParams();
  const tabs = manager ? ['my', 'catalogue', 'matrix', 'compliance'] : ['my'];
  const tab = tabs.includes(params.get('tab') ?? '') ? (params.get('tab') as string) : 'my';
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('lms.title')}
        value={tab}
        onChange={(v) => setParams({ tab: v })}
        items={tabs.map((v) => ({ value: v, label: t(`lms.tabs.${v}`) }))}
      />
      {tab === 'my' && <MyTraining />}
      {tab === 'catalogue' && <Catalogue />}
      {tab === 'matrix' && <Matrix />}
      {tab === 'compliance' && <Compliance />}
    </div>
  );
}

function MyTraining() {
  const { t } = useTranslation();
  const tasks = useQuery({ queryKey: ['lms', 'my'], queryFn: () => api<Task[]>('/lms/my') });
  const act = useLmsAction<{ passed?: boolean; score?: number }>();
  const [answers, setAnswers] = useState<Record<string, number[]>>({});
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('lms.tabs.my')}</CardTitle>
        <CardDescription>{t('lms.myHint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(act.error ?? tasks.error, t('auth.unexpected'))} />
        {act.data?.score !== undefined && (
          <p role="status" className="text-small">
            {t(act.data.passed ? 'lms.passed' : 'lms.failed', { score: act.data.score })}
          </p>
        )}
        {tasks.data?.length === 0 && (
          <p className="text-small text-fg-secondary">{t('lms.nothing')}</p>
        )}
        {tasks.data?.map((a) => (
          <div key={a.id} className="rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-semibold">
                {a.document
                  ? `${a.document.code} Rev.${a.document.revision} · ${a.document.title}`
                  : `${a.course?.code} · ${a.course?.title}`}
              </div>
              <div className="flex gap-1">
                <StatusPill tone="info">{t(`lms.reasons.${a.reason}`)}</StatusPill>
                {a.overdue && <StatusPill tone="danger">{t('lms.overdue')}</StatusPill>}
              </div>
            </div>
            {a.due_date && (
              <p className="text-small text-fg-secondary">
                {t('lms.due')}: {formatDate(a.due_date)}
              </p>
            )}
            {a.kind === 'acknowledge' && a.document && (
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  onClick={() =>
                    void downloadFile(
                      `/dms/controlled/${a.document!.document_id}/revisions/${a.document!.revision_id}/pdf`,
                      `${a.document!.code}.pdf`,
                    )
                  }
                >
                  <Icon name="picture_as_pdf" /> {t('lms.read')}
                </Button>
                <Button
                  variant="primary"
                  onClick={() => act.mutate({ path: `/lms/assignments/${a.id}/acknowledge` })}
                >
                  {t('lms.acknowledge')}
                </Button>
              </div>
            )}
            {a.course?.kind === 'quiz' && (
              <div className="mt-2 flex flex-col gap-2">
                {a.course.questions.map((q, i) => (
                  <fieldset key={i} className="text-small">
                    <legend className="font-semibold">
                      {i + 1}. {q.q}
                    </legend>
                    {q.options.map((o, j) => (
                      <label key={j} className="mr-4 inline-flex items-center gap-1">
                        <input
                          type="radio"
                          name={`${a.id}-${i}`}
                          checked={answers[a.id]?.[i] === j}
                          onChange={() => {
                            const cur = [...(answers[a.id] ?? [])];
                            cur[i] = j;
                            setAnswers({ ...answers, [a.id]: cur });
                          }}
                        />
                        {o}
                      </label>
                    ))}
                  </fieldset>
                ))}
                <div>
                  <Button
                    variant="primary"
                    onClick={() =>
                      act.mutate({
                        path: `/lms/assignments/${a.id}/quiz`,
                        body: { answers: answers[a.id] ?? [] },
                      })
                    }
                  >
                    {t('lms.submitQuiz')}
                  </Button>
                </div>
              </div>
            )}
            {a.course && ['video', 'pdf', 'scorm'].includes(a.course.kind) && (
              <div className="mt-2">
                <Button onClick={() => act.mutate({ path: `/lms/assignments/${a.id}/complete` })}>
                  {t('lms.markDone')}
                </Button>
              </div>
            )}
            {a.course && ['classroom', 'practical'].includes(a.course.kind) && (
              <p className="mt-2 text-small text-fg-secondary">{t('lms.classroomHint')}</p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Catalogue() {
  const { t } = useTranslation();
  const list = useQuery({
    queryKey: ['lms', 'courses'],
    queryFn: () => api<Course[]>('/lms/courses'),
  });
  const act = useLmsAction();
  const [f, setF] = useState({
    code: '',
    title: '',
    kind: 'classroom',
    validity_months: '',
    certificate_name: '',
    cost: '',
  });
  const [s, setS] = useState({ course_code: '', starts_on: today(), location: '' });
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('lms.tabs.catalogue')}</CardTitle>
          <CardDescription>{t('lms.catalogueHint')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('lms.code')} className="w-36">
              <Input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
            </Field>
            <Field label={t('lms.courseTitle')} className="w-64">
              <Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
            </Field>
            <Field label={t('lms.kind')} className="w-40">
              <Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                {['video', 'pdf', 'quiz', 'scorm', 'classroom', 'practical'].map((k) => (
                  <option key={k} value={k}>
                    {t(`lms.kinds.${k}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('lms.validity')} className="w-32">
              <Input
                inputMode="numeric"
                value={f.validity_months}
                onChange={(e) => setF({ ...f, validity_months: e.target.value })}
              />
            </Field>
            <Field label={t('lms.certificate')} className="w-40">
              <Input
                value={f.certificate_name}
                onChange={(e) => setF({ ...f, certificate_name: e.target.value })}
              />
            </Field>
            <Field label={t('lms.cost')} className="w-36">
              <Input
                inputMode="numeric"
                value={f.cost}
                onChange={(e) => setF({ ...f, cost: e.target.value })}
              />
            </Field>
            <Button
              variant="primary"
              disabled={!f.code || !f.title}
              onClick={() =>
                act.mutate({
                  path: `/lms/courses/${encodeURIComponent(f.code)}`,
                  method: 'PUT',
                  body: {
                    ...f,
                    validity_months: f.validity_months ? Number(f.validity_months) : null,
                    certificate_name: f.certificate_name || null,
                    cost: moneyToApi(f.cost) || '0',
                  },
                })
              }
            >
              {t('lms.save')}
            </Button>
          </div>
          <FormError message={errText(act.error ?? list.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('lms.code')}</TH>
                <TH>{t('lms.courseTitle')}</TH>
                <TH>{t('lms.kind')}</TH>
                <TH>{t('lms.validity')}</TH>
                <TH>{t('lms.certificate')}</TH>
                <TH className="text-right">{t('lms.cost')}</TH>
              </TR>
            </THead>
            <TBody>
              {list.data?.map((c) => (
                <TR key={c.code}>
                  <TD>{c.code}</TD>
                  <TD>{c.title}</TD>
                  <TD>{t(`lms.kinds.${c.kind}`)}</TD>
                  <TD>{c.validity_months ?? '-'}</TD>
                  <TD>{c.certificate_name ?? '-'}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(c.cost)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t('lms.sessions')}</CardTitle>
          <CardDescription>{t('lms.sessionsHint')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-2">
          <Field label={t('lms.course')} className="w-56">
            <Select
              value={s.course_code}
              onChange={(e) => setS({ ...s, course_code: e.target.value })}
            >
              <option value="">-</option>
              {list.data
                ?.filter((c) => ['classroom', 'practical'].includes(c.kind))
                .map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.title}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label={t('lms.date')} className="w-40">
            <Input
              type="date"
              value={s.starts_on}
              onChange={(e) => setS({ ...s, starts_on: e.target.value })}
            />
          </Field>
          <Field label={t('lms.location')} className="w-56">
            <Input value={s.location} onChange={(e) => setS({ ...s, location: e.target.value })} />
          </Field>
          <Button
            disabled={!s.course_code}
            onClick={() =>
              act.mutate({ path: '/lms/sessions', body: { ...s, location: s.location || null } })
            }
          >
            {t('lms.schedule')}
          </Button>
        </CardContent>
      </Card>
    </>
  );
}

function Matrix() {
  const { t } = useTranslation();
  const positions = useQuery({
    queryKey: ['lms', 'positions'],
    queryFn: () =>
      api<
        {
          code: string;
          name: string;
          requirements: { course_code: string; mandatory: boolean }[];
        }[]
      >('/lms/positions'),
  });
  const courses = useQuery({
    queryKey: ['lms', 'courses'],
    queryFn: () => api<Course[]>('/lms/courses'),
  });
  const act = useLmsAction();
  const [p, setP] = useState({ code: '', name: '' });
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <CardTitle>{t('lms.tabs.matrix')}</CardTitle>
        <CardDescription>{t('lms.matrixHint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('lms.positionCode')} className="w-36">
            <Input value={p.code} onChange={(e) => setP({ ...p, code: e.target.value })} />
          </Field>
          <Field label={t('lms.positionName')} className="w-64">
            <Input value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} />
          </Field>
          <Button
            disabled={!p.code || !p.name}
            onClick={() =>
              act.mutate({
                path: `/lms/positions/${encodeURIComponent(p.code)}`,
                method: 'PUT',
                body: p,
              })
            }
          >
            {t('lms.addPosition')}
          </Button>
        </div>
        <FormError message={errText(act.error ?? positions.error, t('auth.unexpected'))} />
        <Table>
          <THead>
            <TR>
              <TH>{t('lms.positionName')}</TH>
              {courses.data?.map((c) => (
                <TH key={c.code} className="text-center">
                  {c.code}
                </TH>
              ))}
            </TR>
          </THead>
          <TBody>
            {positions.data?.map((pos) => (
              <TR key={pos.code}>
                <TD>
                  {pos.code} · {pos.name}
                </TD>
                {courses.data?.map((c) => {
                  const has = pos.requirements.some((r) => r.course_code === c.code);
                  return (
                    <TD key={c.code} className="text-center">
                      <input
                        type="checkbox"
                        aria-label={`${pos.code} ${c.code}`}
                        checked={has}
                        onChange={() => {
                          const next = has
                            ? pos.requirements.filter((r) => r.course_code !== c.code)
                            : [...pos.requirements, { course_code: c.code, mandatory: true }];
                          act.mutate({
                            path: `/lms/positions/${pos.code}/requirements`,
                            method: 'PUT',
                            body: { requirements: next },
                          });
                        }}
                      />
                    </TD>
                  );
                })}
              </TR>
            ))}
          </TBody>
        </Table>
        <div>
          <Button onClick={() => act.mutate({ path: '/lms/run' })}>
            <Icon name="playlist_add_check" /> {t('lms.runAuto')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RenewCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState({ employee_code: '', name: '', number: '', expiry_date: '' });
  const [file, setFile] = useState<File | null>(null);
  const renew = useMutation({
    mutationFn: () => {
      const form = new FormData();
      Object.entries(f).forEach(([k, v]) => v && form.append(k, v));
      if (file) form.append('file', file);
      return api('/lms/certificates/renew-upload', { method: 'POST', body: form });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['lms'] }),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('lms.renew')}</CardTitle>
        <CardDescription>{t('lms.renewHint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-end gap-2">
        <Field label={t('lms.employeeCode')} className="w-32">
          <Input
            value={f.employee_code}
            onChange={(e) => setF({ ...f, employee_code: e.target.value })}
          />
        </Field>
        <Field label={t('lms.certificate')} className="w-40">
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label={t('lms.certNumber')} className="w-40">
          <Input value={f.number} onChange={(e) => setF({ ...f, number: e.target.value })} />
        </Field>
        <Field label={t('lms.validUntil')} className="w-40">
          <Input
            type="date"
            value={f.expiry_date}
            onChange={(e) => setF({ ...f, expiry_date: e.target.value })}
          />
        </Field>
        <Field label={t('lms.scan')} className="w-64">
          <Input
            type="file"
            accept=".pdf,.jpg,.jpeg,.png"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
        <Button
          variant="primary"
          disabled={!f.employee_code || !f.name || !f.expiry_date || !file || renew.isPending}
          onClick={() => renew.mutate()}
        >
          {t('lms.renewBtn')}
        </Button>
        {renew.isSuccess && (
          <p role="status" className="text-small">
            {t('lms.renewed')}
          </p>
        )}
        <FormError message={errText(renew.error, t('auth.unexpected'))} />
      </CardContent>
    </Card>
  );
}

function Compliance() {
  const { t } = useTranslation();
  const rows = useQuery({
    queryKey: ['lms', 'compliance'],
    queryFn: () => api<ComplianceRow[]>('/lms/compliance'),
  });
  const year = Number(today().slice(0, 4));
  const budget = useQuery({
    queryKey: ['lms', 'budget', year],
    queryFn: () =>
      api<
        {
          department: string;
          budget: string;
          spent: string;
          remaining: string;
          used_pct: number | null;
        }[]
      >(`/lms/budget/${year}`),
  });
  return (
    <>
      <RenewCard />
      <Card className="overflow-x-auto">
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>{t('lms.tabs.compliance')}</CardTitle>
            <CardDescription>{t('lms.complianceHint')}</CardDescription>
          </div>
          <Button onClick={() => void downloadFile('/lms/evidence-pack', 'csms-iso-evidence.xlsx')}>
            <Icon name="download" /> {t('lms.evidencePack')}
          </Button>
        </CardHeader>
        <CardContent>
          <FormError message={errText(rows.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('lms.employee')}</TH>
                <TH className="text-right">%</TH>
                <TH>{t('lms.items')}</TH>
                <TH>{t('lms.mobilisation')}</TH>
              </TR>
            </THead>
            <TBody>
              {rows.data?.map((r) => (
                <TR key={r.employee_code}>
                  <TD>
                    {r.name}
                    <div className="text-small text-fg-secondary">
                      {r.employee_code} · {r.position_code ?? '-'}
                    </div>
                  </TD>
                  <TD className="text-right">{r.compliance_pct}</TD>
                  <TD className="flex flex-wrap gap-1">
                    {r.items.map((i, k) => (
                      <StatusPill key={k} tone={TONES[i.status] ?? 'neutral'}>
                        {i.name}
                        {i.valid_until ? ` · ${formatDate(i.valid_until)}` : ''}
                      </StatusPill>
                    ))}
                  </TD>
                  <TD>
                    {r.mobilisation_blocked ? (
                      <StatusPill tone="danger">{t('lms.blocked')}</StatusPill>
                    ) : (
                      '-'
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('lms.budget', { year })}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <THead>
              <TR>
                <TH>{t('lms.department')}</TH>
                <TH className="text-right">{t('lms.budgetAmount')}</TH>
                <TH className="text-right">{t('lms.spent')}</TH>
                <TH className="text-right">{t('lms.remaining')}</TH>
              </TR>
            </THead>
            <TBody>
              {budget.data?.map((b) => (
                <TR key={b.department}>
                  <TD>{b.department}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(b.budget)}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(b.spent)}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(b.remaining)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
