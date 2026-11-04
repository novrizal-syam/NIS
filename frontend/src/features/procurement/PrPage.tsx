import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Textarea } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError } from '@/lib/api';
import { formatDate, formatDateTime, formatIDR } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useCancelPr, usePr, useSubmitPr, type PrDetail } from './api';
import { PrForm } from './PrForm';
import { PrStatusPill } from './PrStatusPill';
import { CreateRfqDialog } from './RfqPages';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

export function PrNewPage() {
  return <PrForm pr={null} />;
}

export function PrPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const pr = usePr(id);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');
  const [editing, setEditing] = useState(false);
  if (pr.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (pr.error || !pr.data) return <FormError message={errText(pr.error, t('auth.unexpected'))} />;
  const d = pr.data;

  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/pengadaan/pr"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('pr.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {d.project_number} · {d.wbs_code}/{d.cost_element_code}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{d.purpose || d.project_name}</CardTitle>
            <PrStatusPill status={d.status} />
          </div>
          <CardDescription>
            {t('pr.requester')}: {d.requester_name} · {t('pr.needDate')}: {formatDate(d.need_date)}{' '}
            · {d.delivery_location}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-fg-muted">{t('pr.total')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {formatIDR(d.total)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('project.available')}</dt>
              <dd
                className={cn(
                  'tabular-nums',
                  Number(d.budget.available) < Number(d.total) && d.status !== 'approved'
                    ? 'font-semibold text-danger'
                    : 'text-fg-body',
                )}
              >
                {formatIDR(d.budget.available)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('project.budget')}</dt>
              <dd className="tabular-nums text-fg-body">
                {formatIDR(d.budget.budget)} · {d.budget.used_pct.replace('.', ',')}%
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('pr.heldByPr')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(d.budget.held_by_pr)}</dd>
            </div>
          </dl>
          {d.status === 'blocked' && <BlockedBox d={d} />}
          {d.reject_reason && d.status === 'draft' && (
            <p className="rounded-control bg-warning-tint px-3 py-2 text-small text-warning">
              {t('pr.rejected')}: {d.reject_reason}
            </p>
          )}
          {d.cancel_reason && (
            <p className="text-small text-fg-secondary">
              {t('pr.cancelReason')}: {d.cancel_reason}
            </p>
          )}
          {(d.rfq || d.po) && (
            <p className="flex flex-wrap gap-3 text-small">
              {d.rfq && (
                <Link
                  to={`/pengadaan/rfq/${d.rfq.id}`}
                  className="font-semibold text-fg-accent underline"
                >
                  {d.rfq.number}
                </Link>
              )}
              {d.po && (
                <Link
                  to={`/pengadaan/po/${d.po.id}`}
                  className="font-semibold text-fg-accent underline"
                >
                  {d.po.number}
                </Link>
              )}
            </p>
          )}
          {d.can_rfq && <RfqButton prId={d.id} />}
          {d.linked_bcr && (
            <p className="text-small text-fg-secondary">
              {t('pr.linkedBcr')}: {d.linked_bcr.number} ({t(`bcr.status.${d.linked_bcr.status}`)})
            </p>
          )}
          <Actions d={d} onEdit={() => setEditing(true)} />
        </CardContent>
      </Card>
      {editing && d.can_edit && <PrForm pr={d} onSaved={() => setEditing(false)} />}
      <Tabs
        label={d.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'files', label: t('crm.tabFiles') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && (
        <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
          <Card>
            <CardContent className="overflow-x-auto pt-4">
              <Table>
                <THead>
                  <TR>
                    <TH>{t('quotation.description')}</TH>
                    <TH className="text-right">{t('quotation.qty')}</TH>
                    <TH>{t('quotation.unit')}</TH>
                    <TH className="text-right">{t('pr.estPrice')}</TH>
                    <TH className="text-right">{t('quotation.amount')}</TH>
                  </TR>
                </THead>
                <TBody>
                  {d.lines.map((l, i) => (
                    <TR key={i}>
                      <TD className="min-w-48">
                        {l.description}
                        {l.item_code && (
                          <span className="block text-caption text-fg-muted">{l.item_code}</span>
                        )}
                      </TD>
                      <TD className="text-right tabular-nums">{l.qty.replace('.', ',')}</TD>
                      <TD>{l.uom}</TD>
                      <TD className="whitespace-nowrap text-right tabular-nums">
                        {formatIDR(l.est_price)}
                      </TD>
                      <TD className="whitespace-nowrap text-right tabular-nums">
                        {l.amount ? formatIDR(l.amount) : '–'}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t('pr.approvalHistory')}</CardTitle>
            </CardHeader>
            <CardContent>
              {d.approvals.length === 0 ? (
                <p className="text-small text-fg-secondary">{t('pr.noApprovals')}</p>
              ) : (
                <ol className="flex flex-col gap-2">
                  {d.approvals.map((a, i) => (
                    <li key={i} className="flex flex-col text-small">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-fg">
                          {t(`project.roles.${a.approver_role}`, { defaultValue: a.approver_role })}
                        </span>
                        <StatusPill
                          tone={
                            a.status === 'approved'
                              ? 'success'
                              : a.status === 'rejected'
                                ? 'danger'
                                : 'warning'
                          }
                        >
                          {t(`workflow.stepStatus.${a.status}`, { defaultValue: a.status })}
                        </StatusPill>
                      </span>
                      {a.acted_by && (
                        <span className="text-caption text-fg-muted">
                          {a.acted_by} · {a.acted_at ? formatDateTime(a.acted_at) : ''}
                        </span>
                      )}
                      {a.comment && <span className="text-fg-body">{a.comment}</span>}
                    </li>
                  ))}
                </ol>
              )}
              {d.request_id && (
                <Link
                  to={`/persetujuan/${d.request_id}`}
                  className="mt-3 inline-block text-small font-semibold text-fg-accent underline"
                >
                  {t('crm.openApproval')}
                </Link>
              )}
            </CardContent>
          </Card>
        </div>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="purchase_requisition" entityId={d.id} canWrite={d.can_edit} />
      )}
      {tab === 'history' && <HistoryPanel entityType="purchase_requisition" entityId={d.id} />}
    </div>
  );
}

