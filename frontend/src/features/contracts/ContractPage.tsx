import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { Tabs } from '@/components/ui/tabs';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { moneyToApi } from '@/features/crm/api';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { ApiError } from '@/lib/api';
import { formatIDR, formatNumber } from '@/lib/format';
import {
  RATE_KINDS,
  useContract,
  useSaveContractHeader,
  useSaveRates,
  type ContractDetail,
  type ContractRate,
} from './api';
import { ContractStatusPill, UsageBar } from './ContractBits';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const money = (v: string | null) => (v ? formatNumber(Number(v)) : '');
const pctText = (v: string | null) => (v ? String(Number(v)).replace('.', ',') : '');
const pctToApi = (v: string) => {
  const s = v.replace(/\./g, '').replace(',', '.').trim();
  return s === '' ? null : s;
};

export function ContractPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const contract = useContract(id);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');
  if (contract.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (contract.error || !contract.data)
    return <FormError message={errText(contract.error, t('auth.unexpected'))} />;
  const c = contract.data;

  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/kontrak"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('contract.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {c.number}
            {c.po_number && ` · ${c.po_number}`}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{c.title}</CardTitle>
            <ContractStatusPill status={c.status} />
          </div>
          <CardDescription>{c.company_name}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <dl className="grid gap-x-6 gap-y-3 text-small sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-fg-muted">{t('contract.value')}</dt>
              <dd className="font-heading text-card-title tabular-nums text-fg">
                {formatIDR(c.value)}
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('contract.used')}</dt>
              <dd className="tabular-nums text-fg-body">{formatIDR(c.used_value)}</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('contract.usage')}</dt>
              <dd>
                <UsageBar pct={c.usage_pct} />
              </dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t('contract.term')}</dt>
              <dd className="text-fg-body">{t('contract.days', { count: c.payment_term_days })}</dd>
            </div>
          </dl>
          <p className="flex flex-wrap gap-3 text-small">
            {c.opportunity_number && (
              <Link to={`/peluang/${c.opportunity_id}`} className="text-fg-accent underline">
                {c.opportunity_number}
              </Link>
            )}
            {c.quotation_label && (
              <Link to={`/penawaran/${c.quotation_id}`} className="text-fg-accent underline">
                {c.quotation_label}
              </Link>
            )}
            {c.project_number && (
              <Link to={`/proyek/${c.project_id}`} className="text-fg-accent underline">
                {t('crm.projectLink', { number: c.project_number })}
              </Link>
            )}
          </p>
        </CardContent>
      </Card>
      <Tabs
        label={c.number}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'detail', label: t('crm.tabDetail') },
          { value: 'files', label: t('crm.tabFiles') },
          { value: 'history', label: t('master.tabHistory') },
        ]}
      />
      {tab === 'detail' && (
        <>
          {c.can_edit && <HeaderForm c={c} />}
          <Rates c={c} />
        </>
      )}
      {tab === 'files' && (
        <AttachmentsPanel entityType="contract" entityId={c.id} canWrite={c.can_edit} />
      )}
      {tab === 'history' && <HistoryPanel entityType="contract" entityId={c.id} />}
    </div>
  );
}

