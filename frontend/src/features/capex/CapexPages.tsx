import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { useAttachments } from '@/features/dms/api';
import { ApiError, api, postJson } from '@/lib/api';
import { formatIDR } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

type Case = Record<string, string | null>;
interface Proposal {
  id: string;
  number: string;
  title: string;
  status: string;
  status_label: string;
  amount: string;
  budget: string;
  priority_score: string;
  discount_rate: string;
  case: Case;
  rjpp_ref: string | null;
  asset_class: string;
  equipment_type_code: string | null;
  funding: string;
  day_rate: string;
  internal_day_rate: string;
  utilisation_pct: string;
  opex_pct: string;
  life_years: number;
  salvage_pct: string;
  rental_annual: string;
  lease_monthly: string;
  strategic_fit: number;
  risk: number;
  tax_group: string | null;
  reject_reason: string | null;
  asset_code: string | null;
  auc?: string;
  budget_status?: { budget: string; committed: string; actual: string; available: string };
  changes?: { id: string; number: string; amount: string; reason: string; status: string }[];
  reviews?: { months: number; actuals: Record<string, string | null>; comment: string }[];
}

const TONES: Record<string, StatusTone> = {
  draft: 'neutral',
  submitted: 'warning',
  awaiting_rups: 'warning',
  approved: 'info',
  in_execution: 'info',
  commissioned: 'info',
  capitalised: 'success',
  reviewed: 'success',
};

const EMPTY = {
  title: '',
  rjpp_ref: '',
  asset_class: '',
  equipment_type_code: '',
  amount: '',
  funding: 'equity',
  day_rate: '',
  internal_day_rate: '',
  utilisation_pct: '50',
  opex_pct: '5',
  life_years: '8',
  salvage_pct: '10',
  rental_annual: '',
  lease_monthly: '',
  strategic_fit: '3',
  risk: '3',
  tax_group: 'kelompok_2',
};
type Form = typeof EMPTY;

function toApi(f: Form) {
  return {
    ...f,
    rjpp_ref: f.rjpp_ref || null,
    equipment_type_code: f.equipment_type_code || null,
    amount: moneyToApi(f.amount),
    day_rate: moneyToApi(f.day_rate) || '0',
    internal_day_rate: moneyToApi(f.internal_day_rate) || '0',
    rental_annual: moneyToApi(f.rental_annual) || '0',
    lease_monthly: moneyToApi(f.lease_monthly) || '0',
    life_years: Number(f.life_years),
    strategic_fit: Number(f.strategic_fit),
    risk: Number(f.risk),
    tax_group: f.tax_group || null,
  };
}

function useCapexAction<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown; method?: string }) =>
      v.method
        ? api<R>(v.path, { method: v.method, body: JSON.stringify(v.body) })
        : postJson<R>(v.path, v.body ?? {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['capex'] });
      void qc.invalidateQueries({ queryKey: ['attachments'] });
    },
  });
}

