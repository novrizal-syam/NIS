import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input, Select, Textarea } from '@/components/ui/input';
import { Tabs } from '@/components/ui/tabs';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { useOptions } from '@/features/master/api';
import { ApiError } from '@/lib/api';
import { formatNumber } from '@/lib/format';
import {
  CRITERIA,
  SOURCES,
  moneyToApi,
  useConvertLead,
  useCrmConfig,
  useLead,
  useLeadStatus,
  useOwners,
  useSaveLead,
  type Lead,
} from './api';
import { LeadStatusPill } from './CrmPills';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

interface Draft {
  client_code: string;
  company_name: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  source: string;
  need: string;
  estimated_value: string;
  owner_id: string;
  qualification: Record<string, boolean>;
}

const EMPTY: Draft = {
  client_code: '',
  company_name: '',
  contact_name: '',
  contact_email: '',
  contact_phone: '',
  source: 'civd',
  need: '',
  estimated_value: '',
  owner_id: '',
  qualification: {},
};

const fromLead = (l: Lead): Draft => ({
  client_code: l.client_code ?? '',
  company_name: l.company_name,
  contact_name: l.contact_name ?? '',
  contact_email: l.contact_email ?? '',
  contact_phone: l.contact_phone ?? '',
  source: l.source,
  need: l.need,
  estimated_value: l.estimated_value ? formatNumber(Number(l.estimated_value)) : '',
  owner_id: l.owner_id,
  qualification: l.qualification,
});

