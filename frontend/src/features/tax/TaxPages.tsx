import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, api, postJson } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

interface TaxReturn {
  id: string;
  year: number;
  month: number;
  tax_type: 'ppn' | 'pph21' | 'pph23';
  label: string;
  status: 'draft' | 'billed' | 'paid' | 'filed';
  output_tax: string;
  input_tax: string;
  carried_in: string;
  carry_forward: string;
  amount: string;
  pay_due: string;
  file_due: string;
  pay_overdue: boolean;
  file_overdue: boolean;
  due_soon: boolean;
  billing_code: string | null;
  ntpn: string | null;
  paid_on: string | null;
  payment_method: string | null;
  bpe_no: string | null;
  filed_on: string | null;
}

type Doc = Record<string, string | null>;
interface Workspace {
  returns: TaxReturn[];
  documents: Record<
    'output_fakturs' | 'input_fakturs' | 'pph23_withheld' | 'pph23_by_clients',
    Doc[]
  >;
}

interface Check {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
  blocking: boolean;
}
interface CloseStatus {
  year: number;
  month: number;
  status: string;
  checks: Check[];
  depreciation: {
    total: string;
    fiscal_total: string;
    lines: { asset: string; name: string; commercial: string; fiscal: string; account: string }[];
  } | null;
  history: { action: string; at: string; note: string | null }[];
}

const TONES: Record<string, StatusTone> = {
  draft: 'neutral',
  billed: 'info',
  paid: 'warning',
  filed: 'success',
  open: 'info',
  closed: 'success',
  future: 'neutral',
};

function useAction<R = unknown>(key: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown }) => postJson<R>(v.path, v.body ?? {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [key] }),
  });
}

function usePeriod(): [number, number, (y: number, m: number) => void] {
  const [params, setParams] = useSearchParams();
  const [ty = 2026, tm = 1] = today().split('-').map(Number);
  const prev = tm === 1 ? [ty - 1, 12] : [ty, tm - 1];
  const y = Number(params.get('year')) || prev[0]!;
  const m = Number(params.get('month')) || prev[1]!;
  return [y, m, (yy, mm) => setParams({ year: String(yy), month: String(mm) })];
}

