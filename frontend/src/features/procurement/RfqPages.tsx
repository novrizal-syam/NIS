import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError } from '@/lib/api';
import { formatDate, formatIDR, formatNumber } from '@/lib/format';
import { cn } from '@/lib/utils';
import {
  useAward,
  useCreatePo,
  useCreateRfq,
  usePriceHistory,
  useRecordQuote,
  useRfq,
  useRfqVendors,
  useRfqs,
  useVendorCategories,
  type RfqDetail,
  type RfqQuote,
} from './rfqApi';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const TONE: Record<RfqDetail['status'], StatusTone> = {
  open: 'info',
  award_pending: 'warning',
  awarded: 'success',
  cancelled: 'neutral',
};

export function RfqStatusPill({ status }: { status: RfqDetail['status'] }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`rfq.status.${status}`)}</StatusPill>;
}

/** From an Approved PR: choose the vendor category and >= 3 qualified vendors. */
export function CreateRfqDialog({ prId, onClose }: { prId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const categories = useVendorCategories();
  const [category, setCategory] = useState('');
  const vendors = useRfqVendors(category);
  const create = useCreateRfq();
  const [picked, setPicked] = useState<string[]>([]);
  const [due, setDue] = useState('');
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('rfq.create')}
      description={t('rfq.createHelp')}
      className="max-w-2xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={picked.length < 3 || create.isPending}
            onClick={() =>
              create.mutate(
                { pr_id: prId, category, vendor_codes: picked, due_date: due || null },
                { onSuccess: (r) => navigate(`/pengadaan/rfq/${r.id}`) },
              )
            }
          >
            {t('rfq.send', { count: picked.length })}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <FormError message={errText(create.error, t('auth.unexpected'))} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('rfq.category')} required>
            <Select
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPicked([]);
              }}
            >
              <option value="">–</option>
              {categories.data?.map((c) => (
                <option key={c} value={c}>
                  {t(`rfq.categories.${c}`, { defaultValue: c })}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('rfq.dueDate')}>
            <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </Field>
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-small font-semibold text-fg">{t('rfq.vendors')}</legend>
          {vendors.data?.map((v) => (
            <label
              key={v.code}
              className={cn(
                'flex items-center gap-2 text-small',
                v.excluded ? 'text-fg-muted' : 'text-fg-body',
              )}
            >
              <input
                type="checkbox"
                disabled={v.excluded !== null}
                checked={picked.includes(v.code)}
                onChange={(e) =>
                  setPicked(
                    e.target.checked ? [...picked, v.code] : picked.filter((x) => x !== v.code),
                  )
                }
              />
              {v.name}
              <span className="text-caption text-fg-muted">
                {v.code} · {t('rfq.rating')} {v.rating ?? '–'}
              </span>
              {v.excluded && <StatusPill tone="danger">{v.excluded}</StatusPill>}
            </label>
          ))}
        </fieldset>
      </div>
    </Dialog>
  );
}

export function RfqListPage() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const list = useRfqs({ page });
  return (
    <Card className="overflow-hidden">
      <Table>
        <THead>
          <TR>
            <TH>{t('crm.number')}</TH>
            <TH>PR</TH>
            <TH>{t('rfq.category')}</TH>
            <TH className="text-right">{t('pr.total')}</TH>
            <TH>{t('master.status')}</TH>
            <TH>{t('rfq.winner')}</TH>
          </TR>
        </THead>
        <TBody>
          {list.data?.items.length === 0 && (
            <TR>
              <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                {t('rfq.empty')}
              </TD>
            </TR>
          )}
          {list.data?.items.map((r) => (
            <TR key={r.id}>
              <TD>
                <Link
                  to={`/pengadaan/rfq/${r.id}`}
                  className="font-semibold text-fg underline-offset-2 hover:underline"
                >
                  {r.number}
                </Link>
              </TD>
              <TD>{r.pr_number}</TD>
              <TD>{t(`rfq.categories.${r.category}`, { defaultValue: r.category })}</TD>
              <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.pr_total)}</TD>
              <TD>
                <RfqStatusPill status={r.status} />
              </TD>
              <TD>{r.awarded_vendor_code ?? '–'}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <Pagination page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
    </Card>
  );
}

export function RfqPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const rfq = useRfq(id);
  if (rfq.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (rfq.error || !rfq.data)
    return <FormError message={errText(rfq.error, t('auth.unexpected'))} />;
  const d = rfq.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to={`/pengadaan/pr/${d.pr_id}`}
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {d.pr_number}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {t(`rfq.categories.${d.category}`, { defaultValue: d.category })}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">
              {t('rfq.title', { pr: d.pr_number })}
            </CardTitle>
            <RfqStatusPill status={d.status} />
          </div>
          <CardDescription>
            {t('rfq.weightsInfo', d.weights)}
            {d.due_date && ` · ${t('rfq.dueDate')}: ${formatDate(d.due_date)}`}
          </CardDescription>
        </CardHeader>
      </Card>
      <PriceHistoryCard d={d} />
      <QuotesCard d={d} />
      <AwardCard d={d} />
      <HistoryPanel entityType="rfq" entityId={d.id} />
    </div>
  );
}

