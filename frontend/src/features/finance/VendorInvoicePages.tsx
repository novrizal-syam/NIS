import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, buttonVariants } from '@/components/ui/button';
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
import { FilterTile } from '@/features/crm/CrmPills';
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { JournalCard } from '@/features/inventory/JournalCard';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDate, formatIDR, formatNumber } from '@/lib/format';
import {
  VI_STATUSES,
  useAging,
  useCancelVendorInvoice,
  useCorrectVendorInvoice,
  useCreateVendorInvoice,
  useCreditNote,
  useFinanceVendors,
  useMatchVendorInvoice,
  usePoOptions,
  usePrefill,
  useStatement,
  useVendorInvoice,
  useVendorInvoices,
  viExportPath,
  type ViDetail,
  type ViStatus,
} from './api';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const qtyToApi = (v: string) => v.replace(/\./g, '').replace(',', '.').trim();
const qtyFmt = (v: string) => v.replace('.', ',');
const money = (v: string) => Number(moneyToApi(v) ?? 0);
const TONE: Record<ViStatus, StatusTone> = {
  draft: 'neutral',
  exception: 'danger',
  approved: 'success',
  paid: 'info',
  cancelled: 'neutral',
};
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

export function ViStatusPill({ status }: { status: ViStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`vi.status.${status}`)}</StatusPill>;
}

// ---------------------------------------------------------------- list, aging, statement

export function VendorInvoicesPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'list' | 'aging' | 'statement'>('list');
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('nav.items.vendorInvoices')}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'list', label: t('vi.tabs.list') },
          { value: 'aging', label: t('vi.tabs.aging') },
          { value: 'statement', label: t('vi.tabs.statement') },
        ]}
      />
      {tab === 'list' && <ListTab />}
      {tab === 'aging' && <AgingTab />}
      {tab === 'statement' && <StatementTab />}
    </div>
  );
}

function ListTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<ViStatus | ''>('');
  const [page, setPage] = useState(1);
  const list = useVendorInvoices({ q, status, page });
  const data = list.data;
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {VI_STATUSES.map((s) => (
          <FilterTile
            key={s}
            label={t(`vi.status.${s}`)}
            value={data?.counts[s] ?? '–'}
            active={status === s}
            onClick={() => {
              setStatus(status === s ? '' : s);
              setPage(1);
            }}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('vi.search')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        {can('finance', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile(viExportPath({ q, status }), 'tagihan-vendor.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
        {can('finance', 'create') && (
          <Link
            to="/keuangan/tagihan-vendor/baru"
            className={buttonVariants({ variant: 'primary' })}
          >
            <Icon name="add" /> {t('vi.new')}
          </Link>
        )}
      </div>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('rfq.vendor')}</TH>
              <TH>{t('vi.invoiceNo')}</TH>
              <TH>{t('vi.dueDate')}</TH>
              <TH className="text-right">{t('vi.payable')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {data?.items.length === 0 && (
              <TR>
                <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                  {t('vi.empty')}
                </TD>
              </TR>
            )}
            {data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/keuangan/tagihan-vendor/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.number}
                  </Link>
                  <span className="block text-caption text-fg-muted">{r.po_number}</span>
                </TD>
                <TD className="min-w-40">{r.vendor_name}</TD>
                <TD className="whitespace-nowrap">
                  {r.invoice_no}
                  <span className="block text-caption text-fg-muted">
                    {formatDate(r.invoice_date)}
                  </span>
                </TD>
                <TD className="whitespace-nowrap">{r.due_date ? formatDate(r.due_date) : '–'}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(r.payable)}
                </TD>
                <TD>
                  <ViStatusPill status={r.status} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
      </Card>
    </>
  );
}

const BUCKETS = ['not_due', 'd1_30', 'd31_60', 'd61_90', 'd90_plus', 'total'] as const;

function AgingTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const aging = useAging(true);
  const d = aging.data;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-small text-fg-secondary">
          {d ? t('vi.agingAsOf', { date: formatDate(d.as_of) }) : t('common.loading')}
        </p>
        {can('finance', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile('/finance/ap-aging/export', 'umur-hutang.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
      </div>
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('rfq.vendor')}</TH>
              {BUCKETS.map((b) => (
                <TH key={b} className="text-right">
                  {t(`vi.buckets.${b}`)}
                </TH>
              ))}
            </TR>
          </THead>
          <TBody>
            {d?.rows.length === 0 && (
              <TR>
                <TD colSpan={7} className="py-8 text-center text-fg-secondary">
                  {t('vi.noPayables')}
                </TD>
              </TR>
            )}
            {d?.rows.map((r) => (
              <TR key={r.vendor_code}>
                <TD className="min-w-40">{r.vendor_name}</TD>
                {BUCKETS.map((b) => (
                  <TD key={b} className="whitespace-nowrap text-right tabular-nums">
                    {Number(r[b]) ? formatIDR(r[b]) : '–'}
                  </TD>
                ))}
              </TR>
            ))}
            {d && d.rows.length > 0 && (
              <TR>
                <TD className="font-semibold">{t('vi.total')}</TD>
                {BUCKETS.map((b) => (
                  <TD key={b} className="whitespace-nowrap text-right font-semibold tabular-nums">
                    {formatIDR(d.totals[b])}
                  </TD>
                ))}
              </TR>
            )}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

function StatementTab() {
  const { t } = useTranslation();
  const vendors = useFinanceVendors(true);
  const [vendor, setVendor] = useState('');
  const [from, setFrom] = useState(`${today().slice(0, 4)}-01-01`);
  const [to, setTo] = useState(today());
  const st = useStatement(vendor, from, to);
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('rfq.vendor')} className="w-72">
          <Select value={vendor} onChange={(e) => setVendor(e.target.value)}>
            <option value="">{t('master.choose')}</option>
            {vendors.data?.map((v) => (
              <option key={v.code} value={v.code}>
                {v.code} · {v.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('vi.from')} className="w-44">
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label={t('vi.to')} className="w-44">
          <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
      </div>
      <FormError message={errText(st.error, t('auth.unexpected'))} />
      {st.data && (
        <Card className="overflow-x-auto">
          <CardHeader>
            <CardTitle>{st.data.vendor_name}</CardTitle>
            <CardDescription>{t('vi.statementHelp')}</CardDescription>
          </CardHeader>
          <Table>
            <THead>
              <TR>
                <TH>{t('vi.date')}</TH>
                <TH>{t('vi.document')}</TH>
                <TH className="text-right">{t('ledger.debit')}</TH>
                <TH className="text-right">{t('ledger.credit')}</TH>
                <TH className="text-right">{t('vi.balance')}</TH>
              </TR>
            </THead>
            <TBody>
              <TR>
                <TD colSpan={4}>{t('vi.opening')}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(st.data.opening)}
                </TD>
              </TR>
              {st.data.rows.map((r, i) => (
                <TR key={i}>
                  <TD className="whitespace-nowrap">{formatDate(r.date)}</TD>
                  <TD className="min-w-48">
                    {r.document ?? r.journal}
                    <span className="block text-caption text-fg-muted">{r.description}</span>
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {Number(r.debit) ? formatIDR(r.debit) : ''}
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {Number(r.credit) ? formatIDR(r.credit) : ''}
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(r.balance)}
                  </TD>
                </TR>
              ))}
              <TR>
                <TD colSpan={4} className="font-semibold">
                  {t('vi.closing')}
                </TD>
                <TD className="whitespace-nowrap text-right font-semibold tabular-nums">
                  {formatIDR(st.data.closing)}
                </TD>
              </TR>
            </TBody>
          </Table>
        </Card>
      )}
    </>
  );
}

// ---------------------------------------------------------------- form

interface FormLine {
  seq: number;
  description: string;
  uom?: string;
  open?: string;
  poPrice?: string;
  qty: string;
  price: string;
}

interface FormState {
  invoiceNo: string;
  taxNo: string;
  date: string;
  kind: 'goods' | 'service';
  dpp: string;
  ppn: string;
  ppnManual: boolean;
  term: string;
  note: string;
  lines: FormLine[];
}

const linesTotal = (lines: FormLine[]) =>
  lines.reduce((a, l) => a + Math.round(Number(qtyToApi(l.qty) || 0) * money(l.price)), 0);

function InvoiceFields({
  v,
  set,
  npwp,
  ppnPct,
}: {
  v: FormState;
  set: (v: FormState) => void;
  npwp: string | null;
  ppnPct: number;
}) {
  const { t } = useTranslation();
  const dpp = v.dpp === '' ? linesTotal(v.lines) : money(v.dpp);
  const ppn = v.ppnManual ? money(v.ppn) : Math.round((dpp * ppnPct) / 100);
  const rate = v.kind === 'service' ? (npwp ? 2 : 4) : 0;
  const pph = Math.round((dpp * rate) / 100);
  const setLine = (i: number, patch: Partial<FormLine>) =>
    set({ ...v, lines: v.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={t('vi.invoiceNo')} required>
          <Input value={v.invoiceNo} onChange={(e) => set({ ...v, invoiceNo: e.target.value })} />
        </Field>
        <Field label={t('vi.taxInvoiceNo')}>
          <Input value={v.taxNo} onChange={(e) => set({ ...v, taxNo: e.target.value })} />
        </Field>
        <Field label={t('vi.invoiceDate')} required>
          <Input
            type="date"
            max={today()}
            value={v.date}
            onChange={(e) => set({ ...v, date: e.target.value })}
          />
        </Field>
        <Field label={t('vi.kind')} required>
          <Select
            value={v.kind}
            onChange={(e) => set({ ...v, kind: e.target.value as FormState['kind'] })}
          >
            <option value="goods">{t('vi.kinds.goods')}</option>
            <option value="service">{t('vi.kinds.service')}</option>
          </Select>
        </Field>
        <Field label={t('vi.termDays')}>
          <Input
            inputMode="numeric"
            value={v.term}
            onChange={(e) => set({ ...v, term: e.target.value.replace(/\D/g, '') })}
          />
        </Field>
      </div>
      <div className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('quotation.description')}</TH>
              <TH className="text-right">{t('vi.openToBill')}</TH>
              <TH className="w-28 text-right">{t('quotation.qty')}</TH>
              <TH className="w-40 text-right">{t('quotation.unitPrice')}</TH>
              <TH className="text-right">{t('quotation.amount')}</TH>
            </TR>
          </THead>
          <TBody>
            {v.lines.map((l, i) => (
              <TR key={l.seq}>
                <TD className="min-w-48">
                  {l.description}
                  {l.poPrice && (
                    <span className="block text-caption text-fg-muted">
                      {t('vi.poPrice')}: {formatIDR(l.poPrice)}
                    </span>
                  )}
                </TD>
                <TD className="text-right tabular-nums">
                  {l.open !== undefined ? `${qtyFmt(l.open)} ${l.uom ?? ''}` : '–'}
                </TD>
                <TD>
                  <Input
                    aria-label={`${t('quotation.qty')} ${l.description}`}
                    inputMode="decimal"
                    className="text-right"
                    value={l.qty}
                    onChange={(e) => setLine(i, { qty: e.target.value })}
                  />
                </TD>
                <TD>
                  <Input
                    aria-label={`${t('quotation.unitPrice')} ${l.description}`}
                    inputMode="numeric"
                    className="text-right"
                    value={l.price}
                    onChange={(e) => setLine(i, { price: e.target.value })}
                  />
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(Math.round(Number(qtyToApi(l.qty) || 0) * money(l.price)))}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={t('vi.dpp')} hint={t('vi.dppHint')}>
          <Input
            inputMode="numeric"
            className="text-right"
            value={v.dpp}
            placeholder={formatNumber(linesTotal(v.lines))}
            onChange={(e) => set({ ...v, dpp: e.target.value })}
          />
        </Field>
        <Field label={t('vi.ppnLabel', { pct: ppnPct })}>
          <Input
            inputMode="numeric"
            className="text-right"
            disabled={!v.ppnManual}
            value={v.ppnManual ? v.ppn : formatNumber(ppn)}
            onChange={(e) => set({ ...v, ppn: e.target.value })}
          />
        </Field>
        <label className="flex h-10 items-center gap-2 self-end text-small text-fg-body">
          <input
            type="checkbox"
            checked={v.ppnManual}
            onChange={(e) => set({ ...v, ppnManual: e.target.checked, ppn: formatNumber(ppn) })}
          />
          {t('vi.ppnAsFaktur')}
        </label>
      </div>
      <dl className="grid gap-x-6 gap-y-2 text-small sm:grid-cols-4">
        <div>
          <dt className="text-fg-muted">{t('vi.dpp')}</dt>
          <dd className="tabular-nums text-fg-body">{formatIDR(dpp)}</dd>
        </div>
        <div>
          <dt className="text-fg-muted">PPN</dt>
          <dd className="tabular-nums text-fg-body">{formatIDR(ppn)}</dd>
        </div>
        <div>
          <dt className="text-fg-muted">{t('vi.pph23Label', { pct: rate })}</dt>
          <dd className="tabular-nums text-fg-body">{formatIDR(pph)}</dd>
        </div>
        <div>
          <dt className="text-fg-muted">{t('vi.payable')}</dt>
          <dd className="font-heading text-card-title tabular-nums text-fg">
            {formatIDR(dpp + ppn - pph)}
          </dd>
        </div>
      </dl>
      {v.kind === 'service' && !npwp && <p className="text-small text-warning">{t('vi.noNpwp')}</p>}
      <Field label={t('gr.note')}>
        <Textarea rows={2} value={v.note} onChange={(e) => set({ ...v, note: e.target.value })} />
      </Field>
    </div>
  );
}

function toBody(v: FormState) {
  const dpp = v.dpp === '' ? linesTotal(v.lines) : money(v.dpp);
  return {
    invoice_no: v.invoiceNo.trim(),
    tax_invoice_no: v.taxNo.trim() || null,
    invoice_date: v.date,
    kind: v.kind,
    dpp: String(dpp),
    ppn: v.ppnManual ? moneyToApi(v.ppn) : null,
    term_days: v.term === '' ? null : Number(v.term),
    note: v.note.trim() || null,
    lines: v.lines
      .filter((l) => Number(qtyToApi(l.qty)) > 0)
      .map((l) => ({
        seq: l.seq,
        qty: qtyToApi(l.qty),
        unit_price: moneyToApi(l.price) ?? '0',
      })),
  };
}

const formReady = (v: FormState) =>
  v.invoiceNo.trim() !== '' &&
  v.date !== '' &&
  v.lines.some((l) => Number(qtyToApi(l.qty)) > 0) &&
  (v.dpp === '' ? linesTotal(v.lines) : money(v.dpp)) > 0;

export function VendorInvoiceNewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [poId, setPoId] = useState('');
  const options = usePoOptions(q);
  const prefill = usePrefill(poId);
  const create = useCreateVendorInvoice();
  const [form, setForm] = useState<FormState | null>(null);
  const p = prefill.data;
  const v: FormState | null =
    form ??
    (p
      ? {
          invoiceNo: '',
          taxNo: '',
          date: today(),
          kind: p.kind,
          dpp: '',
          ppn: '',
          ppnManual: false,
          term: String(p.term_days),
          note: '',
          lines: p.lines.map((l) => ({
            seq: l.seq,
            description: l.description,
            uom: l.uom,
            open: l.open,
            poPrice: l.unit_price,
            qty: qtyFmt(l.open),
            price: formatNumber(Number(l.unit_price)),
          })),
        }
      : null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('vi.new')}</CardTitle>
        <CardDescription>{t('vi.howTo')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <FormError message={errText(create.error ?? prefill.error, t('auth.unexpected'))} />
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('vi.searchPo')} className="w-56">
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} />
          </Field>
          <Field label="PO" required className="min-w-0 flex-1">
            <Select
              value={poId}
              onChange={(e) => {
                setPoId(e.target.value);
                setForm(null);
              }}
            >
              <option value="">{t('master.choose')}</option>
              {options.data?.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.number} · {o.vendor_name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {options.data?.length === 0 && (
          <p className="text-small text-fg-secondary">{t('vi.noPo')}</p>
        )}
        {p && v && (
          <>
            <p className="text-small text-fg-secondary">
              {p.vendor_name} · NPWP {p.vendor_npwp ?? '–'}
            </p>
            <InvoiceFields v={v} set={setForm} npwp={p.vendor_npwp} ppnPct={Number(p.ppn_pct)} />
            <Button
              variant="primary"
              className="self-end"
              disabled={!formReady(v) || create.isPending}
              onClick={() =>
                create.mutate(
                  { po_id: p.po_id, ...toBody(v) },
                  { onSuccess: (vi) => navigate(`/keuangan/tagihan-vendor/${vi.id}`) },
                )
              }
            >
              <Icon name="save" /> {t('vi.saveDraft')}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- detail

function fromDetail(d: ViDetail): FormState {
  const poPrice = new Map(d.match_result?.map((r) => [r.seq, r.po_price]) ?? []);
  return {
    invoiceNo: d.invoice_no,
    taxNo: d.tax_invoice_no ?? '',
    date: d.invoice_date,
    kind: d.kind,
    dpp: formatNumber(Number(d.dpp)),
    ppn: formatNumber(Number(d.ppn)),
    ppnManual: true,
    term: String(d.term_days),
    note: d.note ?? '',
    lines: d.lines.map((l) => ({
      seq: l.seq,
      description: l.description,
      poPrice: poPrice.get(l.seq),
      qty: qtyFmt(l.qty),
      price: formatNumber(Number(l.unit_price)),
    })),
  };
}

export function VendorInvoicePage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const vi = useVendorInvoice(id);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');
  const [mode, setMode] = useState<'none' | 'correct' | 'credit' | 'cancel'>('none');
  if (vi.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (vi.error || !vi.data) return <FormError message={errText(vi.error, t('auth.unexpected'))} />;
  const d = vi.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/keuangan/tagihan-vendor"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('vi.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {d.po_number} · {d.project_number}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{d.vendor_name}</CardTitle>
            <ViStatusPill status={d.status} />
          </div>
          <CardDescription>
            {t('vi.invoiceNo')}: {d.invoice_no} · {t('vi.taxInvoiceNo')}: {d.tax_invoice_no ?? '–'}{' '}
            · {formatDate(d.invoice_date)} · {t(`vi.kinds.${d.kind}`)}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-3 lg:grid-cols-6">
            <div>
              <dt className="text-fg-muted">{t('vi.dpp')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.dpp)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">PPN</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.ppn)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('vi.pph23Label', { pct: d.pph23_pct })}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.pph23)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('vi.payable')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {formatIDR(d.payable)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('vi.dueDate')}</dt>
              <dd className="text-fg-body">
                {d.due_date ? formatDate(d.due_date) : t('vi.termOnly', { days: d.term_days })}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('vi.outstanding')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.outstanding)}</dd>
            </div>
          </dl>
          {d.status === 'exception' && (
            <div
              role="alert"
              className="rounded-control border border-danger bg-danger-tint px-3 py-2 text-small text-danger"
            >
              <span className="font-semibold">{t('vi.exceptionTitle')}</span> {d.exception_reason}
            </div>
          )}
          {d.status === 'approved' && (
            <p className="rounded-control bg-success-tint px-3 py-2 text-small text-success">
              {t('vi.approvedNote')}
            </p>
          )}
          <Actions d={d} mode={mode} setMode={setMode} />
        </CardContent>
      </Card>
      {mode === 'correct' && <CorrectCard d={d} onDone={() => setMode('none')} />}
      {mode === 'credit' && <CreditNoteCard d={d} onDone={() => setMode('none')} />}
      <Tabs
        label={d.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'files', label: t('vi.documents') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && (
        <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
          <div className="flex flex-col gap-4">
            <MatchCard d={d} />
            {d.credit_notes.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>{t('vi.creditNotes')}</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2 text-small">
                  {d.credit_notes.map((c) => (
                    <p key={c.credit_note_no}>
                      <span className="font-semibold">{c.credit_note_no}</span> ·{' '}
                      {formatDate(c.note_date)} · DPP {formatIDR(c.dpp)} · PPN {formatIDR(c.ppn)}
                      <span className="block text-fg-secondary">{c.reason}</span>
                    </p>
                  ))}
                </CardContent>
              </Card>
            )}
          </div>
          {d.journal ? (
            <JournalCard journal={d.journal} />
          ) : (
            <Card>
              <CardContent className="pt-4 text-small text-fg-secondary">
                {t('vi.noJournal')}
              </CardContent>
            </Card>
          )}
        </div>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="vendor_invoice" entityId={d.id} canWrite={d.can_edit} />
      )}
      {tab === 'history' && <HistoryPanel entityType="vendor_invoice" entityId={d.id} />}
    </div>
  );
}

function Actions({
  d,
  mode,
  setMode,
}: {
  d: ViDetail;
  mode: string;
  setMode: (m: 'none' | 'correct' | 'credit' | 'cancel') => void;
}) {
  const { t } = useTranslation();
  const match = useMatchVendorInvoice(d.id);
  const cancel = useCancelVendorInvoice(d.id);
  const [reason, setReason] = useState('');
  if (!d.can_match && !d.can_edit) return null;
  return (
    <div className="flex flex-col gap-2">
      <FormError message={errText(match.error ?? cancel.error, t('auth.unexpected'))} />
      {d.can_match && (
        <>
          <p className="text-small text-fg-secondary">{t('vi.attachHint')}</p>
          <AttachmentsPanel entityType="vendor_invoice" entityId={d.id} canWrite />
        </>
      )}
      <div className="flex flex-wrap gap-2">
        {d.can_match && (
          <Button variant="primary" disabled={match.isPending} onClick={() => match.mutate()}>
            <Icon name="rule" /> {t('vi.match')}
          </Button>
        )}
        {d.can_edit && (
          <Button variant="secondary" onClick={() => setMode('correct')}>
            <Icon name="edit" /> {t('vi.correct')}
          </Button>
        )}
        {d.can_credit_note && (
          <Button variant="secondary" onClick={() => setMode('credit')}>
            <Icon name="receipt" /> {t('vi.creditNote')}
          </Button>
        )}
        {d.can_edit && (
          <Button variant="destructive" onClick={() => setMode('cancel')}>
            {t('vi.cancel')}
          </Button>
        )}
      </div>
      {mode === 'cancel' && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('vi.cancelReason')} required className="min-w-0 flex-1">
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Button
            variant="destructive"
            disabled={reason.trim().length < 5 || cancel.isPending}
            onClick={() => cancel.mutate(reason, { onSuccess: () => setMode('none') })}
          >
            {t('vi.confirmCancel')}
          </Button>
        </div>
      )}
    </div>
  );
}

function MatchCard({ d }: { d: ViDetail }) {
  const { t } = useTranslation();
  const ok = (b: boolean) => (
    <Icon
      name={b ? 'check_circle' : 'cancel'}
      className={b ? 'text-success' : 'text-danger'}
      label={b ? t('vi.ok') : t('vi.mismatch')}
    />
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('vi.matchTitle')}</CardTitle>
        <CardDescription>{t('vi.matchHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('quotation.description')}</TH>
              <TH className="text-right">PO</TH>
              <TH className="text-right">{t('gr.received')}</TH>
              <TH className="text-right">{t('vi.billedBefore')}</TH>
              <TH className="text-right">{t('vi.billed')}</TH>
              <TH className="text-right">{t('vi.poPrice')}</TH>
              <TH className="text-right">{t('vi.invoicePrice')}</TH>
            </TR>
          </THead>
          <TBody>
            {d.match_result
              ? d.match_result.map((r) => (
                  <TR key={r.seq}>
                    <TD className="min-w-40">{r.description}</TD>
                    <TD className="text-right tabular-nums">{qtyFmt(r.po_qty)}</TD>
                    <TD className="text-right tabular-nums">{qtyFmt(r.received)}</TD>
                    <TD className="text-right tabular-nums">{qtyFmt(r.invoiced_before)}</TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {qtyFmt(r.qty)} {ok(r.qty_ok)}
                    </TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(r.po_price)}
                    </TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(r.price)} {ok(r.price_ok)}
                    </TD>
                  </TR>
                ))
              : d.lines.map((l) => (
                  <TR key={l.seq}>
                    <TD>{l.description}</TD>
                    <TD colSpan={3} className="text-fg-secondary">
                      {t('vi.notMatched')}
                    </TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.qty)}</TD>
                    <TD />
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(l.unit_price)}
                    </TD>
                  </TR>
                ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function CorrectCard({ d, onDone }: { d: ViDetail; onDone: () => void }) {
  const { t } = useTranslation();
  const save = useCorrectVendorInvoice(d.id);
  const [v, setV] = useState<FormState>(() => fromDetail(d));
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('vi.correct')}</CardTitle>
        <CardDescription>{t('vi.correctHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(save.error, t('auth.unexpected'))} />
        <InvoiceFields v={v} set={setV} npwp={d.vendor_npwp} ppnPct={11} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onDone}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!formReady(v) || save.isPending}
            onClick={() => save.mutate(toBody(v), { onSuccess: onDone })}
          >
            <Icon name="save" /> {t('vi.saveCorrection')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function CreditNoteCard({ d, onDone }: { d: ViDetail; onDone: () => void }) {
  const { t } = useTranslation();
  const save = useCreditNote(d.id);
  const [cn, setCn] = useState({ no: '', date: today(), dpp: '', ppn: '', reason: '' });
  const [lines, setLines] = useState(fromDetail(d).lines);
  const ready =
    cn.no.trim() && money(cn.dpp) > 0 && cn.reason.trim().length >= 5 && lines.length > 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('vi.creditNote')}</CardTitle>
        <CardDescription>{t('vi.creditNoteHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(save.error, t('auth.unexpected'))} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t('vi.creditNoteNo')} required>
            <Input value={cn.no} onChange={(e) => setCn({ ...cn, no: e.target.value })} />
          </Field>
          <Field label={t('vi.date')} required>
            <Input
              type="date"
              value={cn.date}
              onChange={(e) => setCn({ ...cn, date: e.target.value })}
            />
          </Field>
          <Field label={t('vi.cnDpp')} required>
            <Input
              inputMode="numeric"
              className="text-right"
              value={cn.dpp}
              onChange={(e) => setCn({ ...cn, dpp: e.target.value })}
            />
          </Field>
          <Field label={t('vi.cnPpn')}>
            <Input
              inputMode="numeric"
              className="text-right"
              value={cn.ppn}
              onChange={(e) => setCn({ ...cn, ppn: e.target.value })}
            />
          </Field>
        </div>
        <p className="text-small text-fg-secondary">{t('vi.correctedLines')}</p>
        {lines.map((l, i) => (
          <div key={l.seq} className="flex flex-wrap items-end gap-2">
            <span className="min-w-40 flex-1 text-small">{l.description}</span>
            <Field label={`${t('quotation.qty')} ${l.seq}`} className="w-28">
              <Input
                inputMode="decimal"
                className="text-right"
                value={l.qty}
                onChange={(e) =>
                  setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))
                }
              />
            </Field>
            <Field label={`${t('quotation.unitPrice')} ${l.seq}`} className="w-40">
              <Input
                inputMode="numeric"
                className="text-right"
                value={l.price}
                onChange={(e) =>
                  setLines(lines.map((x, j) => (j === i ? { ...x, price: e.target.value } : x)))
                }
              />
            </Field>
          </div>
        ))}
        <Field label={t('vi.cnReason')} required>
          <Textarea
            rows={2}
            value={cn.reason}
            onChange={(e) => setCn({ ...cn, reason: e.target.value })}
          />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onDone}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!ready || save.isPending}
            onClick={() =>
              save.mutate(
                {
                  credit_note_no: cn.no.trim(),
                  note_date: cn.date,
                  dpp: moneyToApi(cn.dpp),
                  ppn: moneyToApi(cn.ppn) ?? '0',
                  reason: cn.reason.trim(),
                  lines: lines.map((l) => ({
                    seq: l.seq,
                    qty: qtyToApi(l.qty),
                    unit_price: moneyToApi(l.price) ?? '0',
                  })),
                },
                { onSuccess: onDone },
              )
            }
          >
            <Icon name="save" /> {t('vi.saveCreditNote')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
