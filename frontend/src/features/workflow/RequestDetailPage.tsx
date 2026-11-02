import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { Textarea } from '@/components/ui/input';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError } from '@/lib/api';
import { formatDateTime, formatIDR } from '@/lib/format';
import { useDecision, useRequest } from './api';
import { ReasonDialog } from './RejectDialog';
import { RequestStatusPill, StepStatusPill } from './StatusPills';

export function RequestDetailPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const request = useRequest(id);
  const decision = useDecision();
  const [comment, setComment] = useState('');
  const [dialog, setDialog] = useState<'reject' | 'cancel' | null>(null);

  if (request.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (request.error || !request.data) {
    return (
      <FormError
        message={request.error instanceof ApiError ? request.error.message : t('auth.unexpected')}
      />
    );
  }
  const r = request.data;
  const error = decision.error instanceof ApiError ? decision.error.message : null;

  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/persetujuan"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('workflow.backToInbox')}
      </Link>

      <Card>
        <CardHeader>
          <p className="eyebrow">
            {r.doc_type_label} · {r.doc_number}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{r.title}</CardTitle>
            <RequestStatusPill status={r.status} />
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-fg-muted">{t('workflow.col.amount')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {r.amount === null ? '–' : formatIDR(r.amount)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('workflow.col.requester')}</dt>
              <dd className="font-semibold text-fg">{r.requester_name}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('workflow.col.submitted')}</dt>
              <dd className="text-fg">{formatDateTime(r.submitted_at)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('workflow.rule')}</dt>
              <dd className="text-fg">{r.rule_name}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {r.changes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('workflow.changes')}</CardTitle>
            {r.change_reason && (
              <p className="text-small text-fg-secondary">
                {t('workflow.reason')}: {r.change_reason}
              </p>
            )}
          </CardHeader>
          <Table>
            <caption className="sr-only">{t('workflow.changes')}</caption>
            <THead>
              <TR>
                <TH>{t('workflow.changeField')}</TH>
                <TH>{t('workflow.changeBefore')}</TH>
                <TH>{t('workflow.changeAfter')}</TH>
              </TR>
            </THead>
            <TBody>
              {r.changes.map((c) => (
                <TR key={c.label}>
                  <TD className="font-semibold text-fg">{c.label}</TD>
                  <TD className="text-fg-secondary">{c.before ?? '–'}</TD>
                  <TD className="font-semibold text-fg">{c.after}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t('workflow.steps')}</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="flex flex-col gap-3">
            {r.steps.map((s, i) => (
              <li key={`${s.seq}-${s.approver_role}`} className="flex gap-3">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-surface-muted text-small font-bold text-fg">
                  {s.seq}
                </span>
                <div className="min-w-0 flex-1 border-b border-border pb-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-fg">
                      {s.label ? `${s.label} · ` : ''}
                      {s.approver_role_name}
                    </span>
                    <StepStatusPill status={s.status} />
                    {i > 0 && r.steps[i - 1]!.seq === s.seq && (
                      <span className="text-caption text-fg-muted">{t('workflow.parallel')}</span>
                    )}
                  </div>
                  {s.acted_by_name && (
                    <p className="mt-1 text-small text-fg-secondary">
                      {s.acted_by_name}
                      {s.on_behalf_of_name &&
                        ` (${t('workflow.onBehalfOf', { name: s.on_behalf_of_name })})`}
                      {s.acted_at && ` · ${formatDateTime(s.acted_at)}`}
                    </p>
                  )}
                  {s.comment && <p className="mt-1 text-small text-fg-body">“{s.comment}”</p>}
                  {s.status === 'pending' && s.due_at && (
                    <p className="mt-1 text-caption text-fg-muted">
                      {t('workflow.dueAt', { date: formatDateTime(s.due_at) })}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t('master.tabFiles')}</CardTitle>
          </CardHeader>
          <CardContent>
            <AttachmentsPanel
              entityType="approval_request"
              entityId={r.id}
              canWrite={r.can_cancel || r.can_act}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t('master.tabHistory')}</CardTitle>
          </CardHeader>
          <CardContent>
            <HistoryPanel entityType="approval_request" entityId={r.id} />
          </CardContent>
        </Card>
      </div>

      {(r.can_act || r.can_cancel) && (
        <Card>
          <CardContent className="flex flex-col gap-3 pt-4">
            <FormError message={dialog ? null : error} />
            {r.can_act && (
              <>
                <label htmlFor="approve-comment" className="text-small font-semibold text-fg">
                  {t('workflow.commentOptional')}
                </label>
                <Textarea
                  id="approve-comment"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={2}
                />
              </>
            )}
            <div className="flex flex-wrap gap-2">
              {r.can_act && (
                <>
                  <Button
                    variant="primary"
                    disabled={decision.isPending}
                    onClick={() => decision.mutate({ id: r.id, action: 'approve', comment })}
                  >
                    <Icon name="check" /> {t('workflow.approve')}
                  </Button>
                  <Button variant="destructive" onClick={() => setDialog('reject')}>
                    <Icon name="block" /> {t('workflow.reject')}
                  </Button>
                </>
              )}
              {r.can_cancel && (
                <Button variant="secondary" onClick={() => setDialog('cancel')}>
                  {t('workflow.withdraw')}
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      <ReasonDialog
        open={dialog !== null}
        required={dialog === 'reject'}
        title={
          dialog === 'reject'
            ? t('workflow.rejectTitle', { number: r.doc_number })
            : t('workflow.withdrawTitle', { number: r.doc_number })
        }
        description={dialog === 'reject' ? t('workflow.rejectHelp') : t('workflow.withdrawHelp')}
        confirmLabel={dialog === 'reject' ? t('workflow.reject') : t('workflow.withdraw')}
        busy={decision.isPending}
        error={dialog ? error : null}
        onClose={() => {
          setDialog(null);
          decision.reset();
        }}
        onConfirm={(reason) =>
          dialog &&
          decision.mutate(
            { id: r.id, action: dialog, comment: reason },
            { onSuccess: () => setDialog(null) },
          )
        }
      />
    </div>
  );
}
