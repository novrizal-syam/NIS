import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router-dom';
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
import { AttachmentsPanel } from './AttachmentsPanel';
import { useAttachments } from './api';
import { ApiError, api, downloadFile, postJson } from '@/lib/api';
import { formatDate } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

const TONES: Record<string, StatusTone> = {
  registered: 'neutral',
  routed: 'warning',
  closed: 'success',
  draft: 'neutral',
  awaiting_approval: 'warning',
  approved: 'info',
  sent: 'success',
  effective: 'success',
  uncontrolled: 'neutral',
  open: 'warning',
  done: 'success',
};

function useDmsAction<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown; method?: string; form?: FormData }) =>
      v.form
        ? api<R>(v.path, { method: 'POST', body: v.form })
        : v.method
          ? api<R>(v.path, { method: v.method, body: JSON.stringify(v.body) })
          : postJson<R>(v.path, v.body ?? {}),
    onSuccess: () => {
      for (const k of ['letters', 'dms', 'attachments'])
        void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}

function Pill({ status, ns }: { status: string; ns: string }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONES[status] ?? 'neutral'}>{t(`${ns}.status.${status}`)}</StatusPill>;
}

// ---------------------------------------------------------------- letters

interface Incoming {
  id: string;
  number: string;
  received_on: string;
  sender: string;
  sender_ref: string | null;
  subject: string;
  status: string;
  file_id: string | null;
  confidential: boolean;
}
interface Outgoing {
  id: string;
  number: string | null;
  status: string;
  department: string;
  to: string;
  subject: string;
  body: string | null;
  letter_date: string;
  esign_ref: string | null;
  emeterai_ref: string | null;
  sent_at: string | null;
  sent_via: string | null;
  file_id: string | null;
  reject_reason: string | null;
}
interface Template {
  code: string;
  name: string;
  placeholders: string[];
}

export function LettersPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'outgoing' ? 'outgoing' : 'incoming';
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('letters.title')}
        value={tab}
        onChange={(v) => setParams({ tab: v })}
        items={[
          { value: 'incoming', label: t('letters.tabs.incoming') },
          { value: 'outgoing', label: t('letters.tabs.outgoing') },
        ]}
      />
      {tab === 'incoming' ? <IncomingList /> : <OutgoingList />}
    </div>
  );
}

