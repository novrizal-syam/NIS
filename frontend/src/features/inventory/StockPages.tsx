import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import {
  stockExportPath,
  useCount,
  useCounts,
  useCreateCount,
  useCreateTransfer,
  useReorder,
  useStock,
  useSubmitCount,
  useTransfers,
  useValuation,
  useWarehouses,
  type CountStatus,
} from './api';
import { JournalCard } from './JournalCard';

type Tab = 'stock' | 'transfers' | 'counts' | 'reorder' | 'valuation';
const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const qtyToApi = (v: string) => v.replace(/\./g, '').replace(',', '.').trim();
const qtyFmt = (v: string) => v.replace('.', ',');
const COUNT_TONE: Record<CountStatus, StatusTone> = {
  draft: 'neutral',
  awaiting_approval: 'warning',
  approved: 'success',
  rejected: 'danger',
};
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

export function StockPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('stock');
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('stock.title')}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'stock', label: t('stock.tabs.stock') },
          { value: 'transfers', label: t('stock.tabs.transfers') },
          { value: 'counts', label: t('stock.tabs.counts') },
          { value: 'reorder', label: t('stock.tabs.reorder') },
          { value: 'valuation', label: t('stock.tabs.valuation') },
        ]}
      />
      {tab === 'stock' && <StockTab />}
      {tab === 'transfers' && <TransfersTab />}
      {tab === 'counts' && <CountsTab />}
      {tab === 'reorder' && <ReorderTab />}
      {tab === 'valuation' && <ValuationTab />}
    </div>
  );
}

function WarehouseSelect({
  value,
  onChange,
  label,
  allowAll,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  allowAll?: boolean;
}) {
  const { t } = useTranslation();
  const wh = useWarehouses();
  return (
    <Field label={label} className="w-56">
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{allowAll ? t('stock.allWarehouses') : t('master.choose')}</option>
        {wh.data?.map((w) => (
          <option key={w.code} value={w.code}>
            {w.code} · {w.name}
          </option>
        ))}
      </Select>
    </Field>
  );
}

function StockTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [warehouse, setWarehouse] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const list = useStock({ warehouse, q, page });
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <WarehouseSelect
          label={t('stock.warehouse')}
          value={warehouse}
          allowAll
          onChange={(v) => {
            setWarehouse(v);
            setPage(1);
          }}
        />
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('stock.search')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        {can('inventory', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile(stockExportPath({ warehouse, q }), 'stok.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
      </div>
      <p className="text-small text-fg-secondary">
        {t('stock.totalValue')}:{' '}
        <span className="font-semibold tabular-nums text-fg">
          {formatIDR(list.data?.total_value ?? '0')}
        </span>
      </p>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('stock.warehouse')}</TH>
              <TH>{t('mr.item')}</TH>
              <TH className="text-right">{t('quotation.qty')}</TH>
              <TH className="text-right">{t('stock.avgCost')}</TH>
              <TH className="text-right">{t('stock.value')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.items.length === 0 && (
              <TR>
                <TD colSpan={5} className="py-8 text-center text-fg-secondary">
                  {t('stock.empty')}
                </TD>
              </TR>
            )}
            {list.data?.items.map((r) => (
              <TR key={`${r.warehouse_code}-${r.item_code}`}>
                <TD>{r.warehouse_code}</TD>
                <TD className="min-w-48">
                  {r.name}
                  <span className="block text-caption text-fg-muted">{r.item_code}</span>
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {qtyFmt(r.qty)} {r.uom}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(Math.round(Number(r.avg_cost)))}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.value)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
      </Card>
    </>
  );
}

interface QtyLine {
  item: string;
  qty: string;
}

function LinesInput({
  lines,
  onChange,
  qtyLabel,
  withReason,
}: {
  lines: (QtyLine & { reason?: string })[];
  onChange: (l: (QtyLine & { reason?: string })[]) => void;
  qtyLabel: string;
  withReason?: boolean;
}) {
  const { t } = useTranslation();
  const set = (i: number, patch: Partial<QtyLine & { reason?: string }>) =>
    onChange(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <div className="flex flex-col gap-2">
      {lines.map((l, i) => (
        <div key={i} className="flex flex-wrap items-end gap-2">
          <Field label={`${t('stock.itemCode')} ${i + 1}`} className="w-40">
            <Input
              value={l.item}
              onChange={(e) => set(i, { item: e.target.value.toUpperCase() })}
            />
          </Field>
          <Field label={qtyLabel} className="w-28">
            <Input
              inputMode="decimal"
              className="text-right"
              value={l.qty}
              onChange={(e) => set(i, { qty: e.target.value })}
            />
          </Field>
          {withReason && (
            <Field label={t('stock.reason')} className="min-w-0 flex-1">
              <Input value={l.reason ?? ''} onChange={(e) => set(i, { reason: e.target.value })} />
            </Field>
          )}
          {lines.length > 1 && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={t('quotation.removeLine')}
              onClick={() => onChange(lines.filter((_, j) => j !== i))}
            >
              <Icon name="delete" />
            </Button>
          )}
        </div>
      ))}
      <Button
        variant="secondary"
        size="sm"
        className="self-start"
        onClick={() => onChange([...lines, { item: '', qty: '' }])}
      >
        <Icon name="add" /> {t('mr.addLine')}
      </Button>
    </div>
  );
}

function TransfersTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const list = useTransfers(page, true);
  const create = useCreateTransfer();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [note, setNote] = useState('');
  const [lines, setLines] = useState<QtyLine[]>([{ item: '', qty: '' }]);
  const ready =
    from && to && from !== to && lines.every((l) => l.item && Number(qtyToApi(l.qty)) > 0);
  return (
    <>
      {can('inventory', 'edit') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('stock.newTransfer')}</CardTitle>
            <CardDescription>{t('stock.transferHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <FormError message={errText(create.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap gap-2">
              <WarehouseSelect label={t('stock.from')} value={from} onChange={setFrom} />
              <WarehouseSelect label={t('stock.to')} value={to} onChange={setTo} />
            </div>
            <LinesInput lines={lines} onChange={setLines} qtyLabel={t('quotation.qty')} />
            <Field label={t('gr.note')}>
              <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <Button
              variant="primary"
              className="self-end"
              disabled={!ready || create.isPending}
              onClick={() =>
                create.mutate(
                  {
                    from_warehouse: from,
                    to_warehouse: to,
                    note: note.trim() || null,
                    lines: lines.map((l) => ({ item_code: l.item, qty: qtyToApi(l.qty) })),
                  },
                  {
                    onSuccess: () => {
                      setLines([{ item: '', qty: '' }]);
                      setNote('');
                    },
                  },
                )
              }
            >
              <Icon name="swap_horiz" /> {t('stock.transfer')}
            </Button>
          </CardContent>
        </Card>
      )}
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('stock.route')}</TH>
              <TH>{t('mr.item')}</TH>
              <TH className="text-right">{t('stock.value')}</TH>
              <TH>{t('stock.date')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.items.length === 0 && (
              <TR>
                <TD colSpan={5} className="py-8 text-center text-fg-secondary">
                  {t('stock.noTransfers')}
                </TD>
              </TR>
            )}
            {list.data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap font-semibold">{r.number}</TD>
                <TD className="whitespace-nowrap">
                  {r.from_warehouse} → {r.to_warehouse}
                </TD>
                <TD>{r.lines.map((l) => `${l.item_code} × ${qtyFmt(l.qty)}`).join(', ')}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.value)}</TD>
                <TD className="whitespace-nowrap">{formatDate(r.created_at)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
      </Card>
    </>
  );
}

