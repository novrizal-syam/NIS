import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { OpportunityQuotationCard } from '@/features/quotations/OpportunityQuotationCard';
import { OpportunityTenderCard } from '@/features/tenders/OpportunityTenderCard';
import { ApiError } from '@/lib/api';
import { formatDate, formatDateTime, formatIDR, formatNumber } from '@/lib/format';
import {
  SCORES,
  moneyToApi,
  scorePercent,
  useBidDecision,
  useCrmConfig,
  useMarkWon,
  useMoveStage,
  useOpportunity,
  useSaveOpportunity,
  type BidDecisionRow,
  type OpportunityDetail,
} from './api';
import { StagePill } from './CrmPills';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

export function OpportunityDetailPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const opp = useOpportunity(id);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');

  if (opp.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (opp.error || !opp.data) {
    return <FormError message={errText(opp.error, t('auth.unexpected'))} />;
  }
  const o = opp.data;
  const open = ['qualified', 'quotation', 'submitted'].includes(o.stage);

  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/peluang"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('crm.backToOpps')}
      </Link>

      <Card>
        <CardHeader>
          <p className="eyebrow">
            {o.number}
            {o.lead_number && ` · ${o.lead_number}`}
            {o.is_tender && ` · ${t('crm.tender')}`}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{o.title}</CardTitle>
            <StagePill stage={o.stage} />
          </div>
          <CardDescription>{o.company_name}</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-5">
            <Stat label={t('crm.value')} value={formatIDR(o.value)} strong />
            <Stat label={t('crm.probability')} value={`${o.probability}%`} />
            <Stat label={t('crm.weighted')} value={formatIDR(o.weighted_value)} />
            <Stat
              label={t('crm.expectedClose')}
              value={o.expected_close ? formatDate(o.expected_close) : '–'}
            />
            <Stat label={t('crm.owner')} value={o.owner_name ?? '–'} />
          </dl>
          {(o.contract || o.project) && (
            <p className="mt-3 flex flex-wrap gap-3 text-small">
              {o.contract && (
                <Link
                  to={`/kontrak/${o.contract.id}`}
                  className="font-semibold text-fg-accent underline"
                >
                  {t('crm.contractLink', { number: o.contract.number })}
                </Link>
              )}
              {o.project && (
                <Link
                  to={`/proyek/${o.project.id}`}
                  className="font-semibold text-fg-accent underline"
                >
                  {t('crm.projectLink', { number: o.project.number })}
                </Link>
              )}
            </p>
          )}
          {o.winner_price && (
            <p className="mt-1 text-small text-fg-secondary">
              {t('crm.winnerPrice')}: {formatIDR(o.winner_price)}
            </p>
          )}
          {o.lost_reason && (
            <p className="mt-3 text-small text-danger">
              {t('crm.lostReason')}: {o.lost_reason}
            </p>
          )}
        </CardContent>
      </Card>

      <Tabs
        label={o.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'files', label: t('crm.tabFiles') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />

      {tab === 'detail' && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="flex flex-col gap-4">
            {o.is_tender && <OpportunityTenderCard opportunityId={o.id} open={open} />}
            <OpportunityQuotationCard opportunityId={o.id} stage={o.stage} canCreate={o.can_edit} />
            {o.can_edit && open && <EditCard o={o} />}
            {o.can_edit && open && <StageCard o={o} />}
          </div>
          <div className="flex flex-col gap-4">
            {o.can_submit && o.stage === 'qualified' && o.bid_status !== 'pending' && (
              <BidCard o={o} />
            )}
            <BidHistory rows={o.bid_decisions} />
          </div>
        </div>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="opportunity" entityId={o.id} canWrite={o.can_edit} />
      )}
      {tab === 'history' && <HistoryPanel entityType="opportunity" entityId={o.id} />}
    </div>
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

function EditCard({ o }: { o: OpportunityDetail }) {
  const { t } = useTranslation();
  const save = useSaveOpportunity(o.id);
  const [v, setV] = useState({
    title: o.title,
    value: formatNumber(Number(o.value)),
    probability: String(o.probability),
    close: o.expected_close ?? '',
    tender: o.is_tender,
  });
  useEffect(() => {
    setV({
      title: o.title,
      value: formatNumber(Number(o.value)),
      probability: String(o.probability),
      close: o.expected_close ?? '',
      tender: o.is_tender,
    });
  }, [o.title, o.value, o.probability, o.expected_close, o.is_tender]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('crm.editOpp')}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(save.error, t('auth.unexpected'))} />
        {save.isSuccess && (
          <p role="status" className="text-small font-medium text-success">
            {t('crm.saved')}
          </p>
        )}
        <Field label={t('crm.oppTitle')} required>
          <Input value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t('crm.value')} hint="Rp">
            <Input
              inputMode="numeric"
              value={v.value}
              onChange={(e) => setV({ ...v, value: e.target.value })}
            />
          </Field>
          <Field label={t('crm.probability')}>
            <Input
              type="number"
              min={0}
              max={100}
              value={v.probability}
              onChange={(e) => setV({ ...v, probability: e.target.value })}
            />
          </Field>
          <Field label={t('crm.expectedClose')}>
            <Input
              type="date"
              value={v.close}
              onChange={(e) => setV({ ...v, close: e.target.value })}
            />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-small text-fg-body">
          <input
            type="checkbox"
            checked={v.tender}
            onChange={(e) => setV({ ...v, tender: e.target.checked })}
          />
          {t('crm.isTender')}
        </label>
        <Button
          variant="primary"
          className="self-start"
          disabled={save.isPending || v.title.trim().length < 3}
          onClick={() =>
            save.mutate({
              title: v.title,
              value: moneyToApi(v.value) ?? '0',
              probability: Number(v.probability || 0),
              expected_close: v.close || null,
              is_tender: v.tender,
            })
          }
        >
          {t('master.save')}
        </Button>
      </CardContent>
    </Card>
  );
}