export function CapexListPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useQuery({ queryKey: ['capex', 'list'], queryFn: () => api<Proposal[]>('/capex') });
  return (
    <Card className="overflow-x-auto">
      <CardHeader className="flex-row items-center justify-between gap-2">
        <div>
          <CardTitle>{t('capex.title')}</CardTitle>
          <CardDescription>{t('capex.hint')}</CardDescription>
        </div>
        {can('capex', 'create') && (
          <Link to="/capex/baru" className="inline-flex">
            <Button variant="primary">
              <Icon name="add" /> {t('capex.new')}
            </Button>
          </Link>
        )}
      </CardHeader>
      <CardContent>
        <FormError message={errText(list.error, t('auth.unexpected'))} />
        <Table>
          <THead>
            <TR>
              <TH>{t('capex.number')}</TH>
              <TH>{t('capex.titleLabel')}</TH>
              <TH className="text-right">{t('capex.amount')}</TH>
              <TH className="text-right">NPV</TH>
              <TH className="text-right">IRR</TH>
              <TH className="text-right">{t('capex.score')}</TH>
              <TH>{t('capex.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.map((p) => (
              <TR key={p.id}>
                <TD>
                  <Link className="text-fg-accent underline" to={`/capex/${p.id}`}>
                    {p.number}
                  </Link>
                </TD>
                <TD>{p.title}</TD>
                <TD className="text-right tabular-nums">{formatIDR(p.amount)}</TD>
                <TD className="text-right tabular-nums">{formatIDR(p.case.npv ?? '0')}</TD>
                <TD className="text-right">{p.case.irr ? `${p.case.irr}%` : '-'}</TD>
                <TD className="text-right">{p.priority_score}</TD>
                <TD>
                  <StatusPill tone={TONES[p.status] ?? 'neutral'}>{p.status_label}</StatusPill>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        {list.data?.length === 0 && (
          <p className="text-small text-fg-secondary">{t('capex.empty')}</p>
        )}
      </CardContent>
    </Card>
  );
}

function CaseView({ c, rate }: { c: Case; rate?: string }) {
  const { t } = useTranslation();
  const rows: [string, string][] = [
    ['revenue_annual', formatIDR(c.revenue_annual ?? '0')],
    ['opex_annual', formatIDR(c.opex_annual ?? '0')],
    ['cash_flow_annual', formatIDR(c.cash_flow_annual ?? '0')],
    ['npv', formatIDR(c.npv ?? '0')],
    ['irr', c.irr ? `${c.irr}%` : '-'],
    ['payback_years', c.payback_years ? `${c.payback_years} ${t('capex.years')}` : '-'],
    ['pv_buy', formatIDR(c.pv_buy ?? '0')],
    ['pv_rent', formatIDR(c.pv_rent ?? '0')],
    ['pv_lease', c.pv_lease ? formatIDR(c.pv_lease) : '-'],
    ['best_option', t(`capex.options.${c.best_option ?? 'buy'}`)],
    ['priority_score', c.priority_score ?? '-'],
  ];
  return (
    <div className="rounded-md border border-border p-3">
      <h3 className="mb-2 font-heading text-body font-semibold">
        {t('capex.case')}
        {rate ? ` · NPV @ ${rate}%` : ''}
      </h3>
      <dl className="grid grid-cols-2 gap-1 text-small">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt>{t(`capex.caseRows.${k}`)}</dt>
            <dd className="text-right tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function CapexFormPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [f, setF] = useState<Form>(EMPTY);
  const settings = useQuery({
    queryKey: ['capex', 'settings'],
    queryFn: () => api<{ discount_rate: string; rental_spend_12m: string }>('/capex/settings'),
  });
  const preview = useCapexAction<Case>();
  const save = useCapexAction<Proposal>();
  const ready = Number(moneyToApi(f.amount)) > 0 && f.title.trim().length >= 3 && f.asset_class;
  useEffect(() => {
    if (!ready) return;
    const id = setTimeout(() => preview.mutate({ path: '/capex/calculate', body: toApi(f) }), 400);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(f)]);
  const field = (k: keyof Form, label: string, props: Record<string, unknown> = {}) => (
    <Field label={label} className="w-52">
      <Input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} {...props} />
    </Field>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>{t('capex.new')}</CardTitle>
          <CardDescription>
            {t('capex.formHint', {
              spend: formatIDR(settings.data?.rental_spend_12m ?? '0'),
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label={t('capex.titleLabel')} required>
            <Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          </Field>
          <div className="flex flex-wrap gap-2">
            {field('rjpp_ref', t('capex.rjpp'))}
            {field('asset_class', t('capex.assetClass'))}
            {field('equipment_type_code', t('capex.equipmentType'))}
            <Field label={t('capex.funding')} className="w-52">
              <Select value={f.funding} onChange={(e) => setF({ ...f, funding: e.target.value })}>
                {['equity', 'loan', 'lease', 'mixed'].map((x) => (
                  <option key={x} value={x}>
                    {t(`capex.fundings.${x}`)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex flex-wrap gap-2">
            {field('amount', t('capex.amount'), { inputMode: 'numeric' })}
            {field('day_rate', t('capex.dayRate'), { inputMode: 'numeric' })}
            {field('internal_day_rate', t('capex.internalRate'), { inputMode: 'numeric' })}
            {field('utilisation_pct', t('capex.utilisation'), { inputMode: 'decimal' })}
            {field('opex_pct', t('capex.opex'), { inputMode: 'decimal' })}
            {field('life_years', t('capex.life'), { inputMode: 'numeric' })}
            {field('salvage_pct', t('capex.salvage'), { inputMode: 'decimal' })}
            {field('rental_annual', t('capex.rental'), { inputMode: 'numeric' })}
            {field('lease_monthly', t('capex.lease'), { inputMode: 'numeric' })}
            {field('strategic_fit', t('capex.strategic'), { type: 'number', min: 1, max: 5 })}
            {field('risk', t('capex.risk'), { type: 'number', min: 1, max: 5 })}
            <Field label={t('capex.taxGroup')} className="w-52">
              <Select
                value={f.tax_group}
                onChange={(e) => setF({ ...f, tax_group: e.target.value })}
              >
                {['kelompok_1', 'kelompok_2', 'kelompok_3', 'kelompok_4'].map((x) => (
                  <option key={x} value={x}>
                    {t(`capex.taxGroups.${x}`)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <FormError message={errText(save.error, t('auth.unexpected'))} />
          <div>
            <Button
              variant="primary"
              disabled={!ready || save.isPending}
              onClick={() =>
                save.mutate(
                  { path: '/capex', body: toApi(f) },
                  { onSuccess: (p) => navigate(`/capex/${p.id}`) },
                )
              }
            >
              {t('capex.save')}
            </Button>
          </div>
        </CardContent>
      </Card>
      <div>
        {preview.data ? (
          <CaseView c={preview.data} rate={settings.data?.discount_rate} />
        ) : (
          <p className="text-small text-fg-secondary">{t('capex.previewHint')}</p>
        )}
      </div>
    </div>
  );
}

export function CapexDetailPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { id = '' } = useParams();
  const q = useQuery({ queryKey: ['capex', id], queryFn: () => api<Proposal>(`/capex/${id}`) });
  const act = useCapexAction();
  const files = useAttachments('capex', id);
  const [ms, setMs] = useState({ amount: '', description: '', vendor_code: '' });
  const [ch, setCh] = useState({ amount: '', reason: '' });
  const [com, setCom] = useState({ attachment_id: '', asset_code: '' });
  const [rev, setRev] = useState({ months: '6', comment: '' });
  const p = q.data;
  if (!p) return <FormError message={errText(q.error, t('auth.unexpected'))} />;
  const base = `/capex/${p.id}`;
  const executing = ['approved', 'in_execution'].includes(p.status);
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>
              {p.number} · {p.title}
            </CardTitle>
            <CardDescription>
              {p.asset_class} · {p.rjpp_ref ?? '-'} · {t(`capex.fundings.${p.funding}`)}
            </CardDescription>
          </div>
          <StatusPill tone={TONES[p.status] ?? 'neutral'}>{p.status_label}</StatusPill>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          <div className="flex flex-col gap-2">
            <p>
              {t('capex.amount')}: <strong>{formatIDR(p.amount)}</strong> · {t('capex.budget')}:{' '}
              <strong>{formatIDR(p.budget)}</strong>
            </p>
            {p.budget_status && (
              <p className="text-small">
                {t('capex.budgetStatus', {
                  actual: formatIDR(p.budget_status.actual),
                  committed: formatIDR(p.budget_status.committed),
                  available: formatIDR(p.budget_status.available),
                })}
              </p>
            )}
            {p.auc !== undefined && (
              <p className="text-small">
                AUC (1520): {formatIDR(p.auc)}
                {p.asset_code ? ` · ${t('capex.asset')} ${p.asset_code}` : ''}
              </p>
            )}
            {p.reject_reason && (
              <p role="alert" className="text-small text-danger">
                {p.reject_reason}
              </p>
            )}
            <FormError message={errText(act.error, t('auth.unexpected'))} />
            {p.status === 'draft' && can('capex', 'submit') && (
              <div>
                <Button variant="primary" onClick={() => act.mutate({ path: `${base}/submit` })}>
                  {t('capex.submit')}
                </Button>
              </div>
            )}
          </div>
          <CaseView c={p.case} rate={p.discount_rate} />
        </CardContent>
      </Card>

      {executing && can('capex', 'post') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('capex.milestone')}</CardTitle>
            <CardDescription>{t('capex.milestoneHint')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-end gap-2">
            <Field label={t('capex.amount')} className="w-44">
              <Input
                inputMode="numeric"
                value={ms.amount}
                onChange={(e) => setMs({ ...ms, amount: e.target.value })}
              />
            </Field>
            <Field label={t('capex.description')} className="w-64">
              <Input
                value={ms.description}
                onChange={(e) => setMs({ ...ms, description: e.target.value })}
              />
            </Field>
            <Field label={t('capex.vendor')} className="w-36">
              <Input
                value={ms.vendor_code}
                onChange={(e) => setMs({ ...ms, vendor_code: e.target.value })}
              />
            </Field>
            <Button
              variant="primary"
              onClick={() =>
                act.mutate({
                  path: `${base}/milestones`,
                  body: { ...ms, amount: moneyToApi(ms.amount), pay: 'payable' },
                })
              }
            >
              {t('capex.post')}
            </Button>
          </CardContent>
        </Card>
      )}

      {executing && can('capex', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('capex.change')}</CardTitle>
            <CardDescription>{t('capex.changeHint')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('capex.increase')} className="w-44">
                <Input
                  inputMode="numeric"
                  value={ch.amount}
                  onChange={(e) => setCh({ ...ch, amount: e.target.value })}
                />
              </Field>
              <Field label={t('capex.reason')} className="w-96">
                <Input
                  value={ch.reason}
                  onChange={(e) => setCh({ ...ch, reason: e.target.value })}
                />
              </Field>
              <Button
                onClick={() =>
                  act.mutate({
                    path: `${base}/changes`,
                    body: { amount: moneyToApi(ch.amount), reason: ch.reason },
                  })
                }
              >
                {t('capex.requestChange')}
              </Button>
            </div>
            {p.changes?.map((c) => (
              <p key={c.id} className="text-small">
                {c.number} · {formatIDR(c.amount)} · {t(`capex.changeStatus.${c.status}`)} —{' '}
                {c.reason}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      {['approved', 'in_execution', 'commissioned', 'capitalised', 'reviewed'].includes(
        p.status,
      ) && (
        <Card>
          <CardHeader>
            <CardTitle>{t('capex.commissioning')}</CardTitle>
            <CardDescription>{t('capex.commissioningHint')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <AttachmentsPanel entityType="capex" entityId={p.id} canWrite={can('capex', 'edit')} />
            {executing && can('capex', 'edit') && (
              <div className="flex flex-wrap items-end gap-2">
                <Field label="BAST" className="w-56">
                  <Select
                    value={com.attachment_id}
                    onChange={(e) => setCom({ ...com, attachment_id: e.target.value })}
                  >
                    <option value="">-</option>
                    {files.data?.map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.filename}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label={t('capex.assetCode')} className="w-44">
                  <Input
                    value={com.asset_code}
                    onChange={(e) => setCom({ ...com, asset_code: e.target.value })}
                  />
                </Field>
                <Button onClick={() => act.mutate({ path: `${base}/commission`, body: com })}>
                  {t('capex.commission')}
                </Button>
              </div>
            )}
            {p.status === 'commissioned' && can('capex', 'post') && (
              <div>
                <Button
                  variant="primary"
                  onClick={() => act.mutate({ path: `${base}/capitalise` })}
                >
                  <Icon name="inventory" /> {t('capex.capitalise')}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {['capitalised', 'reviewed'].includes(p.status) && (
        <Card>
          <CardHeader>
            <CardTitle>{t('capex.review')}</CardTitle>
            <CardDescription>{t('capex.reviewHint')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {p.reviews?.map((r) => (
              <div key={r.months} className="rounded-md border border-border p-3 text-small">
                <strong>{t('capex.reviewMonths', { months: r.months })}</strong>:{' '}
                {t('capex.reviewLine', {
                  util: r.actuals.utilisation_pct,
                  caseUtil: r.actuals.case_utilisation_pct,
                  revenue: formatIDR(r.actuals.revenue_annualised ?? '0'),
                  payback: r.actuals.payback_years ?? '-',
                  casePayback: r.actuals.case_payback_years ?? '-',
                })}
                <p>{r.comment}</p>
              </div>
            ))}
            {can('capex', 'edit') && (
              <div className="flex flex-wrap items-end gap-2">
                <Field label={t('capex.reviewAt')} className="w-32">
                  <Select
                    value={rev.months}
                    onChange={(e) => setRev({ ...rev, months: e.target.value })}
                  >
                    <option value="6">6</option>
                    <option value="12">12</option>
                  </Select>
                </Field>
                <Field label={t('capex.conclusion')} className="w-96">
                  <Textarea
                    value={rev.comment}
                    onChange={(e) => setRev({ ...rev, comment: e.target.value })}
                  />
                </Field>
                <Button
                  onClick={() =>
                    act.mutate({
                      path: `${base}/reviews`,
                      body: { months: Number(rev.months), comment: rev.comment },
                    })
                  }
                >
                  {t('capex.saveReview')}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
