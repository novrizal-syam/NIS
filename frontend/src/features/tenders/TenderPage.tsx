import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
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
import { ApiError } from '@/lib/api';
import { formatDate, formatDateTime, formatIDR, formatNumber } from '@/lib/format';
import {
  CHANNELS,
  METHODS,
  RESULTS,
  SECTIONS,
  fromJakartaInput,
  toJakartaInput,
  useAddClarification,
  useAddDocument,
  useDeleteDocument,
  useRecordResult,
  useRecordSubmission,
  useSaveClarification,
  useSaveDocument,
  useSaveTender,
  useSubmitPackage,
  useTender,
  type Section,
  type TenderDetail,
  type TenderDoc,
  type TenderResult,
} from './api';
import { ClosingIn } from './TendersPage';
import { DocStatusPill, PackagePill, ResultPill } from './TenderPills';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const money = (v: string | null) => (v ? formatNumber(Number(v)) : '');
const pct = (v: string | null) => (v ? String(Number(v)).replace('.', ',') : '');
const pctToApi = (v: string) => (v.trim() ? v.replace(',', '.').trim() : null);

type Tab = 'data' | 'documents' | 'clarifications' | 'submission' | 'history';

export function TenderPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const tender = useTender(id);
  const [tab, setTab] = useState<Tab>('data');
  if (tender.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (tender.error || !tender.data)
    return <FormError message={errText(tender.error, t('auth.unexpected'))} />;
  const d = tender.data;
  const missing = d.documents.filter((x) => x.mandatory && x.status === 'missing').length;

  return (
    <div className="flex flex-col gap-4">
      <Link
        to={`/peluang/${d.opportunity_id}`}
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {d.opportunity_number} · {d.opportunity_title}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.tender_number ?? t('tender.noNumber')} · {t(`tender.methods.${d.method}`)}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{d.opportunity_title}</CardTitle>
            <span className="flex flex-wrap gap-2">
              <PackagePill status={d.package_status} />
              {d.result && <ResultPill result={d.result} />}
            </span>
          </div>
          <CardDescription>{d.company_name}</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-fg-muted">{t('tender.closing')}</dt>
              <dd className="text-fg">
                <ClosingIn iso={d.closing_at} />
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('tender.price')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {d.price ? formatIDR(d.price) : '–'}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('tender.mandatoryMissing')}</dt>
              <dd className={missing ? 'font-semibold text-danger' : 'text-success'}>{missing}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">TKDN</dt>
              <dd className="text-fg-body">
                {d.tkdn_offered_pct ? `${pct(d.tkdn_offered_pct)}%` : '–'}
                {d.tkdn_required_pct && ` / min. ${pct(d.tkdn_required_pct)}%`}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>
      <Tabs
        label={t('tender.title')}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'data', label: t('tender.tabs.data') },
          { value: 'documents', label: t('tender.tabs.documents'), badge: missing },
          {
            value: 'clarifications',
            label: t('tender.tabs.clarifications'),
            badge: d.clarifications.length,
          },
          { value: 'submission', label: t('tender.tabs.submission') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'data' && <DataForm d={d} />}
      {tab === 'documents' && <Checklist d={d} />}
      {tab === 'clarifications' && <Clarifications d={d} />}
      {tab === 'submission' && <Submission d={d} />}
      {tab === 'history' && <HistoryPanel entityType="tender" entityId={d.id} />}
    </div>
  );
}

