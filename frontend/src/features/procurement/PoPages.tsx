import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Textarea } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError } from '@/lib/api';
import { formatDate, formatIDR, formatNumber } from '@/lib/format';
import {
  useIssuePo,
  usePo,
  usePos,
  useRevisePo,
  useSavePo,
  type PoDetail,
  type PoLine,
} from './rfqApi';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const TONE: Record<PoDetail['status'], StatusTone> = {
  draft: 'neutral',
  issued: 'success',
  revision_pending: 'warning',
  cancelled: 'neutral',
  closed: 'neutral',
};
const qtyToApi = (v: string) => v.replace(/\./g, '').replace(',', '.').trim();

export function PoStatusPill({ status }: { status: PoDetail['status'] }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`po.status.${status}`)}</StatusPill>;
}

export function PoListPage() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const list = usePos({ page });
  return (
    <Card className="overflow-hidden">
      <Table>
        <THead>
          <TR>
            <TH>{t('crm.number')}</TH>
            <TH>{t('rfq.vendor')}</TH>
            <TH className="text-right">{t('po.subtotal')}</TH>
            <TH className="text-right">{t('pr.total')}</TH>
            <TH>{t('master.status')}</TH>
            <TH>{t('po.deliveryDate')}</TH>
          </TR>
        </THead>
        <TBody>
          {list.data?.items.length === 0 && (
            <TR>
              <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                {t('po.empty')}
              </TD>
            </TR>
          )}
          {list.data?.items.map((r) => (
            <TR key={r.id}>
              <TD>
                <Link
                  to={`/pengadaan/po/${r.id}`}
                  className="font-semibold text-fg underline-offset-2 hover:underline"
                >
                  {r.number}
                  {r.revision > 0 && ` Rev.${r.revision}`}
                </Link>
              </TD>
              <TD>{r.vendor_name}</TD>
              <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.subtotal)}</TD>
              <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.total)}</TD>
              <TD>
                <PoStatusPill status={r.status} />
              </TD>
              <TD className="whitespace-nowrap">
                {r.delivery_date ? formatDate(r.delivery_date) : '–'}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <Pagination page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
    </Card>
  );
}