export function LeadDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const { me, can } = useAuth();
  const lead = useLead(id);
  const save = useSaveLead(id);
  const status = useLeadStatus(id ?? '');
  const convert = useConvertLead(id ?? '');
  const config = useCrmConfig();
  const clients = useOptions('clients');
  const l = lead.data;
  const [draft, setDraft] = useState<Draft | null>(id ? null : EMPTY);
  const [tab, setTab] = useState<'detail' | 'files' | 'history'>('detail');
  const [mode, setMode] = useState<'disqualify' | 'convert' | null>(null);
  const [reason, setReason] = useState('');
  const [conv, setConv] = useState({ title: '', value: '', probability: '20', close: '' });
  const [notice, setNotice] = useState<string | null>(null);
  const [converted, setConverted] = useState<{ id: string; number: string } | null>(null);

  useEffect(() => {
    if (l && !draft) setDraft(fromLead(l));
  }, [l, draft]);

  const editAll = me?.permissions.crm?.edit === 'all';
  const mayAll = () => editAll;
  const canEdit = can('crm', id ? 'edit' : 'create') && (!l || l.owner_id === me?.id || editAll);
  const owners = useOwners(editAll);
  const locked = l?.status === 'disqualified';
  const met = CRITERIA.filter((c) => draft?.qualification[c]).length;
  const min = config.data?.min_qualified ?? 3;

  const body = () =>
    draft && {
      client_code: draft.client_code || null,
      company_name: draft.company_name || null,
      contact_name: draft.contact_name || null,
      contact_email: draft.contact_email || null,
      contact_phone: draft.contact_phone || null,
      source: draft.source,
      need: draft.need,
      estimated_value: moneyToApi(draft.estimated_value),
      ...(draft.owner_id ? { owner_id: draft.owner_id } : {}),
      ...(id && l?.status !== 'qualified' ? { qualification: draft.qualification } : {}),
    };

  const error = errText(save.error ?? status.error ?? convert.error, t('auth.unexpected'));
  const set = (patch: Partial<Draft>) => draft && setDraft({ ...draft, ...patch });

  const footer = (
    <>
      <Button variant="ghost" onClick={onClose}>
        {t('common.close')}
      </Button>
      {canEdit && !locked && draft && (
        <Button
          variant="primary"
          disabled={save.isPending || draft.need.trim().length < 5}
          onClick={() =>
            save.mutate(body() ?? {}, {
              onSuccess: () => {
                if (!id) onClose();
                else setNotice(t('crm.saved'));
              },
            })
          }
        >
          {id ? t('master.save') : t('crm.createLead')}
        </Button>
      )}
    </>
  );

  return (
    <Dialog
      open
      onClose={onClose}
      title={l ? `${l.number} · ${l.company_name}` : id ? t('common.loading') : t('crm.newLead')}
      className="max-w-3xl"
      footer={footer}
    >
      <div className="flex flex-col gap-4">
        {l && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <LeadStatusPill status={l.status} />
              <span className="text-small text-fg-secondary">
                {t('crm.owner')}: {l.owner_name ?? '–'}
              </span>
              {l.opportunity_id && (
                <Link
                  to={`/peluang/${l.opportunity_id}`}
                  className="text-small font-semibold text-fg-accent underline"
                >
                  {l.opportunity_number}
                </Link>
              )}
            </div>
            <Tabs
              label={l.number}
              value={tab}
              onChange={setTab}
              items={[
                { value: 'detail', label: t('crm.tabDetail') },
                { value: 'files', label: t('crm.tabFiles') },
                { value: 'history', label: t('master.tabHistory') },
              ]}
            />
          </>
        )}
        <FormError message={error} />
        {notice && !error && (
          <p
            role="status"
            className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
          >
            {notice}
          </p>
        )}
        {converted && (
          <p
            role="status"
            className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
          >
            {t('crm.convertedTo')}{' '}
            <Link to={`/peluang/${converted.id}`} className="underline">
              {converted.number}
            </Link>
          </p>
        )}
        {l?.disqualify_reason && (
          <p className="text-small text-fg-secondary">
            {t('crm.disqualifyReason')}: {l.disqualify_reason}
          </p>
        )}

        {tab === 'detail' && draft && (
          <fieldset disabled={!canEdit || locked} className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t('crm.client')} hint={t('crm.clientHint')}>
                <Select
                  value={draft.client_code}
                  onChange={(e) => set({ client_code: e.target.value })}
                >
                  <option value="">{t('crm.prospect')}</option>
                  {clients.data?.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('crm.company')} required={!draft.client_code}>
                <Input
                  value={draft.company_name}
                  onChange={(e) => set({ company_name: e.target.value })}
                />
              </Field>
              <Field label={t('crm.contactName')}>
                <Input
                  value={draft.contact_name}
                  onChange={(e) => set({ contact_name: e.target.value })}
                />
              </Field>
              <Field label={t('crm.contactEmail')}>
                <Input
                  type="email"
                  value={draft.contact_email}
                  onChange={(e) => set({ contact_email: e.target.value })}
                />
              </Field>
              <Field label={t('crm.contactPhone')}>
                <Input
                  value={draft.contact_phone}
                  onChange={(e) => set({ contact_phone: e.target.value })}
                />
              </Field>
              <Field label={t('crm.source')} required>
                <Select value={draft.source} onChange={(e) => set({ source: e.target.value })}>
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {t(`crm.sources.${s}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t('crm.estimatedValue')} hint="Rp">
                <Input
                  inputMode="numeric"
                  value={draft.estimated_value}
                  onChange={(e) => set({ estimated_value: e.target.value })}
                />
              </Field>
              {mayAll() && (
                <Field label={t('crm.owner')}>
                  <Select
                    value={draft.owner_id}
                    onChange={(e) => set({ owner_id: e.target.value })}
                  >
                    <option value="">{t('crm.ownerMe')}</option>
                    {owners.data?.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.full_name}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
            <Field label={t('crm.need')} required>
              <Textarea
                rows={3}
                value={draft.need}
                onChange={(e) => set({ need: e.target.value })}
              />
            </Field>

            {id && (
              <fieldset
                className="rounded-card border border-border p-3"
                disabled={!canEdit || l?.status === 'qualified' || locked}
              >
                <legend className="px-1 text-small font-semibold text-fg">
                  {t('crm.qualification')} ·{' '}
                  <span className={met >= min ? 'text-success' : 'text-fg-secondary'}>
                    {t('crm.criteriaMet', { count: met, min })}
                  </span>
                </legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {CRITERIA.map((c) => (
                    <label key={c} className="flex items-start gap-2 text-small text-fg-body">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={Boolean(draft.qualification[c])}
                        onChange={(e) =>
                          set({ qualification: { ...draft.qualification, [c]: e.target.checked } })
                        }
                      />
                      {t(`crm.criteria.${c}`)}
                    </label>
                  ))}
                </div>
              </fieldset>
            )}
          </fieldset>
        )}

        {tab === 'detail' && l && canEdit && !locked && (
          <div className="flex flex-col gap-3 border-t border-border pt-3">
            <div className="flex flex-wrap gap-2">
              {l.status === 'new' && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => status.mutate({ to: 'contacted' })}
                >
                  {t('crm.markContacted')}
                </Button>
              )}
              {l.status === 'contacted' && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={met < min}
                  title={met < min ? t('crm.qualifyHint', { min }) : undefined}
                  onClick={() =>
                    save.mutate(body() ?? {}, {
                      onSuccess: () => status.mutate({ to: 'qualified' }),
                    })
                  }
                >
                  {t('crm.qualify')}
                </Button>
              )}
              {l.status === 'qualified' && !l.opportunity_id && can('crm', 'create') && (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    setConv({
                      title: l.need.slice(0, 200),
                      value: l.estimated_value ? formatNumber(Number(l.estimated_value)) : '',
                      probability: '20',
                      close: '',
                    });
                    setMode('convert');
                  }}
                >
                  {t('crm.convert')}
                </Button>
              )}
              {(l.status === 'new' || l.status === 'contacted') && (
                <Button size="sm" variant="destructive" onClick={() => setMode('disqualify')}>
                  {t('crm.disqualify')}
                </Button>
              )}
            </div>

            {mode === 'disqualify' && (
              <div className="flex flex-col gap-2 rounded-card border border-border p-3">
                <Field label={t('crm.disqualifyReason')} required>
                  <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
                <Button
                  size="sm"
                  variant="destructive"
                  className="self-start"
                  disabled={reason.trim().length < 5 || status.isPending}
                  onClick={() =>
                    status.mutate(
                      { to: 'disqualified', reason },
                      { onSuccess: () => setMode(null) },
                    )
                  }
                >
                  {t('crm.confirmDisqualify')}
                </Button>
              </div>
            )}

            {mode === 'convert' && (
              <div className="flex flex-col gap-3 rounded-card border border-border p-3">
                <Field label={t('crm.oppTitle')} required>
                  <Input
                    value={conv.title}
                    onChange={(e) => setConv({ ...conv, title: e.target.value })}
                  />
                </Field>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label={t('crm.value')} hint="Rp">
                    <Input
                      inputMode="numeric"
                      value={conv.value}
                      onChange={(e) => setConv({ ...conv, value: e.target.value })}
                    />
                  </Field>
                  <Field label={t('crm.probability')}>
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={conv.probability}
                      onChange={(e) => setConv({ ...conv, probability: e.target.value })}
                    />
                  </Field>
                  <Field label={t('crm.expectedClose')}>
                    <Input
                      type="date"
                      value={conv.close}
                      onChange={(e) => setConv({ ...conv, close: e.target.value })}
                    />
                  </Field>
                </div>
                <Button
                  size="sm"
                  variant="primary"
                  className="self-start"
                  disabled={conv.title.trim().length < 3 || convert.isPending}
                  onClick={() =>
                    convert.mutate(
                      {
                        title: conv.title,
                        value: moneyToApi(conv.value),
                        probability: Number(conv.probability || 0),
                        expected_close: conv.close || null,
                        is_tender: l.source === 'eproc' || l.source === 'invitation',
                      },
                      {
                        onSuccess: (o) => {
                          setMode(null);
                          setConverted({ id: o.id, number: o.number });
                        },
                      },
                    )
                  }
                >
                  {t('crm.confirmConvert')}
                </Button>
              </div>
            )}
          </div>
        )}

        {tab === 'files' && l && (
          <AttachmentsPanel entityType="lead" entityId={l.id} canWrite={canEdit && !locked} />
        )}
        {tab === 'history' && l && <HistoryPanel entityType="lead" entityId={l.id} />}
      </div>
    </Dialog>
  );
}