export function CountStatusPill({ status }: { status: CountStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={COUNT_TONE[status]}>{t(`stock.countStatus.${status}`)}</StatusPill>;
}

function CountsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const list = useCounts(page, true);
  const create = useCreateCount();
  const [wh, setWh] = useState('');
  const [date, setDate] = useState(today());
  const [lines, setLines] = useState<(QtyLine & { reason?: string })[]>([{ item: '', qty: '' }]);
  const ready = wh && date && lines.every((l) => l.item && qtyToApi(l.qty) !== '');
  return (
    <>
      {can('inventory', 'edit') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('stock.newCount')}</CardTitle>
            <CardDescription>{t('stock.countHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <FormError message={errText(create.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap gap-2">
              <WarehouseSelect label={t('stock.warehouse')} value={wh} onChange={setWh} />
              <Field label={t('stock.date')} className="w-44">
                <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              </Field>
            </div>
            <LinesInput
              lines={lines}
              onChange={setLines}
              qtyLabel={t('stock.counted')}
              withReason
            />
            <Button
              variant="primary"
              className="self-end"
              disabled={!ready || create.isPending}
              onClick={() =>
                create.mutate(
                  {
                    warehouse_code: wh,
                    count_date: date,
                    lines: lines.map((l) => ({
                      item_code: l.item,
                      counted_qty: qtyToApi(l.qty),
                      reason: l.reason?.trim() || null,
                    })),
                  },
                  { onSuccess: (c) => navigate(`/gudang/opname/${c.id}`) },
                )
              }
            >
              <Icon name="save" /> {t('stock.saveCount')}
            </Button>
          </CardContent>
        </Card>
      )}
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('stock.warehouse')}</TH>
              <TH>{t('stock.date')}</TH>
              <TH className="text-right">{t('stock.variance')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.items.length === 0 && (
              <TR>
                <TD colSpan={5} className="py-8 text-center text-fg-secondary">
                  {t('stock.noCounts')}
                </TD>
              </TR>
            )}
            {list.data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/gudang/opname/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.number}
                  </Link>
                </TD>
                <TD>{r.warehouse_code}</TD>
                <TD className="whitespace-nowrap">{formatDate(r.count_date)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(r.variance_value)}
                </TD>
                <TD>
                  <CountStatusPill status={r.status} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
      </Card>
    </>
  );
}

