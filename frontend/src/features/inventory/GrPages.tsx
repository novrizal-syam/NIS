import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
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
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import {
  useCancelGr,
  useCreateGr,
  useGr,
  useGrs,
  usePostGr,
  useReceivable,
  useWarehouses,
  type GrStatus,
} from './api';
import { JournalCard } from './JournalCard';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const qtyToApi = (v: string) => v.replace(/\./g, '').replace(',', '.').trim();
const qtyFmt = (v: string) => v.replace('.', ',');
const TONE: Record<GrStatus, StatusTone> = {
  draft: 'warning',
  posted: 'success',
  cancelled: 'neutral',
};
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

export function GrStatusPill({ status }: { status: GrStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`gr.status.${status}`)}</StatusPill>;
}

export function GrListPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<GrStatus | ''>('');
  const [page, setPage] = useState(1);
  const list = useGrs({ status, page });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.status')} className="w-48">
          <Select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as GrStatus | '');
              setPage(1);
            }}
          >
            <option value="">{t('gr.allStatus')}</option>
            {(['draft', 'posted', 'cancelled'] as const).map((x) => (
              <option key={x} value={x}>
                {t(`gr.status.${x}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Button
          variant="secondary"
          className="ml-auto"
          onClick={() => void downloadFile('/inventory/grs/export', 'gr.xlsx')}
        >
          <Icon name="download" /> {t('list.export')}
        </Button>
      </div>
      <p className="text-small text-fg-secondary">{t('gr.howTo')}</p>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>PO</TH>
              <TH>{t('gr.kind')}</TH>
              <TH>{t('gr.receivedDate')}</TH>
              <TH className="text-right">{t('gr.amount')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.items.length === 0 && (
              <TR>
                <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                  {t('gr.empty')}
                </TD>
              </TR>
            )}
            {list.data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/gudang/gr/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.number}
                  </Link>
                </TD>
                <TD className="whitespace-nowrap">
                  {r.po_number}
                  <span className="block text-caption text-fg-muted">{r.vendor_code}</span>
                </TD>
                <TD>
                  {t(`gr.kinds.${r.kind}`)}
                  {r.warehouse_code && (
                    <span className="block text-caption text-fg-muted">{r.warehouse_code}</span>
                  )}
                </TD>
                <TD className="whitespace-nowrap">{formatDate(r.received_date)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.amount)}</TD>
                <TD>
                  <GrStatusPill status={r.status} />
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

/** New GR from a PO: quantities default to what is still open (full receipt). */
export function GrNewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const poId = params.get('po') ?? '';
  const rec = useReceivable(poId);
  const warehouses = useWarehouses();
  const create = useCreateGr();
  const [qty, setQty] = useState<Record<number, string> | null>(null);
  const [v, setV] = useState({ date: today(), warehouse: '', deliveryNote: '', note: '' });
  if (!poId) return <FormError message={t('gr.noPo')} />;
  if (rec.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (rec.error || !rec.data)
    return <FormError message={errText(rec.error, t('auth.unexpected'))} />;
  const d = rec.data;
  const values =
    qty ?? Object.fromEntries(d.lines.map((l) => [l.seq, qtyFmt(l.open === '0' ? '0' : l.open)]));
  const picked = d.lines.filter((l) => Number(qtyToApi(values[l.seq] ?? '0')) > 0);
  const tooMuch = d.lines.some((l) => Number(qtyToApi(values[l.seq] ?? '0')) > Number(l.open));
  const total = d.lines.reduce(
    (a, l) => a + Number(qtyToApi(values[l.seq] ?? '0')) * Number(l.unit_price),
    0,
  );
  const hasItems = d.lines.some((l) => l.item_code);

  return (
    <div className="flex flex-col gap-4">
      <Link
        to={`/pengadaan/po/${d.po_id}`}
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {d.po_number}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.po_number} · {t(`gr.kinds.${d.kind}`)}
          </p>
          <CardTitle className="text-section-title">{t('gr.new')}</CardTitle>
          <CardDescription>
            {d.vendor_name} · {d.kind === 'goods' ? t('gr.goodsWho') : t('gr.serviceWho')}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {!d.can_receive && <FormError message={t('gr.notAllowed')} />}
          <FormError message={errText(create.error, t('auth.unexpected'))} />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label={t('gr.receivedDate')} required>
              <Input
                type="date"
                value={v.date}
                max={today()}
                onChange={(e) => setV({ ...v, date: e.target.value })}
              />
            </Field>
            {d.kind === 'goods' && hasItems && (
              <Field label={t('gr.warehouse')} hint={t('gr.warehouseHint')}>
                <Select
                  value={v.warehouse}
                  onChange={(e) => setV({ ...v, warehouse: e.target.value })}
                >
                  <option value="">{t('gr.direct')}</option>
                  {warehouses.data?.map((w) => (
                    <option key={w.code} value={w.code}>
                      {w.code} · {w.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <Field label={d.kind === 'goods' ? t('gr.deliveryNote') : t('gr.bastNo')}>
              <Input
                value={v.deliveryNote}
                maxLength={60}
                onChange={(e) => setV({ ...v, deliveryNote: e.target.value })}
              />
            </Field>
          </div>
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>{t('quotation.description')}</TH>
                  <TH className="text-right">{t('gr.ordered')}</TH>
                  <TH className="text-right">{t('gr.received')}</TH>
                  <TH className="w-32 text-right">{t('gr.receiveNow')}</TH>
                  <TH>{t('quotation.unit')}</TH>
                </TR>
              </THead>
              <TBody>
                {d.lines.map((l) => (
                  <TR key={l.seq}>
                    <TD className="min-w-48">
                      {l.description}
                      {l.item_code && (
                        <span className="block text-caption text-fg-muted">{l.item_code}</span>
                      )}
                    </TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.ordered)}</TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.received)}</TD>
                    <TD>
                      <Input
                        aria-label={`${t('gr.receiveNow')} ${l.description}`}
                        inputMode="decimal"
                        className="text-right"
                        value={values[l.seq] ?? '0'}
                        disabled={l.open === '0'}
                        onChange={(e) => setQty({ ...values, [l.seq]: e.target.value })}
                      />
                    </TD>
                    <TD>{l.uom}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
          {tooMuch && <p className="text-small text-danger">{t('gr.tooMuch')}</p>}
          <Field label={t('gr.note')}>
            <Textarea
              rows={2}
              value={v.note}
              onChange={(e) => setV({ ...v, note: e.target.value })}
            />
          </Field>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-small text-fg-secondary">
              {t('gr.amount')}:{' '}
              <span className="font-semibold tabular-nums text-fg">{formatIDR(total)}</span>
            </span>
            <Button
              variant="primary"
              disabled={!d.can_receive || picked.length === 0 || tooMuch || create.isPending}
              onClick={() =>
                create.mutate(
                  {
                    po_id: d.po_id,
                    received_date: v.date,
                    warehouse_code: v.warehouse || null,
                    delivery_note: v.deliveryNote.trim() || null,
                    note: v.note.trim() || null,
                    lines: picked.map((l) => ({ seq: l.seq, qty: qtyToApi(values[l.seq]!) })),
                  },
                  { onSuccess: (gr) => navigate(`/gudang/gr/${gr.id}`) },
                )
              }
            >
              <Icon name="save" /> {t('gr.saveDraft')}
            </Button>
          </div>
          <p className="text-caption text-fg-muted">{t('gr.evidenceHint')}</p>
        </CardContent>
      </Card>
    </div>
  );
}

export function GrPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const gr = useGr(id);
  const post = usePostGr(id);
  const cancel = useCancelGr(id);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');
  if (gr.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (gr.error || !gr.data) return <FormError message={errText(gr.error, t('auth.unexpected'))} />;
  const d = gr.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/gudang/gr"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('gr.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {d.project_number} · {d.cost_element_code}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{d.vendor_name}</CardTitle>
            <GrStatusPill status={d.status} />
          </div>
          <CardDescription>
            <Link to={`/pengadaan/po/${d.po_id}`} className="underline">
              {d.po_number}
            </Link>{' '}
            · {t(`gr.kinds.${d.kind}`)} · {formatDate(d.received_date)}
            {d.warehouse_code ? ` · ${t('gr.toStock', { wh: d.warehouse_code })}` : ''}
            {d.delivery_note ? ` · ${d.delivery_note}` : ''}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="font-heading text-card-title tabular-nums text-fg">{formatIDR(d.amount)}</p>
          <FormError message={errText(post.error ?? cancel.error, t('auth.unexpected'))} />
          {d.can_post && (
            <>
              <p className="rounded-control bg-warning-tint px-3 py-2 text-small text-warning">
                {d.kind === 'goods' ? t('gr.attachGoods') : t('gr.attachService')}
              </p>
              <AttachmentsPanel entityType="goods_receipt" entityId={d.id} canWrite />
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" disabled={post.isPending} onClick={() => post.mutate()}>
                  <Icon name="task_alt" /> {t('gr.post')}
                </Button>
                <Button
                  variant="destructive"
                  disabled={cancel.isPending}
                  onClick={() => cancel.mutate()}
                >
                  {t('gr.cancel')}
                </Button>
              </div>
              <p className="text-caption text-fg-muted">{t('gr.postHelp')}</p>
            </>
          )}
        </CardContent>
      </Card>
      <Tabs
        label={d.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'files', label: t('gr.evidence') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && (
        <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
          <Card>
            <CardContent className="overflow-x-auto pt-4">
              <Table>
                <THead>
                  <TR>
                    <TH>{t('quotation.description')}</TH>
                    <TH className="text-right">{t('quotation.qty')}</TH>
                    <TH>{t('quotation.unit')}</TH>
                    <TH className="text-right">{t('quotation.unitPrice')}</TH>
                    <TH className="text-right">{t('quotation.amount')}</TH>
                  </TR>
                </THead>
                <TBody>
                  {d.lines.map((l) => (
                    <TR key={l.seq}>
                      <TD className="min-w-48">
                        {l.description}
                        <span className="block text-caption text-fg-muted">
                          {l.item_code ?? ''}
                          {l.to_stock ? ` · ${t('gr.toStock', { wh: d.warehouse_code })}` : ''}
                        </span>
                      </TD>
                      <TD className="text-right tabular-nums">{qtyFmt(l.qty)}</TD>
                      <TD>{l.uom}</TD>
                      <TD className="whitespace-nowrap text-right tabular-nums">
                        {formatIDR(l.unit_price)}
                      </TD>
                      <TD className="whitespace-nowrap text-right tabular-nums">
                        {formatIDR(l.amount)}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {d.note && <p className="mt-3 text-small text-fg-body">{d.note}</p>}
            </CardContent>
          </Card>
          {d.journal ? (
            <JournalCard journal={d.journal} />
          ) : (
            <Card>
              <CardContent className="pt-4 text-small text-fg-secondary">
                {t('gr.noJournal')}
              </CardContent>
            </Card>
          )}
        </div>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="goods_receipt" entityId={d.id} canWrite={d.can_post} />
      )}
      {tab === 'history' && <HistoryPanel entityType="goods_receipt" entityId={d.id} />}
    </div>
  );
}