function BlockedBox({ d }: { d: PrDetail }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const params = new URLSearchParams({
    tab: 'bcr',
    wbs: d.wbs_code,
    element: d.cost_element_code,
    amount: d.bcr_suggestion ?? '',
    ref_type: 'purchase_requisition',
    ref_id: d.id,
    ref_label: d.number,
  });
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-control border border-danger bg-danger-tint px-3 py-2 text-small text-danger"
    >
      <span className="font-semibold">{t('pr.blockedTitle')}</span>
      <span>{d.block_message}</span>
      {d.bcr_suggestion &&
        (can('budget', 'submit') ? (
          <Button
            variant="secondary"
            size="sm"
            className="self-start"
            onClick={() => navigate(`/proyek/${d.project_id}?${params.toString()}`)}
          >
            <Icon name="published_with_changes" />{' '}
            {t('pr.requestBcr', { amount: formatIDR(d.bcr_suggestion) })}
          </Button>
        ) : (
          <span className="text-fg-body">
            {t('pr.askPlanner', { amount: formatIDR(d.bcr_suggestion), number: d.number })}
          </span>
        ))}
    </div>
  );
}

function Actions({ d, onEdit }: { d: PrDetail; onEdit: () => void }) {
  const { t } = useTranslation();
  const submit = useSubmitPr(d.id);
  const cancel = useCancelPr(d.id);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState('');
  if (!d.can_edit && !d.can_submit && !d.can_cancel) return null;
  return (
    <div className="flex flex-col gap-2">
      <FormError message={errText(submit.error ?? cancel.error, t('auth.unexpected'))} />
      <div className="flex flex-wrap gap-2">
        {d.can_submit && (
          <Button variant="primary" disabled={submit.isPending} onClick={() => submit.mutate()}>
            <Icon name="send" /> {t('pr.submit')}
          </Button>
        )}
        {d.can_edit && (
          <Button variant="secondary" onClick={onEdit}>
            <Icon name="edit" /> {t('pr.edit')}
          </Button>
        )}
        {d.can_cancel && (
          <Button variant="destructive" onClick={() => setCancelling(true)}>
            {t('pr.cancel')}
          </Button>
        )}
      </div>
      {cancelling && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('pr.cancelReason')} required className="min-w-0 flex-1">
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Button
            variant="destructive"
            disabled={reason.trim().length < 5 || cancel.isPending}
            onClick={() => cancel.mutate(reason)}
          >
            {t('pr.confirmCancel')}
          </Button>
        </div>
      )}
    </div>
  );
}

function RfqButton({ prId }: { prId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="primary" className="self-start" onClick={() => setOpen(true)}>
        <Icon name="compare_arrows" /> {t('rfq.create')}
      </Button>
      {open && <CreateRfqDialog prId={prId} onClose={() => setOpen(false)} />}
    </>
  );
}
