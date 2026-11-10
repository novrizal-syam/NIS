import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { SignaturePad } from '@/features/billing/SignaturePad';
import { moneyToApi } from '@/features/crm/api';
import { ApiError, api, downloadFile, postJson } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

function usePortal<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown; method?: string; form?: FormData }) =>
      v.form
        ? api<R>(v.path, { method: 'POST', body: v.form })
        : v.method
          ? api<R>(v.path, { method: v.method, body: JSON.stringify(v.body) })
          : postJson<R>(v.path, v.body ?? {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['portal'] }),
  });
}

export function PortalPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const me = useQuery({
    queryKey: ['portal', 'me'],
    queryFn: () =>
      api<{
        client: { code: string; name: string } | null;
        vendor: { code: string; name: string } | null;
      }>('/portal/me'),
  });
  return (
    <div className="flex flex-col gap-4">
      {me.data?.client && <ClientPortal name={me.data.client.name} />}
      {me.data?.vendor && <VendorPortal name={me.data.vendor.name} />}
      {can('finance', 'view') && <SubmissionsQueue />}
      {can('users', 'edit') && <LinkAccounts />}
      {me.data &&
        !me.data.client &&
        !me.data.vendor &&
        !can('finance', 'view') &&
        !can('users', 'edit') && (
          <p className="text-small text-fg-secondary">{t('portal.notLinked')}</p>
        )}
    </div>
  );
}

// ---------------------------------------------------------------- client

interface Ticket {
  id: string;
  number: string;
  contract: string;
  period_from: string;
  period_to: string;
  status_label: string;
  value: string;
  can_sign: boolean;
}