function IncomingList() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const list = useQuery({
    queryKey: ['letters', 'incoming', q],
    queryFn: () => api<Incoming[]>(`/letters/incoming${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  });
  const act = useDmsAction<Incoming>();
  const [f, setF] = useState({ sender: '', sender_ref: '', subject: '', received_on: today() });
  return (
    <>
      {can('letters', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('letters.register')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-end gap-2">
            <Field label={t('letters.receivedOn')} className="w-40">
              <Input
                type="date"
                value={f.received_on}
                onChange={(e) => setF({ ...f, received_on: e.target.value })}
              />
            </Field>
            <Field label={t('letters.sender')} className="w-56">
              <Input value={f.sender} onChange={(e) => setF({ ...f, sender: e.target.value })} />
            </Field>
            <Field label={t('letters.senderRef')} className="w-48">
              <Input
                value={f.sender_ref}
                onChange={(e) => setF({ ...f, sender_ref: e.target.value })}
              />
            </Field>
            <Field label={t('letters.subject')} className="w-72">
              <Input value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} />
            </Field>
            <Button
              variant="primary"
              disabled={!f.sender || !f.subject}
              onClick={() =>
                act.mutate(
                  { path: '/letters/incoming', body: { ...f, sender_ref: f.sender_ref || null } },
                  { onSuccess: () => setF({ ...f, sender: '', sender_ref: '', subject: '' }) },
                )
              }
            >
              {t('letters.registerBtn')}
            </Button>
            <FormError message={errText(act.error, t('auth.unexpected'))} />
          </CardContent>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <CardHeader className="flex-row flex-wrap items-end justify-between gap-2">
          <CardTitle>{t('letters.tabs.incoming')}</CardTitle>
          <Field label={t('letters.search')} className="w-72">
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('letters.searchHint')}
            />
          </Field>
        </CardHeader>
        <CardContent>
          <FormError message={errText(list.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('letters.number')}</TH>
                <TH>{t('letters.receivedOn')}</TH>
                <TH>{t('letters.sender')}</TH>
                <TH>{t('letters.subject')}</TH>
                <TH>{t('letters.statusLabel')}</TH>
              </TR>
            </THead>
            <TBody>
              {list.data?.map((x) => (
                <TR key={x.id}>
                  <TD>
                    <Link className="text-fg-accent underline" to={`/surat/masuk/${x.id}`}>
                      {x.number}
                    </Link>
                  </TD>
                  <TD>{formatDate(x.received_on)}</TD>
                  <TD>{x.sender}</TD>
                  <TD>{x.subject}</TD>
                  <TD>
                    <Pill status={x.status} ns="letters" />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {list.data?.length === 0 && (
            <p className="text-small text-fg-secondary">{t('letters.empty')}</p>
          )}
        </CardContent>
      </Card>
    </>
  );
}

export function IncomingDetailPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const { can, me } = useAuth();
  const q = useQuery({
    queryKey: ['letters', 'in', id],
    queryFn: () =>
      api<
        Incoming & {
          close_note: string | null;
          dispositions: {
            id: string;
            pic_id: string;
            pic: string | null;
            instruction: string;
            deadline: string;
            status: string;
            done_note: string | null;
          }[];
          replies: Outgoing[];
        }
      >(`/letters/incoming/${id}`),
  });
  const files = useAttachments('incoming_letter', id);
  const people = useQuery({
    queryKey: ['letters', 'people'],
    queryFn: () => api<{ id: string; name: string }[]>('/letters/people'),
    enabled: can('letters', 'edit'),
  });
  const sent = useQuery({
    queryKey: ['letters', 'outgoing'],
    queryFn: () => api<Outgoing[]>('/letters/outgoing'),
    enabled: can('letters', 'edit'),
  });
  const act = useDmsAction();
  const [d, setD] = useState({ pic_id: '', instruction: '', deadline: today() });
  const [note, setNote] = useState('');
  const [reply, setReply] = useState('');
  const x = q.data;
  if (!x) return <FormError message={errText(q.error, t('auth.unexpected'))} />;
  const base = `/letters/incoming/${x.id}`;
  const writer = can('letters', 'edit');
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>
              {x.number} · {x.subject}
            </CardTitle>
            <CardDescription>
              {x.sender} {x.sender_ref ? `(${x.sender_ref})` : ''} · {formatDate(x.received_on)}
            </CardDescription>
          </div>
          <Pill status={x.status} ns="letters" />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <AttachmentsPanel
            entityType="incoming_letter"
            entityId={x.id}
            canWrite={writer && x.status !== 'closed'}
          />
          {writer && !x.file_id && (files.data?.length ?? 0) > 0 && (
            <div>
              <Button
                onClick={() =>
                  act.mutate({ path: `${base}/scan`, body: { attachment_id: files.data![0]!.id } })
                }
              >
                {t('letters.setScan')}
              </Button>
            </div>
          )}
          <FormError message={errText(act.error, t('auth.unexpected'))} />
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('letters.dispositions')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Table>
            <TBody>
              {x.dispositions.map((dd) => (
                <TR key={dd.id}>
                  <TD>{dd.pic}</TD>
                  <TD>{dd.instruction}</TD>
                  <TD>{formatDate(dd.deadline)}</TD>
                  <TD>
                    <Pill status={dd.status} ns="letters" />
                    {dd.done_note ? ` ${dd.done_note}` : ''}
                  </TD>
                  <TD>
                    {dd.status === 'open' && dd.pic_id === me?.id && (
                      <Button
                        size="sm"
                        onClick={() =>
                          act.mutate({
                            path: `/letters/dispositions/${dd.id}/done`,
                            body: { note: note || 'Selesai' },
                          })
                        }
                      >
                        {t('letters.done')}
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {writer && x.status !== 'closed' && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('letters.pic')} className="w-72">
                <Select value={d.pic_id} onChange={(e) => setD({ ...d, pic_id: e.target.value })}>
                  <option value="">-</option>
                  {people.data?.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('letters.instruction')} className="w-72">
                <Input
                  value={d.instruction}
                  onChange={(e) => setD({ ...d, instruction: e.target.value })}
                />
              </Field>
              <Field label={t('letters.deadline')} className="w-40">
                <Input
                  type="date"
                  value={d.deadline}
                  onChange={(e) => setD({ ...d, deadline: e.target.value })}
                />
              </Field>
              <Button onClick={() => act.mutate({ path: `${base}/dispositions`, body: d })}>
                {t('letters.dispose')}
              </Button>
            </div>
          )}
          <Field label={t('letters.note')}>
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          {writer && x.status !== 'closed' && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('letters.replyLetter')} className="w-72">
                <Select value={reply} onChange={(e) => setReply(e.target.value)}>
                  <option value="">{t('letters.noReply')}</option>
                  {sent.data
                    ?.filter((o) => o.status === 'sent')
                    .map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.number} · {o.subject}
                      </option>
                    ))}
                </Select>
              </Field>
              <Button
                variant="primary"
                onClick={() =>
                  act.mutate({
                    path: `${base}/close`,
                    body: { reply_id: reply || null, note: note || null },
                  })
                }
              >
                {t('letters.close')}
              </Button>
            </div>
          )}
          {x.replies.map((r) => (
            <p key={r.id} className="text-small">
              {t('letters.reply')}: {r.number} · {r.subject}
            </p>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function OutgoingList() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useQuery({
    queryKey: ['letters', 'outgoing'],
    queryFn: () => api<Outgoing[]>('/letters/outgoing'),
  });
  const templates = useQuery({
    queryKey: ['letters', 'templates'],
    queryFn: () => api<Template[]>('/letters/templates'),
  });
  const act = useDmsAction<Outgoing>();
  const [f, setF] = useState({
    department: 'OPS',
    to: '',
    template_code: 'UMUM',
    signer_name: '',
    needs_meterai: false,
  });
  const [values, setValues] = useState<Record<string, string>>({});
  const tpl = templates.data?.find((x) => x.code === f.template_code);
  const [via, setVia] = useState('email');
  return (
    <>
      {can('letters', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('letters.draft')}</CardTitle>
            <CardDescription>{t('letters.draftHint')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2">
              <Field label={t('letters.department')} className="w-28">
                <Input
                  value={f.department}
                  onChange={(e) => setF({ ...f, department: e.target.value })}
                />
              </Field>
              <Field label={t('letters.to')} className="w-72">
                <Input value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} />
              </Field>
              <Field label={t('letters.template')} className="w-48">
                <Select
                  value={f.template_code}
                  onChange={(e) => setF({ ...f, template_code: e.target.value })}
                >
                  {templates.data?.map((x) => (
                    <option key={x.code} value={x.code}>
                      {x.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('letters.signer')} className="w-48">
                <Input
                  value={f.signer_name}
                  onChange={(e) => setF({ ...f, signer_name: e.target.value })}
                />
              </Field>
              <label className="flex items-center gap-2 text-small">
                <input
                  type="checkbox"
                  checked={f.needs_meterai}
                  onChange={(e) => setF({ ...f, needs_meterai: e.target.checked })}
                />
                {t('letters.meterai')}
              </label>
            </div>
            {tpl?.placeholders.map((ph) => (
              <Field key={ph} label={ph}>
                {ph === 'isi' ? (
                  <Textarea
                    value={values[ph] ?? ''}
                    onChange={(e) => setValues({ ...values, [ph]: e.target.value })}
                  />
                ) : (
                  <Input
                    value={values[ph] ?? ''}
                    onChange={(e) => setValues({ ...values, [ph]: e.target.value })}
                  />
                )}
              </Field>
            ))}
            <FormError message={errText(act.error, t('auth.unexpected'))} />
            <div>
              <Button
                variant="primary"
                disabled={!f.to}
                onClick={() =>
                  act.mutate({
                    path: '/letters/outgoing',
                    body: { ...f, signer_name: f.signer_name || null, values },
                  })
                }
              >
                {t('letters.saveDraft')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('letters.sentLog')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <THead>
              <TR>
                <TH>{t('letters.number')}</TH>
                <TH>{t('letters.to')}</TH>
                <TH>{t('letters.subject')}</TH>
                <TH>{t('letters.statusLabel')}</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {list.data?.map((x) => (
                <TR key={x.id}>
                  <TD>{x.number ?? '-'}</TD>
                  <TD>{x.to}</TD>
                  <TD>{x.subject}</TD>
                  <TD>
                    <Pill status={x.status} ns="letters" />
                    {x.sent_at && (
                      <div className="text-small">
                        {formatDate(x.sent_at.slice(0, 10))} · {x.sent_via}
                      </div>
                    )}
                  </TD>
                  <TD className="flex flex-wrap gap-1">
                    {x.status === 'draft' && can('letters', 'submit') && (
                      <Button
                        size="sm"
                        onClick={() => act.mutate({ path: `/letters/outgoing/${x.id}/submit` })}
                      >
                        {t('letters.submit')}
                      </Button>
                    )}
                    {x.status === 'approved' && can('letters', 'create') && (
                      <>
                        <Select
                          aria-label={t('letters.via')}
                          value={via}
                          onChange={(e) => setVia(e.target.value)}
                        >
                          {['email', 'courier', 'hand', 'portal'].map((v) => (
                            <option key={v} value={v}>
                              {t(`letters.vias.${v}`)}
                            </option>
                          ))}
                        </Select>
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() =>
                            act.mutate({ path: `/letters/outgoing/${x.id}/send`, body: { via } })
                          }
                        >
                          {t('letters.send')}
                        </Button>
                      </>
                    )}
                    {x.file_id && (
                      <Button
                        size="sm"
                        onClick={() =>
                          void downloadFile(
                            `/attachments/${x.file_id}/content?download=true`,
                            `${x.number}.pdf`,
                          )
                        }
                      >
                        <Icon name="picture_as_pdf" /> PDF
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- documents

interface LibDoc {
  id: string;
  category: string;
  category_label: string;
  title: string;
  tags: string[];
  expiry_date: string | null;
  retention_until: string;
  legal_hold: boolean;
}
interface Controlled {
  id: string;
  code: string;
  title: string;
  kind: string;
  system: string | null;
  current_revision: number | null;
  effective_date: string | null;
  next_review: string | null;
}

export function DocumentsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab =
    (['library', 'controlled', 'search'] as const).find((x) => x === params.get('tab')) ??
    'library';
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('dmsdocs.title')}
        value={tab}
        onChange={(v) => setParams({ tab: v })}
        items={['library', 'controlled', 'search'].map((v) => ({
          value: v,
          label: t(`dmsdocs.tabs.${v}`),
        }))}
      />
      {tab === 'library' && <LibraryTab openId={params.get('doc')} />}
      {tab === 'controlled' && <ControlledTab />}
      {tab === 'search' && <SearchTab />}
    </div>
  );
}

function LibraryTab({ openId }: { openId: string | null }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [category, setCategory] = useState('');
  const cats = useQuery({
    queryKey: ['dms', 'cats'],
    queryFn: () => api<{ value: string; label: string }[]>('/dms/categories'),
  });
  const list = useQuery({
    queryKey: ['dms', 'library', category],
    queryFn: () => api<LibDoc[]>(`/dms/library${category ? `?category=${category}` : ''}`),
  });
  const act = useDmsAction<LibDoc>();
  const [f, setF] = useState({ category: 'legal', title: '', tags: '', expiry_date: '' });
  const [open, setOpen] = useState<string | null>(openId);
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader className="flex-row flex-wrap items-end justify-between gap-2">
          <div>
            <CardTitle>{t('dmsdocs.tabs.library')}</CardTitle>
            <CardDescription>{t('dmsdocs.libraryHint')}</CardDescription>
          </div>
          <Field label={t('dmsdocs.category')} className="w-56">
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">{t('dmsdocs.all')}</option>
              {cats.data?.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Field>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {can('dms', 'create') && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('dmsdocs.category')} className="w-48">
                <Select
                  value={f.category}
                  onChange={(e) => setF({ ...f, category: e.target.value })}
                >
                  {cats.data?.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('dmsdocs.docTitle')} className="w-72">
                <Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
              </Field>
              <Field label={t('dmsdocs.tags')} className="w-48">
                <Input value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} />
              </Field>
              <Field label={t('dmsdocs.expiry')} className="w-40">
                <Input
                  type="date"
                  value={f.expiry_date}
                  onChange={(e) => setF({ ...f, expiry_date: e.target.value })}
                />
              </Field>
              <Button
                variant="primary"
                disabled={f.title.trim().length < 2}
                onClick={() =>
                  act.mutate(
                    {
                      path: '/dms/library',
                      body: {
                        category: f.category,
                        title: f.title,
                        tags: f.tags
                          .split(',')
                          .map((x) => x.trim())
                          .filter(Boolean),
                        expiry_date: f.expiry_date || null,
                      },
                    },
                    { onSuccess: (d) => (setOpen(d.id), setF({ ...f, title: '', tags: '' })) },
                  )
                }
              >
                {t('dmsdocs.add')}
              </Button>
            </div>
          )}
          <FormError message={errText(act.error ?? list.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('dmsdocs.docTitle')}</TH>
                <TH>{t('dmsdocs.category')}</TH>
                <TH>{t('dmsdocs.tags')}</TH>
                <TH>{t('dmsdocs.expiry')}</TH>
              </TR>
            </THead>
            <TBody>
              {list.data?.map((d) => (
                <TR key={d.id}>
                  <TD>
                    <Button size="sm" variant="link" onClick={() => setOpen(d.id)}>
                      {d.title}
                    </Button>
                    {d.legal_hold && (
                      <StatusPill tone="danger">{t('dmsdocs.legalHold')}</StatusPill>
                    )}
                  </TD>
                  <TD>{d.category_label}</TD>
                  <TD>{d.tags.join(', ')}</TD>
                  <TD>{d.expiry_date ? formatDate(d.expiry_date) : '-'}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
      {open && <LibraryDetail id={open} />}
    </>
  );
}

function LibraryDetail({ id }: { id: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['dms', 'doc', id],
    queryFn: () =>
      api<
        LibDoc & {
          can_write: boolean;
          legal_hold_reason: string | null;
          access_log: { at: string; user: string; action: string; detail: string | null }[];
        }
      >(`/dms/library/${id}`),
  });
  const files = useAttachments('library_doc', id);
  const act = useDmsAction<{ url: string }>();
  const [link, setLink] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const d = q.data;
  if (!d) return <FormError message={errText(q.error, t('auth.unexpected'))} />;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{d.title}</CardTitle>
        <CardDescription>
          {d.category_label} · {t('dmsdocs.retention', { date: formatDate(d.retention_until) })}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <AttachmentsPanel entityType="library_doc" entityId={d.id} canWrite={d.can_write} />
        {d.can_write && files.data && files.data.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() =>
                act.mutate(
                  { path: `/dms/files/${files.data![0]!.id}/share`, body: { days: 7 } },
                  { onSuccess: (r) => setLink(`${window.location.origin}${r.url}`) },
                )
              }
            >
              <Icon name="link" /> {t('dmsdocs.share')}
            </Button>
            {link && (
              <Input readOnly value={link} aria-label={t('dmsdocs.shareLink')} className="w-96" />
            )}
          </div>
        )}
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('dmsdocs.holdReason')} className="w-80">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Button
            onClick={() =>
              act.mutate({
                path: `/dms/library/${d.id}/legal-hold`,
                body: { hold: !d.legal_hold, reason },
              })
            }
          >
            {d.legal_hold ? t('dmsdocs.releaseHold') : t('dmsdocs.setHold')}
          </Button>
        </div>
        <FormError message={errText(act.error, t('auth.unexpected'))} />
        {d.access_log.length > 0 && (
          <div>
            <h3 className="mb-1 font-heading text-body font-semibold">{t('dmsdocs.accessLog')}</h3>
            <ul className="text-small">
              {d.access_log.map((x, i) => (
                <li key={i}>
                  {formatDate(x.at.slice(0, 10))} · {x.user} · {x.action} {x.detail ?? ''}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ControlledTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const list = useQuery({
    queryKey: ['dms', 'controlled', q],
    queryFn: () => api<Controlled[]>(`/dms/controlled${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  });
  const act = useDmsAction<{ created: number; updated: number; errors: string[] }>();
  return (
    <Card className="overflow-x-auto">
      <CardHeader className="flex-row flex-wrap items-end justify-between gap-2">
        <div>
          <CardTitle>{t('dmsdocs.tabs.controlled')}</CardTitle>
          <CardDescription>{t('dmsdocs.controlledHint')}</CardDescription>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('dmsdocs.search')} className="w-56">
            <Input value={q} onChange={(e) => setQ(e.target.value)} />
          </Field>
          {can('dms', 'edit') && (
            <Field label={t('dmsdocs.import')} className="w-64">
              <Input
                type="file"
                accept=".xlsx"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const form = new FormData();
                  form.append('file', file);
                  act.mutate({ path: '/dms/controlled/import', form });
                }}
              />
            </Field>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {act.data && (
          <p role="status" className="text-small">
            {t('dmsdocs.importResult', {
              created: act.data.created,
              updated: act.data.updated,
              errors: act.data.errors.length,
            })}
          </p>
        )}
        <FormError message={errText(act.error ?? list.error, t('auth.unexpected'))} />
        <Table>
          <THead>
            <TR>
              <TH>{t('dmsdocs.code')}</TH>
              <TH>{t('dmsdocs.docTitle')}</TH>
              <TH>{t('dmsdocs.kind')}</TH>
              <TH>Rev.</TH>
              <TH>{t('dmsdocs.effective')}</TH>
              <TH>{t('dmsdocs.nextReview')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.map((d) => (
              <TR key={d.id}>
                <TD>
                  <Link className="text-fg-accent underline" to={`/dokumen/terkendali/${d.id}`}>
                    {d.code}
                  </Link>
                </TD>
                <TD>{d.title}</TD>
                <TD>{t(`dmsdocs.kinds.${d.kind}`)}</TD>
                <TD>{d.current_revision ?? '-'}</TD>
                <TD>{d.effective_date ? formatDate(d.effective_date) : '-'}</TD>
                <TD>{d.next_review ? formatDate(d.next_review) : '-'}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export function ControlledDetailPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const q = useQuery({
    queryKey: ['dms', 'ctl', id],
    queryFn: () =>
      api<
        Controlled & {
          can_write: boolean;
          revisions: {
            id: string;
            revision: number;
            status: string;
            change_summary: string;
            effective_date: string | null;
            reject_reason: string | null;
          }[];
        }
      >(`/dms/controlled/${id}`),
  });
  const files = useAttachments('controlled_doc', id);
  const act = useDmsAction();
  const [rev, setRev] = useState({ change_summary: '', attachment_id: '' });
  const d = q.data;
  if (!d) return <FormError message={errText(q.error, t('auth.unexpected'))} />;
  const base = `/dms/controlled/${d.id}`;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {d.code} · {d.title}
        </CardTitle>
        <CardDescription>
          {t(`dmsdocs.kinds.${d.kind}`)} · {d.system ?? '-'} · {t('dmsdocs.nextReview')}{' '}
          {d.next_review ? formatDate(d.next_review) : '-'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Table>
          <TBody>
            {d.revisions.map((r) => (
              <TR key={r.id}>
                <TD>Rev.{r.revision}</TD>
                <TD>
                  <Pill status={r.status} ns="dmsdocs" />
                </TD>
                <TD>{r.change_summary}</TD>
                <TD>{r.effective_date ? formatDate(r.effective_date) : '-'}</TD>
                <TD className="flex gap-1">
                  <Button
                    size="sm"
                    onClick={() =>
                      void downloadFile(
                        `${base}/revisions/${r.id}/pdf`,
                        `${d.code}-Rev${r.revision}.pdf`,
                      )
                    }
                  >
                    <Icon name="picture_as_pdf" /> PDF
                  </Button>
                  {r.status === 'draft' && d.can_write && (
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => act.mutate({ path: `${base}/revisions/${r.id}/submit` })}
                    >
                      {t('dmsdocs.submitRelease')}
                    </Button>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        {d.can_write && (
          <>
            <AttachmentsPanel entityType="controlled_doc" entityId={d.id} canWrite />
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('dmsdocs.revisionFile')} className="w-56">
                <Select
                  value={rev.attachment_id}
                  onChange={(e) => setRev({ ...rev, attachment_id: e.target.value })}
                >
                  <option value="">-</option>
                  {files.data?.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.filename}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('dmsdocs.changeSummary')} className="w-80">
                <Input
                  value={rev.change_summary}
                  onChange={(e) => setRev({ ...rev, change_summary: e.target.value })}
                />
              </Field>
              <Button onClick={() => act.mutate({ path: `${base}/revisions`, body: rev })}>
                {t('dmsdocs.newRevision')}
              </Button>
            </div>
          </>
        )}
        <FormError message={errText(act.error, t('auth.unexpected'))} />
      </CardContent>
    </Card>
  );
}

function SearchTab() {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const [term, setTerm] = useState('');
  const res = useQuery({
    queryKey: ['dms', 'search', term],
    queryFn: () =>
      api<
        {
          kind: string;
          id: string;
          title: string;
          snippet: string | null;
          entity_type?: string;
          category?: string;
        }[]
      >(`/dms/search?q=${encodeURIComponent(term)}`),
    enabled: term.length >= 2,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('dmsdocs.tabs.search')}</CardTitle>
        <CardDescription>{t('dmsdocs.searchHint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setTerm(q.trim());
          }}
        >
          <Input
            aria-label={t('dmsdocs.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <Button type="submit" variant="primary">
            <Icon name="search" /> {t('dmsdocs.search')}
          </Button>
        </form>
        <FormError message={errText(res.error, t('auth.unexpected'))} />
        <ul className="flex flex-col gap-2">
          {res.data?.map((h) => (
            <li key={`${h.kind}-${h.id}`} className="rounded-md border border-border p-2">
              <div className="font-semibold">{h.title}</div>
              <div className="text-small text-fg-secondary">
                {h.kind === 'file' ? h.entity_type : h.category}
              </div>
              {h.snippet && (
                // ts_headline marks matches with <b>; render as text, not HTML.
                <div className="text-small">{h.snippet.replace(/<\/?b>/g, '')}</div>
              )}
            </li>
          ))}
        </ul>
        {res.data?.length === 0 && (
          <p className="text-small text-fg-secondary">{t('dmsdocs.noHits')}</p>
        )}
      </CardContent>
    </Card>
  );
}
