import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError, fetchBlob } from '@/lib/api';
import { formatDate, formatDateTime, formatIDR, formatNumber } from '@/lib/format';
import {
  usePriceItems,
  useQuotation,
  useQuotationConfig,
  useReviseQuotation,
  useSaveQuotation,
  useSendQuotation,
  useSubmitQuotation,
  type QuotationDetail,
  type QuotationLine,
} from './api';
import { MarginPill, QuotationStatusPill } from './QuotationPills';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

const money = (v: string) => (v ? formatNumber(Number(v)) : '');
const qtyText = (v: string) => v.replace('.', ',');
const qtyToApi = (v: string) => v.replace(/\./g, '').replace(',', '.').trim();

interface Draft {
  discount: string;
  validUntil: string;
  notes: string;
  terms: string;
  lines: QuotationLine[];
}

const toDraft = (q: QuotationDetail): Draft => ({
  discount: qtyText(String(Number(q.discount_pct))),
  validUntil: q.valid_until ?? '',
  notes: q.notes ?? '',
  terms: q.terms ?? '',
  lines: q.lines.map((x) => ({
    ...x,
    qty: qtyText(x.qty),
    unit_cost: money(x.unit_cost),
    unit_price: money(x.unit_price),
  })),
});

export function QuotationPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const quotation = useQuotation(id);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');

  if (quotation.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (quotation.error || !quotation.data)
    return <FormError message={errText(quotation.error, t('auth.unexpected'))} />;
  const q = quotation.data;

  return (
    <div className="flex flex-col gap-4">
      <Link
        to={`/peluang/${q.opportunity_id}`}
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {q.opportunity_number} · {q.opportunity_title}
      </Link>
      <Header q={q} />
      {q.margin_warning && (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-control border border-danger bg-danger-tint px-3 py-2 text-small font-medium text-danger"
        >
          <Icon name="warning" />
          <LowMarginText q={q} />
        </p>
      )}
      <Tabs
        label={q.label}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'files', label: t('crm.tabFiles') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && (
        <div className="grid gap-4 xl:grid-cols-[1fr_20rem]">
          <Editor key={`${q.id}-${q.status}`} q={q} />
          <div className="flex flex-col gap-4">
            <Actions q={q} />
            <Revisions q={q} />
          </div>
        </div>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="quotation" entityId={q.id} canWrite={q.can_edit} />
      )}
      {tab === 'history' && <HistoryPanel entityType="quotation" entityId={q.id} />}
    </div>
  );
}

function LowMarginText({ q }: { q: QuotationDetail }) {
  const { t } = useTranslation();
  const config = useQuotationConfig();
  return (
    <span>
      {t('quotation.lowMarginBanner', {
        value: q.margin_pct.replace('.', ','),
        threshold: config.data?.margin_warning_pct ?? '20',
      })}
    </span>
  );
}

