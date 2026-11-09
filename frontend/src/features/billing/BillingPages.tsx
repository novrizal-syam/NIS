import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { FilterTile } from '@/features/crm/CrmPills';
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDate, formatDateTime, formatIDR } from '@/lib/format';
import {
  useArAging,
  useBankImport,
  useBankLines,
  useBillableDors,
  useBillingPost,
  useBillingProjects,
  useCashKpis,
  useDisputes,
  useInvoice,
  useInvoices,
  useReceipts,
  useSignedTickets,
  useTicket,
  useTicketByToken,
  useTickets,
  type InvStatus,
  type Ticket,
} from './api';
import { SignaturePad } from './SignaturePad';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());
const TK_TONE: Record<Ticket['status'], StatusTone> = {
  awaiting_signature: 'warning',
  signed: 'success',
  invoiced: 'info',
  cancelled: 'neutral',
};
const INV_TONE: Record<InvStatus, StatusTone> = {
  draft: 'neutral',
  faktur_issued: 'info',
  sent: 'warning',
  paid: 'success',
  cancelled: 'neutral',
};
const TABS = ['tickets', 'invoices', 'receipts', 'bank', 'disputes', 'aging'] as const;
type Tab = (typeof TABS)[number];

export function BillingPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get('tab') ?? '')
    ? (params.get('tab') as Tab)
    : 'tickets';
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('billing.title')}
        value={tab}
        onChange={(v) => setParams({ tab: v })}
        items={TABS.map((v) => ({ value: v, label: t(`billing.tabs.${v}`) }))}
      />
      {tab === 'tickets' && <TicketsTab />}
      {tab === 'invoices' && <InvoicesTab />}
      {tab === 'receipts' && <ReceiptsTab />}
      {tab === 'bank' && <BankTab />}
      {tab === 'disputes' && <DisputesTab />}
      {tab === 'aging' && <AgingTab />}
    </div>
  );
}

// ---------------------------------------------------------------- tickets

function TicketsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState('');
  const list = useTickets(status);
  const projects = useBillingProjects();
  const post = useBillingPost<Ticket>();
  const [project, setProject] = useState('');
  const dors = useBillableDors(project);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState(today());
  return (
    <>
      {can('billing', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('billing.newTicket')}</CardTitle>
            <CardDescription>{t('billing.newTicketHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('pr.project')} className="min-w-0 flex-1">
                <Select value={project} onChange={(e) => setProject(e.target.value)}>
                  <option value="">{t('master.choose')}</option>
                  {projects.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.number} · {p.contract_number} · {p.name}
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
              <Button
                variant="primary"
                disabled={!project || !from || !to || post.isPending}
                onClick={() =>
                  post.mutate(
                    {
                      path: '/billing/tickets',
                      body: { project_id: project, date_from: from, date_to: to },
                    },
                    { onSuccess: (tk) => navigate(`/tagihan/tiket/${tk.id}`) },
                  )
                }
              >
                <Icon name="fact_check" /> {t('billing.createTicket')}
              </Button>
            </div>
            {dors.data && (
              <p className="text-small text-fg-secondary">
                {dors.data.length === 0
                  ? t('billing.noBillableDors')
                  : t('billing.billableDors', {
                      count: dors.data.length,
                      list: dors.data
                        .map((d) => `${d.number} (${formatDate(d.report_date)})`)
                        .join(', '),
                    })}
              </p>
            )}
          </CardContent>
        </Card>
      )}
      <div className="flex flex-wrap gap-2">
        {(['awaiting_signature', 'signed', 'invoiced'] as const).map((s) => (
          <Button
            key={s}
            size="sm"
            variant={status === s ? 'primary' : 'secondary'}
            onClick={() => setStatus(status === s ? '' : s)}
          >
            {t(`billing.tkStatus.${s}`)}
          </Button>
        ))}
      </div>
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('pr.project')}</TH>
              <TH>{t('billing.period')}</TH>
              <TH className="text-right">{t('billing.value')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.length === 0 && (
              <TR>
                <TD colSpan={5} className="py-8 text-center text-fg-secondary">
                  {t('billing.noTickets')}
                </TD>
              </TR>
            )}
            {list.data?.map((r) => (
              <TR key={r.id}>
                <TD>
                  <Link
                    to={`/tagihan/tiket/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.number}
                  </Link>
                </TD>
                <TD>{r.project_number}</TD>
                <TD className="whitespace-nowrap">
                  {formatDate(r.period_from)} – {formatDate(r.period_to)}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(r.value)}
                  {Number(r.disputed_value) > 0 && (
                    <span className="block text-caption text-danger">
                      −{formatIDR(r.disputed_value)}
                    </span>
                  )}
                </TD>
                <TD>
                  <StatusPill tone={TK_TONE[r.status]}>
                    {t(`billing.tkStatus.${r.status}`)}
                  </StatusPill>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

/** Lines with optional dispute checkboxes + signature; used on the tablet and via the link. */
function SignForm({ tk, path, onSigned }: { tk: Ticket; path: string; onSigned: () => void }) {
  const { t } = useTranslation();
  const post = useBillingPost();
  const [disputes, setDisputes] = useState<Record<string, string>>({});
  const [signer, setSigner] = useState('');
  const [acceptance, setAcceptance] = useState('');
  const [png, setPng] = useState<string | null>(null);
  const disputed = tk.lines
    .filter((l) => l.id in disputes)
    .reduce((a, l) => a + Number(l.amount), 0);
  const ready =
    signer.trim().length >= 3 &&
    png !== null &&
    Object.values(disputes).every((r) => r.trim().length >= 5);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('billing.signTitle')}</CardTitle>
        <CardDescription>{t('billing.signHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>{t('billing.dispute')}</TH>
                <TH>{t('vi.date')}</TH>
                <TH>{t('quotation.description')}</TH>
                <TH className="text-right">{t('quotation.amount')}</TH>
              </TR>
            </THead>
            <TBody>
              {tk.lines.map((l) => (
                <TR key={l.id}>
                  <TD className="w-64">
                    <label className="flex items-center gap-2 text-small">
                      <input
                        type="checkbox"
                        aria-label={`${t('billing.dispute')} ${l.description}`}
                        checked={l.id in disputes}
                        onChange={(e) => {
                          const next = { ...disputes };
                          if (e.target.checked) next[l.id] = '';
                          else delete next[l.id];
                          setDisputes(next);
                        }}
                      />
                      {t('billing.dispute')}
                    </label>
                    {l.id in disputes && (
                      <Input
                        aria-label={`${t('billing.disputeReason')} ${l.description}`}
                        placeholder={t('billing.disputeReason')}
                        value={disputes[l.id]}
                        onChange={(e) => setDisputes({ ...disputes, [l.id]: e.target.value })}
                      />
                    )}
                  </TD>
                  <TD className="whitespace-nowrap">{formatDate(l.work_date)}</TD>
                  <TD className="min-w-56">{l.description}</TD>
                  <TD
                    className={
                      l.id in disputes
                        ? 'whitespace-nowrap text-right tabular-nums text-danger line-through'
                        : 'whitespace-nowrap text-right tabular-nums'
                    }
                  >
                    {formatIDR(l.amount)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
        <p className="text-small">
          {t('billing.approvedValue')}:{' '}
          <span className="font-semibold tabular-nums text-fg">
            {formatIDR(Number(tk.gross_value) - disputed)}
          </span>
          {disputed > 0 && (
            <span className="ml-2 text-danger">
              ({t('billing.disputed')} {formatIDR(disputed)})
            </span>
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <Field label={t('billing.signerName')} required className="min-w-0 flex-1">
            <Input value={signer} onChange={(e) => setSigner(e.target.value)} />
          </Field>
          <Field label={t('billing.acceptanceNo')} className="w-56">
            <Input value={acceptance} onChange={(e) => setAcceptance(e.target.value)} />
          </Field>
        </div>
        <SignaturePad onChange={setPng} />
        <FormError message={errText(post.error, t('auth.unexpected'))} />
        <Button
          variant="primary"
          className="self-start"
          disabled={!ready || post.isPending}
          onClick={() =>
            post.mutate(
              {
                path,
                body: {
                  signer_name: signer.trim(),
                  signature: png,
                  acceptance_no: acceptance.trim() || null,
                  disputes: Object.entries(disputes).map(([line_id, reason]) => ({
                    line_id,
                    reason,
                  })),
                },
              },
              { onSuccess: onSigned },
            )
          }
        >
          <Icon name="draw" /> {t('billing.signButton')}
        </Button>
      </CardContent>
    </Card>
  );
}

function TicketSummary({ tk }: { tk: Ticket }) {
  const { t } = useTranslation();
  return (
    <Card>
      <CardHeader>
        <p className="eyebrow">
          {tk.number} · {tk.project_number} · {tk.contract_number}
        </p>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-section-title">{tk.client_name}</CardTitle>
          <StatusPill tone={TK_TONE[tk.status]}>{t(`billing.tkStatus.${tk.status}`)}</StatusPill>
        </div>
        <CardDescription>
          {formatDate(tk.period_from)} – {formatDate(tk.period_to)} · DOR{' '}
          {tk.dors.map((d) => d.number).join(', ')}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-small">
        <p>
          {t('billing.value')}:{' '}
          <span className="font-heading text-card-title tabular-nums text-fg">
            {formatIDR(tk.value)}
          </span>
          {Number(tk.disputed_value) > 0 && (
            <span className="ml-2 text-danger">
              ({t('billing.disputed')} {formatIDR(tk.disputed_value)})
            </span>
          )}
        </p>
        {tk.signed_at && (
          <p className="text-fg-secondary">
            {t('billing.signedBy', {
              name: tk.signer_name,
              at: formatDateTime(tk.signed_at),
              method: t(`billing.method.${tk.sign_method ?? 'tablet'}`),
            })}
            {tk.acceptance_no ? ` · ${t('billing.acceptanceNo')}: ${tk.acceptance_no}` : ''}
            {tk.psre_ref ? ` · PSrE ${tk.psre_ref}` : ''}
          </p>
        )}
        {tk.invoice && (
          <Link
            to={`/tagihan/invoice/${tk.invoice.id}`}
            className="font-semibold text-fg-accent underline"
          >
            {tk.invoice.number}
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

export function TicketPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const tk = useTicket(id);
  const post = useBillingPost<{ url: string }>();
  const [mode, setMode] = useState<'none' | 'tablet' | 'link'>('none');
  const [email, setEmail] = useState('');
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');
  if (tk.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (tk.error || !tk.data) return <FormError message={errText(tk.error, t('auth.unexpected'))} />;
  const d = tk.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/tagihan"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('billing.back')}
      </Link>
      <TicketSummary tk={d} />
      {d.can_sign && (
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => setMode('tablet')}>
            <Icon name="tablet" /> {t('billing.signTablet')}
          </Button>
          <Button variant="secondary" onClick={() => setMode('link')}>
            <Icon name="link" /> {t('billing.signLink')}
          </Button>
        </div>
      )}
      {mode === 'link' && d.can_sign && (
        <Card>
          <CardContent className="flex flex-col gap-2 pt-4">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('billing.clientEmail')} className="min-w-0 flex-1">
                <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </Field>
              <Button
                variant="primary"
                disabled={!email.includes('@') || post.isPending}
                onClick={() =>
                  post.mutate({ path: `/billing/tickets/${d.id}/sign-link`, body: { email } })
                }
              >
                <Icon name="send" /> {t('billing.sendLink')}
              </Button>
            </div>
            {post.data && (
              <p role="status" className="break-all text-small text-success">
                {t('billing.linkSent')} {post.data.url}
              </p>
            )}
          </CardContent>
        </Card>
      )}
      {mode === 'tablet' && d.can_sign && (
        <SignForm tk={d} path={`/billing/tickets/${d.id}/sign`} onSigned={() => setMode('none')} />
      )}
      <Tabs
        label={d.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'files', label: t('billing.documents') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && mode !== 'tablet' && (
        <Card className="overflow-x-auto">
          <Table>
            <TBody>
              {d.lines.map((l) => (
                <TR key={l.id}>
                  <TD className="whitespace-nowrap">{formatDate(l.work_date)}</TD>
                  <TD className="min-w-56">
                    {l.description}
                    {l.disputed && (
                      <span className="block text-caption text-danger">
                        {t('billing.dispute')}: {l.dispute_reason}
                      </span>
                    )}
                  </TD>
                  <TD
                    className={
                      l.disputed
                        ? 'whitespace-nowrap text-right tabular-nums line-through'
                        : 'whitespace-nowrap text-right tabular-nums'
                    }
                  >
                    {formatIDR(l.amount)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="service_ticket" entityId={d.id} canWrite={false} />
      )}
      {tab === 'history' && <HistoryPanel entityType="service_ticket" entityId={d.id} />}
    </div>
  );
}

/** /tanda-tangan/:token — opened by the client representative from the e-mailed link. */
export function ClientSignPage() {
  const { t } = useTranslation();
  const { token = '' } = useParams();
  const tk = useTicketByToken(token);
  const [done, setDone] = useState(false);
  if (tk.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (done)
    return (
      <p role="status" className="rounded-control bg-success-tint px-3 py-2 text-success">
        {t('billing.thanks')}
      </p>
    );
  if (tk.error || !tk.data) return <FormError message={errText(tk.error, t('auth.unexpected'))} />;
  return (
    <div className="flex flex-col gap-4">
      <TicketSummary tk={tk.data} />
      {tk.data.can_sign && (
        <SignForm tk={tk.data} path={`/billing/sign/${token}`} onSigned={() => setDone(true)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- invoices

function InvoicesTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const list = useInvoices(status, q);
  const signed = useSignedTickets();
  const post = useBillingPost<{ id: string }>();
  const [picked, setPicked] = useState<string[]>([]);
  const [date, setDate] = useState(today());
  const contract = signed.data?.find((s) => s.id === picked[0])?.contract_id;
  return (
    <>
      {can('billing', 'create') && (signed.data?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('billing.newInvoice')}</CardTitle>
            <CardDescription>{t('billing.newInvoiceHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            {signed.data?.map((s) => (
              <label key={s.id} className="flex items-center gap-2 text-small">
                <input
                  type="checkbox"
                  checked={picked.includes(s.id)}
                  disabled={contract !== undefined && contract !== s.contract_id}
                  onChange={(e) =>
                    setPicked(
                      e.target.checked ? [...picked, s.id] : picked.filter((x) => x !== s.id),
                    )
                  }
                />
                {s.number} · {s.contract_number} · {s.project_number} · {formatIDR(s.value)}
              </label>
            ))}
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('vi.invoiceDate')} className="w-44">
                <Input
                  type="date"
                  max={today()}
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
              </Field>
              <Button
                variant="primary"
                disabled={picked.length === 0 || post.isPending}
                onClick={() =>
                  post.mutate(
                    { path: '/billing/invoices', body: { ticket_ids: picked, invoice_date: date } },
                    { onSuccess: (inv) => navigate(`/tagihan/invoice/${inv.id}`) },
                  )
                }
              >
                <Icon name="description" /> {t('billing.createInvoice')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      <div className="flex flex-wrap items-end gap-2">
        {(['draft', 'faktur_issued', 'sent', 'overdue', 'paid'] as const).map((s) => (
          <FilterTile
            key={s}
            label={t(`billing.invStatus.${s}`)}
            value={s === 'overdue' ? '' : (list.data?.counts[s] ?? 0)}
            active={status === s}
            onClick={() => setStatus(status === s ? '' : s)}
          />
        ))}
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
      </div>
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('billing.client')}</TH>
              <TH>{t('vi.dueDate')}</TH>
              <TH className="text-right">{t('pr.total')}</TH>
              <TH className="text-right">{t('vi.outstanding')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/tagihan/invoice/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.number}
                  </Link>
                  <span className="block text-caption text-fg-muted">{r.faktur_number ?? '–'}</span>
                </TD>
                <TD>{r.client_name}</TD>
                <TD className="whitespace-nowrap">
                  {formatDate(r.due_date)}
                  {r.overdue && (
                    <span className="ml-1 text-caption font-semibold text-danger">
                      {t('mnt.overdue')}
                    </span>
                  )}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.total)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(r.outstanding)}
                </TD>
                <TD>
                  <StatusPill tone={INV_TONE[r.status]}>
                    {t(`billing.invStatus.${r.status}`)}
                  </StatusPill>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

export function InvoicePage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { id = '' } = useParams();
  const inv = useInvoice(id);
  const post = useBillingPost<{ email_status?: string }>();
  const [faktur, setFaktur] = useState({ no: '', date: today() });
  const [email, setEmail] = useState<string | null>(null);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');
  if (inv.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (inv.error || !inv.data)
    return <FormError message={errText(inv.error, t('auth.unexpected'))} />;
  const d = inv.data;
  const edit = can('billing', 'edit');
  const rows: [string, string, boolean?][] = [
    [t('billing.subtotal'), d.subtotal],
    [t('billing.dppOther'), d.dpp_other],
    [`PPN ${d.ppn_rate}%`, d.ppn],
    [t('pr.total'), d.total, true],
    [t('billing.pph23Expected', { pct: d.pph23_rate }), d.pph23_expected],
    [t('billing.netCash'), d.net_cash, true],
  ];
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/tagihan?tab=invoices"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('billing.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {d.contract_number} · {d.faktur_number ?? t('billing.noFaktur')}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{d.client_name}</CardTitle>
            <StatusPill tone={INV_TONE[d.status]}>{t(`billing.invStatus.${d.status}`)}</StatusPill>
          </div>
          <CardDescription>
            {formatDate(d.invoice_date)} · {t('vi.dueDate')} {formatDate(d.due_date)}
            {d.sent_at
              ? ` · ${t('billing.sentTo', { to: d.sent_to, at: formatDateTime(d.sent_at) })}`
              : ''}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <dl className="grid max-w-md gap-1 text-small">
            {rows.map(([label, value, bold]) => (
              <div key={label} className="flex justify-between gap-4">
                <dt className={bold ? 'font-semibold text-fg' : 'text-fg-muted'}>{label}</dt>
                <dd
                  className={
                    bold ? 'font-semibold tabular-nums text-fg' : 'tabular-nums text-fg-body'
                  }
                >
                  {formatIDR(value)}
                </dd>
              </div>
            ))}
            {Number(d.stamp_duty) > 0 && (
              <p className="text-caption text-fg-muted">
                {t('billing.stampDuty', { amount: formatIDR(d.stamp_duty) })}
              </p>
            )}
          </dl>
          <FormError message={errText(post.error, t('auth.unexpected'))} />
          {edit && d.status === 'draft' && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('billing.fakturNo')} hint={t('billing.fakturHint')} className="w-64">
                <Input
                  value={faktur.no}
                  onChange={(e) => setFaktur({ ...faktur, no: e.target.value })}
                />
              </Field>
              <Field label={t('billing.fakturDate')} className="w-44">
                <Input
                  type="date"
                  value={faktur.date}
                  onChange={(e) => setFaktur({ ...faktur, date: e.target.value })}
                />
              </Field>
              <Button
                variant="primary"
                disabled={faktur.no.trim().length < 10 || post.isPending}
                onClick={() =>
                  post.mutate({
                    path: `/billing/invoices/${d.id}/faktur`,
                    body: { faktur_number: faktur.no.trim(), faktur_date: faktur.date },
                  })
                }
              >
                <Icon name="receipt_long" /> {t('billing.issueFaktur')}
              </Button>
              <Button
                variant="destructive"
                onClick={() => post.mutate({ path: `/billing/invoices/${d.id}/cancel` })}
              >
                {t('vi.cancel')}
              </Button>
            </div>
          )}
          {d.status !== 'draft' && d.status !== 'cancelled' && (
            <div className="flex flex-wrap items-end gap-2">
              <Button
                variant="secondary"
                onClick={() =>
                  void downloadFile(`/billing/coretax.xml?ids=${d.id}`, `${d.number}.xml`)
                }
              >
                <Icon name="code" /> {t('billing.coretaxXml')}
              </Button>
              {edit && (
                <>
                  <Field label={t('billing.clientEmail')} className="w-64">
                    <Input
                      type="email"
                      value={email ?? d.client_email ?? ''}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </Field>
                  <Button
                    variant="primary"
                    disabled={!(email ?? d.client_email ?? '').includes('@') || post.isPending}
                    onClick={() =>
                      post.mutate({
                        path: `/billing/invoices/${d.id}/send`,
                        body: { email: email ?? d.client_email },
                      })
                    }
                  >
                    <Icon name="send" /> {t('billing.sendInvoice')}
                  </Button>
                </>
              )}
            </div>
          )}
          {post.data?.email_status && (
            <p role="status" className="text-small text-fg-secondary">
              {t(`billing.emailStatus.${post.data.email_status}`, {
                defaultValue: post.data.email_status,
              })}
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
          { value: 'files', label: t('billing.documents') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>{t('billing.tabs.tickets')}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-1 text-small">
              {d.tickets.map((tk) => (
                <Link key={tk.id} to={`/tagihan/tiket/${tk.id}`} className="underline">
                  {tk.number} · {formatIDR(tk.value)}{' '}
                  {tk.acceptance_no ? `· ${tk.acceptance_no}` : ''}
                </Link>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t('billing.tabs.receipts')}</CardTitle>
              <CardDescription>{t('billing.bpHelp')}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-1 text-small">
              {d.receipts.length === 0 && (
                <span className="text-fg-secondary">{t('billing.noReceipts')}</span>
              )}
              {d.receipts.map((r) => (
                <span key={r.number}>
                  {r.number} · {formatDate(r.receipt_date)} · {formatIDR(r.cash)} + PPh 23{' '}
                  {formatIDR(r.pph23)}
                  {r.bukti_potong_no ? ` · BP ${r.bukti_potong_no}` : ''}
                </span>
              ))}
            </CardContent>
          </Card>
        </div>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="customer_invoice" entityId={d.id} canWrite={edit} />
      )}
      {tab === 'history' && <HistoryPanel entityType="customer_invoice" entityId={d.id} />}
    </div>
  );
}

// ---------------------------------------------------------------- receipts, bank

function ReceiptsTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useReceipts();
  const open = useInvoices('', '');
  const post = useBillingPost();
  const [v, setV] = useState({ invoice: '', date: today(), cash: '', pph: '', bp: '', ref: '' });
  const payable =
    open.data?.items.filter((i) => i.status === 'faktur_issued' || i.status === 'sent') ?? [];
  return (
    <>
      {can('billing', 'create') && (
        <Card>
          <CardHeader>
            <CardTitle>{t('billing.newReceipt')}</CardTitle>
            <CardDescription>{t('billing.receiptHelp')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-end gap-2">
            <FormError message={errText(post.error, t('auth.unexpected'))} />
            <Field label="Invoice" className="min-w-0 flex-1">
              <Select value={v.invoice} onChange={(e) => setV({ ...v, invoice: e.target.value })}>
                <option value="">{t('master.choose')}</option>
                {payable.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.number} · {i.client_name} · {formatIDR(i.outstanding)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('vi.date')} className="w-40">
              <Input
                type="date"
                max={today()}
                value={v.date}
                onChange={(e) => setV({ ...v, date: e.target.value })}
              />
            </Field>
            <Field label={t('billing.cash')} className="w-40">
              <Input
                inputMode="numeric"
                value={v.cash}
                onChange={(e) => setV({ ...v, cash: e.target.value })}
              />
            </Field>
            <Field label={t('billing.pph23Withheld')} className="w-36">
              <Input
                inputMode="numeric"
                value={v.pph}
                onChange={(e) => setV({ ...v, pph: e.target.value })}
              />
            </Field>
            <Field label={t('billing.bpNo')} className="w-40">
              <Input value={v.bp} onChange={(e) => setV({ ...v, bp: e.target.value })} />
            </Field>
            <Button
              variant="primary"
              disabled={!v.invoice || !moneyToApi(v.cash) || post.isPending}
              onClick={() =>
                post.mutate(
                  {
                    path: '/billing/receipts',
                    body: {
                      receipt_date: v.date,
                      bank_ref: v.ref || null,
                      allocations: [
                        {
                          invoice_id: v.invoice,
                          cash: moneyToApi(v.cash),
                          pph23: moneyToApi(v.pph) ?? '0',
                          bukti_potong_no: v.bp || null,
                        },
                      ],
                    },
                  },
                  { onSuccess: () => setV({ ...v, invoice: '', cash: '', pph: '', bp: '' }) },
                )
              }
            >
              <Icon name="payments" /> {t('billing.recordReceipt')}
            </Button>
          </CardContent>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('billing.client')}</TH>
              <TH>{t('vi.date')}</TH>
              <TH className="text-right">{t('billing.cash')}</TH>
              <TH className="text-right">PPh 23</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.map((r) => (
              <TR key={r.id}>
                <TD>
                  {r.number}
                  <span className="block text-caption text-fg-muted">
                    {r.source === 'bank_import' ? t('billing.fromBank') : t('billing.manual')}
                  </span>
                </TD>
                <TD>{r.client_name}</TD>
                <TD className="whitespace-nowrap">{formatDate(r.receipt_date)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.cash)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.pph23)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

function BankTab() {
  const { t } = useTranslation();
  const lines = useBankLines();
  const imp = useBankImport();
  const post = useBillingPost();
  const open = useInvoices('', '');
  const [pick, setPick] = useState<Record<string, string>>({});
  const payable =
    open.data?.items.filter((i) => i.status === 'faktur_issued' || i.status === 'sent') ?? [];
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t('billing.bankImport')}</CardTitle>
          <CardDescription>{t('billing.bankImportHelp')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <input
            type="file"
            accept=".csv,.txt,.sta,.940,.mt940"
            aria-label={t('billing.bankFile')}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) imp.mutate(f);
              e.target.value = '';
            }}
          />
          <FormError message={errText(imp.error ?? post.error, t('auth.unexpected'))} />
          {imp.data && (
            <p role="status" className="text-small text-success">
              {t('billing.imported', imp.data)}
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('vi.date')}</TH>
              <TH>{t('qhse.description')}</TH>
              <TH className="text-right">{t('billing.cash')}</TH>
              <TH>Invoice</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {lines.data?.length === 0 && (
              <TR>
                <TD colSpan={5} className="py-6 text-center text-fg-secondary">
                  {t('billing.noBankLines')}
                </TD>
              </TR>
            )}
            {lines.data?.map((b) => {
              const chosen = pick[b.id] ?? b.suggested_invoice_id ?? '';
              return (
                <TR key={b.id}>
                  <TD className="whitespace-nowrap">{formatDate(b.value_date)}</TD>
                  <TD className="min-w-48">
                    {b.description}
                    <span className="block text-caption text-fg-muted">{b.reference}</span>
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(b.amount)}
                  </TD>
                  <TD className="min-w-56">
                    <Select
                      aria-label={`Invoice ${b.description}`}
                      value={chosen}
                      onChange={(e) => setPick({ ...pick, [b.id]: e.target.value })}
                    >
                      <option value="">–</option>
                      {payable.map((i) => (
                        <option key={i.id} value={i.id}>
                          {i.number} · {formatIDR(i.outstanding)}
                        </option>
                      ))}
                    </Select>
                    {b.match_rule && chosen === b.suggested_invoice_id && (
                      <span className="text-caption text-success">
                        {t(`billing.rule.${b.match_rule}`)}
                      </span>
                    )}
                  </TD>
                  <TD className="whitespace-nowrap">
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={!chosen || post.isPending}
                      onClick={() =>
                        post.mutate({
                          path: `/billing/bank-lines/${b.id}/confirm`,
                          body: { invoice_id: chosen },
                        })
                      }
                    >
                      {t('billing.confirm')}
                    </Button>{' '}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => post.mutate({ path: `/billing/bank-lines/${b.id}/ignore` })}
                    >
                      {t('billing.ignore')}
                    </Button>
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </Card>
    </>
  );
}

function DisputesTab() {
  const { t } = useTranslation();
  const list = useDisputes();
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <CardDescription>{t('billing.disputeHelp')}</CardDescription>
      </CardHeader>
      <Table>
        <THead>
          <TR>
            <TH>Ticket</TH>
            <TH>{t('vi.date')}</TH>
            <TH>{t('quotation.description')}</TH>
            <TH>{t('billing.disputeReason')}</TH>
            <TH className="text-right">{t('quotation.amount')}</TH>
          </TR>
        </THead>
        <TBody>
          {list.data?.map((x) => (
            <TR key={x.id}>
              <TD className="whitespace-nowrap">
                {x.ticket_number}
                <span className="block text-caption text-fg-muted">{x.project_number}</span>
              </TD>
              <TD className="whitespace-nowrap">{formatDate(x.work_date)}</TD>
              <TD>{x.description}</TD>
              <TD>{x.dispute_reason}</TD>
              <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(x.amount)}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </Card>
  );
}

const BUCKETS = ['not_due', 'd1_30', 'd31_60', 'd61_90', 'd90_plus', 'total'] as const;

function AgingTab() {
  const { t } = useTranslation();
  const aging = useArAging();
  const k = useCashKpis();
  const tile = (label: string, value: string | null, good?: boolean) => (
    <div className="rounded-control border border-border px-3 py-2">
      <dt className="text-caption text-fg-muted">{label}</dt>
      <dd
        className={
          good === undefined
            ? 'font-heading text-card-title tabular-nums text-fg'
            : good
              ? 'font-heading text-card-title tabular-nums text-success'
              : 'font-heading text-card-title tabular-nums text-danger'
        }
      >
        {value ?? '–'}
      </dd>
    </div>
  );
  return (
    <>
      {k.data && (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {tile(t('billing.arBalance'), formatIDR(k.data.ar_balance))}
          {tile(
            'DSO',
            k.data.dso_days ? `${k.data.dso_days.replace('.', ',')} ${t('billing.days')}` : null,
          )}
          {tile(
            t('billing.daysToCash'),
            k.data.days_to_cash
              ? `${k.data.days_to_cash.replace('.', ',')} ${t('billing.days')}`
              : null,
            k.data.days_to_cash ? Number(k.data.days_to_cash) < 30 : undefined,
          )}
          {tile(t('billing.paidInvoices'), String(k.data.paid_invoices))}
        </dl>
      )}
      <Card className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('billing.client')}</TH>
              {BUCKETS.map((b) => (
                <TH key={b} className="text-right">
                  {t(`vi.buckets.${b}`)}
                </TH>
              ))}
            </TR>
          </THead>
          <TBody>
            {aging.data?.rows.map((r) => (
              <TR key={r.client_code}>
                <TD>{r.client_name}</TD>
                {BUCKETS.map((b) => (
                  <TD key={b} className="whitespace-nowrap text-right tabular-nums">
                    {Number(r[b]) ? formatIDR(r[b]) : '–'}
                  </TD>
                ))}
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}