function DataForm({ d }: { d: TenderDetail }) {
  const { t } = useTranslation();
  const save = useSaveTender(d.id);
  const ro = !d.can_edit;
  const priceLocked = d.package_status === 'pending' || d.package_status === 'approved';
  const [v, setV] = useState({
    number: d.tender_number ?? '',
    method: d.method,
    aanwijzing: toJakartaInput(d.aanwijzing_at),
    clarification: toJakartaInput(d.clarification_deadline),
    closing: toJakartaInput(d.closing_at),
    opening: toJakartaInput(d.opening_at),
    validity: d.bid_validity_until ?? '',
    bondRequired: d.bid_bond_required,
    bondAmount: money(d.bid_bond_amount),
    bondNumber: d.bid_bond_number ?? '',
    tkdnRequired: pct(d.tkdn_required_pct),
    tkdnOffered: pct(d.tkdn_offered_pct),
    price: money(d.price),
  });
  const set = (patch: Partial<typeof v>) => setV({ ...v, ...patch });
  const dt = (label: string, key: 'aanwijzing' | 'clarification' | 'closing' | 'opening') => (
    <Field label={label} hint="WIB">
      <Input
        type="datetime-local"
        value={v[key]}
        onChange={(e) => set({ [key]: e.target.value })}
      />
    </Field>
  );

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 pt-4">
        <FormError message={errText(save.error, t('auth.unexpected'))} />
        {save.isSuccess && (
          <p role="status" className="text-small font-medium text-success">
            {t('crm.saved')}
          </p>
        )}
        <fieldset disabled={ro} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t('tender.number')}>
            <Input value={v.number} onChange={(e) => set({ number: e.target.value })} />
          </Field>
          <Field label={t('tender.method')}>
            <Select
              value={v.method}
              onChange={(e) => set({ method: e.target.value as TenderDetail['method'] })}
            >
              {METHODS.map((m) => (
                <option key={m} value={m}>
                  {t(`tender.methods.${m}`)}
                </option>
              ))}
            </Select>
          </Field>
          {dt(t('tender.aanwijzing'), 'aanwijzing')}
          {dt(t('tender.clarificationDeadline'), 'clarification')}
          {dt(t('tender.closing'), 'closing')}
          {dt(t('tender.opening'), 'opening')}
          <Field label={t('tender.validity')}>
            <Input
              type="date"
              value={v.validity}
              onChange={(e) => set({ validity: e.target.value })}
            />
          </Field>
          <Field label={t('tender.price')} hint={priceLocked ? t('tender.priceLocked') : 'Rp'}>
            <Input
              inputMode="numeric"
              disabled={priceLocked}
              value={v.price}
              onChange={(e) => set({ price: e.target.value })}
            />
          </Field>
          <label className="flex items-center gap-2 self-end pb-2 text-small text-fg-body">
            <input
              type="checkbox"
              checked={v.bondRequired}
              onChange={(e) => set({ bondRequired: e.target.checked })}
            />
            {t('tender.bondRequired')}
          </label>
          <Field label={t('tender.bondAmount')} hint="Rp">
            <Input
              inputMode="numeric"
              value={v.bondAmount}
              onChange={(e) => set({ bondAmount: e.target.value })}
            />
          </Field>
          <Field label={t('tender.bondNumber')}>
            <Input value={v.bondNumber} onChange={(e) => set({ bondNumber: e.target.value })} />
          </Field>
          <Field label={t('tender.tkdnRequired')} hint="%">
            <Input
              inputMode="decimal"
              value={v.tkdnRequired}
              onChange={(e) => set({ tkdnRequired: e.target.value })}
            />
          </Field>
          <Field label={t('tender.tkdnOffered')} hint="%">
            <Input
              inputMode="decimal"
              value={v.tkdnOffered}
              onChange={(e) => set({ tkdnOffered: e.target.value })}
            />
          </Field>
        </fieldset>
        {!ro && (
          <Button
            variant="primary"
            className="self-start"
            disabled={save.isPending}
            onClick={() =>
              save.mutate({
                tender_number: v.number || null,
                method: v.method,
                aanwijzing_at: fromJakartaInput(v.aanwijzing),
                clarification_deadline: fromJakartaInput(v.clarification),
                closing_at: fromJakartaInput(v.closing),
                opening_at: fromJakartaInput(v.opening),
                bid_validity_until: v.validity || null,
                bid_bond_required: v.bondRequired,
                bid_bond_amount: moneyToApi(v.bondAmount),
                bid_bond_number: v.bondNumber || null,
                tkdn_required_pct: pctToApi(v.tkdnRequired),
                tkdn_offered_pct: pctToApi(v.tkdnOffered),
                price: moneyToApi(v.price),
              })
            }
          >
            {t('master.save')}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function Checklist({ d }: { d: TenderDetail }) {
  const { t } = useTranslation();
  const saveDoc = useSaveDocument(d.id);
  const addDoc = useAddDocument(d.id);
  const delDoc = useDeleteDocument(d.id);
  const [files, setFiles] = useState<TenderDoc | null>(null);
  const [add, setAdd] = useState<{ section: Section; name: string; mandatory: boolean }>({
    section: 'admin',
    name: '',
    mandatory: true,
  });
  const editable = d.can_edit && d.package_status !== 'pending';
  const body = (x: TenderDoc, patch: Partial<TenderDoc>) => {
    const n = { ...x, ...patch };
    return {
      section: n.section,
      name: n.name,
      mandatory: n.mandatory,
      not_applicable: n.not_applicable,
      expiry_date: n.expiry_date,
      note: n.note,
    };
  };

  return (
    <div className="flex flex-col gap-4">
      <FormError
        message={errText(saveDoc.error ?? addDoc.error ?? delDoc.error, t('auth.unexpected'))}
      />
      <p className="text-small text-fg-secondary">{t('tender.checklistHelp')}</p>
      {SECTIONS.map((section) => (
        <Card key={section}>
          <CardHeader>
            <CardTitle>{t(`tender.sections.${section}`)}</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>{t('tender.document')}</TH>
                  <TH>{t('master.status')}</TH>
                  <TH>{t('tender.mandatory')}</TH>
                  <TH>{t('tender.na')}</TH>
                  <TH>{t('tender.expiry')}</TH>
                  <TH>{t('tender.files')}</TH>
                  {editable && <TH className="w-10">{''}</TH>}
                </TR>
              </THead>
              <TBody>
                {d.documents
                  .filter((x) => x.section === section)
                  .map((x) => (
                    <TR key={x.id}>
                      <TD className="min-w-48">{x.name}</TD>
                      <TD>
                        <DocStatusPill doc={x} />
                      </TD>
                      <TD>
                        <input
                          type="checkbox"
                          aria-label={`${t('tender.mandatory')}: ${x.name}`}
                          disabled={!editable}
                          checked={x.mandatory}
                          onChange={(e) =>
                            saveDoc.mutate({
                              docId: x.id,
                              body: body(x, { mandatory: e.target.checked }),
                            })
                          }
                        />
                      </TD>
                      <TD>
                        <input
                          type="checkbox"
                          aria-label={`${t('tender.na')}: ${x.name}`}
                          disabled={!editable}
                          checked={x.not_applicable}
                          onChange={(e) =>
                            saveDoc.mutate({
                              docId: x.id,
                              body: body(x, { not_applicable: e.target.checked }),
                            })
                          }
                        />
                      </TD>
                      <TD>
                        {editable ? (
                          <Input
                            type="date"
                            aria-label={`${t('tender.expiry')}: ${x.name}`}
                            value={x.expiry_date ?? ''}
                            onChange={(e) =>
                              saveDoc.mutate({
                                docId: x.id,
                                body: body(x, { expiry_date: e.target.value || null }),
                              })
                            }
                          />
                        ) : x.expiry_date ? (
                          formatDate(x.expiry_date)
                        ) : (
                          '–'
                        )}
                      </TD>
                      <TD>
                        <Button size="sm" variant="secondary" onClick={() => setFiles(x)}>
                          <Icon name="attach_file" /> {x.files}
                        </Button>
                      </TD>
                      {editable && (
                        <TD>
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={`${t('tender.removeDoc')}: ${x.name}`}
                            disabled={x.files > 0}
                            onClick={() => delDoc.mutate(x.id)}
                          >
                            <Icon name="delete" />
                          </Button>
                        </TD>
                      )}
                    </TR>
                  ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      ))}
      {editable && (
        <Card>
          <CardContent className="flex flex-wrap items-end gap-2 pt-4">
            <Field label={t('tender.section')} className="w-full sm:w-44">
              <Select
                value={add.section}
                onChange={(e) => setAdd({ ...add, section: e.target.value as Section })}
              >
                {SECTIONS.map((s) => (
                  <option key={s} value={s}>
                    {t(`tender.sections.${s}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('tender.document')} className="min-w-0 flex-1">
              <Input value={add.name} onChange={(e) => setAdd({ ...add, name: e.target.value })} />
            </Field>
            <label className="flex h-10 items-center gap-2 text-small text-fg-body">
              <input
                type="checkbox"
                checked={add.mandatory}
                onChange={(e) => setAdd({ ...add, mandatory: e.target.checked })}
              />
              {t('tender.mandatory')}
            </label>
            <Button
              variant="secondary"
              disabled={add.name.trim().length < 2 || addDoc.isPending}
              onClick={() => addDoc.mutate(add, { onSuccess: () => setAdd({ ...add, name: '' }) })}
            >
              <Icon name="add" /> {t('tender.addDoc')}
            </Button>
          </CardContent>
        </Card>
      )}
      <Dialog
        open={files !== null}
        onClose={() => setFiles(null)}
        title={files?.name ?? ''}
        description={t('tender.filesHelp')}
        className="max-w-2xl"
      >
        {files && (
          <AttachmentsPanel
            entityType="tender_document"
            entityId={files.id}
            canWrite={d.can_edit}
          />
        )}
      </Dialog>
    </div>
  );
}

function Clarifications({ d }: { d: TenderDetail }) {
  const { t } = useTranslation();
  const add = useAddClarification(d.id);
  const save = useSaveClarification(d.id);
  const [q, setQ] = useState({
    question: '',
    reference: '',
    asked: toJakartaInput(new Date().toISOString()),
  });
  const [answers, setAnswers] = useState<Record<string, string>>({});

  return (
    <div className="flex flex-col gap-4">
      <FormError message={errText(add.error ?? save.error, t('auth.unexpected'))} />
      {d.clarification_deadline && (
        <p className="text-small text-fg-secondary">
          {t('tender.clarificationDeadline')}: {formatDateTime(d.clarification_deadline)}
        </p>
      )}
      {d.clarifications.length === 0 && (
        <p className="text-small text-fg-secondary">{t('tender.noClarifications')}</p>
      )}
      {d.clarifications.map((c, i) => (
        <Card key={c.id}>
          <CardContent className="flex flex-col gap-2 pt-4">
            <p className="text-caption text-fg-muted">
              #{i + 1} · {formatDateTime(c.asked_at)}
              {c.reference && ` · ${c.reference}`}
            </p>
            <p className="text-body text-fg">{c.question}</p>
            {c.answer ? (
              <p className="rounded-control bg-surface-muted px-3 py-2 text-small text-fg-body">
                {c.answer}
                {c.answered_at && (
                  <span className="block text-caption text-fg-muted">
                    {formatDateTime(c.answered_at)}
                  </span>
                )}
              </p>
            ) : (
              d.can_edit && (
                <div className="flex flex-wrap items-end gap-2">
                  <Field label={t('tender.answer')} className="min-w-0 flex-1">
                    <Textarea
                      rows={2}
                      value={answers[c.id] ?? ''}
                      onChange={(e) => setAnswers({ ...answers, [c.id]: e.target.value })}
                    />
                  </Field>
                  <Button
                    variant="secondary"
                    disabled={!(answers[c.id] ?? '').trim() || save.isPending}
                    onClick={() =>
                      save.mutate({
                        cid: c.id,
                        body: {
                          question: c.question,
                          asked_at: c.asked_at,
                          reference: c.reference,
                          answer: answers[c.id],
                        },
                      })
                    }
                  >
                    {t('tender.saveAnswer')}
                  </Button>
                </div>
              )
            )}
          </CardContent>
        </Card>
      ))}
      {d.can_edit && (
        <Card>
          <CardHeader>
            <CardTitle>{t('tender.newQuestion')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Field label={t('tender.question')} required>
              <Textarea
                rows={3}
                value={q.question}
                onChange={(e) => setQ({ ...q, question: e.target.value })}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t('tender.askedAt')} hint="WIB">
                <Input
                  type="datetime-local"
                  value={q.asked}
                  onChange={(e) => setQ({ ...q, asked: e.target.value })}
                />
              </Field>
              <Field label={t('tender.reference')}>
                <Input
                  value={q.reference}
                  onChange={(e) => setQ({ ...q, reference: e.target.value })}
                />
              </Field>
            </div>
            <Button
              variant="primary"
              className="self-start"
              disabled={q.question.trim().length < 5 || !q.asked || add.isPending}
              onClick={() =>
                add.mutate(
                  {
                    question: q.question,
                    asked_at: fromJakartaInput(q.asked),
                    reference: q.reference || null,
                  },
                  { onSuccess: () => setQ({ ...q, question: '', reference: '' }) },
                )
              }
            >
              {t('tender.addQuestion')}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Submission({ d }: { d: TenderDetail }) {
  const { t } = useTranslation();
  const pkg = useSubmitPackage(d.id);
  const sub = useRecordSubmission(d.id);
  const res = useRecordResult(d.id);
  const [s, setS] = useState({
    at: toJakartaInput(d.submitted_at ?? new Date().toISOString()),
    channel: d.submission_channel ?? 'eproc',
    receipt: d.receipt_number ?? '',
  });
  const [r, setR] = useState<{
    result: TenderResult;
    rank: string;
    winner: string;
    price: string;
    lessons: string;
  }>({ result: 'won', rank: '', winner: '', price: '', lessons: '' });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{t('tender.packageTitle')}</CardTitle>
          <CardDescription>{t('tender.packageHelp')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FormError message={errText(pkg.error, t('auth.unexpected'))} />
          <PackagePill status={d.package_status} />
          {d.readiness.problems.length > 0 && (
            <ul
              className="list-inside list-disc text-small text-danger"
              aria-label={t('tender.notReady')}
            >
              {d.readiness.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          {d.readiness.missing.length > 0 && (
            <p className="text-small text-fg-secondary">{d.readiness.missing.join(', ')}</p>
          )}
          {(d.package_status === 'none' || d.package_status === 'rejected') && !d.result && (
            <Button
              variant="primary"
              className="self-start"
              disabled={!d.can_submit_package || !d.readiness.ready || pkg.isPending}
              onClick={() => pkg.mutate()}
            >
              <Icon name="send" /> {t('tender.submitPackage')}
            </Button>
          )}
          {d.request_id && (
            <Link
              to={`/persetujuan/${d.request_id}`}
              className="text-small font-semibold text-fg-accent underline"
            >
              {t('crm.openApproval')}
            </Link>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('tender.submissionTitle')}</CardTitle>
          <CardDescription>{t('tender.submissionHelp')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FormError message={errText(sub.error, t('auth.unexpected'))} />
          <fieldset
            disabled={!d.can_edit || d.package_status !== 'approved'}
            className="grid gap-3 sm:grid-cols-3"
          >
            <Field label={t('tender.submittedAt')} hint="WIB">
              <Input
                type="datetime-local"
                value={s.at}
                onChange={(e) => setS({ ...s, at: e.target.value })}
              />
            </Field>
            <Field label={t('tender.channel')}>
              <Select
                value={s.channel}
                onChange={(e) =>
                  setS({ ...s, channel: e.target.value as (typeof CHANNELS)[number] })
                }
              >
                {CHANNELS.map((c) => (
                  <option key={c} value={c}>
                    {t(`tender.channels.${c}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('tender.receipt')}>
              <Input value={s.receipt} onChange={(e) => setS({ ...s, receipt: e.target.value })} />
            </Field>
          </fieldset>
          {d.can_edit && d.package_status === 'approved' && (
            <Button
              variant="secondary"
              className="self-start"
              disabled={!s.at || sub.isPending}
              onClick={() =>
                sub.mutate({
                  submitted_at: fromJakartaInput(s.at),
                  channel: s.channel,
                  receipt_number: s.receipt || null,
                })
              }
            >
              {t('tender.saveSubmission')}
            </Button>
          )}
          {d.submitted_at && (
            <p role="status" className="text-small text-success">
              {t('tender.submittedInfo', { at: formatDateTime(d.submitted_at) })}
            </p>
          )}
          <AttachmentsPanel entityType="tender" entityId={d.id} canWrite={d.can_edit} />
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>{t('tender.resultTitle')}</CardTitle>
          <CardDescription>{t('tender.resultHelp')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FormError message={errText(res.error, t('auth.unexpected'))} />
          {d.result ? (
            <dl className="grid gap-x-6 gap-y-2 text-small sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-fg-muted">{t('tender.resultCol')}</dt>
                <dd>
                  <ResultPill result={d.result} />
                </dd>
              </div>
              <div>
                <dt className="text-fg-muted">{t('tender.rank')}</dt>
                <dd className="text-fg-body">{d.rank ?? '–'}</dd>
              </div>
              <div>
                <dt className="text-fg-muted">{t('tender.winner')}</dt>
                <dd className="text-fg-body">{d.winner_name ?? '–'}</dd>
              </div>
              <div>
                <dt className="text-fg-muted">{t('tender.winningPrice')}</dt>
                <dd className="tabular-nums text-fg-body">
                  {d.winning_price ? formatIDR(d.winning_price) : '–'}
                </dd>
              </div>
              {d.lessons_learned && (
                <div className="sm:col-span-2 lg:col-span-4">
                  <dt className="text-fg-muted">{t('tender.lessons')}</dt>
                  <dd className="whitespace-pre-line text-fg-body">{d.lessons_learned}</dd>
                </div>
              )}
              {d.result === 'won' && (
                <p className="text-small text-fg-secondary sm:col-span-2 lg:col-span-4">
                  {t('tender.wonHint')}{' '}
                  <Link to={`/peluang/${d.opportunity_id}`} className="text-fg-accent underline">
                    {d.opportunity_number}
                  </Link>
                </p>
              )}
            </dl>
          ) : (
            d.can_edit && (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Field label={t('tender.resultCol')}>
                    <Select
                      value={r.result}
                      onChange={(e) => setR({ ...r, result: e.target.value as TenderResult })}
                    >
                      {RESULTS.map((x) => (
                        <option key={x} value={x}>
                          {t(`tender.results.${x}`)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label={t('tender.rank')}>
                    <Input
                      type="number"
                      min={1}
                      value={r.rank}
                      onChange={(e) => setR({ ...r, rank: e.target.value })}
                    />
                  </Field>
                  <Field label={t('tender.winner')}>
                    <Input
                      value={r.winner}
                      onChange={(e) => setR({ ...r, winner: e.target.value })}
                    />
                  </Field>
                  <Field label={t('tender.winningPrice')} hint="Rp">
                    <Input
                      inputMode="numeric"
                      value={r.price}
                      onChange={(e) => setR({ ...r, price: e.target.value })}
                    />
                  </Field>
                </div>
                <Field
                  label={t('tender.lessons')}
                  required={r.result === 'lost' || r.result === 'disqualified'}
                >
                  <Textarea
                    rows={3}
                    value={r.lessons}
                    onChange={(e) => setR({ ...r, lessons: e.target.value })}
                  />
                </Field>
                <Button
                  variant="primary"
                  className="self-start"
                  disabled={res.isPending}
                  onClick={() =>
                    res.mutate({
                      result: r.result,
                      rank: r.rank ? Number(r.rank) : null,
                      winner_name: r.winner || null,
                      winning_price: moneyToApi(r.price),
                      lessons_learned: r.lessons || null,
                    })
                  }
                >
                  {t('tender.saveResult')}
                </Button>
              </>
            )
          )}
        </CardContent>
      </Card>
    </div>
  );
}