function PeriodPicker({
  year,
  month,
  onChange,
}: {
  year: number;
  month: number;
  onChange: (y: number, m: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label={t('tax.year')} className="w-28">
        <Input
          type="number"
          value={year}
          onChange={(e) => onChange(Number(e.target.value), month)}
        />
      </Field>
      <Field label={t('tax.month')} className="w-28">
        <Select value={month} onChange={(e) => onChange(year, Number(e.target.value))}>
          {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
            <option key={n} value={n}>
              {String(n).padStart(2, '0')}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}

// ---------------------------------------------------------------- tax workspace

export function TaxPage() {
  const { t } = useTranslation();
  const [year, month, setPeriod] = usePeriod();
  const ws = useQuery({
    queryKey: ['tax', year, month],
    queryFn: () => api<Workspace>(`/tax/periods/${year}/${month}`),
  });
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('tax.title')}</CardTitle>
          <CardDescription>{t('tax.hint')}</CardDescription>
        </CardHeader>
        <CardContent>
          <PeriodPicker year={year} month={month} onChange={setPeriod} />
        </CardContent>
      </Card>
      <FormError message={errText(ws.error, t('auth.unexpected'))} />
      <div className="grid gap-4 lg:grid-cols-3">
        {ws.data?.returns.map((r) => (
          <ReturnCard key={r.id} r={r} />
        ))}
      </div>
      {ws.data && (
        <Card className="overflow-x-auto">
          <CardHeader>
            <CardTitle>{t('tax.documents')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {(
              ['output_fakturs', 'input_fakturs', 'pph23_withheld', 'pph23_by_clients'] as const
            ).map((k) => (
              <DocTable key={k} title={t(`tax.lists.${k}`)} rows={ws.data.documents[k]} />
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function DocTable({ title, rows }: { title: string; rows: Doc[] }) {
  const { t } = useTranslation();
  const cols = rows[0] ? Object.keys(rows[0]) : [];
  const money = new Set(['dpp', 'ppn', 'pph23']);
  return (
    <div>
      <h3 className="mb-2 font-heading text-body font-semibold">
        {title} ({rows.length})
      </h3>
      {rows.length === 0 ? (
        <p className="text-small text-fg-secondary">{t('tax.none')}</p>
      ) : (
        <Table>
          <THead>
            <TR>
              {cols.map((c) => (
                <TH key={c} className={money.has(c) ? 'text-right' : ''}>
                  {t(`tax.cols.${c}`)}
                </TH>
              ))}
            </TR>
          </THead>
          <TBody>
            {rows.map((row, i) => (
              <TR key={i}>
                {cols.map((c) => (
                  <TD key={c} className={money.has(c) ? 'text-right tabular-nums' : ''}>
                    {money.has(c)
                      ? formatIDR(row[c] ?? '0')
                      : c === 'date'
                        ? formatDate(row[c] ?? '')
                        : (row[c] ?? '-')}
                  </TD>
                ))}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}

function ReturnCard({ r }: { r: TaxReturn }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const act = useAction('tax');
  const [f, setF] = useState({
    billing: '',
    ntpn: '',
    paid_on: today(),
    method: 'direct',
    run: '',
    bpe: '',
  });
  const base = `/tax/returns/${r.id}`;
  const amount = Number(r.amount);
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>
          {r.label} {String(r.month).padStart(2, '0')}/{r.year}
        </CardTitle>
        <StatusPill tone={TONES[r.status]}>{t(`tax.status.${r.status}`)}</StatusPill>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {r.tax_type === 'ppn' && (
          <dl className="grid grid-cols-2 gap-1 text-small">
            <dt>{t('tax.output')}</dt>
            <dd className="text-right tabular-nums">{formatIDR(r.output_tax)}</dd>
            <dt>{t('tax.input')}</dt>
            <dd className="text-right tabular-nums">{formatIDR(r.input_tax)}</dd>
            <dt>{t('tax.carriedIn')}</dt>
            <dd className="text-right tabular-nums">{formatIDR(r.carried_in)}</dd>
            {Number(r.carry_forward) > 0 && (
              <>
                <dt>{t('tax.carryForward')}</dt>
                <dd className="text-right tabular-nums">{formatIDR(r.carry_forward)}</dd>
              </>
            )}
          </dl>
        )}
        <div className="text-h4 font-heading tabular-nums">{formatIDR(r.amount)}</div>
        <p className="text-small text-fg-secondary">
          {t('tax.due', { pay: formatDate(r.pay_due), file: formatDate(r.file_due) })}
        </p>
        {(r.pay_overdue || r.file_overdue) && (
          <StatusPill tone="danger">{t('tax.overdue')}</StatusPill>
        )}
        {!r.pay_overdue && !r.file_overdue && r.due_soon && (
          <StatusPill tone="warning">{t('tax.dueSoon')}</StatusPill>
        )}
        {r.billing_code && (
          <p className="text-small">
            {t('tax.billingCode')}: {r.billing_code}
          </p>
        )}
        {r.ntpn && (
          <p className="text-small">
            NTPN {r.ntpn} · {r.paid_on ? formatDate(r.paid_on) : ''}
          </p>
        )}
        {r.bpe_no && (
          <p className="text-small">
            BPE {r.bpe_no} · {r.filed_on ? formatDate(r.filed_on) : ''}
          </p>
        )}
        <FormError message={errText(act.error, t('auth.unexpected'))} />
        {r.status === 'draft' && amount > 0 && can('tax', 'edit') && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('tax.billingCode')} className="w-48">
              <Input
                inputMode="numeric"
                value={f.billing}
                onChange={(e) => setF({ ...f, billing: e.target.value })}
              />
            </Field>
            <Button
              variant="primary"
              onClick={() =>
                act.mutate({ path: `${base}/billing`, body: { billing_code: f.billing } })
              }
            >
              {t('tax.saveBilling')}
            </Button>
          </div>
        )}
        {r.status === 'billed' && can('tax', 'post') && (
          <div className="flex flex-col gap-2">
            <Field label="NTPN">
              <Input value={f.ntpn} onChange={(e) => setF({ ...f, ntpn: e.target.value })} />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Field label={t('tax.paidOn')} className="w-40">
                <Input
                  type="date"
                  value={f.paid_on}
                  onChange={(e) => setF({ ...f, paid_on: e.target.value })}
                />
              </Field>
              <Field label={t('tax.method')} className="w-44">
                <Select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
                  <option value="direct">{t('tax.methods.direct')}</option>
                  {r.tax_type !== 'ppn' && (
                    <option value="payment_run">{t('tax.methods.payment_run')}</option>
                  )}
                </Select>
              </Field>
            </div>
            {f.method === 'payment_run' && (
              <Field label={t('tax.paymentRunId')}>
                <Input value={f.run} onChange={(e) => setF({ ...f, run: e.target.value })} />
              </Field>
            )}
            <Button
              variant="primary"
              onClick={() =>
                act.mutate({
                  path: `${base}/pay`,
                  body: {
                    ntpn: f.ntpn,
                    paid_on: f.paid_on,
                    method: f.method,
                    payment_run_id: f.method === 'payment_run' ? f.run : null,
                  },
                })
              }
            >
              {t('tax.recordPayment')}
            </Button>
          </div>
        )}
        {(r.status === 'paid' || (r.status === 'draft' && amount === 0)) && can('tax', 'post') && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('tax.bpe')} className="w-48">
              <Input value={f.bpe} onChange={(e) => setF({ ...f, bpe: e.target.value })} />
            </Field>
            <Button
              variant="primary"
              onClick={() =>
                act.mutate({ path: `${base}/file`, body: { bpe_no: f.bpe, filed_on: today() } })
              }
            >
              {t('tax.file')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- period close

export function ClosePage() {
  const { t } = useTranslation();
  const { me, can } = useAuth();
  const [year, month, setPeriod] = usePeriod();
  const st = useQuery({
    queryKey: ['close', year, month],
    queryFn: () => api<CloseStatus>(`/close/periods/${year}/${month}`),
  });
  const act = useAction('close');
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');
  const roles = new Set(me?.roles.map((r) => r.code));
  const base = `/close/periods/${year}/${month}`;
  const d = st.data;
  const blocked = d?.checks.some((c) => c.blocking && !c.ok);
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>{t('close.title')}</CardTitle>
            <CardDescription>{t('close.hint')}</CardDescription>
          </div>
          {d && <StatusPill tone={TONES[d.status]}>{t(`close.status.${d.status}`)}</StatusPill>}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <PeriodPicker year={year} month={month} onChange={setPeriod} />
          <FormError message={errText(act.error ?? st.error, t('auth.unexpected'))} />
          {d && (
            <ul className="flex flex-col gap-2" aria-label={t('close.checklist')}>
              {d.checks.map((c) => (
                <li key={c.key} className="flex items-start gap-2">
                  <Icon
                    name={c.ok ? 'check_circle' : c.blocking ? 'block' : 'warning'}
                    className={c.ok ? 'text-success' : c.blocking ? 'text-danger' : 'text-warning'}
                  />
                  <div>
                    <div className="font-semibold">
                      {c.label}
                      {!c.ok && (
                        <StatusPill tone={c.blocking ? 'danger' : 'warning'} className="ml-2">
                          {c.blocking ? t('close.blocking') : t('close.warning')}
                        </StatusPill>
                      )}
                    </div>
                    <div className="text-small text-fg-secondary">{c.detail}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {d && d.status !== 'closed' && (
            <div className="flex flex-col gap-2">
              {!d.depreciation && can('finance', 'post') && (
                <div>
                  <Button onClick={() => act.mutate({ path: `${base}/depreciation` })}>
                    <Icon name="trending_down" /> {t('close.runDepreciation')}
                  </Button>
                </div>
              )}
              {roles.has('lead_controller') && (
                <>
                  <Field label={t('close.note')}>
                    <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
                  </Field>
                  <div>
                    <Button
                      variant="primary"
                      disabled={blocked}
                      onClick={() => act.mutate({ path: `${base}/close`, body: { note } })}
                    >
                      <Icon name="lock" /> {t('close.close')}
                    </Button>
                  </div>
                </>
              )}
            </div>
          )}
          {d?.status === 'closed' && roles.has('head_of_finance') && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('close.reason')} className="w-96">
                <Input value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
              <Button
                variant="destructive"
                disabled={reason.trim().length < 10}
                onClick={() => act.mutate({ path: `${base}/reopen`, body: { reason } })}
              >
                <Icon name="lock_open" /> {t('close.reopen')}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      {d?.depreciation && (
        <Card className="overflow-x-auto">
          <CardHeader>
            <CardTitle>{t('close.depreciation')}</CardTitle>
            <CardDescription>
              {t('close.depreciationTotals', {
                commercial: formatIDR(d.depreciation.total),
                fiscal: formatIDR(d.depreciation.fiscal_total),
              })}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <THead>
                <TR>
                  <TH>{t('close.asset')}</TH>
                  <TH>{t('close.account')}</TH>
                  <TH className="text-right">{t('close.commercial')}</TH>
                  <TH className="text-right">{t('close.fiscal')}</TH>
                </TR>
              </THead>
              <TBody>
                {d.depreciation.lines.map((x) => (
                  <TR key={x.asset}>
                    <TD>
                      {x.asset} · {x.name}
                    </TD>
                    <TD>{x.account}</TD>
                    <TD className="text-right tabular-nums">{formatIDR(x.commercial)}</TD>
                    <TD className="text-right tabular-nums">{formatIDR(x.fiscal)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      )}
      {d && d.history.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('close.history')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-1 text-small">
              {d.history.map((h, i) => (
                <li key={i}>
                  {formatDate(h.at.slice(0, 10))} · {t(`close.actions.${h.action}`)}
                  {h.note ? ` — ${h.note}` : ''}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