function HeaderForm({ c }: { c: ContractDetail }) {
  const { t } = useTranslation();
  const save = useSaveContractHeader(c.id);
  const [v, setV] = useState({
    po: c.po_number ?? '',
    start: c.start_date ?? '',
    end: c.end_date ?? '',
    term: String(c.payment_term_days),
    status: c.status,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('contract.header')}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(save.error, t('auth.unexpected'))} />
        {save.isSuccess && (
          <p role="status" className="text-small font-medium text-success">
            {t('crm.saved')}
          </p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label={t('contract.po')}>
            <Input value={v.po} onChange={(e) => setV({ ...v, po: e.target.value })} />
          </Field>
          <Field label={t('crm.startDate')}>
            <Input
              type="date"
              value={v.start}
              onChange={(e) => setV({ ...v, start: e.target.value })}
            />
          </Field>
          <Field label={t('crm.endDate')}>
            <Input
              type="date"
              value={v.end}
              onChange={(e) => setV({ ...v, end: e.target.value })}
            />
          </Field>
          <Field label={t('crm.paymentTerm')}>
            <Input
              type="number"
              min={0}
              max={365}
              value={v.term}
              onChange={(e) => setV({ ...v, term: e.target.value })}
            />
          </Field>
          <Field label={t('master.status')}>
            <Select
              value={v.status}
              onChange={(e) => setV({ ...v, status: e.target.value as ContractDetail['status'] })}
            >
              {(['active', 'completed', 'terminated'] as const).map((s) => (
                <option key={s} value={s}>
                  {t(`contract.status.${s}`)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Button
          variant="primary"
          className="self-start"
          disabled={save.isPending}
          onClick={() =>
            save.mutate({
              po_number: v.po || null,
              start_date: v.start || null,
              end_date: v.end || null,
              payment_term_days: Number(v.term || 0),
              status: v.status,
            })
          }
        >
          {t('master.save')}
        </Button>
      </CardContent>
    </Card>
  );
}

const toRows = (rates: ContractRate[]): ContractRate[] =>
  rates.map((r) => ({
    ...r,
    rate: money(r.rate),
    standby_rate: money(r.standby_rate),
    breakdown_rate: money(r.breakdown_rate),
    unit_cost: money(r.unit_cost),
    markup_pct: pctText(r.markup_pct),
  }));

function Rates({ c }: { c: ContractDetail }) {
  const { t } = useTranslation();
  const save = useSaveRates(c.id);
  const editable = c.can_edit && c.status === 'active';
  const [rows, setRows] = useState<ContractRate[]>(() => toRows(c.rates));
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (!dirty) setRows(toRows(c.rates));
  }, [c.rates, dirty]);
  const set = (i: number, patch: Partial<ContractRate>) => {
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    setDirty(true);
  };
  const cell = (i: number, key: keyof ContractRate, label: string, show = true) =>
    !show ? (
      <span className="text-fg-muted">–</span>
    ) : editable ? (
      <Input
        aria-label={`${label} ${i + 1}`}
        inputMode="numeric"
        className="text-right"
        value={(rows[i]![key] as string | null) ?? ''}
        onChange={(e) => set(i, { [key]: e.target.value })}
      />
    ) : (rows[i]![key] as string | null) ? (
      `Rp ${rows[i]![key] as string}`
    ) : (
      '–'
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('contract.rates')}</CardTitle>
        <CardDescription>{t('contract.ratesHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(save.error, t('auth.unexpected'))} />
        <div className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>{t('contract.kind')}</TH>
                <TH>{t('quotation.description')}</TH>
                <TH className="w-20">{t('quotation.unit')}</TH>
                <TH className="w-36 text-right">{t('contract.rate')}</TH>
                <TH className="w-36 text-right">{t('contract.standby')}</TH>
                <TH className="w-32 text-right">{t('contract.breakdown')}</TH>
                <TH className="w-36 text-right">{t('quotation.unitCost')}</TH>
                <TH className="w-24 text-right">{t('contract.markup')}</TH>
                {editable && <TH className="w-10">{''}</TH>}
              </TR>
            </THead>
            <TBody>
              {rows.map((r, i) => (
                <TR key={i}>
                  <TD>
                    {editable ? (
                      <Select
                        aria-label={`${t('contract.kind')} ${i + 1}`}
                        value={r.kind}
                        onChange={(e) => set(i, { kind: e.target.value as ContractRate['kind'] })}
                      >
                        {RATE_KINDS.map((k) => (
                          <option key={k} value={k}>
                            {t(`contract.kinds.${k}`)}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      t(`contract.kinds.${r.kind}`)
                    )}
                  </TD>
                  <TD className="min-w-48">
                    {editable ? (
                      <Input
                        aria-label={`${t('quotation.description')} ${i + 1}`}
                        value={r.description}
                        onChange={(e) => set(i, { description: e.target.value })}
                      />
                    ) : (
                      r.description
                    )}
                  </TD>
                  <TD>
                    {editable ? (
                      <Input
                        aria-label={`${t('quotation.unit')} ${i + 1}`}
                        value={r.unit}
                        onChange={(e) => set(i, { unit: e.target.value })}
                      />
                    ) : (
                      r.unit
                    )}
                  </TD>
                  <TD className="text-right tabular-nums">
                    {r.kind === 'consumable' && editable
                      ? r.rate
                        ? `Rp ${r.rate}`
                        : t('contract.computed')
                      : cell(i, 'rate', t('contract.rate'))}
                  </TD>
                  <TD className="text-right tabular-nums">
                    {cell(i, 'standby_rate', t('contract.standby'), r.kind === 'equipment')}
                  </TD>
                  <TD className="text-right tabular-nums">
                    {cell(i, 'breakdown_rate', t('contract.breakdown'), r.kind === 'equipment')}
                  </TD>
                  <TD className="text-right tabular-nums">
                    {cell(i, 'unit_cost', t('quotation.unitCost'), r.kind === 'consumable')}
                  </TD>
                  <TD className="text-right tabular-nums">
                    {r.kind !== 'consumable' ? (
                      <span className="text-fg-muted">–</span>
                    ) : editable ? (
                      <Input
                        aria-label={`${t('contract.markup')} ${i + 1}`}
                        inputMode="decimal"
                        className="text-right"
                        value={r.markup_pct ?? ''}
                        onChange={(e) => set(i, { markup_pct: e.target.value })}
                      />
                    ) : (
                      `${r.markup_pct ?? '–'}%`
                    )}
                  </TD>
                  {editable && (
                    <TD>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`${t('quotation.removeLine')} ${i + 1}`}
                        onClick={() => {
                          setRows(rows.filter((_, j) => j !== i));
                          setDirty(true);
                        }}
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
        {editable && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                setRows([
                  ...rows,
                  {
                    kind: 'mobilisation',
                    price_item_code: null,
                    cost_element_code: null,
                    description: '',
                    unit: 'lot',
                    rate: '',
                    standby_rate: null,
                    breakdown_rate: null,
                    unit_cost: null,
                    markup_pct: null,
                    quoted_qty: null,
                  },
                ]);
                setDirty(true);
              }}
            >
              <Icon name="add" /> {t('contract.addRate')}
            </Button>
            <Button
              variant="primary"
              disabled={!dirty || save.isPending}
              onClick={() =>
                save.mutate(
                  rows.map((r) => ({
                    kind: r.kind,
                    price_item_code: r.price_item_code,
                    cost_element_code: r.cost_element_code,
                    description: r.description,
                    unit: r.unit,
                    rate: moneyToApi(r.rate ?? ''),
                    standby_rate: moneyToApi(r.standby_rate ?? ''),
                    breakdown_rate: moneyToApi(r.breakdown_rate ?? ''),
                    unit_cost: moneyToApi(r.unit_cost ?? ''),
                    markup_pct: pctToApi(r.markup_pct ?? ''),
                    quoted_qty: r.quoted_qty,
                  })),
                  { onSuccess: () => setDirty(false) },
                )
              }
            >
              {t('contract.saveRates')}
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