function StageCard({ o }: { o: OpportunityDetail }) {
  const { t } = useTranslation();
  const move = useMoveStage(o.id);
  const won = useMarkWon(o.id);
  const [mode, setMode] = useState<'won' | 'lost' | null>(null);
  const [reason, setReason] = useState('');
  const [winner, setWinner] = useState('');
  const [w, setW] = useState({ po: '', start: '', end: '', term: '' });
  const pending = o.bid_status === 'pending';

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('crm.stageLabel')}</CardTitle>
        <CardDescription>
          {o.stage === 'qualified'
            ? t('crm.qualifiedHint')
            : o.stage === 'submitted'
              ? t('crm.submittedHint')
              : t('crm.stageHint')}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(move.error ?? won.error, t('auth.unexpected'))} />
        {pending && (
          <p role="note" className="text-small text-warning">
            {t('crm.bidPendingNote')}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {o.stage === 'quotation' && (
            <Button
              variant="secondary"
              disabled={move.isPending}
              onClick={() => move.mutate({ to: 'submitted' })}
            >
              {t('crm.moveTo.submitted')}
            </Button>
          )}
          {o.stage === 'submitted' && (
            <Button variant="primary" onClick={() => setMode('won')}>
              <Icon name="emoji_events" /> {t('crm.markWon')}
            </Button>
          )}
          <Button variant="destructive" disabled={pending} onClick={() => setMode('lost')}>
            {t('crm.markLost')}
          </Button>
        </div>
        {mode === 'won' && (
          <div className="flex flex-col gap-3 rounded-card border border-border p-3">
            <p className="text-small text-fg-secondary">{t('crm.wonHelp')}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t('crm.poNumber')}>
                <Input value={w.po} onChange={(e) => setW({ ...w, po: e.target.value })} />
              </Field>
              <Field label={t('crm.paymentTerm')} hint={t('crm.paymentTermHint')}>
                <Input
                  type="number"
                  min={0}
                  max={365}
                  value={w.term}
                  onChange={(e) => setW({ ...w, term: e.target.value })}
                />
              </Field>
              <Field label={t('crm.startDate')}>
                <Input
                  type="date"
                  value={w.start}
                  onChange={(e) => setW({ ...w, start: e.target.value })}
                />
              </Field>
              <Field label={t('crm.endDate')}>
                <Input
                  type="date"
                  value={w.end}
                  onChange={(e) => setW({ ...w, end: e.target.value })}
                />
              </Field>
            </div>
            <Button
              variant="primary"
              className="self-start"
              disabled={won.isPending}
              onClick={() =>
                won.mutate({
                  po_number: w.po || undefined,
                  start_date: w.start || null,
                  end_date: w.end || null,
                  payment_term_days: w.term ? Number(w.term) : null,
                })
              }
            >
              {t('crm.confirmWon')}
            </Button>
          </div>
        )}
        {mode === 'lost' && (
          <div className="flex flex-col gap-2 rounded-card border border-border p-3">
            <Field label={t('crm.lostReason')} required>
              <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Field label={t('crm.winnerPrice')} hint={t('crm.winnerPriceHint')}>
              <Input
                inputMode="numeric"
                value={winner}
                onChange={(e) => setWinner(e.target.value)}
              />
            </Field>
            <Button
              variant="destructive"
              className="self-start"
              disabled={reason.trim().length < 5 || move.isPending}
              onClick={() => move.mutate({ to: 'lost', reason, winner_price: moneyToApi(winner) })}
            >
              {t('crm.confirmLost')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BidCard({ o }: { o: OpportunityDetail }) {
  const { t } = useTranslation();
  const config = useCrmConfig();
  const submit = useBidDecision(o.id);
  const [scores, setScores] = useState<Record<string, number>>({});
  const [proposal, setProposal] = useState<'bid' | 'no_bid' | ''>('');
  const [note, setNote] = useState('');
  const pct = scorePercent(scores);
  const threshold = Number(config.data?.bid_threshold ?? 60);
  const rec = pct === null ? null : pct >= threshold ? 'bid' : 'no_bid';
  const differs = rec !== null && proposal !== '' && proposal !== rec;
  const ready = pct !== null && proposal !== '' && (!differs || note.trim().length >= 10);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('crm.bidTitle')}</CardTitle>
        <CardDescription>{t('crm.bidHelp', { threshold })}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(submit.error, t('auth.unexpected'))} />
        <div className="grid gap-3 sm:grid-cols-2">
          {SCORES.map((k) => (
            <Field key={k} label={t(`crm.scores.${k}`)} required>
              <Select
                value={scores[k] ?? ''}
                onChange={(e) => setScores({ ...scores, [k]: Number(e.target.value) })}
              >
                <option value="">–</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </Select>
            </Field>
          ))}
        </div>
        <div
          role="status"
          className="flex flex-wrap items-center gap-2 rounded-control bg-surface-muted px-3 py-2"
        >
          <span className="text-small text-fg-secondary">{t('crm.score')}</span>
          <span className="font-heading text-card-title tabular-nums text-fg">
            {pct === null ? '–' : `${pct.toFixed(2).replace('.', ',')}%`}
          </span>
          {rec && (
            <StatusPill tone={rec === 'bid' ? 'success' : 'danger'}>
              {t(`crm.recommend.${rec}`)}
            </StatusPill>
          )}
        </div>
        <fieldset className="flex flex-wrap gap-4">
          <legend className="mb-1 text-small font-semibold text-fg">{t('crm.proposal')}</legend>
          {(['bid', 'no_bid'] as const).map((p) => (
            <label key={p} className="flex items-center gap-2 text-small text-fg-body">
              <input
                type="radio"
                name="proposal"
                checked={proposal === p}
                onChange={() => setProposal(p)}
              />
              {t(`crm.proposals.${p}`)}
            </label>
          ))}
        </fieldset>
        <Field
          label={t('crm.bidNote')}
          required={differs}
          hint={differs ? t('crm.justifyHint') : undefined}
        >
          <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Button
          variant="primary"
          className="self-start"
          disabled={!ready || submit.isPending}
          onClick={() =>
            proposal &&
            submit.mutate({ scores, proposal, ...(note.trim() ? { note: note.trim() } : {}) })
          }
        >
          {t('crm.submitBid')}
        </Button>
      </CardContent>
    </Card>
  );
}

const DECISION_TONE = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  cancelled: 'neutral',
} as const;

