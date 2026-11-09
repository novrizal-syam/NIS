import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { moneyToApi } from '@/features/crm/api';
import { qs } from '@/features/inventory/api';
import { ApiError, api, downloadFile, postJson } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

interface ReportData {
  title: string;
  columns: { header: string; key: string; kind: string }[];
  rows: Record<string, string | null>[];
  summary: Record<string, string | null>;
}
interface Account {
  code: string;
  name: string;
  type: string;
  postable: boolean;
}

const REPORTS = [
  'trial-balance',
  'general-ledger',
  'profit-loss',
  'profit-loss-projects',
  'balance-sheet',
  'cash-flow',
  'dimensions',
  'project-pnl',
] as const;
type ReportName = (typeof REPORTS)[number];
const TABS = ['reports', 'journals', 'manual', 'opening', 'rules'] as const;
type Tab = (typeof TABS)[number];

const useAccounts = () =>
  useQuery({
    queryKey: ['ledger', 'accounts'],
    queryFn: () => api<Account[]>('/ledger/accounts'),
    staleTime: 300_000,
  });

function useLedgerPost<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown; method?: string }) =>
      v.method
        ? api<R>(v.path, { method: v.method, body: JSON.stringify(v.body) })
        : postJson<R>(v.path, v.body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['ledger'] }),
  });
}

export function LedgerPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('reports');
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('nav.items.ledger')}
        value={tab}
        onChange={setTab}
        items={TABS.map((v) => ({ value: v, label: t(`ledger.tabs.${v}`) }))}
      />
      {tab === 'reports' && <ReportsTab />}
      {tab === 'journals' && <JournalsTab />}
      {tab === 'manual' && <ManualTab />}
      {tab === 'opening' && <OpeningTab />}
      {tab === 'rules' && <RulesTab />}
    </div>
  );
}

// ---------------------------------------------------------------- reports

function cellValue(v: string | null | undefined, kind: string): string {
  if (v == null || v === '') return '';
  if (kind === 'idr') return formatIDR(v);
  if (kind === 'date') return formatDate(v);
  if (kind === 'number') return v.replace('.', ',');
  return v;
}

