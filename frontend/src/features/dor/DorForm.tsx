import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { FormError } from '@/features/auth/AuthLayout';
import { ApiError } from '@/lib/api';
import { formatIDR } from '@/lib/format';
import { fetchByClient, useDorOptions, useSubmitDor } from './api';
import { draftFromServer, emptyData, newClientId, today } from './draft';
import { getDraft, putDraft, type LocalDraft } from './offlineStore';
import { checks, price } from './pricing';
import { requestBackgroundSync, syncDraft } from './sync';
import type { DorData, FormOptions } from './types';
import { useDorSync } from './useDorSync';

/** /operasi/dor/baru?project=… → a new client id, then the form. */
export function DorNewPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  useEffect(() => {
    navigate(`/operasi/dor/isi/${newClientId()}?project=${params.get('project') ?? ''}`, {
      replace: true,
    });
  }, [navigate, params]);
  return null;
}

export function DorFormPage() {
  const { t } = useTranslation();
  const { clientId = '' } = useParams();
  const [params] = useSearchParams();
  const [draft, setDraft] = useState<LocalDraft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const local = await getDraft(clientId).catch(() => undefined);
      if (local) {
        if (alive) setDraft(local);
        return;
      }
      try {
        const server = await fetchByClient(clientId);
        const d = draftFromServer(server);
        await putDraft(d);
        if (alive) setDraft(d);
      } catch (e) {
        if (e instanceof ApiError && e.status !== 404) {
          if (alive) setLoadError(e.message);
          return;
        }
        if (alive) setDraft(null);
      }
    })();
    return () => {
      alive = false;
    };
  }, [clientId]);

  const projectId = draft?.project_id ?? params.get('project') ?? '';
  const options = useDorOptions(projectId);
  if (loadError) return <FormError message={loadError} />;
  if (!projectId) return <FormError message={t('dor.noProject')} />;
  if (options.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (!options.data)
    return (
      <FormError
        message={
          options.error instanceof ApiError ? options.error.message : t('dor.offlineNoCache')
        }
      />
    );
  return (
    <DorEditor
      key={clientId}
      clientId={clientId}
      options={options.data}
      initial={
        draft ?? {
          client_id: clientId,
          project_id: projectId,
          project_number: options.data.project.number,
          server_id: null,
          number: null,
          base_version: null,
          status: 'local',
          data: emptyData(options.data),
          state: 'dirty',
          message: null,
          updated_at: new Date().toISOString(),
        }
      }
    />
  );
}

const STATE_TONE = {
  dirty: 'warning',
  synced: 'success',
  conflict: 'danger',
  error: 'danger',
} as const;