function Header({ q }: { q: QuotationDetail }) {
  const { t } = useTranslation();
  return (
    <Card>
      <CardHeader>
        <p className="eyebrow">
          {q.label}
          {q.letter && ` · ${q.letter.number}`}
        </p>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-section-title">{q.opportunity_title}</CardTitle>
          <QuotationStatusPill status={q.status} />
        </div>
        <CardDescription>
          {q.company_name}
          {q.contact_name && ` · Up. ${q.contact_name}`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-5">
          <Stat label={t('quotation.subtotal')} value={formatIDR(q.subtotal)} />
          <Stat
            label={t('quotation.discount', { pct: q.discount_pct.replace('.', ',') })}
            value={formatIDR(q.discount_amount)}
          />
          <Stat label={t('quotation.total')} value={formatIDR(q.total_price)} strong />
          <Stat label={t('quotation.cost')} value={formatIDR(q.total_cost)} />
          <div>
            <dt className="text-fg-muted">{t('quotation.margin')}</dt>
            <dd className="text-fg">
              {formatIDR(q.margin)} · <MarginPill pct={q.margin_pct} warning={q.margin_warning} />
            </dd>
          </div>
        </dl>
        {q.decision_comment && (
          <p className="mt-3 text-small text-fg-body">
            {t('quotation.approverNote')}: {q.decision_comment}
          </p>
        )}
        {q.revision_reason && (
          <p className="mt-1 text-small text-fg-secondary">
            {t('quotation.revisionReason')}: {q.revision_reason}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <dt className="text-fg-muted">{label}</dt>
      <dd
        className={
          strong ? 'font-heading text-card-title tabular-nums text-fg' : 'tabular-nums text-fg-body'
        }
      >
        {value}
      </dd>
    </div>
  );
}

function Editor({ q }: { q: QuotationDetail }) {
  const { t } = useTranslation();
  const items = usePriceItems();
  const save = useSaveQuotation(q.id);
  const [d, setD] = useState<Draft>(() => toDraft(q));
  const [dirty, setDirty] = useState(false);
  const [pick, setPick] = useState('');
  useEffect(() => {
    if (!dirty) setD(toDraft(q));
  }, [q, dirty]);
  const ro = !q.can_edit;
  const change = (patch: Partial<Draft>) => {
    setD({ ...d, ...patch });
    setDirty(true);
  };
  const setLine = (i: number, patch: Partial<QuotationLine>) =>
    change({ lines: d.lines.map((x, j) => (j === i ? { ...x, ...patch } : x)) });

  const addItem = (code: string) => {
    const p = items.data?.find((x) => x.code === code);
    if (!p) return;
    change({
      lines: [
        ...d.lines,
        {
          price_item_code: p.code,
          description: p.name,
          unit: p.unit,
          qty: '1',
          unit_cost: money(p.unit_cost),
          unit_price: money(p.unit_price),
        },
      ],
    });
    setPick('');
  };

  const submitSave = () =>
    save.mutate(
      {
        discount_pct: qtyToApi(d.discount) || '0',
        valid_until: d.validUntil || null,
        notes: d.notes,
        terms: d.terms,
        lines: d.lines.map((x) => ({
          price_item_code: x.price_item_code,
          description: x.description,
          unit: x.unit,
          qty: qtyToApi(x.qty),
          unit_cost: moneyToApi(x.unit_cost) ?? '0',
          unit_price: moneyToApi(x.unit_price) ?? '0',
        })),
      },
      { onSuccess: () => setDirty(false) },
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('quotation.lines')}</CardTitle>
        <CardDescription>{ro ? t('quotation.readOnly') : t('quotation.linesHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(save.error, t('auth.unexpected'))} />
        <div className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>{t('quotation.description')}</TH>
                <TH className="w-24 text-right">{t('quotation.qty')}</TH>
                <TH className="w-20">{t('quotation.unit')}</TH>
                <TH className="w-36 text-right">{t('quotation.unitCost')}</TH>
                <TH className="w-36 text-right">{t('quotation.unitPrice')}</TH>
                <TH className="text-right">{t('quotation.amount')}</TH>
                {!ro && <TH className="w-10">{''}</TH>}
              </TR>
            </THead>
            <TBody>
              {d.lines.length === 0 && (
                <TR>
                  <TD colSpan={7} className="py-6 text-center text-fg-secondary">
                    {t('quotation.noLines')}
                  </TD>
                </TR>
              )}
              {d.lines.map((x, i) => (
                <TR key={i}>
                  <TD className="min-w-48">
                    {ro ? (
                      x.description
                    ) : (
                      <Input
                        aria-label={`${t('quotation.description')} ${i + 1}`}
                        value={x.description}
                        onChange={(e) => setLine(i, { description: e.target.value })}
                      />
                    )}
                    {x.price_item_code && (
                      <span className="block text-caption text-fg-muted">{x.price_item_code}</span>
                    )}
                  </TD>
                  <TD className="text-right tabular-nums">
                    {ro ? (
                      x.qty
                    ) : (
                      <Input
                        aria-label={`${t('quotation.qty')} ${i + 1}`}
                        inputMode="decimal"
                        className="text-right"
                        value={x.qty}
                        onChange={(e) => setLine(i, { qty: e.target.value })}
                      />
                    )}
                  </TD>
                  <TD>
                    {ro ? (
                      x.unit
                    ) : (
                      <Input
                        aria-label={`${t('quotation.unit')} ${i + 1}`}
                        value={x.unit}
                        onChange={(e) => setLine(i, { unit: e.target.value })}
                      />
                    )}
                  </TD>
                  {(['unit_cost', 'unit_price'] as const).map((k) => (
                    <TD key={k} className="text-right tabular-nums">
                      {ro ? (
                        `Rp ${x[k]}`
                      ) : (
                        <Input
                          aria-label={`${t(k === 'unit_cost' ? 'quotation.unitCost' : 'quotation.unitPrice')} ${i + 1}`}
                          inputMode="numeric"
                          className="text-right"
                          value={x[k]}
                          onChange={(e) => setLine(i, { [k]: e.target.value })}
                        />
                      )}
                    </TD>
                  ))}
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {!dirty && x.line_price ? formatIDR(x.line_price) : '–'}
                  </TD>
                  {!ro && (
                    <TD>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`${t('quotation.removeLine')} ${i + 1}`}
                        onClick={() => change({ lines: d.lines.filter((_, j) => j !== i) })}
                      >
                        <Icon name="delete" />
                      </Button>
                    </TD>
                  )}
                </TR>
              ))}
            </TBody>
          </Table>
        </div>

        {!ro && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('quotation.addFromPrice')} className="min-w-0 flex-1">
              <Select value={pick} onChange={(e) => addItem(e.target.value)}>
                <option value="">{t('quotation.choosePrice')}</option>
                {items.data?.map((p) => (
                  <option key={p.code} value={p.code}>
                    {p.code} · {p.name} ({formatIDR(p.unit_price)}/{p.unit})
                  </option>
                ))}
              </Select>
            </Field>
            <Button
              variant="secondary"
              onClick={() =>
                change({
                  lines: [
                    ...d.lines,
                    {
                      price_item_code: null,
                      description: '',
                      unit: 'lot',
                      qty: '1',
                      unit_cost: '',
                      unit_price: '',
                    },
                  ],
                })
              }
            >
              <Icon name="add" /> {t('quotation.freeLine')}
            </Button>
          </div>
        )}

        <fieldset disabled={ro} className="grid gap-3 sm:grid-cols-2">
          <Field label={t('quotation.discountPct')} hint="%">
            <Input
              inputMode="decimal"
              value={d.discount}
              onChange={(e) => change({ discount: e.target.value })}
            />
          </Field>
          <Field label={t('quotation.validUntil')}>
            <Input
              type="date"
              value={d.validUntil}
              onChange={(e) => change({ validUntil: e.target.value })}
            />
          </Field>
          <Field label={t('quotation.terms')} className="sm:col-span-2">
            <Textarea
              rows={3}
              value={d.terms}
              onChange={(e) => change({ terms: e.target.value })}
            />
          </Field>
          <Field label={t('quotation.notes')} className="sm:col-span-2">
            <Textarea
              rows={2}
              value={d.notes}
              onChange={(e) => change({ notes: e.target.value })}
            />
          </Field>
        </fieldset>
        {!ro && (
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={save.isPending || !dirty} onClick={submitSave}>
              {t('quotation.saveRecalc')}
            </Button>
            {dirty && (
              <span role="status" className="text-small text-warning">
                {t('quotation.unsaved')}
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Actions({ q }: { q: QuotationDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const submit = useSubmitQuotation(q.id);
  const revise = useReviseQuotation(q.id);
  const [dialog, setDialog] = useState<'revise' | 'send' | null>(null);
  const [reason, setReason] = useState('');
  const [previewError, setPreviewError] = useState<string | null>(null);

  const preview = async () => {
    setPreviewError(null);
    try {
      const url = URL.createObjectURL(await fetchBlob(`/quotations/${q.id}/pdf`));
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setPreviewError(errText(e, t('auth.unexpected')));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('quotation.actions')}</CardTitle>
        <CardDescription>{t(`quotation.next.${q.status}`)}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <FormError
          message={errText(submit.error ?? revise.error, t('auth.unexpected')) ?? previewError}
        />
        {submit.data?.approver && (
          <p role="status" className="text-small font-medium text-success">
            {t('quotation.submittedTo', { role: t(`quotation.approver.${submit.data.approver}`) })}
          </p>
        )}
        {q.can_submit && (
          <Button variant="primary" disabled={submit.isPending} onClick={() => submit.mutate()}>
            <Icon name="send" /> {t('quotation.submit')}
          </Button>
        )}
        {q.can_send && (
          <Button variant="primary" onClick={() => setDialog('send')}>
            <Icon name="outgoing_mail" /> {t('quotation.sendToClient')}
          </Button>
        )}
        <Button variant="secondary" onClick={() => void preview()}>
          <Icon name="picture_as_pdf" />{' '}
          {q.letter ? t('quotation.openLetter') : t('quotation.preview')}
        </Button>
        {q.can_revise && (
          <Button variant="secondary" onClick={() => setDialog('revise')}>
            <Icon name="edit_note" /> {t('quotation.revise')}
          </Button>
        )}
        {q.request_id && (
          <Link
            to={`/persetujuan/${q.request_id}`}
            className="text-small font-semibold text-fg-accent underline"
          >
            {t('crm.openApproval')}
          </Link>
        )}
        {q.letter && (
          <p className="text-small text-fg-secondary">
            {t('quotation.sentInfo', {
              number: q.letter.number,
              date: formatDate(q.letter.date),
            })}
            {q.sent_to_email && ` · ${q.sent_to_email}`}
          </p>
        )}
      </CardContent>

      <Dialog
        open={dialog === 'revise'}
        onClose={() => setDialog(null)}
        title={t('quotation.revise')}
        description={t('quotation.reviseHelp')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              disabled={reason.trim().length < 5 || revise.isPending}
              onClick={() =>
                revise.mutate(reason, {
                  onSuccess: (r) => {
                    setDialog(null);
                    navigate(`/penawaran/${r.id}`);
                  },
                })
              }
            >
              {t('quotation.createRevision')}
            </Button>
          </>
        }
      >
        <FormError message={errText(revise.error, t('auth.unexpected'))} />
        <Field label={t('quotation.revisionReason')} required>
          <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </Dialog>
      {dialog === 'send' && <SendDialog q={q} onClose={() => setDialog(null)} />}
    </Card>
  );
}

function SendDialog({ q, onClose }: { q: QuotationDetail; onClose: () => void }) {
  const { t } = useTranslation();
  const config = useQuotationConfig();
  const send = useSendQuotation(q.id);
  const [byEmail, setByEmail] = useState(Boolean(q.contact_email));
  const [to, setTo] = useState(q.contact_email ?? '');
  const [message, setMessage] = useState('');
  const done = send.data;

  return (
    <Dialog
      open
      onClose={onClose}
      title={t('quotation.sendToClient')}
      description={t('quotation.sendHelp')}
      footer={
        done ? (
          <Button variant="secondary" onClick={onClose}>
            {t('common.close')}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              disabled={send.isPending || (byEmail && !to.includes('@'))}
              onClick={() =>
                send.mutate({
                  send_email: byEmail,
                  ...(byEmail ? { to_email: to } : {}),
                  ...(message.trim() ? { message } : {}),
                })
              }
            >
              {t('quotation.confirmSend')}
            </Button>
          </>
        )
      }
    >
      {done ? (
        <p
          role="status"
          className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
        >
          {t('quotation.sentDone', { number: done.letter_number })}{' '}
          {t(`quotation.emailStatus.${done.email_status}`)}
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <FormError message={errText(send.error, t('auth.unexpected'))} />
          <label className="flex items-center gap-2 text-small text-fg-body">
            <input
              type="checkbox"
              checked={byEmail}
              onChange={(e) => setByEmail(e.target.checked)}
            />
            {t('quotation.alsoEmail')}
          </label>
          {config.data && !config.data.email_configured && byEmail && (
            <p className="text-small text-warning">{t('quotation.emailNotConfigured')}</p>
          )}
          {byEmail && (
            <>
              <Field label={t('crm.contactEmail')} required>
                <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} />
              </Field>
              <Field label={t('quotation.emailMessage')}>
                <Textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} />
              </Field>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

function Revisions({ q }: { q: QuotationDetail }) {
  const { t } = useTranslation();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('quotation.revisions')}</CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="flex flex-col gap-2">
          {q.revisions.map((r) => (
            <li
              key={r.id}
              className="flex flex-col gap-0.5 border-b border-border pb-2 last:border-0"
            >
              <div className="flex flex-wrap items-center gap-2">
                {r.id === q.id ? (
                  <span className="text-small font-semibold text-fg">Rev.{r.revision}</span>
                ) : (
                  <Link
                    to={`/penawaran/${r.id}`}
                    className="text-small font-semibold text-fg-accent underline"
                  >
                    Rev.{r.revision}
                  </Link>
                )}
                <QuotationStatusPill status={r.status} />
              </div>
              <span className="text-caption tabular-nums text-fg-secondary">
                {formatIDR(r.total_price)} · {r.margin_pct.replace('.', ',')}% ·{' '}
                {formatDateTime(r.created_at)}
              </span>
              {r.reason && <span className="text-caption text-fg-body">{r.reason}</span>}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