function BidHistory({ rows }: { rows: BidDecisionRow[] }) {
  const { t } = useTranslation();
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('crm.bidHistory')}</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-3">
          {rows.map((d) => (
            <li
              key={d.id}
              className="flex flex-col gap-1 border-b border-border pb-3 last:border-0"
            >
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill tone={DECISION_TONE[d.status]}>
                  {t(`crm.decisionStatus.${d.status}`)}
                </StatusPill>
                <span className="text-small font-semibold text-fg">
                  {t(`crm.proposals.${d.proposal}`)} · {d.percent.replace('.', ',')}%
                </span>
                <span className="text-caption text-fg-muted">
                  {t(`crm.recommend.${d.recommendation}`)}
                </span>
              </div>
              <span className="text-caption text-fg-secondary">
                {d.created_by_name} · {formatDateTime(d.created_at)}
              </span>
              {d.note && <p className="text-small text-fg-body">{d.note}</p>}
              {d.decision_comment && (
                <p className="text-small text-fg-body">
                  {t('crm.directorComment')}: {d.decision_comment}
                </p>
              )}
              {d.request_id && (
                <Link
                  to={`/persetujuan/${d.request_id}`}
                  className="text-small font-semibold text-fg-accent underline"
                >
                  {t('crm.openApproval')}
                </Link>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