function DorEditor({
  clientId,
  options: o,
  initial,
}: {
  clientId: string;
  options: FormOptions;
  initial: LocalDraft;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const online = useDorSync();
  const submit = useSubmitDor();
  const [draft, setDraft] = useState<LocalDraft>(initial);
  const [d, setD] = useState<DorData>(initial.data);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // A background sync (reconnect / service worker) updates the stored draft: reflect its
  // server number, version and sync state without touching what is being typed.
  useEffect(() => {
    const refresh = () => {
      void getDraft(clientId).then((stored) => {
        if (stored) setDraft((cur) => ({ ...stored, data: cur.data }));
      });
    };
    window.addEventListener('dor-drafts-changed', refresh);
    return () => window.removeEventListener('dor-drafts-changed', refresh);
  }, [clientId]);
  const pricing = useMemo(() => price(d, o), [d, o]);
  const issues = useMemo(() => checks(d, o, pricing), [d, o, pricing]);
  const editable = ['local', 'draft', 'returned'].includes(draft.status);
  const set = (patch: Partial<DorData>) => setD({ ...d, ...patch });
  const siteStock = o.stock.filter((s) => s.warehouse_code === d.site_warehouse);
  const rates = (kind: string) => o.rates.filter((r) => r.kind === kind);

  async function save(): Promise<LocalDraft> {
    const local: LocalDraft = {
      ...draft,
      data: d,
      state: 'dirty',
      message: null,
      updated_at: new Date().toISOString(),
    };
    await putDraft(local);
    if (!navigator.onLine) {
      requestBackgroundSync();
      setDraft(local);
      setNotice(t('dor.savedOffline'));
      return local;
    }
    const synced = await syncDraft(local);
    setDraft(synced);
    setNotice(
      synced.state === 'synced'
        ? t('dor.savedSynced', { number: synced.number })
        : synced.state === 'dirty'
          ? t('dor.savedOffline')
          : null,
    );
    if (synced.state === 'dirty') requestBackgroundSync();
    return synced;
  }

  async function onSave() {
    setBusy(true);
    try {
      await save();
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit() {
    setBusy(true);
    try {
      const s = await save();
      if (s.state !== 'synced' || !s.server_id) return;
      const res = await submit.mutateAsync(s.server_id);
      await putDraft({ ...s, status: res.status, base_version: res.version });
      navigate(`/operasi/dor/${res.id}`);
    } catch {
      /* shown through submit.error */
    } finally {
      setBusy(false);
    }
  }

  async function loadServer() {
    const server = await fetchByClient(clientId);
    const fresh = draftFromServer(server);
    await putDraft(fresh);
    setDraft(fresh);
    setD(fresh.data);
    setNotice(null);
  }

  async function keepMine() {
    const server = await fetchByClient(clientId);
    const mine: LocalDraft = { ...draft, data: d, base_version: server.version, state: 'dirty' };
    await putDraft(mine);
    setDraft(await syncDraft(mine));
  }

  const hourInput = (i: number, key: 'operating' | 'standby' | 'breakdown' | 'rig') => (
    <Field label={t(`dor.hours.${key}`)} className="w-24">
      <Input
        inputMode="decimal"
        className="text-right"
        value={d.equipment[i]![key]}
        disabled={!editable}
        onChange={(e) =>
          set({
            equipment: d.equipment.map((x, j) => (j === i ? { ...x, [key]: e.target.value } : x)),
          })
        }
      />
    </Field>
  );

  return (
    <div className="flex flex-col gap-4 pb-24">
      <Link
        to="/operasi/dor"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('dor.back')}
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-heading text-section-title text-fg">
          {draft.number ?? t('dor.newTitle')} · {o.project.number}
        </h2>
        <StatusPill tone={online ? 'success' : 'warning'}>
          {online ? t('dor.online') : t('dor.offline')}
        </StatusPill>
        <StatusPill tone={STATE_TONE[draft.state]}>{t(`dor.state.${draft.state}`)}</StatusPill>
      </div>
      {notice && (
        <p role="status" className="rounded-control bg-info-tint px-3 py-2 text-small text-info">
          {notice}
        </p>
      )}
      {draft.state === 'conflict' && (
        <div
          role="alert"
          className="flex flex-col gap-2 rounded-control border border-danger bg-danger-tint px-3 py-2 text-small text-danger"
        >
          <span>{draft.message}</span>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => void loadServer()}>
              {t('dor.loadServer')}
            </Button>
            <Button size="sm" variant="destructive" onClick={() => void keepMine()}>
              {t('dor.keepMine')}
            </Button>
          </div>
        </div>
      )}
      {draft.state === 'error' && <FormError message={draft.message} />}
      {!editable && <p className="text-small text-fg-secondary">{t('dor.readOnly')}</p>}

      <Card>
        <CardHeader>
          <CardTitle>{t('dor.sections.header')}</CardTitle>
          <CardDescription>
            {o.project.name}
            {o.project.contract_number
              ? ` · ${o.project.contract_number}`
              : ` · ${t('dor.noContract')}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          <Field label={t('dor.reportDate')} required>
            <Input
              type="date"
              max={today()}
              value={d.report_date}
              disabled={!editable || draft.server_id !== null}
              onChange={(e) => set({ report_date: e.target.value })}
            />
          </Field>
          <Field label="WBS">
            <Select
              value={d.wbs_code}
              disabled={!editable}
              onChange={(e) => set({ wbs_code: e.target.value })}
            >
              {o.wbs.map((w) => (
                <option key={w.code} value={w.code}>
                  {w.code} · {w.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('mr.site')}>
            <Select
              value={d.site_warehouse ?? ''}
              disabled={!editable}
              onChange={(e) => set({ site_warehouse: e.target.value || null })}
            >
              <option value="">–</option>
              {o.sites.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code} · {s.name}
                </option>
              ))}
            </Select>
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('dor.sections.equipment')}</CardTitle>
          <CardDescription>{t('dor.equipmentHelp')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {d.equipment.map((x, i) => {
            const a = o.assets.find((y) => y.code === x.asset_code);
            const p = pricing.equipment[i]!;
            return (
              <div key={i} className="flex flex-col gap-2 border-b border-border pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-fg">
                    {x.asset_code} · {a?.name}
                  </span>
                  {editable && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('quotation.removeLine')}
                      onClick={() => set({ equipment: d.equipment.filter((_, j) => j !== i) })}
                    >
                      <Icon name="delete" />
                    </Button>
                  )}
                </div>
                {a?.warning && <span className="text-caption text-warning">{a.warning}</span>}
                <Field label={t('dor.rate')}>
                  <Select
                    value={x.rate_id ?? ''}
                    disabled={!editable}
                    onChange={(e) =>
                      set({
                        equipment: d.equipment.map((y, j) =>
                          j === i ? { ...y, rate_id: e.target.value || null } : y,
                        ),
                      })
                    }
                  >
                    <option value="">{t('dor.notBillable')}</option>
                    {rates('equipment').map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.description} · {formatIDR(r.rate)}/{r.unit}
                      </option>
                    ))}
                  </Select>
                </Field>
                <div className="flex flex-wrap gap-2">
                  {hourInput(i, 'operating')}
                  {hourInput(i, 'standby')}
                  {hourInput(i, 'breakdown')}
                  {hourInput(i, 'rig')}
                </div>
                <span
                  className={
                    p.hours === 24
                      ? 'text-caption text-success'
                      : 'text-caption font-semibold text-danger'
                  }
                >
                  {t('dor.totalHours', { hours: p.hours })} · {formatIDR(p.revenue)}
                </span>
              </div>
            );
          })}
          {editable && (
            <Field label={t('dor.addUnit')}>
              <Select
                value=""
                onChange={(e) =>
                  e.target.value &&
                  set({
                    equipment: [
                      ...d.equipment,
                      {
                        asset_code: e.target.value,
                        rate_id: rates('equipment')[0]?.id ?? null,
                        operating: '24',
                        standby: '0',
                        breakdown: '0',
                        rig: '0',
                      },
                    ],
                  })
                }
              >
                <option value="">{t('master.choose')}</option>
                {o.assets
                  .filter((a) => !d.equipment.some((x) => x.asset_code === a.code))
                  .map((a) => (
                    <option key={a.code} value={a.code} disabled={a.blocked !== null}>
                      {a.code} · {a.name}
                      {a.blocked ? ` — ${t('dor.blocked')}: ${a.blocked}` : ''}
                    </option>
                  ))}
              </Select>
            </Field>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('dor.sections.crew')}</CardTitle>
          <CardDescription>{t('dor.crewHelp')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {d.crew.map((c, i) => {
            const e = o.crew.find((y) => y.code === c.employee_code);
            return (
              <div key={i} className="flex flex-wrap items-end gap-2 border-b border-border pb-3">
                <span className="min-w-40 flex-1 text-small">
                  <span className="font-semibold text-fg">{e?.full_name ?? c.employee_code}</span>
                  <span className="block text-caption text-fg-muted">{e?.position}</span>
                  {e?.warning && (
                    <span className="block text-caption text-warning">{e.warning}</span>
                  )}
                </span>
                <Field label={t('dor.rate')} className="w-56">
                  <Select
                    value={c.rate_id ?? ''}
                    disabled={!editable}
                    onChange={(ev) =>
                      set({
                        crew: d.crew.map((y, j) =>
                          j === i ? { ...y, rate_id: ev.target.value || null } : y,
                        ),
                      })
                    }
                  >
                    <option value="">{t('dor.notBillable')}</option>
                    {rates('personnel').map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.description} · {formatIDR(r.rate)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label={t('dor.hoursWorked')} className="w-24">
                  <Input
                    inputMode="decimal"
                    className="text-right"
                    value={c.hours}
                    disabled={!editable}
                    onChange={(ev) =>
                      set({
                        crew: d.crew.map((y, j) =>
                          j === i ? { ...y, hours: ev.target.value } : y,
                        ),
                      })
                    }
                  />
                </Field>
                <Field label={t('dor.overtime')} className="w-24">
                  <Input
                    inputMode="decimal"
                    className="text-right"
                    value={c.overtime_hours}
                    disabled={!editable}
                    onChange={(ev) =>
                      set({
                        crew: d.crew.map((y, j) =>
                          j === i ? { ...y, overtime_hours: ev.target.value } : y,
                        ),
                      })
                    }
                  />
                </Field>
                {editable && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t('quotation.removeLine')}
                    onClick={() => set({ crew: d.crew.filter((_, j) => j !== i) })}
                  >
                    <Icon name="delete" />
                  </Button>
                )}
              </div>
            );
          })}
          {editable && (
            <Field label={t('dor.addCrew')}>
              <Select
                value=""
                onChange={(e) =>
                  e.target.value &&
                  set({
                    crew: [
                      ...d.crew,
                      {
                        employee_code: e.target.value,
                        rate_id: rates('personnel')[0]?.id ?? null,
                        hours: '12',
                        overtime_hours: '0',
                      },
                    ],
                  })
                }
              >
                <option value="">{t('master.choose')}</option>
                {o.crew
                  .filter((p) => !d.crew.some((c) => c.employee_code === p.code))
                  .map((p) => (
                    <option key={p.code} value={p.code} disabled={p.blocked !== null}>
                      {p.full_name} · {p.position}
                      {p.blocked ? ` — ${t('dor.blocked')}: ${p.blocked}` : ''}
                    </option>
                  ))}
              </Select>
            </Field>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('dor.sections.consumables')}</CardTitle>
          <CardDescription>
            {t('dor.consumablesHelp', { site: d.site_warehouse ?? '–' })}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {d.consumables.map((k, i) => {
            const s = siteStock.find((x) => x.item_code === k.item_code);
            const p = pricing.consumables[i]!;
            return (
              <div key={i} className="flex flex-wrap items-end gap-2 border-b border-border pb-3">
                <span className="min-w-40 flex-1 text-small">
                  <span className="font-semibold text-fg">{s?.name ?? k.item_code}</span>
                  <span className="block text-caption text-fg-muted">
                    {t('dor.siteStock', { qty: p.available, uom: s?.uom ?? '' })}
                  </span>
                </span>
                <Field label={t('dor.rate')} className="w-56">
                  <Select
                    value={k.rate_id ?? ''}
                    disabled={!editable}
                    onChange={(ev) =>
                      set({
                        consumables: d.consumables.map((y, j) =>
                          j === i ? { ...y, rate_id: ev.target.value || null } : y,
                        ),
                      })
                    }
                  >
                    <option value="">{t('dor.notBillable')}</option>
                    {rates('consumable').map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.description} · +{r.markup_pct ?? 0}%
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label={t('quotation.qty')} className="w-24">
                  <Input
                    aria-label={`${t('quotation.qty')} ${k.item_code}`}
                    inputMode="decimal"
                    className="text-right"
                    value={k.qty}
                    disabled={!editable}
                    onChange={(ev) =>
                      set({
                        consumables: d.consumables.map((y, j) =>
                          j === i ? { ...y, qty: ev.target.value } : y,
                        ),
                      })
                    }
                  />
                </Field>
                {editable && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t('quotation.removeLine')}
                    onClick={() => set({ consumables: d.consumables.filter((_, j) => j !== i) })}
                  >
                    <Icon name="delete" />
                  </Button>
                )}
              </div>
            );
          })}
          {editable && (
            <Field label={t('dor.addConsumable')}>
              <Select
                value=""
                onChange={(e) =>
                  e.target.value &&
                  set({
                    consumables: [
                      ...d.consumables,
                      {
                        item_code: e.target.value,
                        rate_id: rates('consumable')[0]?.id ?? null,
                        qty: '1',
                      },
                    ],
                  })
                }
              >
                <option value="">{t('master.choose')}</option>
                {siteStock
                  .filter((s) => !d.consumables.some((k) => k.item_code === s.item_code))
                  .map((s) => (
                    <option key={s.item_code} value={s.item_code}>
                      {s.item_code} · {s.name} ({s.qty.replace('.', ',')} {s.uom})
                    </option>
                  ))}
              </Select>
            </Field>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('dor.sections.activities')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label={t('dor.activities')} required>
            <Textarea
              rows={4}
              value={d.activities}
              disabled={!editable}
              onChange={(e) => set({ activities: e.target.value })}
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Field label={t('dor.nptHours')} className="w-28">
              <Input
                inputMode="decimal"
                className="text-right"
                value={d.npt_hours}
                disabled={!editable}
                onChange={(e) => set({ npt_hours: e.target.value })}
              />
            </Field>
            <Field label={t('dor.nptReason')} className="min-w-0 flex-1">
              <Input
                value={d.npt_reason}
                disabled={!editable}
                onChange={(e) => set({ npt_reason: e.target.value })}
              />
            </Field>
          </div>
        </CardContent>
      </Card>

      {o.template && (
        <Card>
          <CardHeader>
            <CardTitle>{t('dor.sections.technical', { label: o.template.label })}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {o.template.fields.map((f) => (
              <Field key={f.key} label={f.unit ? `${f.label} (${f.unit})` : f.label}>
                <Input
                  inputMode={f.type === 'text' ? 'text' : 'decimal'}
                  value={d.technical[f.key] ?? ''}
                  disabled={!editable}
                  onChange={(e) => set({ technical: { ...d.technical, [f.key]: e.target.value } })}
                />
              </Field>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t('dor.sections.hse')}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(['incidents', 'near_misses', 'unsafe_acts', 'toolbox_talks'] as const).map((k) => (
            <Field key={k} label={t(`dor.hse.${k}`)}>
              <Input
                inputMode="numeric"
                className="text-right"
                value={d.hse[k] ?? '0'}
                disabled={!editable}
                onChange={(e) => set({ hse: { ...d.hse, [k]: e.target.value.replace(/\D/g, '') } })}
              />
            </Field>
          ))}
        </CardContent>
      </Card>

      {issues.length > 0 && editable && (
        <ul className="list-disc rounded-control bg-warning-tint py-2 pl-8 pr-3 text-small text-warning">
          {issues.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      )}
      <FormError message={submit.error instanceof ApiError ? submit.error.message : null} />

      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-surface px-4 py-3 shadow-lg">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2">
          <span className="text-small">
            {t('dor.revenue')}:{' '}
            <span className="font-semibold tabular-nums text-fg">{formatIDR(pricing.revenue)}</span>{' '}
            · {t('dor.internalCost')}:{' '}
            <span className="tabular-nums text-fg-body">{formatIDR(pricing.cost)}</span>
          </span>
          {editable && (
            <span className="flex gap-2">
              <Button variant="secondary" disabled={busy} onClick={() => void onSave()}>
                <Icon name="save" /> {t('dor.save')}
              </Button>
              <Button
                variant="primary"
                disabled={busy || !online || issues.length > 0}
                onClick={() => void onSubmit()}
              >
                <Icon name="send" /> {t('dor.submit')}
              </Button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
