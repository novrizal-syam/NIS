import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Icon } from '@/components/ui/icon';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError } from '@/lib/api';
import { formatDate, formatIDR, formatNumber } from '@/lib/format';
import {
  BCR_REASONS,
  BCR_SOURCES,
  useBcrs,
  useCreateBcr,
  type BcrReason,
  type BcrRow,
  type BcrSource,
  type ProjectDetail,
} from './api';

const TONE: Record<BcrRow['status'], StatusTone> = {
  submitted: 'warning',
  approved: 'success',
  rejected: 'danger',
  cancelled: 'neutral',
};
const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

export function BcrTab({ p }: { p: ProjectDetail }) {
  const { t } = useTranslation();
  const list = useBcrs(p.id, true);
  const create = useCreateBcr(p.id);
  const canCreate = p.can_bcr;
  const [files, setFiles] = useState<BcrRow | null>(null);
  const elements = p.cost_elements.filter((e) => e.code !== 'CONTINGENCY');
  // Prefill from a blocked PR ("Ajukan BCR"): ?wbs=&element=&amount=&ref_type=&ref_id=&ref_label=
  const [search] = useSearchParams();
  const prefillAmount = search.get('amount');
  const [v, setV] = useState({
    source: (prefillAmount ? 'budget_increase' : 'contingency_release') as BcrSource,
    wbs: search.get('wbs') ?? p.wbs[0]?.code ?? 'EXEC',
    element: search.get('element') ?? elements[0]?.code ?? '',
    amount: prefillAmount ? formatNumber(Number(prefillAmount)) : '',
    fromWbs: p.wbs[0]?.code ?? 'EXEC',
    fromElement: '',
    reason: 'scope_change' as BcrReason,
    justification: '',
    revenue: '',
    refType: search.get('ref_type') ?? '',
    refId: search.get('ref_id') ?? '',
  });
  const refLabel = search.get('ref_label');
  const set = (patch: Partial<typeof v>) => setV({ ...v, ...patch });
  const contingency = p.cells
    .filter((c) => c.cost_element_code === 'CONTINGENCY')
    .reduce((a, c) => a + Number(c.amount), 0);

  return (
    <div className="flex flex-col gap-4">
      {canCreate && (
        <Card>
          <CardHeader>
            <CardTitle>{t('bcr.new')}</CardTitle>
            <CardDescription>
              {t('bcr.help', { contingency: formatIDR(contingency) })}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <FormError message={errText(create.error, t('auth.unexpected'))} />
            {create.data && (
              <p role="status" className="text-small font-medium text-success">
                {t('bcr.submitted', {
                  number: create.data.number,
                  role: t(`project.roles.${create.data.approver ?? 'director'}`),
                })}
              </p>
            )}
            {refLabel && (
              <p className="rounded-control bg-info-tint px-3 py-2 text-small text-info">
                {t('bcr.forDocument', { number: refLabel })}
              </p>
            )}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label={t('bcr.source')}>
                <Select
                  value={v.source}
                  onChange={(e) => set({ source: e.target.value as BcrSource })}
                >
                  {BCR_SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {t(`bcr.sources.${s}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('bcr.targetWbs')}>
                <Select value={v.wbs} onChange={(e) => set({ wbs: e.target.value })}>
                  {p.wbs.map((w) => (
                    <option key={w.id} value={w.code}>
                      {w.code} · {w.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('bcr.targetElement')}>
                <Select value={v.element} onChange={(e) => set({ element: e.target.value })}>
                  {elements.map((e) => (
                    <option key={e.code} value={e.code}>
                      {e.code} · {e.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('bcr.amount')} hint="Rp" required>
                <Input
                  inputMode="numeric"
                  value={v.amount}
                  onChange={(e) => set({ amount: e.target.value })}
                />
              </Field>
              {v.source === 'transfer' && (
                <>
                  <Field label={t('bcr.fromWbs')}>
                    <Select value={v.fromWbs} onChange={(e) => set({ fromWbs: e.target.value })}>
                      {p.wbs.map((w) => (
                        <option key={w.id} value={w.code}>
                          {w.code}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label={t('bcr.fromElement')} required>
                    <Select
                      value={v.fromElement}
                      onChange={(e) => set({ fromElement: e.target.value })}
                    >
                      <option value="">–</option>
                      {elements.map((e) => (
                        <option key={e.code} value={e.code}>
                          {e.code} · {e.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </>
              )}
              <Field label={t('bcr.reason')}>
                <Select
                  value={v.reason}
                  onChange={(e) => set({ reason: e.target.value as BcrReason })}
                >
                  {BCR_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {t(`bcr.reasons.${r}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              {v.source === 'budget_increase' && (
                <Field label={t('bcr.revenueChange')} hint={t('bcr.revenueHint')}>
                  <Input
                    inputMode="numeric"
                    value={v.revenue}
                    onChange={(e) => set({ revenue: e.target.value })}
                  />
                </Field>
              )}
              <Field label={t('bcr.refType')} hint={t('bcr.refHint')}>
                <Input value={v.refType} onChange={(e) => set({ refType: e.target.value })} />
              </Field>
              <Field label={t('bcr.refId')}>
                <Input value={v.refId} onChange={(e) => set({ refId: e.target.value })} />
              </Field>
            </div>
            <Field label={t('bcr.justification')} required>
              <Textarea
                rows={3}
                value={v.justification}
                onChange={(e) => set({ justification: e.target.value })}
              />
            </Field>
            <Button
              variant="primary"
              className="self-start"
              disabled={
                create.isPending ||
                !moneyToApi(v.amount) ||
                v.justification.trim().length < 10 ||
                (v.source === 'transfer' && !v.fromElement)
              }
              onClick={() =>
                create.mutate(
                  {
                    source: v.source,
                    wbs_code: v.wbs,
                    cost_element_code: v.element,
                    amount: moneyToApi(v.amount),
                    reason: v.reason,
                    justification: v.justification,
                    ...(v.source === 'transfer'
                      ? { from_wbs_code: v.fromWbs, from_cost_element_code: v.fromElement }
                      : {}),
                    ...(v.source === 'budget_increase' && moneyToApi(v.revenue)
                      ? { revenue_change: moneyToApi(v.revenue) }
                      : {}),
                    ...(v.refType && v.refId
                      ? { ref_doc_type: v.refType, ref_doc_id: v.refId }
                      : {}),
                  },
                  { onSuccess: () => set({ amount: '', justification: '', revenue: '' }) },
                )
              }
            >
              {t('bcr.submit')}
            </Button>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle>{t('bcr.list')}</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {list.data?.length === 0 ? (
            <p className="text-small text-fg-secondary">{t('bcr.empty')}</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>{t('crm.number')}</TH>
                  <TH>{t('bcr.source')}</TH>
                  <TH>{t('bcr.line')}</TH>
                  <TH className="text-right">{t('bcr.amount')}</TH>
                  <TH>{t('bcr.reason')}</TH>
                  <TH>{t('master.status')}</TH>
                  <TH>{t('bcr.version')}</TH>
                  <TH>{t('tender.files')}</TH>
                </TR>
              </THead>
              <TBody>
                {list.data?.map((b) => (
                  <TR key={b.id}>
                    <TD className="whitespace-nowrap">
                      {b.request_id ? (
                        <Link
                          to={`/persetujuan/${b.request_id}`}
                          className="font-semibold text-fg-accent underline"
                        >
                          {b.number}
                        </Link>
                      ) : (
                        b.number
                      )}
                      <span className="block text-caption text-fg-muted">
                        {formatDate(b.created_at)} · {b.created_by_name}
                      </span>
                    </TD>
                    <TD>
                      {t(`bcr.sources.${b.source}`)}
                      {b.from_cost_element_code && (
                        <span className="block text-caption text-fg-muted">
                          {t('bcr.from')} {b.from_wbs_code}/{b.from_cost_element_code}
                        </span>
                      )}
                    </TD>
                    <TD>
                      {b.wbs_code}/{b.cost_element_code}
                    </TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(b.amount)}
                      {b.increase_pct && Number(b.increase_pct) > 0 && (
                        <span className="block text-caption text-fg-muted">
                          +{b.increase_pct.replace('.', ',')}%
                        </span>
                      )}
                    </TD>
                    <TD className="min-w-48">
                      {t(`bcr.reasons.${b.reason}`)}
                      <span className="block text-caption text-fg-secondary">
                        {b.justification}
                      </span>
                    </TD>
                    <TD>
                      <StatusPill tone={TONE[b.status]}>{t(`bcr.status.${b.status}`)}</StatusPill>
                      {b.decision_comment && (
                        <span className="block text-caption text-fg-muted">
                          {b.decision_comment}
                        </span>
                      )}
                    </TD>
                    <TD>{b.version !== null ? `v${b.version}` : '–'}</TD>
                    <TD>
                      <Button size="sm" variant="secondary" onClick={() => setFiles(b)}>
                        <Icon name="attach_file" /> {t('bcr.attach')}
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <Dialog
        open={files !== null}
        onClose={() => setFiles(null)}
        title={files?.number ?? ''}
        description={t('bcr.attachmentsHelp')}
        className="max-w-2xl"
      >
        {files && <AttachmentsPanel entityType="bcr" entityId={files.id} canWrite={p.can_bcr} />}
      </Dialog>
    </div>
  );
}
