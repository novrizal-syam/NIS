import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { Tabs } from '@/components/ui/tabs';
import { FormError } from '@/features/auth/AuthLayout';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDateTime, formatIDR } from '@/lib/format';
import { cn } from '@/lib/utils';
import {
  inboxQueryString,
  useBulkApprove,
  useDecision,
  useDocTypes,
  useInbox,
  type BulkResult,
  type InboxItem,
} from './api';
import { DelegationsPanel } from './DelegationsPanel';
import { ReasonDialog } from './RejectDialog';

function Money({ value }: { value: string | null }) {
  return <>{value === null ? '–' : formatIDR(value)}</>;
}

export function InboxPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'inbox' | 'delegations'>('inbox');
  const [docType, setDocType] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rejecting, setRejecting] = useState<InboxItem | null>(null);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  const docTypes = useDocTypes();
  const inbox = useInbox({ doc_type: docType || undefined, q: q || undefined, page });
  const decision = useDecision();
  const bulk = useBulkApprove();

  const items = inbox.data?.items ?? [];
  const counts = inbox.data?.counts ?? {};
  const totalPending = Object.values(counts).reduce((a, b) => a + b, 0);
  const label = (code: string) => docTypes.data?.find((d) => d.code === code)?.label ?? code;

  const filterBy = (code: string) => {
    setDocType(code);
    setPage(1);
    setSelected(new Set());
  };
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allOnPage = items.length > 0 && items.every((i) => selected.has(i.request_id));

  const approveOne = async (item: InboxItem) => {
    setNotice(null);
    try {
      await decision.mutateAsync({ id: item.request_id, action: 'approve' });
      setNotice({ tone: 'ok', text: t('workflow.approvedOne', { number: item.doc_number }) });
    } catch (err) {
      setNotice({
        tone: 'error',
        text: err instanceof ApiError ? err.message : t('auth.unexpected'),
      });
    }
  };

  const approveSelected = async () => {
    setNotice(null);
    const results: BulkResult[] = await bulk.mutateAsync({
      doc_type: docType,
      request_ids: [...selected],
    });
    const ok = results.filter((r) => r.ok).length;
    const failed = results.filter((r) => !r.ok);
    setSelected(new Set());
    setNotice(
      failed.length
        ? {
            tone: 'error',
            text: t('workflow.bulkPartial', {
              ok,
              failed: failed.length,
              reason: failed[0]?.message ?? '',
            }),
          }
        : { tone: 'ok', text: t('workflow.bulkDone', { count: ok }) },
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label={t('workflow.tabsLabel')}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'inbox', label: t('workflow.tabInbox'), badge: totalPending },
          { value: 'delegations', label: t('workflow.tabDelegations') },
        ]}
      />

      {tab === 'delegations' ? (
        <DelegationsPanel />
      ) : (
        <>
          {/* Summary first: counts per document type, click to filter */}
          <div role="group" className="flex flex-wrap gap-2" aria-label={t('workflow.summary')}>
            <button
              type="button"
              aria-pressed={docType === ''}
              onClick={() => filterBy('')}
              className={cn(
                'rounded-card border px-3 py-2 text-left',
                docType === ''
                  ? 'border-border-strong bg-surface-raised'
                  : 'border-border bg-surface-raised',
              )}
            >
              <span className="block text-caption uppercase text-fg-muted">
                {t('workflow.all')}
              </span>
              <span className="font-heading text-section-title tabular-nums text-fg">
                {totalPending}
              </span>
            </button>
            {Object.entries(counts).map(([code, count]) => (
              <button
                key={code}
                type="button"
                aria-pressed={docType === code}
                onClick={() => filterBy(code)}
                className={cn(
                  'rounded-card border px-3 py-2 text-left',
                  docType === code
                    ? 'border-border-strong bg-surface-raised'
                    : 'border-border bg-surface-raised',
                )}
              >
                <span className="block text-caption uppercase text-fg-muted">{label(code)}</span>
                <span className="font-heading text-section-title tabular-nums text-fg">
                  {count}
                </span>
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('workflow.search')} className="min-w-0 flex-1">
              <Input
                type="search"
                value={q}
                placeholder={t('workflow.searchPlaceholder')}
                onChange={(e) => {
                  setQ(e.target.value);
                  setPage(1);
                }}
              />
            </Field>
            <Field label={t('workflow.docType')} className="w-full sm:w-64">
              <Select value={docType} onChange={(e) => filterBy(e.target.value)}>
                <option value="">{t('workflow.allTypes')}</option>
                {docTypes.data?.map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Button
              variant="secondary"
              onClick={() =>
                void downloadFile(
                  `/workflow/inbox/export?${inboxQueryString({ doc_type: docType || undefined, q: q || undefined })}`,
                  'persetujuan-saya.xlsx',
                )
              }
            >
              <Icon name="download" /> {t('list.export')}
            </Button>
            <Button
              variant="primary"
              disabled={!docType || selected.size === 0 || bulk.isPending}
              title={!docType ? t('workflow.bulkNeedsType') : undefined}
              onClick={() => void approveSelected()}
            >
              <Icon name="done_all" /> {t('workflow.approveSelected', { count: selected.size })}
            </Button>
          </div>
          {!docType && (
            <p className="text-small text-fg-secondary">{t('workflow.bulkNeedsType')}</p>
          )}

          {notice &&
            (notice.tone === 'error' ? (
              <FormError message={notice.text} />
            ) : (
              <p
                role="status"
                className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
              >
                {notice.text}
              </p>
            ))}

          <Card>
            <Table>
              <caption className="sr-only">{t('workflow.tableCaption')}</caption>
              <THead>
                <TR>
                  <TH className="w-10">
                    <input
                      type="checkbox"
                      aria-label={t('workflow.selectAll')}
                      disabled={!docType || items.length === 0}
                      checked={allOnPage}
                      onChange={() =>
                        setSelected(allOnPage ? new Set() : new Set(items.map((i) => i.request_id)))
                      }
                      className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
                    />
                  </TH>
                  <TH>{t('workflow.col.number')}</TH>
                  <TH>{t('workflow.col.title')}</TH>
                  <TH numeric>{t('workflow.col.amount')}</TH>
                  <TH>{t('workflow.col.requester')}</TH>
                  <TH>{t('workflow.col.submitted')}</TH>
                  <TH>{t('workflow.col.due')}</TH>
                  <TH className="text-right">{t('workflow.col.actions')}</TH>
                </TR>
              </THead>
              <TBody>
                {items.length === 0 && (
                  <TR>
                    <TD colSpan={8} className="py-8 text-center text-fg-secondary">
                      {inbox.isLoading ? t('common.loading') : t('workflow.empty')}
                    </TD>
                  </TR>
                )}
                {items.map((item) => (
                  <TR key={item.request_id}>
                    <TD>
                      <input
                        type="checkbox"
                        aria-label={t('workflow.selectOne', { number: item.doc_number })}
                        disabled={!docType}
                        checked={selected.has(item.request_id)}
                        onChange={() => toggle(item.request_id)}
                        className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
                      />
                    </TD>
                    <TD className="whitespace-nowrap">
                      <Link
                        to={`/persetujuan/${item.request_id}`}
                        className="font-semibold text-fg underline-offset-2 hover:underline"
                      >
                        {item.doc_number}
                      </Link>
                      <span className="block text-caption text-fg-muted">
                        {item.doc_type_label}
                      </span>
                    </TD>
                    <TD className="min-w-48">
                      {item.title}
                      <span className="block text-caption text-fg-muted">{item.step_label}</span>
                    </TD>
                    <TD numeric className="whitespace-nowrap">
                      <Money value={item.amount} />
                    </TD>
                    <TD className="whitespace-nowrap">{item.requester_name}</TD>
                    <TD className="whitespace-nowrap">{formatDateTime(item.submitted_at)}</TD>
                    <TD className="whitespace-nowrap">
                      {!item.due_at ? (
                        '–'
                      ) : item.overdue || item.escalated ? (
                        <StatusPill tone="danger">
                          {item.escalated ? t('workflow.escalated') : formatDateTime(item.due_at)}
                        </StatusPill>
                      ) : (
                        formatDateTime(item.due_at)
                      )}
                    </TD>
                    <TD className="whitespace-nowrap text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={decision.isPending}
                          onClick={() => void approveOne(item)}
                        >
                          {t('workflow.approve')}
                        </Button>
                        <Button size="sm" variant="destructive" onClick={() => setRejecting(item)}>
                          {t('workflow.reject')}
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination
              page={page}
              pageSize={25}
              total={inbox.data?.total ?? 0}
              onPage={(p) => {
                setPage(p);
                setSelected(new Set());
              }}
            />
          </Card>
        </>
      )}

      <ReasonDialog
        open={rejecting !== null}
        title={t('workflow.rejectTitle', { number: rejecting?.doc_number ?? '' })}
        description={t('workflow.rejectHelp')}
        confirmLabel={t('workflow.reject')}
        busy={decision.isPending}
        error={decision.error instanceof ApiError ? decision.error.message : null}
        onClose={() => {
          setRejecting(null);
          decision.reset();
        }}
        onConfirm={(reason) => {
          if (!rejecting) return;
          const number = rejecting.doc_number;
          decision.mutate(
            { id: rejecting.request_id, action: 'reject', comment: reason },
            {
              onSuccess: () => {
                setRejecting(null);
                setNotice({ tone: 'ok', text: t('workflow.rejectedOne', { number }) });
              },
            },
          );
        }}
      />
    </div>
  );
}