function PriceHistoryCard({ d }: { d: RfqDetail }) {
  const { t } = useTranslation();
  const first = d.pr_lines[0];
  const [open, setOpen] = useState(false);
  const history = usePriceHistory(
    first?.item_code
      ? { item_code: first.item_code }
      : { q: first?.description.split(' ').slice(0, 2).join(' ') },
    open && first !== undefined,
  );
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 pt-4">
        <Button variant="ghost" size="sm" className="self-start" onClick={() => setOpen(!open)}>
          <Icon name="history" /> {t('rfq.priceHistory')}
        </Button>
        {open && (
          <Table>
            <THead>
              <TR>
                <TH>{t('quotation.description')}</TH>
                <TH>{t('rfq.vendor')}</TH>
                <TH className="text-right">{t('quotation.unitPrice')}</TH>
                <TH>{t('rfq.source')}</TH>
                <TH>{t('rfq.date')}</TH>
              </TR>
            </THead>
            <TBody>
              {history.data?.length === 0 && (
                <TR>
                  <TD colSpan={5} className="text-center text-fg-secondary">
                    {t('rfq.noHistory')}
                  </TD>
                </TR>
              )}
              {history.data?.map((h, i) => (
                <TR key={i}>
                  <TD>{h.description}</TD>
                  <TD>{h.vendor_name}</TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(h.unit_price)}/{h.uom}
                  </TD>
                  <TD>
                    {t(`rfq.sources.${h.source}`)} · {h.doc_number}
                  </TD>
                  <TD className="whitespace-nowrap">{formatDate(h.at)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function QuotesCard({ d }: { d: RfqDetail }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<RfqQuote | null>(null);
  const [files, setFiles] = useState<RfqQuote | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('rfq.quotes')}</CardTitle>
        <CardDescription>{t('rfq.quotesHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('rfq.vendor')}</TH>
              <TH>{t('master.status')}</TH>
              <TH className="text-right">{t('pr.total')}</TH>
              <TH className="text-right">{t('rfq.days')}</TH>
              <TH className="text-right">{t('rfq.scorePrice')}</TH>
              <TH className="text-right">{t('rfq.scoreDelivery')}</TH>
              <TH className="text-right">{t('rfq.scoreRating')}</TH>
              <TH className="text-right">{t('rfq.scoreTotal')}</TH>
              <TH>{''}</TH>
            </TR>
          </THead>
          <TBody>
            {d.quotes.map((q) => {
              const best = q.vendor_code === d.best_vendor_code;
              return (
                <TR key={q.id} className={cn(best && 'bg-success-tint')}>
                  <TD className="min-w-44">
                    {q.vendor_name}
                    <span className="block text-caption text-fg-muted">
                      {q.vendor_code} · {t('rfq.rating')} {q.rating ?? '–'}
                    </span>
                  </TD>
                  <TD>
                    <StatusPill tone={q.status === 'quoted' ? 'success' : 'neutral'}>
                      {t(`rfq.quoteStatus.${q.status}`)}
                    </StatusPill>
                    {best && (
                      <StatusPill tone="success" className="ml-1">
                        {t('rfq.best')}
                      </StatusPill>
                    )}
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {q.total ? formatIDR(q.total) : '–'}
                  </TD>
                  <TD className="text-right tabular-nums">{q.delivery_days ?? '–'}</TD>
                  <TD className="text-right tabular-nums">{q.score?.price ?? '–'}</TD>
                  <TD className="text-right tabular-nums">{q.score?.delivery ?? '–'}</TD>
                  <TD className="text-right tabular-nums">{q.score?.rating ?? '–'}</TD>
                  <TD className="text-right font-semibold tabular-nums text-fg">
                    {q.score?.total ?? '–'}
                  </TD>
                  <TD className="whitespace-nowrap">
                    {d.can_edit && (
                      <Button size="sm" variant="secondary" onClick={() => setEditing(q)}>
                        {t('rfq.enterQuote')}
                      </Button>
                    )}{' '}
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`${t('crm.tabFiles')} ${q.vendor_name}`}
                      onClick={() => setFiles(q)}
                    >
                      <Icon name="attach_file" />
                    </Button>
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </CardContent>
      {editing && <QuoteDialog d={d} q={editing} onClose={() => setEditing(null)} />}
      <Dialog
        open={files !== null}
        onClose={() => setFiles(null)}
        title={files?.vendor_name ?? ''}
        className="max-w-2xl"
      >
        {files && (
          <AttachmentsPanel entityType="rfq_quote" entityId={files.id} canWrite={d.can_edit} />
        )}
      </Dialog>
    </Card>
  );
}

function QuoteDialog({ d, q, onClose }: { d: RfqDetail; q: RfqQuote; onClose: () => void }) {
  const { t } = useTranslation();
  const save = useRecordQuote(d.id);
  const [prices, setPrices] = useState<Record<number, string>>(
    Object.fromEntries(q.lines.map((l) => [l.seq, formatNumber(Number(l.unit_price))])),
  );
  const [v, setV] = useState({
    days: q.delivery_days?.toString() ?? '',
    terms: q.payment_terms ?? '',
    valid: q.valid_until ?? '',
    note: q.note ?? '',
  });
  const submit = (declined: boolean) =>
    save.mutate(
      {
        quoteId: q.id,
        body: declined
          ? { declined: true }
          : {
              unit_prices: Object.fromEntries(
                d.pr_lines.map((l) => [l.seq, moneyToApi(prices[l.seq] ?? '') ?? '0']),
              ),
              delivery_days: Number(v.days || 0),
              payment_terms: v.terms || null,
              valid_until: v.valid || null,
              note: v.note || null,
            },
      },
      { onSuccess: onClose },
    );
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('rfq.quoteFor', { vendor: q.vendor_name })}
      className="max-w-2xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => submit(true)}>
            {t('rfq.declined')}
          </Button>
          <Button
            variant="primary"
            disabled={save.isPending || d.pr_lines.some((l) => !prices[l.seq])}
            onClick={() => submit(false)}
          >
            {t('master.save')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <FormError message={errText(save.error, t('auth.unexpected'))} />
        {d.pr_lines.map((l) => (
          <Field
            key={l.seq}
            label={`${l.description} (${l.qty.replace('.', ',')} ${l.uom})`}
            hint={t('quotation.unitPrice')}
          >
            <Input
              inputMode="numeric"
              value={prices[l.seq] ?? ''}
              onChange={(e) => setPrices({ ...prices, [l.seq]: e.target.value })}
            />
          </Field>
        ))}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t('rfq.days')} required>
            <Input
              type="number"
              min={0}
              value={v.days}
              onChange={(e) => setV({ ...v, days: e.target.value })}
            />
          </Field>
          <Field label={t('rfq.terms')}>
            <Input value={v.terms} onChange={(e) => setV({ ...v, terms: e.target.value })} />
          </Field>
          <Field label={t('rfq.validUntil')}>
            <Input
              type="date"
              value={v.valid}
              onChange={(e) => setV({ ...v, valid: e.target.value })}
            />
          </Field>
        </div>
        <Field label={t('quotation.notes')}>
          <Textarea
            rows={2}
            value={v.note}
            onChange={(e) => setV({ ...v, note: e.target.value })}
          />
        </Field>
      </div>
    </Dialog>
  );
}

function AwardCard({ d }: { d: RfqDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const award = useAward(d.id);
  const createPo = useCreatePo(d.id);
  const quoted = d.quotes.filter((q) => q.status === 'quoted');
  const [vendor, setVendor] = useState(d.best_vendor_code ?? '');
  const [reason, setReason] = useState('');
  const nonBest = vendor !== '' && vendor !== d.best_vendor_code;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('rfq.award')}</CardTitle>
        <CardDescription>{t('rfq.awardHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(award.error ?? createPo.error, t('auth.unexpected'))} />
        {d.status === 'awarded' && (
          <p role="status" className="text-small font-medium text-success">
            {t('rfq.awardedTo', { vendor: d.awarded_vendor_code })}
            {d.award_reason && ` · ${d.award_reason}`}
          </p>
        )}
        {d.status === 'award_pending' && (
          <p role="status" className="text-small text-warning">
            {t('rfq.pending', { vendor: d.pending_vendor_code })}{' '}
            {d.request_id && (
              <Link to={`/persetujuan/${d.request_id}`} className="underline">
                {t('crm.openApproval')}
              </Link>
            )}
          </p>
        )}
        {d.can_edit && quoted.length > 0 && (
          <>
            <Field label={t('rfq.winner')}>
              <Select value={vendor} onChange={(e) => setVendor(e.target.value)}>
                {quoted.map((q) => (
                  <option key={q.vendor_code} value={q.vendor_code}>
                    {q.vendor_name} · {q.score?.total}
                    {q.vendor_code === d.best_vendor_code ? ` (${t('rfq.best')})` : ''}
                  </option>
                ))}
              </Select>
            </Field>
            {nonBest && (
              <Field label={t('rfq.reason')} required hint={t('rfq.reasonHint')}>
                <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
            )}
            <Button
              variant="primary"
              className="self-start"
              disabled={!vendor || (nonBest && reason.trim().length < 10) || award.isPending}
              onClick={() => award.mutate({ vendor_code: vendor, ...(nonBest ? { reason } : {}) })}
            >
              {nonBest ? t('rfq.submitAward') : t('rfq.confirmAward')}
            </Button>
          </>
        )}
        {d.po && (
          <Link
            to={`/pengadaan/po/${d.po.id}`}
            className="text-small font-semibold text-fg-accent underline"
          >
            {d.po.number}
          </Link>
        )}
        {d.can_create_po && (
          <Button
            variant="primary"
            className="self-start"
            disabled={createPo.isPending}
            onClick={() =>
              createPo.mutate(undefined, { onSuccess: (po) => navigate(`/pengadaan/po/${po.id}`) })
            }
          >
            <Icon name="shopping_cart" /> {t('rfq.createPo')}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