function ReorderTab() {
  const { t } = useTranslation();
  const list = useReorder(true);
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardDescription>{t('stock.reorderHelp')}</CardDescription>
      </CardHeader>
      <Table>
        <THead>
          <TR>
            <TH>{t('mr.item')}</TH>
            <TH className="text-right">{t('stock.onHand')}</TH>
            <TH className="text-right">{t('stock.reorderPoint')}</TH>
            <TH className="text-right">{t('stock.suggested')}</TH>
            <TH className="text-right">{t('stock.estValue')}</TH>
          </TR>
        </THead>
        <TBody>
          {list.data?.length === 0 && (
            <TR>
              <TD colSpan={5} className="py-8 text-center text-fg-secondary">
                {t('stock.noReorder')}
              </TD>
            </TR>
          )}
          {list.data?.map((r) => (
            <TR key={r.item_code}>
              <TD className="min-w-48">
                {r.name}
                <span className="block text-caption text-fg-muted">{r.item_code}</span>
              </TD>
              <TD className="text-right tabular-nums">
                {qtyFmt(r.on_hand)} {r.uom}
              </TD>
              <TD className="text-right tabular-nums">{qtyFmt(r.reorder_point)}</TD>
              <TD className="text-right font-semibold tabular-nums">{qtyFmt(r.suggested_qty)}</TD>
              <TD className="whitespace-nowrap text-right tabular-nums">
                {formatIDR(r.est_value)}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </Card>
  );
}

function ValuationTab() {
  const { t } = useTranslation();
  const v = useValuation(true);
  if (!v.data) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  const d = v.data;
  return (
    <>
      <div
        role="status"
        className={
          d.reconciled
            ? 'rounded-control bg-success-tint px-3 py-2 text-small text-success'
            : 'rounded-control bg-danger-tint px-3 py-2 text-small text-danger'
        }
      >
        {d.reconciled
          ? t('stock.reconciled')
          : t('stock.notReconciled', { diff: formatIDR(d.difference) })}
      </div>
      <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-3">
        <div>
          <dt className="text-fg-muted">{t('stock.stockValue')}</dt>
          <dd className="font-heading text-card-title tabular-nums text-fg">
            {formatIDR(d.total)}
          </dd>
        </div>
        <div>
          <dt className="text-fg-muted">{t('stock.ledger1310')}</dt>
          <dd className="font-heading text-card-title tabular-nums text-fg">
            {formatIDR(d.ledger_1310)}
          </dd>
        </div>
        <div>
          <dt className="text-fg-muted">{t('stock.difference')}</dt>
          <dd className="tabular-nums text-fg-body">{formatIDR(d.difference)}</dd>
        </div>
      </dl>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('stock.warehouse')}</TH>
              <TH>{t('mr.item')}</TH>
              <TH className="text-right">{t('quotation.qty')}</TH>
              <TH className="text-right">{t('stock.avgCost')}</TH>
              <TH className="text-right">{t('stock.value')}</TH>
            </TR>
          </THead>
          <TBody>
            {d.rows.map((r) => (
              <TR key={`${r.warehouse_code}-${r.item_code}`}>
                <TD>{r.warehouse_code}</TD>
                <TD>
                  {r.name}
                  <span className="block text-caption text-fg-muted">{r.item_code}</span>
                </TD>
                <TD className="text-right tabular-nums">
                  {qtyFmt(r.qty)} {r.uom}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(Math.round(Number(r.avg_cost)))}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.value)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

export function CountPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const sc = useCount(id);
  const submit = useSubmitCount(id);
  if (sc.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (sc.error || !sc.data) return <FormError message={errText(sc.error, t('auth.unexpected'))} />;
  const d = sc.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/gudang/stok"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('stock.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {d.warehouse_code}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">
              {t('stock.countTitle', { date: formatDate(d.count_date) })}
            </CardTitle>
            <CountStatusPill status={d.status} />
          </div>
          <CardDescription>
            {t('stock.variance')}: {formatIDR(d.variance_value)}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <FormError message={errText(submit.error, t('auth.unexpected'))} />
          {d.reject_reason && (
            <p className="rounded-control bg-warning-tint px-3 py-2 text-small text-warning">
              {t('pr.rejected')}: {d.reject_reason}
            </p>
          )}
          {d.request_id && (
            <Link
              to={`/persetujuan/${d.request_id}`}
              className="text-small font-semibold text-fg-accent underline"
            >
              {t('crm.openApproval')}
            </Link>
          )}
          {d.can_submit && (
            <>
              <Button
                variant="primary"
                className="self-start"
                disabled={submit.isPending}
                onClick={() => submit.mutate()}
              >
                <Icon name="send" /> {t('stock.submitCount')}
              </Button>
              <p className="text-caption text-fg-muted">{t('stock.submitHelp')}</p>
            </>
          )}
        </CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
        <Card>
          <CardContent className="overflow-x-auto pt-4">
            <Table>
              <THead>
                <TR>
                  <TH>{t('mr.item')}</TH>
                  <TH className="text-right">{t('stock.system')}</TH>
                  <TH className="text-right">{t('stock.counted')}</TH>
                  <TH className="text-right">{t('stock.difference')}</TH>
                  <TH className="text-right">{t('stock.variance')}</TH>
                </TR>
              </THead>
              <TBody>
                {d.lines.map((l) => (
                  <TR key={l.item_code}>
                    <TD className="min-w-48">
                      {l.name}
                      <span className="block text-caption text-fg-muted">
                        {l.item_code}
                        {l.reason ? ` · ${l.reason}` : ''}
                      </span>
                    </TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.system_qty)}</TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.counted_qty)}</TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.variance_qty)}</TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(l.variance_value)}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
        {d.journal && <JournalCard journal={d.journal} />}
      </div>
    </div>
  );
}