function ReportsTab() {
  const { t } = useTranslation();
  const accounts = useAccounts();
  const [name, setName] = useState<ReportName>('trial-balance');
  const [p, setP] = useState({
    as_of: today(),
    date_from: `${today().slice(0, 8)}01`,
    date_to: today(),
    account: '1110',
    dimension: 'project',
  });
  const params: Record<string, string> = {};
  if (['trial-balance', 'balance-sheet'].includes(name)) params.as_of = p.as_of;
  else if (name !== 'project-pnl') {
    params.date_from = p.date_from;
    params.date_to = p.date_to;
  }
  if (name === 'general-ledger') params.account = p.account;
  if (name === 'dimensions') params.dimension = p.dimension;
  const report = useQuery({
    queryKey: ['ledger', 'report', name, params],
    queryFn: () => api<ReportData>(`/ledger/reports/${name}?${qs(params)}`),
  });
  const d = report.data;
  const exportAs = (format: 'xlsx' | 'pdf') =>
    void downloadFile(`/ledger/reports/${name}?${qs({ ...params, format })}`, `${name}.${format}`);
  return (
    <>
      <Card>
        <CardContent className="flex flex-wrap items-end gap-2 pt-4">
          <Field label={t('ledger.report')} className="w-64">
            <Select value={name} onChange={(e) => setName(e.target.value as ReportName)}>
              {REPORTS.map((r) => (
                <option key={r} value={r}>
                  {t(`ledger.reports.${r}`)}
                </option>
              ))}
            </Select>
          </Field>
          {'as_of' in params && (
            <Field label={t('ledger.asOf')} className="w-44">
              <Input
                type="date"
                value={p.as_of}
                onChange={(e) => setP({ ...p, as_of: e.target.value })}
              />
            </Field>
          )}
          {'date_from' in params && (
            <>
              <Field label={t('vi.from')} className="w-44">
                <Input
                  type="date"
                  value={p.date_from}
                  onChange={(e) => setP({ ...p, date_from: e.target.value })}
                />
              </Field>
              <Field label={t('vi.to')} className="w-44">
                <Input
                  type="date"
                  value={p.date_to}
                  onChange={(e) => setP({ ...p, date_to: e.target.value })}
                />
              </Field>
            </>
          )}
          {name === 'general-ledger' && (
            <Field label={t('ledger.account')} className="w-64">
              <Select value={p.account} onChange={(e) => setP({ ...p, account: e.target.value })}>
                {accounts.data?.map((a) => (
                  <option key={a.code} value={a.code}>
                    {a.code} · {a.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {name === 'dimensions' && (
            <Field label={t('ledger.dimension')} className="w-48">
              <Select
                value={p.dimension}
                onChange={(e) => setP({ ...p, dimension: e.target.value })}
              >
                {['project', 'cost_element', 'cost_center', 'asset', 'partner'].map((x) => (
                  <option key={x} value={x}>
                    {t(`ledger.dims.${x}`)}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Button variant="secondary" onClick={() => exportAs('xlsx')}>
            <Icon name="download" /> Excel
          </Button>
          <Button variant="secondary" onClick={() => exportAs('pdf')}>
            <Icon name="picture_as_pdf" /> PDF
          </Button>
        </CardContent>
      </Card>
      <FormError message={errText(report.error, t('auth.unexpected'))} />
      {d && (
        <Card className="overflow-x-auto">
          <CardHeader>
            <CardTitle>{d.title}</CardTitle>
          </CardHeader>
          <Table>
            <THead>
              <TR>
                {d.columns.map((c) => (
                  <TH
                    key={c.key}
                    className={c.kind === 'idr' || c.kind === 'number' ? 'text-right' : ''}
                  >
                    {c.header}
                  </TH>
                ))}
              </TR>
            </THead>
            <TBody>
              {d.rows.length === 0 && (
                <TR>
                  <TD colSpan={d.columns.length} className="py-6 text-center text-fg-secondary">
                    {t('ledger.noRows')}
                  </TD>
                </TR>
              )}
              {d.rows.map((r, i) => (
                <TR key={i}>
                  {d.columns.map((c) => (
                    <TD
                      key={c.key}
                      className={
                        c.kind === 'idr' || c.kind === 'number'
                          ? 'whitespace-nowrap text-right tabular-nums'
                          : ''
                      }
                    >
                      {cellValue(r[c.key], c.kind)}
                    </TD>
                  ))}
                </TR>
              ))}
            </TBody>
          </Table>
          {Object.keys(d.summary).length > 0 && (
            <CardContent>
              <dl className="grid gap-x-6 gap-y-1 text-small sm:grid-cols-3">
                {Object.entries(d.summary).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2">
                    <dt className="text-fg-muted">
                      {t(`ledger.summary.${k}`, { defaultValue: k })}
                    </dt>
                    <dd
                      className={
                        k === 'difference' && v !== '0'
                          ? 'font-semibold tabular-nums text-danger'
                          : 'font-semibold tabular-nums text-fg'
                      }
                    >
                      {v !== null && /^-?\d+(\.\d+)?$/.test(v) ? formatIDR(v) : v}
                    </dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          )}
        </Card>
      )}
    </>
  );
}

// ---------------------------------------------------------------- journals

interface JournalRow {
  id: string;
  number: string;
  entry_date: string;
  description: string;
  source_type: string;
  source_number: string | null;
  event: string | null;
  total: string;
  reversal_of: string | null;
  reversed: boolean;
}

function JournalsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const list = useQuery({
    queryKey: ['ledger', 'journals', q],
    queryFn: () => api<{ items: JournalRow[]; total: number }>(`/ledger/journals?${qs({ q })}`),
  });
  const detail = useQuery({
    queryKey: ['ledger', 'journal', open],
    queryFn: () =>
      api<{
        lines: {
          account: string;
          name: string;
          debit: string;
          credit: string;
          memo: string | null;
          partner: string | null;
        }[];
      }>(`/ledger/journals/${open}`),
    enabled: open !== null,
  });
  const post = useLedgerPost();
  return (
    <>
      <Field label={t('master.search')} className="max-w-md">
        <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </Field>
      <FormError message={errText(post.error, t('auth.unexpected'))} />
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('vi.date')}</TH>
              <TH>{t('ledger.source')}</TH>
              <TH>{t('qhse.description')}</TH>
              <TH className="text-right">{t('pr.total')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.items.map((j) => (
              <>
                <TR key={j.id}>
                  <TD className="whitespace-nowrap">
                    <button
                      type="button"
                      className="font-semibold underline-offset-2 hover:underline"
                      onClick={() => setOpen(open === j.id ? null : j.id)}
                    >
                      {j.number}
                    </button>
                    {j.reversed && <StatusPill tone="neutral">{t('ledger.reversed')}</StatusPill>}
                    {j.reversal_of && <StatusPill tone="info">{t('ledger.reversal')}</StatusPill>}
                  </TD>
                  <TD className="whitespace-nowrap">{formatDate(j.entry_date)}</TD>
                  <TD className="whitespace-nowrap">
                    {j.source_number ?? j.source_type}
                    <span className="block text-caption text-fg-muted">{j.event ?? ''}</span>
                  </TD>
                  <TD>{j.description}</TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(j.total)}
                  </TD>
                </TR>
                {open === j.id && detail.data && (
                  <TR key={`${j.id}-d`}>
                    <TD colSpan={5}>
                      <Table>
                        <TBody>
                          {detail.data.lines.map((l, i) => (
                            <TR key={i}>
                              <TD>
                                {l.account} · {l.name}
                                {l.partner && (
                                  <span className="block text-caption text-fg-muted">
                                    {l.partner}
                                  </span>
                                )}
                              </TD>
                              <TD className="text-right tabular-nums">
                                {Number(l.debit) ? formatIDR(l.debit) : ''}
                              </TD>
                              <TD className="text-right tabular-nums">
                                {Number(l.credit) ? formatIDR(l.credit) : ''}
                              </TD>
                            </TR>
                          ))}
                        </TBody>
                      </Table>
                      {can('finance', 'approve') && !j.reversed && !j.reversal_of && (
                        <div className="mt-2 flex flex-wrap items-end gap-2">
                          <Field label={t('ledger.reverseReason')} className="min-w-0 flex-1">
                            <Input value={reason} onChange={(e) => setReason(e.target.value)} />
                          </Field>
                          <Button
                            variant="destructive"
                            disabled={reason.trim().length < 5 || post.isPending}
                            onClick={() =>
                              post.mutate(
                                { path: `/ledger/journals/${j.id}/reverse`, body: { reason } },
                                { onSuccess: () => setReason('') },
                              )
                            }
                          >
                            {t('ledger.reverse')}
                          </Button>
                        </div>
                      )}
                    </TD>
                  </TR>
                )}
              </>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- manual journals

interface MjLine {
  account: string;
  debit: string;
  credit: string;
  memo: string;
}
interface Mj {
  id: string;
  number: string;
  entry_date: string;
  description: string;
  total: string;
  status: 'draft' | 'awaiting_approval' | 'posted';
  reject_reason: string | null;
}

function ManualTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const accounts = useAccounts();
  const list = useQuery({
    queryKey: ['ledger', 'mj'],
    queryFn: () => api<Mj[]>('/ledger/manual-journals'),
  });
  const post = useLedgerPost<Mj>();
  const [date, setDate] = useState(today());
  const [desc, setDesc] = useState('');
  const empty = (): MjLine => ({ account: '', debit: '', credit: '', memo: '' });
  const [lines, setLines] = useState<MjLine[]>([empty(), empty()]);
  const sum = (k: 'debit' | 'credit') =>
    lines.reduce((a, l) => a + Number(moneyToApi(l[k]) ?? 0), 0);
  const balanced = sum('debit') === sum('credit') && sum('debit') > 0;
  const set = (i: number, patch: Partial<MjLine>) =>
    setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <>
      {can('finance', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('ledger.newManual')}</CardTitle>
            <CardDescription>{t('ledger.manualHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap gap-2">
              <Field label={t('vi.date')} className="w-44">
                <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              </Field>
              <Field label={t('qhse.description')} className="min-w-0 flex-1">
                <Input value={desc} onChange={(e) => setDesc(e.target.value)} />
              </Field>
            </div>
            {lines.map((l, i) => (
              <div key={i} className="flex flex-wrap items-end gap-2">
                <Field label={`${t('ledger.account')} ${i + 1}`} className="w-64">
                  <Select value={l.account} onChange={(e) => set(i, { account: e.target.value })}>
                    <option value="">{t('master.choose')}</option>
                    {accounts.data
                      ?.filter((a) => a.postable)
                      .map((a) => (
                        <option key={a.code} value={a.code}>
                          {a.code} · {a.name}
                        </option>
                      ))}
                  </Select>
                </Field>
                <Field label={`${t('ledger.debit')} ${i + 1}`} className="w-36">
                  <Input
                    inputMode="numeric"
                    className="text-right"
                    value={l.debit}
                    onChange={(e) => set(i, { debit: e.target.value, credit: '' })}
                  />
                </Field>
                <Field label={`${t('ledger.credit')} ${i + 1}`} className="w-36">
                  <Input
                    inputMode="numeric"
                    className="text-right"
                    value={l.credit}
                    onChange={(e) => set(i, { credit: e.target.value, debit: '' })}
                  />
                </Field>
                <Field label={t('mnt.note')} className="min-w-0 flex-1">
                  <Input value={l.memo} onChange={(e) => set(i, { memo: e.target.value })} />
                </Field>
              </div>
            ))}
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="secondary" size="sm" onClick={() => setLines([...lines, empty()])}>
                <Icon name="add" /> {t('mr.addLine')}
              </Button>
              <span className={balanced ? 'text-small text-success' : 'text-small text-danger'}>
                {t('ledger.debit')} {formatIDR(sum('debit'))} · {t('ledger.credit')}{' '}
                {formatIDR(sum('credit'))}
              </span>
              <Button
                variant="primary"
                disabled={
                  !balanced ||
                  desc.trim().length < 5 ||
                  lines.some((l) => !l.account) ||
                  post.isPending
                }
                onClick={() =>
                  post.mutate(
                    {
                      path: '/ledger/manual-journals',
                      body: {
                        entry_date: date,
                        description: desc,
                        lines: lines.map((l) => ({
                          account: l.account,
                          debit: moneyToApi(l.debit) ?? '0',
                          credit: moneyToApi(l.credit) ?? '0',
                          memo: l.memo || null,
                        })),
                      },
                    },
                    {
                      onSuccess: () => {
                        setDesc('');
                        setLines([empty(), empty()]);
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
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('vi.date')}</TH>
              <TH>{t('qhse.description')}</TH>
              <TH className="text-right">{t('pr.total')}</TH>
              <TH>{t('master.status')}</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {list.data?.map((m) => (
              <TR key={m.id}>
                <TD className="whitespace-nowrap font-semibold">{m.number}</TD>
                <TD className="whitespace-nowrap">{formatDate(m.entry_date)}</TD>
                <TD>
                  {m.description}
                  {m.reject_reason && (
                    <span className="block text-caption text-danger">{m.reject_reason}</span>
                  )}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(m.total)}</TD>
                <TD>
                  <StatusPill
                    tone={
                      m.status === 'posted'
                        ? 'success'
                        : m.status === 'draft'
                          ? 'neutral'
                          : 'warning'
                    }
                  >
                    {t(`ledger.mjStatus.${m.status}`)}
                  </StatusPill>
                </TD>
                <TD>
                  {m.status === 'draft' && can('finance', 'create') && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        post.mutate({ path: `/ledger/manual-journals/${m.id}/submit` })
                      }
                    >
                      {t('dor.submit')}
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

// ---------------------------------------------------------------- opening balance

function OpeningTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ['ledger', 'opening'],
    queryFn: () => api<{ opening_date: string | null }>('/ledger/opening'),
  });
  const [asOf, setAsOf] = useState(today());
  const imp = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append('file', file);
      form.append('as_of', asOf);
      return api<{
        journal: string;
        total: string;
        ar_items: number;
        ap_items: number;
        stock_rows: number;
        assets: number;
      }>('/ledger/opening', { method: 'POST', body: form });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['ledger'] }),
  });
  const errors =
    imp.error instanceof ApiError
      ? (imp.error.details as { errors?: string[] } | undefined)?.errors
      : undefined;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('ledger.openingTitle')}</CardTitle>
        <CardDescription>{t('ledger.openingHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {status.data?.opening_date ? (
          <p role="status" className="text-small text-success">
            {t('ledger.openingDone', { date: formatDate(status.data.opening_date) })}
          </p>
        ) : (
          can('finance', 'approve') && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('ledger.goLive')} className="w-44">
                <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
              </Field>
              <input
                type="file"
                accept=".xlsx"
                aria-label={t('ledger.openingFile')}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) imp.mutate(f);
                  e.target.value = '';
                }}
              />
            </div>
          )
        )}
        <FormError message={errText(imp.error, t('auth.unexpected'))} />
        {errors && (
          <ul className="list-disc pl-6 text-small text-danger">
            {errors.slice(0, 30).map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        )}
        {imp.data && (
          <p role="status" className="text-small text-success">
            {t('ledger.openingPosted', imp.data)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- posting rules

interface RuleRow {
  event: string;
  label: string;
  used_by: string;
  legs: {
    role: string;
    side: string;
    account: string;
    account_name: string | null;
    default: string;
    dims: string[];
  }[];
}

function RulesTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const rules = useQuery({
    queryKey: ['ledger', 'rules'],
    queryFn: () => api<RuleRow[]>('/ledger/posting-rules'),
  });
  const accounts = useAccounts();
  const post = useLedgerPost();
  return (
    <>
      <p className="text-small text-fg-secondary">{t('ledger.rulesHelp')}</p>
      <FormError message={errText(post.error, t('auth.unexpected'))} />
      {rules.data?.map((r) => (
        <Card key={r.event}>
          <CardHeader>
            <CardTitle>{r.label}</CardTitle>
            <CardDescription>
              {r.event} · {r.used_by}
            </CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TBody>
                {r.legs.map((leg, i) => (
                  <TR key={i}>
                    <TD className="w-24">
                      {leg.side === 'debit' ? t('ledger.debit') : t('ledger.credit')}
                    </TD>
                    <TD className="w-40">{leg.role}</TD>
                    <TD>
                      {can('finance', 'approve') && !leg.account.startsWith('@') ? (
                        <Select
                          aria-label={`${r.event} ${leg.role}`}
                          value={leg.account}
                          onChange={(e) =>
                            post.mutate({
                              path: '/ledger/posting-rules',
                              method: 'PUT',
                              body: { event: r.event, role: leg.role, account: e.target.value },
                            })
                          }
                        >
                          {accounts.data
                            ?.filter((a) => a.postable)
                            .map((a) => (
                              <option key={a.code} value={a.code}>
                                {a.code} · {a.name}
                              </option>
                            ))}
                        </Select>
                      ) : (
                        <span>
                          {leg.account}{' '}
                          {leg.account_name ??
                            t(`ledger.placeholder.${leg.account.slice(1)}`, { defaultValue: '' })}
                        </span>
                      )}
                      {leg.account !== leg.default && (
                        <span className="block text-caption text-warning">
                          {t('ledger.overridden', { account: leg.default })}
                        </span>
                      )}
                    </TD>
                    <TD className="text-caption text-fg-muted">{leg.dims.join(', ')}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </>
  );
}