function LinesEditor({ lines, onChange }: { lines: PoLine[]; onChange: (l: PoLine[]) => void }) {
  const { t } = useTranslation();
  const set = (i: number, patch: Partial<PoLine>) =>
    onChange(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <div className="overflow-x-auto">
      <Table>
        <THead>
          <TR>
            <TH>{t('quotation.description')}</TH>
            <TH className="w-24 text-right">{t('quotation.qty')}</TH>
            <TH className="w-20">{t('quotation.unit')}</TH>
            <TH className="w-40 text-right">{t('quotation.unitPrice')}</TH>
          </TR>
        </THead>
        <TBody>
          {lines.map((l, i) => (
            <TR key={l.seq}>
              <TD className="min-w-48">{l.description}</TD>
              <TD>
                <Input
                  aria-label={`${t('quotation.qty')} ${i + 1}`}
                  inputMode="decimal"
                  className="text-right"
                  value={l.qty}
                  onChange={(e) => set(i, { qty: e.target.value })}
                />
              </TD>
              <TD>{l.uom}</TD>
              <TD>
                <Input
                  aria-label={`${t('quotation.unitPrice')} ${i + 1}`}
                  inputMode="numeric"
                  className="text-right"
                  value={l.unit_price}
                  onChange={(e) => set(i, { unit_price: e.target.value })}
                />
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

const toEditable = (lines: PoLine[]): PoLine[] =>
  lines.map((l) => ({
    ...l,
    qty: l.qty.replace('.', ','),
    unit_price: formatNumber(Number(l.unit_price)),
  }));
const toApi = (lines: PoLine[]) =>
  lines.map((l) => ({
    seq: l.seq,
    item_code: l.item_code,
    description: l.description,
    qty: qtyToApi(l.qty),
    uom: l.uom,
    unit_price: moneyToApi(l.unit_price) ?? '0',
  }));

export function PoPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const po = usePo(id);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');
  if (po.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (po.error || !po.data) return <FormError message={errText(po.error, t('auth.unexpected'))} />;
  const d = po.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/pengadaan/po"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('po.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number}
            {d.revision > 0 && ` Rev.${d.revision}`} · {d.project_number} · {d.wbs_code}/
            {d.cost_element_code}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{d.vendor_name}</CardTitle>
            <PoStatusPill status={d.status} />
          </div>
          <CardDescription>
            <Link to={`/pengadaan/pr/${d.pr_id}`} className="underline">
              {d.pr_number}
            </Link>
            {d.rfq_id && (
              <>
                {' · '}
                <Link to={`/pengadaan/rfq/${d.rfq_id}`} className="underline">
                  {d.rfq_number}
                </Link>
              </>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-5">
            <div>
              <dt className="text-fg-muted">{t('po.subtotal')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.subtotal)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">PPN {d.ppn_pct.replace('.00', '')}%</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.ppn_amount)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('pr.total')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {formatIDR(d.total)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('po.committed')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.budget.commit_by_po)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('project.available')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.budget.available)}</dd>
            </div>
          </dl>
          {d.pending_revision && (
            <p className="mt-3 rounded-control bg-warning-tint px-3 py-2 text-small text-warning">
              {t('po.revisionPending', { reason: d.pending_revision.reason })}{' '}
              {d.request_id && (
                <Link to={`/persetujuan/${d.request_id}`} className="underline">
                  {t('crm.openApproval')}
                </Link>
              )}
            </p>
          )}
        </CardContent>
      </Card>
      <Tabs
        label={d.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'files', label: t('po.documents') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && (d.can_edit ? <DraftEditor d={d} /> : <ReadOnly d={d} />)}
      {tab === 'detail' && d.can_revise && <ReviseCard d={d} />}
      {tab === 'files' && (
        <AttachmentsPanel entityType="purchase_order" entityId={d.id} canWrite={false} />
      )}
      {tab === 'history' && <HistoryPanel entityType="purchase_order" entityId={d.id} />}
    </div>
  );
}

function ReadOnly({ d }: { d: PoDetail }) {
  const { t } = useTranslation();
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-4">
        <Table>
          <THead>
            <TR>
              <TH>{t('quotation.description')}</TH>
              <TH className="text-right">{t('quotation.qty')}</TH>
              <TH>{t('quotation.unit')}</TH>
              <TH className="text-right">{t('quotation.unitPrice')}</TH>
              <TH className="text-right">{t('quotation.amount')}</TH>
              {d.status !== 'draft' && <TH className="text-right">{t('gr.received')}</TH>}
            </TR>
          </THead>
          <TBody>
            {d.lines.map((l) => (
              <TR key={l.seq}>
                <TD>{l.description}</TD>
                <TD className="text-right tabular-nums">{l.qty.replace('.', ',')}</TD>
                <TD>{l.uom}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(l.unit_price)}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {l.amount ? formatIDR(l.amount) : '–'}
                </TD>
                {d.status !== 'draft' && (
                  <TD className="text-right tabular-nums">
                    {(l.received ?? '0').replace('.', ',')}
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
        {d.can_receive && (
          <Button asChild variant="primary" className="self-start">
            <Link to={`/gudang/gr/baru?po=${d.id}`}>
              <Icon name="local_shipping" /> {t('gr.receive')}
            </Link>
          </Button>
        )}
        {d.grs && d.grs.length > 0 && (
          <p className="flex flex-wrap gap-3 text-small">
            {d.grs.map((g) => (
              <Link
                key={g.id}
                to={`/gudang/gr/${g.id}`}
                className="font-semibold text-fg-accent underline"
              >
                {g.number} ({t(`gr.status.${g.status}`)})
              </Link>
            ))}
          </p>
        )}
        <p className="text-small text-fg-secondary">
          {t('po.deliveryDate')}: {d.delivery_date ? formatDate(d.delivery_date) : '–'} ·{' '}
          {d.delivery_location} · {d.payment_terms}
        </p>
        {d.terms && <p className="whitespace-pre-line text-small text-fg-body">{d.terms}</p>}
      </CardContent>
    </Card>
  );
}

function DraftEditor({ d }: { d: PoDetail }) {
  const { t } = useTranslation();
  const save = useSavePo(d.id);
  const issue = useIssuePo(d.id);
  const [lines, setLines] = useState(toEditable(d.lines));
  const [v, setV] = useState({
    date: d.delivery_date ?? '',
    location: d.delivery_location,
    payment: d.payment_terms ?? '',
    terms: d.terms ?? '',
  });
  const body = () => ({
    lines: toApi(lines),
    delivery_date: v.date || null,
    delivery_location: v.location,
    payment_terms: v.payment || null,
    terms: v.terms || null,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('po.draft')}</CardTitle>
        <CardDescription>{t('po.issueHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(save.error ?? issue.error, t('auth.unexpected'))} />
        <LinesEditor lines={lines} onChange={setLines} />
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t('po.deliveryDate')}>
            <Input
              type="date"
              value={v.date}
              onChange={(e) => setV({ ...v, date: e.target.value })}
            />
          </Field>
          <Field label={t('pr.location')}>
            <Input value={v.location} onChange={(e) => setV({ ...v, location: e.target.value })} />
          </Field>
          <Field label={t('rfq.terms')}>
            <Input value={v.payment} onChange={(e) => setV({ ...v, payment: e.target.value })} />
          </Field>
        </div>
        <Field label={t('quotation.terms')}>
          <Textarea
            rows={3}
            value={v.terms}
            onChange={(e) => setV({ ...v, terms: e.target.value })}
          />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={save.isPending} onClick={() => save.mutate(body())}>
            {t('master.save')}
          </Button>
          <Button
            variant="primary"
            disabled={issue.isPending || save.isPending}
            onClick={() => save.mutate(body(), { onSuccess: () => issue.mutate() })}
          >
            <Icon name="send" /> {t('po.issue')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ReviseCard({ d }: { d: PoDetail }) {
  const { t } = useTranslation();
  const revise = useRevisePo(d.id);
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState(toEditable(d.lines));
  const [reason, setReason] = useState('');
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('po.revise')}</CardTitle>
        <CardDescription>{t('po.reviseHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(revise.error, t('auth.unexpected'))} />
        {revise.data && (
          <p role="status" className="text-small font-medium text-success">
            {revise.data.approval_needed
              ? t('po.revisionSubmitted')
              : t('po.revisionApplied', { revision: revise.data.revision })}
          </p>
        )}
        {!open ? (
          <Button variant="secondary" className="self-start" onClick={() => setOpen(true)}>
            <Icon name="edit_note" /> {t('po.revise')}
          </Button>
        ) : (
          <>
            <LinesEditor lines={lines} onChange={setLines} />
            <Field label={t('quotation.revisionReason')} required>
              <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Button
              variant="primary"
              className="self-start"
              disabled={reason.trim().length < 5 || revise.isPending}
              onClick={() =>
                revise.mutate({ lines: toApi(lines), reason }, { onSuccess: () => setOpen(false) })
              }
            >
              {t('po.submitRevision')}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
