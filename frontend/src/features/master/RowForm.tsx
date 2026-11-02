import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { Tabs } from '@/components/ui/tabs';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { ApiError } from '@/lib/api';
import {
  useDeleteRow,
  useOptions,
  useSaveRow,
  type EntityMeta,
  type ExpiringDoc,
  type FieldMeta,
  type Row,
} from './api';

type Values = Record<string, unknown>;

function RefSelect({
  f,
  value,
  onChange,
  disabled,
}: {
  f: FieldMeta;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const opts = useOptions(f.ref);
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      <option value="">{f.required ? t('master.choose') : t('master.none')}</option>
      {opts.data?.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
      {value && !opts.data?.some((o) => o.value === value) && (
        <option value={value}>{value}</option>
      )}
    </Select>
  );
}

function DocsEditor({
  value,
  onChange,
}: {
  value: ExpiringDoc[];
  onChange: (v: ExpiringDoc[]) => void;
}) {
  const { t } = useTranslation();
  const set = (i: number, patch: Partial<ExpiringDoc>) =>
    onChange(value.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  return (
    <div className="flex flex-col gap-2">
      {value.map((d, i) => (
        <div
          key={i}
          className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto] items-end gap-2"
        >
          <Field label={t('master.docName')}>
            <Input value={d.name} onChange={(e) => set(i, { name: e.target.value })} />
          </Field>
          <Field label={t('master.docNumber')}>
            <Input
              value={d.number ?? ''}
              onChange={(e) => set(i, { number: e.target.value || null })}
            />
          </Field>
          <Field label={t('master.docExpiry')}>
            <Input
              type="date"
              value={d.expiry_date ?? ''}
              onChange={(e) => set(i, { expiry_date: e.target.value || null })}
            />
          </Field>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('master.removeDoc')}
            onClick={() => onChange(value.filter((_, j) => j !== i))}
          >
            <Icon name="delete" />
          </Button>
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => onChange([...value, { name: '', number: null, expiry_date: null }])}
      >
        <Icon name="add" /> {t('master.addDoc')}
      </Button>
    </div>
  );
}

function toInput(f: FieldMeta, v: unknown): unknown {
  if (f.kind === 'docs') return (v as ExpiringDoc[] | undefined) ?? [];
  if (f.kind === 'bool') return Boolean(v);
  return v === null || v === undefined ? '' : String(v);
}

/** Converts form strings to API values; id-ID thousand dots are accepted in money fields. */
function toApi(f: FieldMeta, v: unknown): unknown {
  if (f.kind === 'docs' || f.kind === 'bool') return v;
  const s = String(v ?? '').trim();
  if (s === '') return null;
  if (f.kind === 'idr') return s.replace(/[^\d-]/g, '');
  if (f.kind === 'decimal') return s.replace(/\./g, '').replace(',', '.');
  if (f.kind === 'int') return Number(s.replace(/\./g, ''));
  return s;
}

export function RowForm({
  meta,
  row,
  onClose,
}: {
  meta: EntityMeta;
  row: Row | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const editing = row !== null;
  const save = useSaveRow(meta.key);
  const remove = useDeleteRow(meta.key);
  const readOnly = editing ? !meta.can.edit : !meta.can.create;
  const [values, setValues] = useState<Values>(() => {
    const init: Values = {};
    for (const f of meta.fields)
      init[f.name] = toInput(f, row?.[f.name] ?? (f.kind === 'docs' ? [] : undefined));
    if (meta.has_active) init.is_active = row ? row.is_active : true;
    return init;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [tab, setTab] = useState<'data' | 'history' | 'files'>('data');

  const set = (name: string, v: unknown) => setValues((all) => ({ ...all, [name]: v }));

  const submit = async () => {
    setErrors({});
    setFormError(null);
    const missing: Record<string, string> = {};
    const data: Values = {};
    for (const f of meta.fields) {
      if (editing && f.key) continue;
      const v = toApi(f, values[f.name]);
      if ((f.required || f.key) && (v === null || v === '')) missing[f.name] = t('master.required');
      if (!editing && v === null) continue;
      data[f.name] = v;
    }
    if (meta.has_active) data.is_active = values.is_active;
    if (Object.keys(missing).length) return setErrors(missing);
    try {
      await save.mutateAsync({ id: row?.id, data });
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        const details = Array.isArray(err.details)
          ? (err.details as { field: string; message: string }[])
          : [];
        setErrors(Object.fromEntries(details.map((d) => [d.field.split('.')[0], d.message])));
        setFormError(err.message);
      } else setFormError(t('auth.unexpected'));
    }
  };

  const title = editing
    ? t('master.editTitle', { entity: meta.label, name: String(row?.[meta.title_field] ?? '') })
    : t('master.newTitle', { entity: meta.label });

  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      className="max-w-3xl"
      footer={
        <>
          {editing && meta.can.delete && (
            <Button
              variant="destructive"
              className="mr-auto"
              disabled={remove.isPending}
              onClick={() => {
                if (!confirmDelete) return setConfirmDelete(true);
                remove.mutate(row.id, {
                  onSuccess: onClose,
                  onError: (err) =>
                    setFormError(err instanceof ApiError ? err.message : t('auth.unexpected')),
                });
              }}
            >
              <Icon name="delete" />{' '}
              {confirmDelete ? t('master.confirmDelete') : t('master.delete')}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            {readOnly ? t('common.close') : t('common.cancel')}
          </Button>
          {!readOnly && tab === 'data' && (
            <Button variant="primary" disabled={save.isPending} onClick={() => void submit()}>
              {t('master.save')}
            </Button>
          )}
        </>
      }
    >
      {editing && (
        <div className="mb-4">
          <Tabs
            label={title}
            value={tab}
            onChange={setTab}
            items={[
              { value: 'data', label: t('master.tabData') },
              { value: 'history', label: t('master.tabHistory') },
              { value: 'files', label: t('master.tabFiles') },
            ]}
          />
        </div>
      )}
      {editing && tab === 'history' && (
        <HistoryPanel
          entityType={meta.key}
          entityId={row.id}
          labels={{
            ...Object.fromEntries(meta.fields.map((f) => [f.name, f.label])),
            is_active: t('master.active'),
            file: t('dms.file'),
            version: t('dms.version'),
            size: t('dms.size'),
          }}
        />
      )}
      {editing && tab === 'files' && (
        <AttachmentsPanel entityType={meta.key} entityId={row.id} canWrite={meta.can.edit} />
      )}
      <div className={tab === 'data' ? 'flex flex-col gap-4' : 'hidden'}>
        <FormError message={formError} />
        <div className="grid gap-4 sm:grid-cols-2">
          {meta.fields.map((f) => {
            const disabled = readOnly || (editing && f.key);
            const common = { disabled };
            const err = errors[f.name];
            if (f.kind === 'docs') {
              return (
                <fieldset key={f.name} className="sm:col-span-2" disabled={disabled}>
                  <legend className="mb-2 text-small font-semibold text-fg">{f.label}</legend>
                  <DocsEditor
                    value={values[f.name] as ExpiringDoc[]}
                    onChange={(v) => set(f.name, v)}
                  />
                </fieldset>
              );
            }
            if (f.kind === 'bool') {
              return (
                <label
                  key={f.name}
                  className="flex items-center gap-2 self-end pb-2 text-small font-semibold text-fg"
                >
                  <input
                    type="checkbox"
                    checked={Boolean(values[f.name])}
                    onChange={(e) => set(f.name, e.target.checked)}
                    className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
                    {...common}
                  />
                  {f.label}
                </label>
              );
            }
            const hint = f.sensitive
              ? t('master.sensitiveHint')
              : f.kind === 'idr'
                ? t('master.idrHint')
                : undefined;
            return (
              <Field key={f.name} label={f.label} required={f.required} error={err} hint={hint}>
                {f.kind === 'choice' ? (
                  <Select
                    value={String(values[f.name])}
                    onChange={(e) => set(f.name, e.target.value)}
                    {...common}
                  >
                    <option value="">{f.required ? t('master.choose') : t('master.none')}</option>
                    {f.choices.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                ) : f.kind === 'ref' ? (
                  <RefSelect
                    f={f}
                    value={String(values[f.name])}
                    onChange={(v) => set(f.name, v)}
                    {...common}
                  />
                ) : (
                  <Input
                    value={String(values[f.name])}
                    onChange={(e) => set(f.name, e.target.value)}
                    type={f.kind === 'date' ? 'date' : 'text'}
                    inputMode={['idr', 'int', 'decimal'].includes(f.kind) ? 'decimal' : undefined}
                    maxLength={f.max_length ?? undefined}
                    className={
                      ['idr', 'int', 'decimal'].includes(f.kind)
                        ? 'text-right tabular-nums'
                        : undefined
                    }
                    {...common}
                  />
                )}
              </Field>
            );
          })}
          {meta.has_active && (
            <label className="flex items-center gap-2 text-small font-semibold text-fg">
              <input
                type="checkbox"
                checked={Boolean(values.is_active)}
                disabled={readOnly}
                onChange={(e) => set('is_active', e.target.checked)}
                className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
              />
              {t('master.active')}
            </label>
          )}
        </div>
      </div>
    </Dialog>
  );
}
