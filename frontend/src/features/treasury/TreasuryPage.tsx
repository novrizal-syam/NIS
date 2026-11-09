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
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { useAttachments } from '@/features/dms/api';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import {
  type Advance,
  type BankAccount,
  type PaymentRun,
  useAdvance,
  useAdvanceOptions,
  useAdvances,
  useBankAccounts,
  useDueItems,
  useForecast,
  useReconciliation,
  useRun,
  useRuns,
  useTreasuryAction,
} from './api';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());
const plusDays = (n: number) => {
  const d = new Date(`${today()}T00:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};

const TABS = ['accounts', 'runs', 'advances', 'forecast'] as const;
type Tab = (typeof TABS)[number];

const TONES: Record<string, StatusTone> = {
  draft: 'neutral',
  awaiting_approval: 'warning',
  approved: 'info',
  released: 'success',
  disbursed: 'info',
  settlement_submitted: 'warning',
  settled: 'success',
  cancelled: 'neutral',
};

function Status({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <StatusPill tone={TONES[status] ?? 'neutral'}>{t(`treasury.status.${status}`)}</StatusPill>
  );
}

export function TreasuryPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get('tab') ?? '')
    ? (params.get('tab') as Tab)
    : 'accounts';
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('nav.items.treasury')}
        value={tab}
        onChange={(v) => setParams({ tab: v })}
        items={TABS.map((v) => ({ value: v, label: t(`treasury.tabs.${v}`) }))}
      />
      {tab === 'accounts' && <AccountsTab />}
      {tab === 'runs' && <RunsTab />}
      {tab === 'advances' && <AdvancesTab initial={params.get('id')} />}
      {tab === 'forecast' && <ForecastTab />}
    </div>
  );
}

// ---------------------------------------------------------------- bank accounts

function AccountsTab() {
  const { t } = useTranslation();
  const accounts = useBankAccounts();
  const [selected, setSelected] = useState<string | null>(null);
  const current = selected ?? accounts.data?.find((a) => a.is_default)?.id ?? null;
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('treasury.accounts.title')}</CardTitle>
          <CardDescription>{t('treasury.accounts.hint')}</CardDescription>
        </CardHeader>
        <CardContent>
          <FormError message={errText(accounts.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('treasury.accounts.account')}</TH>
                <TH>{t('treasury.accounts.bank')}</TH>
                <TH>GL</TH>
                <TH className="text-right">{t('treasury.accounts.balance')}</TH>
                <TH className="text-right">{t('treasury.accounts.unreconciled')}</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {accounts.data?.map((a) => (
                <TR key={a.id} aria-selected={a.id === current}>
                  <TD>
                    <div className="font-semibold">{a.name}</div>
                    <div className="text-small text-fg-secondary">
                      {a.code} · {a.currency}
                    </div>
                  </TD>
                  <TD>
                    {a.bank_name} {a.account_no}
                  </TD>
                  <TD>{a.gl_account}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(a.balance)}</TD>
                  <TD className="text-right">{a.unreconciled_statement_lines}</TD>
                  <TD>
                    <Button size="sm" variant="ghost" onClick={() => setSelected(a.id)}>
                      {t('treasury.accounts.reconcile')}
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
      {current && accounts.data && (
        <ReconciliationCard account={accounts.data.find((a) => a.id === current)!} />
      )}
    </>
  );
}

function ReconciliationCard({ account }: { account: BankAccount }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const rec = useReconciliation(account.id);
  const act = useTreasuryAction<{ lines?: number; duplicates?: number; reconciled: number }>();
  const [line, setLine] = useState<string | null>(null);
  const [book, setBook] = useState<string | null>(null);
  const edit = can('treasury', 'edit');
  const r = rec.data;
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <CardTitle>
          {t('treasury.recon.title')} · {account.name}
        </CardTitle>
        <CardDescription>{t('treasury.recon.hint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {edit && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('treasury.recon.import')} className="w-80">
              <Input
                type="file"
                accept=".csv,.txt,.sta,.940"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  const form = new FormData();
                  form.append('file', f);
                  act.mutate({ path: `/treasury/bank-accounts/${account.id}/statements`, form });
                  e.target.value = '';
                }}
              />
            </Field>
            <Button
              onClick={() =>
                act.mutate({ path: `/treasury/bank-accounts/${account.id}/auto-match` })
              }
            >
              <Icon name="join_inner" /> {t('treasury.recon.autoMatch')}
            </Button>
          </div>
        )}
        {act.data && (
          <p role="status" className="text-small text-fg-secondary">
            {t('treasury.recon.result', {
              lines: act.data.lines ?? 0,
              duplicates: act.data.duplicates ?? 0,
              reconciled: act.data.reconciled,
            })}
          </p>
        )}
        <FormError message={errText(act.error ?? rec.error, t('auth.unexpected'))} />
        {r && (
          <>
            <div className="grid gap-2 sm:grid-cols-3">
              <Stat label={t('treasury.recon.book')} value={formatIDR(r.book_balance)} />
              <Stat label={t('treasury.recon.reconciled')} value={String(r.reconciled)} />
              <Stat
                label={t('treasury.recon.open')}
                value={`${r.unmatched_statement.length} / ${r.unmatched_book.length}`}
              />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <h3 className="mb-2 font-heading text-body font-semibold">
                  {t('treasury.recon.statement')}
                </h3>
                <Table>
                  <TBody>
                    {r.unmatched_statement.map((x) => (
                      <TR key={x.id}>
                        <TD>
                          <input
                            type="radio"
                            name="stmt"
                            aria-label={x.description}
                            checked={line === x.id}
                            onChange={() => setLine(x.id)}
                          />
                        </TD>
                        <TD>{formatDate(x.value_date)}</TD>
                        <TD className="max-w-48 truncate">{x.description}</TD>
                        <TD className="text-right tabular-nums">{formatIDR(x.amount)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
                {r.unmatched_statement.length === 0 && (
                  <p className="text-small text-fg-secondary">{t('treasury.recon.none')}</p>
                )}
              </div>
              <div>
                <h3 className="mb-2 font-heading text-body font-semibold">
                  {t('treasury.recon.bookLines')}
                </h3>
                <Table>
                  <TBody>
                    {r.unmatched_book.map((x) => (
                      <TR key={x.id}>
                        <TD>
                          <input
                            type="radio"
                            name="book"
                            aria-label={x.number}
                            checked={book === x.id}
                            onChange={() => setBook(x.id)}
                          />
                        </TD>
                        <TD>{formatDate(x.entry_date)}</TD>
                        <TD className="max-w-48 truncate">
                          {x.number} · {x.source_number ?? x.description}
                        </TD>
                        <TD className="text-right tabular-nums">{formatIDR(x.amount)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
                {r.unmatched_book.length === 0 && (
                  <p className="text-small text-fg-secondary">{t('treasury.recon.none')}</p>
                )}
              </div>
            </div>
            {edit && (
              <div>
                <Button
                  variant="primary"
                  disabled={!line || !book}
                  onClick={() =>
                    act.mutate(
                      {
                        path: `/treasury/bank-lines/${line}/match`,
                        body: { journal_line_id: book },
                      },
                      { onSuccess: () => (setLine(null), setBook(null)) },
                    )
                  }
                >
                  {t('treasury.recon.match')}
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="rounded-md border border-border p-3">
      <div className="text-small text-fg-secondary">{label}</div>
      <div className={`text-h4 font-heading tabular-nums ${danger ? 'text-danger' : ''}`}>
        {value}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- payment runs

function RunsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const runs = useRuns();
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader className="flex-row items-center justify-between gap-2">
          <div>
            <CardTitle>{t('treasury.runs.title')}</CardTitle>
            <CardDescription>{t('treasury.runs.hint')}</CardDescription>
          </div>
          {can('treasury', 'create') && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Icon name="add" /> {t('treasury.runs.new')}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <FormError message={errText(runs.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('treasury.number')}</TH>
                <TH>{t('treasury.runs.payDate')}</TH>
                <TH>{t('treasury.runs.bank')}</TH>
                <TH className="text-right">{t('treasury.total')}</TH>
                <TH>{t('treasury.statusLabel')}</TH>
              </TR>
            </THead>
            <TBody>
              {runs.data?.map((r) => (
                <TR key={r.id}>
                  <TD>
                    <Button size="sm" variant="link" onClick={() => setOpen(r.id)}>
                      {r.number}
                    </Button>
                  </TD>
                  <TD>{formatDate(r.pay_date)}</TD>
                  <TD>{r.bank_account?.name}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(r.total)}</TD>
                  <TD>
                    <Status status={r.status} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {runs.data?.length === 0 && (
            <p className="text-small text-fg-secondary">{t('treasury.runs.empty')}</p>
          )}
        </CardContent>
      </Card>
      {creating && (
        <NewRunCard
          onDone={(id) => {
            setCreating(false);
            if (id) setOpen(id);
          }}
        />
      )}
      {open && <RunDetail id={open} />}
    </>
  );
}

function NewRunCard({ onDone }: { onDone: (id?: string) => void }) {
  const { t } = useTranslation();
  const accounts = useBankAccounts();
  const [dueBy, setDueBy] = useState(plusDays(7));
  const due = useDueItems(dueBy, true);
  const [payDate, setPayDate] = useState(today());
  const [bank, setBank] = useState('');
  const [picked, setPicked] = useState<Record<string, string>>({});
  const act = useTreasuryAction<PaymentRun>();
  const idr = accounts.data?.filter((a) => a.currency === 'IDR' && a.is_active) ?? [];
  const bankId = bank || idr.find((a) => a.is_default)?.id || idr[0]?.id || '';
  const toggle = (key: string, amount: string) =>
    setPicked((p) => {
      const n = { ...p };
      if (key in n) delete n[key];
      else n[key] = amount;
      return n;
    });
  const total = Object.values(picked).reduce((s, v) => s + Number(moneyToApi(v) || 0), 0);
  const submit = () => {
    const items = Object.entries(picked).map(([key, amount]) =>
      key.startsWith('vi:')
        ? { kind: 'vendor_invoice', vendor_invoice_id: key.slice(3), amount: moneyToApi(amount) }
        : { kind: key.slice(4), amount: moneyToApi(amount) },
    );
    act.mutate(
      {
        path: '/treasury/payment-runs',
        body: { pay_date: payDate, bank_account_id: bankId, items },
      },
      { onSuccess: (r) => onDone(r.id) },
    );
  };
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <CardTitle>{t('treasury.runs.new')}</CardTitle>
        <CardDescription>{t('treasury.runs.newHint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('treasury.runs.payDate')} className="w-44">
            <Input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} />
          </Field>
          <Field label={t('treasury.runs.bank')} className="w-64">
            <Select value={bankId} onChange={(e) => setBank(e.target.value)}>
              {idr.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} · {formatIDR(a.balance)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('treasury.runs.dueBy')} className="w-44">
            <Input type="date" value={dueBy} onChange={(e) => setDueBy(e.target.value)} />
          </Field>
        </div>
        <Table>
          <THead>
            <TR>
              <TH />
              <TH>{t('treasury.runs.item')}</TH>
              <TH>{t('treasury.runs.due')}</TH>
              <TH className="text-right">{t('treasury.runs.open')}</TH>
              <TH className="text-right">{t('treasury.runs.pay')}</TH>
            </TR>
          </THead>
          <TBody>
            {due.data?.invoices.map((x) => {
              const key = `vi:${x.vendor_invoice_id}`;
              return (
                <TR key={key}>
                  <TD>
                    <input
                      type="checkbox"
                      aria-label={x.number}
                      checked={key in picked}
                      onChange={() => toggle(key, x.outstanding)}
                    />
                  </TD>
                  <TD>
                    <div className="font-semibold">{x.vendor_name}</div>
                    <div className="text-small text-fg-secondary">
                      {x.number} · {x.invoice_no}
                    </div>
                  </TD>
                  <TD>{x.due_date ? formatDate(x.due_date) : '-'}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(x.outstanding)}</TD>
                  <TD className="w-40">
                    {key in picked && (
                      <Input
                        aria-label={`${t('treasury.runs.pay')} ${x.number}`}
                        inputMode="numeric"
                        value={picked[key]}
                        onChange={(e) => setPicked({ ...picked, [key]: e.target.value })}
                      />
                    )}
                  </TD>
                </TR>
              );
            })}
            {due.data?.liabilities.map((x) => {
              const key = `lia:${x.kind}`;
              return (
                <TR key={key}>
                  <TD>
                    <input
                      type="checkbox"
                      aria-label={x.label}
                      checked={key in picked}
                      onChange={() => toggle(key, x.outstanding)}
                    />
                  </TD>
                  <TD className="font-semibold">{t(`treasury.kinds.${x.kind}`)}</TD>
                  <TD>-</TD>
                  <TD className="text-right tabular-nums">{formatIDR(x.outstanding)}</TD>
                  <TD className="w-40">
                    {key in picked && (
                      <Input
                        aria-label={`${t('treasury.runs.pay')} ${x.label}`}
                        inputMode="numeric"
                        value={picked[key]}
                        onChange={(e) => setPicked({ ...picked, [key]: e.target.value })}
                      />
                    )}
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
        {due.data && due.data.invoices.length + due.data.liabilities.length === 0 && (
          <p className="text-small text-fg-secondary">{t('treasury.runs.nothingDue')}</p>
        )}
        <FormError message={errText(act.error ?? due.error, t('auth.unexpected'))} />
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">
            {t('treasury.total')}: {formatIDR(String(total))}
          </span>
          <Button
            variant="primary"
            disabled={!bankId || Object.keys(picked).length === 0 || act.isPending}
            onClick={submit}
          >
            {t('treasury.runs.create')}
          </Button>
          <Button variant="ghost" onClick={() => onDone()}>
            {t('treasury.cancel')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RunDetail({ id }: { id: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const run = useRun(id);
  const act = useTreasuryAction();
  const r = run.data;
  if (!r) return <FormError message={errText(run.error, t('auth.unexpected'))} />;
  const base = `/treasury/payment-runs/${r.id}`;
  return (
    <Card className="overflow-x-auto">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>
            {r.number} · {formatIDR(r.total)}
          </CardTitle>
          <CardDescription>
            {formatDate(r.pay_date)} · {r.bank_account?.name}
          </CardDescription>
        </div>
        <Status status={r.status} />
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {r.reject_reason && (
          <p role="alert" className="text-small text-danger">
            {t('treasury.rejected')}: {r.reject_reason}
          </p>
        )}
        <Table>
          <THead>
            <TR>
              <TH>#</TH>
              <TH>{t('treasury.runs.payee')}</TH>
              <TH>{t('treasury.runs.reference')}</TH>
              <TH className="text-right">{t('treasury.amount')}</TH>
            </TR>
          </THead>
          <TBody>
            {r.items.map((x) => (
              <TR key={x.seq}>
                <TD>{x.seq}</TD>
                <TD>
                  <div className="font-semibold">{x.payee}</div>
                  <div className="text-small text-fg-secondary">
                    {t(`treasury.kinds.${x.kind}`)}
                  </div>
                </TD>
                <TD>{x.reference}</TD>
                <TD className="text-right tabular-nums">{formatIDR(x.amount)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <p className="text-small text-fg-secondary">{t('treasury.runs.sod')}</p>
        <FormError message={errText(act.error, t('auth.unexpected'))} />
        <div className="flex flex-wrap gap-2">
          {r.status === 'draft' && can('treasury', 'submit') && (
            <Button variant="primary" onClick={() => act.mutate({ path: `${base}/submit` })}>
              {t('treasury.submit')}
            </Button>
          )}
          {r.status === 'approved' && can('treasury', 'post') && (
            <Button variant="primary" onClick={() => act.mutate({ path: `${base}/release` })}>
              <Icon name="send_money" /> {t('treasury.runs.release')}
            </Button>
          )}
          {['draft', 'approved'].includes(r.status) && can('treasury', 'create') && (
            <Button
              variant="destructive"
              onClick={() =>
                act.mutate({ path: `${base}/cancel`, body: { reason: t('treasury.cancelled') } })
              }
            >
              {t('treasury.cancel')}
            </Button>
          )}
          {r.status === 'released' && can('treasury', 'post') && (
            <Button
              onClick={() =>
                void downloadFile(`${base}/bank-file`, `${r.number}-bulk-transfer.csv`)
              }
            >
              <Icon name="download" /> {t('treasury.runs.bankFile')}
            </Button>
          )}
          {r.status === 'released' &&
            r.bukti_potong_vendors?.map((v) => (
              <Button
                key={v}
                onClick={() =>
                  void downloadFile(`${base}/bukti-potong/${v}`, `BP23-${r.number}-${v}.pdf`)
                }
              >
                <Icon name="picture_as_pdf" /> {t('treasury.runs.buktiPotong', { vendor: v })}
              </Button>
            ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- cash advances

function AdvancesTab({ initial }: { initial: string | null }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useAdvances();
  const [open, setOpen] = useState<string | null>(initial);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader className="flex-row items-center justify-between gap-2">
          <div>
            <CardTitle>{t('treasury.advances.title')}</CardTitle>
            <CardDescription>{t('treasury.advances.hint')}</CardDescription>
          </div>
          {can('treasury', 'create') && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Icon name="add" /> {t('treasury.advances.new')}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <FormError message={errText(list.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('treasury.number')}</TH>
                <TH>{t('treasury.advances.purpose')}</TH>
                <TH className="text-right">{t('treasury.amount')}</TH>
                <TH>{t('treasury.statusLabel')}</TH>
              </TR>
            </THead>
            <TBody>
              {list.data?.map((a) => (
                <TR key={a.id}>
                  <TD>
                    <Button size="sm" variant="link" onClick={() => setOpen(a.id)}>
                      {a.number}
                    </Button>
                  </TD>
                  <TD className="max-w-72 truncate">{a.purpose}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(a.amount)}</TD>
                  <TD className="flex flex-wrap gap-1">
                    <Status status={a.status} />
                    {a.overdue && (
                      <StatusPill tone="danger">
                        {t('treasury.advances.overdue', { days: a.days_open })}
                      </StatusPill>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {list.data?.length === 0 && (
            <p className="text-small text-fg-secondary">{t('treasury.advances.empty')}</p>
          )}
        </CardContent>
      </Card>
      {creating && (
        <NewAdvanceCard
          onDone={(id) => {
            setCreating(false);
            if (id) setOpen(id);
          }}
        />
      )}
      {open && <AdvanceDetail id={open} />}
    </>
  );
}

function NewAdvanceCard({ onDone }: { onDone: (id?: string) => void }) {
  const { t } = useTranslation();
  const opts = useAdvanceOptions();
  const act = useTreasuryAction<Advance>();
  const [f, setF] = useState({ purpose: '', amount: '', needed_date: today(), project_id: '' });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('treasury.advances.new')}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field label={t('treasury.advances.purpose')} required>
          <Input value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Field label={t('treasury.amount')} required className="w-48">
            <Input
              inputMode="numeric"
              value={f.amount}
              onChange={(e) => setF({ ...f, amount: e.target.value })}
            />
          </Field>
          <Field label={t('treasury.advances.neededDate')} className="w-44">
            <Input
              type="date"
              value={f.needed_date}
              onChange={(e) => setF({ ...f, needed_date: e.target.value })}
            />
          </Field>
          <Field label={t('treasury.advances.project')} className="w-72">
            <Select
              value={f.project_id}
              onChange={(e) => setF({ ...f, project_id: e.target.value })}
            >
              <option value="">{t('treasury.advances.noProject')}</option>
              {opts.data?.projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.number} · {p.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <FormError message={errText(act.error, t('auth.unexpected'))} />
        <div className="flex gap-2">
          <Button
            variant="primary"
            disabled={!f.purpose.trim() || !moneyToApi(f.amount) || act.isPending}
            onClick={() =>
              act.mutate(
                {
                  path: '/treasury/advances',
                  body: {
                    purpose: f.purpose,
                    amount: moneyToApi(f.amount),
                    needed_date: f.needed_date,
                    project_id: f.project_id || null,
                  },
                },
                { onSuccess: (a) => onDone(a.id) },
              )
            }
          >
            {t('treasury.save')}
          </Button>
          <Button variant="ghost" onClick={() => onDone()}>
            {t('treasury.cancel')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

interface LineDraft {
  spent_on: string;
  cost_element: string;
  wbs_code: string;
  description: string;
  amount: string;
  attachment_id: string;
}

function AdvanceDetail({ id }: { id: string }) {
  const { t } = useTranslation();
  const { can, me } = useAuth();
  const adv = useAdvance(id);
  const act = useTreasuryAction();
  const [reason, setReason] = useState('');
  const a = adv.data;
  if (!a) return <FormError message={errText(adv.error, t('auth.unexpected'))} />;
  const base = `/treasury/advances/${a.id}`;
  const mine = me?.id === a.requester_id;
  const cashier = can('treasury', 'post') && !mine;
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>
            {a.number} · {formatIDR(a.amount)}
          </CardTitle>
          <CardDescription>{a.purpose}</CardDescription>
        </div>
        <Status status={a.status} />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {a.reject_reason && (
          <p role="alert" className="text-small text-danger">
            {t('treasury.rejected')}: {a.reject_reason}
          </p>
        )}
        {a.overdue && (
          <p role="alert" className="text-small text-danger">
            {t('treasury.advances.overdueHint', { days: a.days_open })}
          </p>
        )}
        <FormError message={errText(act.error, t('auth.unexpected'))} />
        <div className="flex flex-wrap gap-2">
          {a.status === 'draft' && mine && (
            <Button variant="primary" onClick={() => act.mutate({ path: `${base}/submit` })}>
              {t('treasury.submit')}
            </Button>
          )}
          {a.status === 'approved' && cashier && (
            <Button variant="primary" onClick={() => act.mutate({ path: `${base}/disburse` })}>
              <Icon name="payments" /> {t('treasury.advances.disburse')}
            </Button>
          )}
          {a.status === 'settlement_submitted' && cashier && (
            <Button variant="primary" onClick={() => act.mutate({ path: `${base}/settle` })}>
              <Icon name="task_alt" /> {t('treasury.advances.settle')}
            </Button>
          )}
          {['draft', 'approved'].includes(a.status) && (mine || cashier) && (
            <Button
              variant="destructive"
              onClick={() =>
                act.mutate({ path: `${base}/cancel`, body: { reason: t('treasury.cancelled') } })
              }
            >
              {t('treasury.cancel')}
            </Button>
          )}
        </div>
        {a.status === 'settlement_submitted' && cashier && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('treasury.advances.returnReason')} className="w-80">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Button
              disabled={reason.trim().length < 3}
              onClick={() => act.mutate({ path: `${base}/settlement/return`, body: { reason } })}
            >
              {t('treasury.advances.return')}
            </Button>
          </div>
        )}
        {a.lines.length > 0 && (
          <Table>
            <THead>
              <TR>
                <TH>{t('treasury.advances.spentOn')}</TH>
                <TH>{t('treasury.advances.costElement')}</TH>
                <TH>{t('treasury.advances.description')}</TH>
                <TH className="text-right">{t('treasury.amount')}</TH>
              </TR>
            </THead>
            <TBody>
              {a.lines.map((x) => (
                <TR key={x.seq}>
                  <TD>{formatDate(x.spent_on)}</TD>
                  <TD>
                    {x.cost_element}
                    {x.wbs_code ? ` · ${x.wbs_code}` : ''}
                  </TD>
                  <TD>{x.description}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(x.amount)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
        {a.difference && (
          <p className="text-small">
            {Number(a.difference) < 0
              ? t('treasury.advances.refund', { amount: formatIDR(a.difference.slice(1)) })
              : Number(a.difference) > 0
                ? t('treasury.advances.reimburse', { amount: formatIDR(a.difference) })
                : t('treasury.advances.exact')}
          </p>
        )}
        {['disbursed', 'settlement_submitted', 'settled'].includes(a.status) && (
          <AttachmentsPanel
            entityType="cash_advance"
            entityId={a.id}
            canWrite={mine && a.status === 'disbursed'}
          />
        )}
        {a.status === 'disbursed' && mine && <SettlementForm advance={a} />}
      </CardContent>
    </Card>
  );
}

function SettlementForm({ advance }: { advance: Advance }) {
  const { t } = useTranslation();
  const opts = useAdvanceOptions();
  const files = useAttachments('cash_advance', advance.id);
  const act = useTreasuryAction();
  const blank = (): LineDraft => ({
    spent_on: today(),
    cost_element: '',
    wbs_code: '',
    description: '',
    amount: '',
    attachment_id: '',
  });
  const [lines, setLines] = useState<LineDraft[]>([blank()]);
  const [note, setNote] = useState('');
  const project = opts.data?.projects.find((p) => p.id === advance.project_id);
  const set = (i: number, patch: Partial<LineDraft>) =>
    setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const spent = lines.reduce((s, l) => s + Number(moneyToApi(l.amount) || 0), 0);
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border p-3">
      <h3 className="font-heading text-body font-semibold">{t('treasury.advances.settlement')}</h3>
      <p className="text-small text-fg-secondary">{t('treasury.advances.settlementHint')}</p>
      {lines.map((l, i) => (
        <div key={i} className="flex flex-wrap items-end gap-2">
          <Field label={t('treasury.advances.spentOn')} className="w-40">
            <Input
              type="date"
              value={l.spent_on}
              onChange={(e) => set(i, { spent_on: e.target.value })}
            />
          </Field>
          <Field label={t('treasury.advances.costElement')} className="w-48">
            <Select
              value={l.cost_element}
              onChange={(e) => set(i, { cost_element: e.target.value })}
            >
              <option value="">-</option>
              {opts.data?.cost_elements.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          {project && (
            <Field label="WBS" className="w-32">
              <Select value={l.wbs_code} onChange={(e) => set(i, { wbs_code: e.target.value })}>
                <option value="">-</option>
                {project.wbs.map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label={t('treasury.advances.description')} className="w-56">
            <Input
              value={l.description}
              onChange={(e) => set(i, { description: e.target.value })}
            />
          </Field>
          <Field label={t('treasury.amount')} className="w-36">
            <Input
              inputMode="numeric"
              value={l.amount}
              onChange={(e) => set(i, { amount: e.target.value })}
            />
          </Field>
          <Field label={t('treasury.advances.receipt')} className="w-48">
            <Select
              value={l.attachment_id}
              onChange={(e) => set(i, { attachment_id: e.target.value })}
            >
              <option value="">-</option>
              {files.data?.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.filename}
                </option>
              ))}
            </Select>
          </Field>
          {lines.length > 1 && (
            <Button
              variant="ghost"
              aria-label={t('treasury.advances.removeLine')}
              onClick={() => setLines(lines.filter((_, j) => j !== i))}
            >
              <Icon name="delete" />
            </Button>
          )}
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" onClick={() => setLines([...lines, blank()])}>
          <Icon name="add" /> {t('treasury.advances.addLine')}
        </Button>
        <span className="text-small">
          {t('treasury.advances.spent')}: {formatIDR(String(spent))} / {formatIDR(advance.amount)}
        </span>
      </div>
      <Field label={t('treasury.advances.note')}>
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <FormError message={errText(act.error, t('auth.unexpected'))} />
      <div>
        <Button
          variant="primary"
          disabled={act.isPending}
          onClick={() =>
            act.mutate({
              path: `/treasury/advances/${advance.id}/settlement`,
              body: {
                note: note.trim() || null,
                lines: lines.map((l) => ({
                  spent_on: l.spent_on,
                  cost_element: l.cost_element,
                  wbs_code: l.wbs_code || null,
                  description: l.description,
                  amount: moneyToApi(l.amount),
                  attachment_id: l.attachment_id || null,
                })),
              },
            })
          }
        >
          {t('treasury.advances.submitSettlement')}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- forecast

function ForecastTab() {
  const { t } = useTranslation();
  const fc = useForecast();
  const d = fc.data;
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <CardTitle>{t('treasury.forecast.title')}</CardTitle>
        <CardDescription>{t('treasury.forecast.hint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <FormError message={errText(fc.error, t('auth.unexpected'))} />
        {d && (
          <>
            <div className="grid gap-2 sm:grid-cols-3">
              <Stat label={t('treasury.forecast.opening')} value={formatIDR(d.opening)} />
              <Stat
                label={t('treasury.forecast.lowest')}
                value={formatIDR(d.lowest)}
                danger={Number(d.lowest) < 0}
              />
              <Stat label={t('treasury.forecast.closing')} value={formatIDR(d.closing)} />
            </div>
            <Table>
              <THead>
                <TR>
                  <TH className="sticky left-0 bg-surface">{t('treasury.forecast.line')}</TH>
                  {d.weeks.map((w) => (
                    <TH key={w.week} className="text-right">
                      <div>W{w.week}</div>
                      <div className="text-small font-normal">{formatDate(w.start)}</div>
                    </TH>
                  ))}
                </TR>
              </THead>
              <TBody>
                {[
                  { key: 'opening', label: t('treasury.forecast.opening'), strong: true },
                  ...d.inflows.map((x) => ({
                    key: x.key,
                    label: t(`treasury.forecast.rows.${x.key}`),
                    strong: false,
                  })),
                  { key: 'inflow', label: t('treasury.forecast.inflow'), strong: true },
                  ...d.outflows.map((x) => ({
                    key: x.key,
                    label: t(`treasury.forecast.rows.${x.key}`),
                    strong: false,
                  })),
                  { key: 'outflow', label: t('treasury.forecast.outflow'), strong: true },
                  { key: 'closing', label: t('treasury.forecast.closing'), strong: true },
                ].map((row) => (
                  <TR key={row.key}>
                    <TD className={`sticky left-0 bg-surface ${row.strong ? 'font-semibold' : ''}`}>
                      {row.label}
                    </TD>
                    {d.weeks.map((w) => (
                      <TD
                        key={w.week}
                        className={`text-right tabular-nums ${row.strong ? 'font-semibold' : ''} ${
                          row.key === 'closing' && w.negative ? 'text-danger' : ''
                        }`}
                      >
                        {formatIDR(String(w[row.key]))}
                      </TD>
                    ))}
                  </TR>
                ))}
              </TBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  );
}