function ClientPortal({ name }: { name: string }) {
  const { t } = useTranslation();
  const tickets = useQuery({
    queryKey: ['portal', 'tickets'],
    queryFn: () => api<Ticket[]>('/portal/client/tickets'),
  });
  const invoices = useQuery({
    queryKey: ['portal', 'invoices'],
    queryFn: () =>
      api<
        {
          id: string;
          number: string;
          invoice_date: string;
          due_date: string;
          total: string;
          outstanding: string;
          status: string;
          has_pack: boolean;
        }[]
      >('/portal/client/invoices'),
  });
  const act = usePortal();
  const [signing, setSigning] = useState<string | null>(null);
  const [signer, setSigner] = useState('');
  const [png, setPng] = useState<string | null>(null);
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('portal.client.tickets', { name })}</CardTitle>
          <CardDescription>{t('portal.client.ticketsHint')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FormError message={errText(tickets.error ?? act.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('portal.number')}</TH>
                <TH>{t('portal.period')}</TH>
                <TH className="text-right">{t('portal.value')}</TH>
                <TH>{t('portal.status')}</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {tickets.data?.map((x) => (
                <TR key={x.id}>
                  <TD>
                    {x.number}
                    <div className="text-small text-fg-secondary">{x.contract}</div>
                  </TD>
                  <TD>
                    {formatDate(x.period_from)} – {formatDate(x.period_to)}
                  </TD>
                  <TD className="text-right tabular-nums">{formatIDR(x.value)}</TD>
                  <TD>{x.status_label}</TD>
                  <TD>
                    {x.can_sign && (
                      <Button size="sm" variant="primary" onClick={() => setSigning(x.id)}>
                        {t('portal.client.sign')}
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {signing && (
            <div className="flex flex-col gap-2 rounded-md border border-border p-3">
              <Field label={t('portal.client.signer')}>
                <Input value={signer} onChange={(e) => setSigner(e.target.value)} />
              </Field>
              <SignaturePad onChange={setPng} />
              <div>
                <Button
                  variant="primary"
                  disabled={signer.trim().length < 3 || !png}
                  onClick={() =>
                    act.mutate(
                      {
                        path: `/portal/client/tickets/${signing}/sign`,
                        body: { signer_name: signer, signature: png },
                      },
                      { onSuccess: () => setSigning(null) },
                    )
                  }
                >
                  {t('portal.client.confirmSign')}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('portal.client.invoices')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <THead>
              <TR>
                <TH>{t('portal.number')}</TH>
                <TH>{t('portal.due')}</TH>
                <TH className="text-right">{t('portal.total')}</TH>
                <TH className="text-right">{t('portal.outstanding')}</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {invoices.data?.map((i) => (
                <TR key={i.id}>
                  <TD>{i.number}</TD>
                  <TD>{formatDate(i.due_date)}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(i.total)}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(i.outstanding)}</TD>
                  <TD>
                    {i.has_pack && (
                      <Button
                        size="sm"
                        onClick={() =>
                          void downloadFile(
                            `/portal/client/invoices/${i.id}/pack`,
                            `${i.number}.pdf`,
                          )
                        }
                      >
                        <Icon name="picture_as_pdf" /> {t('portal.client.pack')}
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {invoices.data?.length === 0 && (
            <p className="text-small text-fg-secondary">{t('portal.none')}</p>
          )}
        </CardContent>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- vendor

interface RfqRow {
  quote_id: string;
  rfq: string;
  due_date: string | null;
  open: boolean;
  status: string;
  total: string | null;
}

function VendorPortal({ name }: { name: string }) {
  const { t } = useTranslation();
  const rfqs = useQuery({
    queryKey: ['portal', 'rfqs'],
    queryFn: () => api<RfqRow[]>('/portal/vendor/rfqs'),
  });
  const inv = useQuery({
    queryKey: ['portal', 'vinv'],
    queryFn: () =>
      api<{
        submissions: {
          id: string;
          po_number: string;
          invoice_no: string;
          amount: string;
          status: string;
          reject_reason: string | null;
        }[];
        invoices: {
          number: string;
          invoice_no: string;
          due_date: string | null;
          payable: string;
          outstanding: string;
          status: string;
          paid_on: string | null;
        }[];
      }>('/portal/vendor/invoices'),
  });
  const act = usePortal();
  const [open, setOpen] = useState<string | null>(null);
  const [f, setF] = useState({
    po_number: '',
    invoice_no: '',
    invoice_date: today(),
    amount: '',
    tax_invoice_no: '',
  });
  const [file, setFile] = useState<File | null>(null);
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('portal.vendor.rfqs', { name })}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FormError message={errText(rfqs.error ?? act.error, t('auth.unexpected'))} />
          <Table>
            <TBody>
              {rfqs.data?.map((r) => (
                <TR key={r.quote_id}>
                  <TD>{r.rfq}</TD>
                  <TD>{r.due_date ? formatDate(r.due_date) : '-'}</TD>
                  <TD>
                    <StatusPill tone={r.status === 'quoted' ? 'success' : 'warning'}>
                      {t(`portal.vendor.quoteStatus.${r.status}`, r.status)}
                    </StatusPill>
                  </TD>
                  <TD className="text-right tabular-nums">{r.total ? formatIDR(r.total) : '-'}</TD>
                  <TD>
                    {r.open && (
                      <Button size="sm" onClick={() => setOpen(r.quote_id)}>
                        {t('portal.vendor.quote')}
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {rfqs.data?.length === 0 && (
            <p className="text-small text-fg-secondary">{t('portal.none')}</p>
          )}
          {open && <QuoteForm qid={open} onDone={() => setOpen(null)} />}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t('portal.vendor.upload')}</CardTitle>
          <CardDescription>{t('portal.vendor.uploadHint')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-2">
          <Field label={t('portal.vendor.po')} className="w-40">
            <Input
              value={f.po_number}
              onChange={(e) => setF({ ...f, po_number: e.target.value })}
            />
          </Field>
          <Field label={t('portal.vendor.invoiceNo')} className="w-44">
            <Input
              value={f.invoice_no}
              onChange={(e) => setF({ ...f, invoice_no: e.target.value })}
            />
          </Field>
          <Field label={t('portal.vendor.date')} className="w-40">
            <Input
              type="date"
              value={f.invoice_date}
              onChange={(e) => setF({ ...f, invoice_date: e.target.value })}
            />
          </Field>
          <Field label={t('portal.total')} className="w-40">
            <Input
              inputMode="numeric"
              value={f.amount}
              onChange={(e) => setF({ ...f, amount: e.target.value })}
            />
          </Field>
          <Field label={t('portal.vendor.taxInvoice')} className="w-44">
            <Input
              value={f.tax_invoice_no}
              onChange={(e) => setF({ ...f, tax_invoice_no: e.target.value })}
            />
          </Field>
          <Field label={t('portal.vendor.file')} className="w-64">
            <Input
              type="file"
              accept=".pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Field>
          <Button
            variant="primary"
            disabled={!f.po_number || !f.invoice_no || !moneyToApi(f.amount) || !file}
            onClick={() => {
              const form = new FormData();
              Object.entries({ ...f, amount: moneyToApi(f.amount) }).forEach(
                ([k, v]) => v && form.append(k, v),
              );
              form.append('file', file!);
              act.mutate({ path: '/portal/vendor/invoices', form });
            }}
          >
            {t('portal.vendor.send')}
          </Button>
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('portal.vendor.status')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Table>
            <TBody>
              {inv.data?.submissions.map((s) => (
                <TR key={s.id}>
                  <TD>
                    {s.invoice_no} · {s.po_number}
                  </TD>
                  <TD className="text-right tabular-nums">{formatIDR(s.amount)}</TD>
                  <TD>
                    {t(`portal.vendor.subStatus.${s.status}`)}
                    {s.reject_reason ? ` — ${s.reject_reason}` : ''}
                  </TD>
                </TR>
              ))}
              {inv.data?.invoices.map((v) => (
                <TR key={v.number}>
                  <TD>
                    {v.invoice_no} · {v.number}
                  </TD>
                  <TD className="text-right tabular-nums">{formatIDR(v.outstanding)}</TD>
                  <TD>
                    {v.status}
                    {v.paid_on
                      ? ` · ${t('portal.vendor.paidOn', { date: formatDate(v.paid_on) })}`
                      : ''}
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

function QuoteForm({ qid, onDone }: { qid: string; onDone: () => void }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['portal', 'rfq', qid],
    queryFn: () =>
      api<{
        rfq: string;
        lines: {
          seq: number;
          description: string;
          qty: string;
          uom: string;
          unit_price: string | null;
        }[];
      }>(`/portal/vendor/rfqs/${qid}`),
  });
  const act = usePortal();
  const [prices, setPrices] = useState<Record<number, string>>({});
  const [days, setDays] = useState('7');
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-3">
      <h3 className="font-heading text-body font-semibold">{q.data?.rfq}</h3>
      {q.data?.lines.map((l) => (
        <div key={l.seq} className="flex flex-wrap items-end gap-2">
          <span className="w-72 text-small">
            {l.description} ({l.qty} {l.uom})
          </span>
          <Field label={t('portal.vendor.unitPrice')} className="w-44">
            <Input
              inputMode="numeric"
              value={prices[l.seq] ?? l.unit_price ?? ''}
              onChange={(e) => setPrices({ ...prices, [l.seq]: e.target.value })}
            />
          </Field>
        </div>
      ))}
      <Field label={t('portal.vendor.deliveryDays')} className="w-32">
        <Input inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} />
      </Field>
      <FormError message={errText(act.error, t('auth.unexpected'))} />
      <div className="flex gap-2">
        <Button
          variant="primary"
          onClick={() =>
            act.mutate(
              {
                path: `/portal/vendor/rfqs/${qid}`,
                method: 'PUT',
                body: {
                  unit_prices: Object.fromEntries(
                    (q.data?.lines ?? []).map((l) => [
                      l.seq,
                      moneyToApi(prices[l.seq] ?? l.unit_price ?? ''),
                    ]),
                  ),
                  delivery_days: Number(days) || 0,
                },
              },
              { onSuccess: onDone },
            )
          }
        >
          {t('portal.vendor.submitQuote')}
        </Button>
        <Button
          variant="ghost"
          onClick={() =>
            act.mutate(
              { path: `/portal/vendor/rfqs/${qid}`, method: 'PUT', body: { declined: true } },
              { onSuccess: onDone },
            )
          }
        >
          {t('portal.vendor.decline')}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- internal side

function SubmissionsQueue() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const q = useQuery({
    queryKey: ['portal', 'subs'],
    queryFn: () =>
      api<
        {
          id: string;
          vendor_code: string;
          po_number: string;
          invoice_no: string;
          amount: string;
          attachment_id: string;
        }[]
      >('/portal/submissions'),
  });
  const act = usePortal();
  const [vi, setVi] = useState<Record<string, string>>({});
  if (!q.data?.length) return null;
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <CardTitle>{t('portal.ap.title')}</CardTitle>
        <CardDescription>{t('portal.ap.hint')}</CardDescription>
      </CardHeader>
      <CardContent>
        <FormError message={errText(act.error, t('auth.unexpected'))} />
        <Table>
          <TBody>
            {q.data.map((s) => (
              <TR key={s.id}>
                <TD>
                  {s.vendor_code} · {s.invoice_no} · {s.po_number}
                </TD>
                <TD className="text-right tabular-nums">{formatIDR(s.amount)}</TD>
                <TD>
                  <Button
                    size="sm"
                    onClick={() =>
                      void downloadFile(
                        `/attachments/${s.attachment_id}/content?download=true`,
                        `${s.invoice_no}.pdf`,
                      )
                    }
                  >
                    PDF
                  </Button>
                </TD>
                {can('finance', 'create') && (
                  <TD className="flex flex-wrap gap-1">
                    <Input
                      aria-label={t('portal.ap.viNumber')}
                      placeholder={t('portal.ap.viNumber')}
                      value={vi[s.id] ?? ''}
                      onChange={(e) => setVi({ ...vi, [s.id]: e.target.value })}
                      className="w-36"
                    />
                    <Button
                      size="sm"
                      onClick={() =>
                        act.mutate({
                          path: `/portal/submissions/${s.id}/decide`,
                          body: { vendor_invoice_number: vi[s.id] },
                        })
                      }
                    >
                      {t('portal.ap.register')}
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() =>
                        act.mutate({
                          path: `/portal/submissions/${s.id}/decide`,
                          body: { reject_reason: vi[s.id] || t('portal.ap.defaultReject') },
                        })
                      }
                    >
                      {t('portal.ap.reject')}
                    </Button>
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function LinkAccounts() {
  const { t } = useTranslation();
  const act = usePortal();
  const [f, setF] = useState({ user_id: '', client_code: '', vendor_code: '' });
  const users = useQuery({
    queryKey: ['portal', 'users'],
    queryFn: () =>
      api<{ items: { id: string; email: string; full_name: string; roles: string[] }[] }>(
        '/users?page_size=200',
      ),
  });
  const external =
    users.data?.items.filter((u) => u.roles.some((r) => r === 'client_rep' || r === 'vendor')) ??
    [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('portal.link.title')}</CardTitle>
        <CardDescription>{t('portal.link.hint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-end gap-2">
        <Field label={t('portal.link.user')} className="w-72">
          <Select value={f.user_id} onChange={(e) => setF({ ...f, user_id: e.target.value })}>
            <option value="">-</option>
            {external.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name} ({u.email})
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('portal.link.client')} className="w-36">
          <Input
            value={f.client_code}
            onChange={(e) => setF({ ...f, client_code: e.target.value })}
          />
        </Field>
        <Field label={t('portal.link.vendor')} className="w-36">
          <Input
            value={f.vendor_code}
            onChange={(e) => setF({ ...f, vendor_code: e.target.value })}
          />
        </Field>
        <Button
          disabled={!f.user_id}
          onClick={() =>
            act.mutate({
              path: `/portal/links/${f.user_id}`,
              method: 'PUT',
              body: { client_code: f.client_code || null, vendor_code: f.vendor_code || null },
            })
          }
        >
          {t('portal.link.save')}
        </Button>
        <FormError message={errText(act.error, t('auth.unexpected'))} />
        {act.isSuccess && <p className="text-small">{t('portal.link.saved')}</p>}
      </CardContent>
    </Card>
  );
}
