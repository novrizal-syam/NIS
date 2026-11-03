import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { visibleNav } from '@/app/nav';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';
import {
  fetchPreview,
  useCatalog,
  useRole,
  useSaveGrants,
  useUpdateRole,
  type GrantRow,
} from './api';

type Matrix = Record<string, string>; // "module.action" -> scope ('' = none)
const SENSITIVE = 'sensitive';

function PreviewDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchPreview>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetchPreview(id)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : t('auth.unexpected')));
  }, [id, t]);
  const groups = data ? visibleNav(false, (m) => Boolean(data.permissions[m]?.view)) : [];
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('roles.viewAsTitle', { name: data?.role.name ?? '' })}
      description={t('roles.viewAsHelp')}
      className="max-w-xl"
    >
      <FormError message={error} />
      {data && (
        <div className="flex flex-col gap-4">
          <div className="rounded-card bg-brand-ink p-3 text-sidebar-fg">
            {groups.map((g) => (
              <div key={g.key} className="mb-2">
                <p className="text-eyebrow uppercase text-sidebar-muted">
                  {t(`nav.groups.${g.key}`)}
                </p>
                <ul className="text-small">
                  {g.items.map((i) => (
                    <li key={i.key}>{t(`nav.items.${i.key}`)}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <p className="text-small text-fg-body">
            {t('roles.sensitiveAccess')}:{' '}
            {data.sensitive.length ? data.sensitive.join(', ') : t('roles.none')}
          </p>
        </div>
      )}
    </Dialog>
  );
}

export function RoleDetailPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const { can } = useAuth();
  const role = useRole(id);
  const catalog = useCatalog();
  const save = useSaveGrants(id);
  const update = useUpdateRole(id);
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [meta, setMeta] = useState<{
    name: string;
    description: string;
    requires_2fa: boolean;
  } | null>(null);
  const [preview, setPreview] = useState(false);
  const [saved, setSaved] = useState(false);
  const r = role.data;

  const initial = useMemo(() => {
    const m: Matrix = {};
    for (const g of r?.grants ?? []) m[`${g.module}.${g.action}`] = g.scope;
    return m;
  }, [r]);
  useEffect(() => {
    if (r) {
      setMatrix(initial);
      setMeta({ name: r.name, description: r.description, requires_2fa: r.requires_2fa });
    }
  }, [r, initial]);

  if (!r || !catalog.data || !matrix || !meta)
    return <p className="text-fg-secondary">{t('common.loading')}</p>;
  const editable = can('users', 'admin') && !r.locked;
  const dirty = JSON.stringify(matrix) !== JSON.stringify(initial);
  const set = (key: string, scope: string) => {
    setSaved(false);
    setMatrix((m) => ({ ...m!, [key]: scope }));
  };
  const grants = (): GrantRow[] =>
    Object.entries(matrix)
      .filter(([, s]) => s)
      .map(([k, scope]) => {
        const [module, action] = k.split('.') as [string, string];
        return { module, action, scope };
      });

  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/pengaturan/peran"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('roles.back')}
      </Link>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-section-title">{r.name}</CardTitle>
            <StatusPill tone={r.is_system ? 'neutral' : 'info'}>
              {r.is_system ? t('roles.system') : t('roles.custom')}
            </StatusPill>
            {!r.is_active && <StatusPill tone="neutral">{t('master.inactive')}</StatusPill>}
            {r.locked && <StatusPill tone="warning">{t('roles.locked')}</StatusPill>}
            <span className="text-small text-fg-secondary">
              {r.code} · {t('roles.userCount', { count: r.user_count })}
            </span>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FormError message={update.error instanceof ApiError ? update.error.message : null} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('roles.name')}>
              <Input
                value={meta.name}
                disabled={!editable}
                onChange={(e) => setMeta({ ...meta, name: e.target.value })}
              />
            </Field>
            <Field label={t('roles.description')}>
              <Input
                value={meta.description}
                disabled={!editable}
                onChange={(e) => setMeta({ ...meta, description: e.target.value })}
              />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-small font-semibold text-fg">
              <input
                type="checkbox"
                disabled={!editable}
                checked={meta.requires_2fa}
                onChange={(e) => setMeta({ ...meta, requires_2fa: e.target.checked })}
                className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
              />
              {t('roles.requires2fa')}
            </label>
            {editable && (
              <Button size="sm" variant="secondary" onClick={() => update.mutate(meta)}>
                {t('master.save')}
              </Button>
            )}
            {editable && !r.is_system && (
              <Button
                size="sm"
                variant={r.is_active ? 'destructive' : 'secondary'}
                onClick={() => update.mutate({ is_active: !r.is_active })}
              >
                {r.is_active ? t('users.actions.deactivate') : t('users.actions.activate')}
              </Button>
            )}
            {can('users', 'admin') && (
              <Button size="sm" variant="ghost" onClick={() => setPreview(true)}>
                <Icon name="visibility" /> {t('roles.viewAs')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('roles.matrix')}</CardTitle>
          <p className="text-small text-fg-secondary">{t('roles.matrixHelp')}</p>
        </CardHeader>
        <div className="w-full overflow-x-auto">
          <table className="w-full border-collapse text-table">
            <caption className="sr-only">{t('roles.matrix')}</caption>
            <thead className="bg-surface-muted">
              <tr>
                <th
                  scope="col"
                  className="sticky left-0 bg-surface-muted px-3 py-2 text-left text-small font-semibold text-fg-secondary"
                >
                  {t('roles.module')}
                </th>
                {catalog.data.actions.map((a) => (
                  <th
                    key={a.code}
                    scope="col"
                    className="px-1 py-2 text-center text-caption font-semibold text-fg-secondary"
                  >
                    {a.code}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {catalog.data.modules.map((m) => (
                <tr key={m.code} className="border-b border-border">
                  <th
                    scope="row"
                    className="sticky left-0 whitespace-nowrap bg-surface-raised px-3 py-1 text-left text-small font-medium text-fg"
                  >
                    {m.label}
                  </th>
                  {catalog.data.actions.map((a) => {
                    const key = `${m.code}.${a.code}`;
                    const value = matrix[key] ?? '';
                    return (
                      <td key={a.code} className="px-1 py-1 text-center">
                        <select
                          aria-label={`${m.label} – ${a.label}`}
                          value={value}
                          disabled={!editable}
                          onChange={(e) => set(key, e.target.value)}
                          className={cn(
                            'h-7 w-[4.5rem] rounded-control border text-caption',
                            value
                              ? 'border-border-strong bg-surface-raised font-semibold text-fg'
                              : 'border-border bg-surface-muted text-fg-muted',
                          )}
                        >
                          <option value="">–</option>
                          {catalog.data.scopes.map((s) => (
                            <option key={s} value={s}>
                              {t(`roles.scope.${s}`)}
                            </option>
                          ))}
                        </select>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <CardContent className="flex flex-col gap-3 pt-4">
          <fieldset disabled={!editable}>
            <legend className="mb-2 text-small font-semibold text-fg">
              {t('roles.sensitiveFields')}
            </legend>
            <div className="flex flex-wrap gap-4">
              {catalog.data.sensitive.map((f) => {
                const key = `${SENSITIVE}.${f.code}`;
                return (
                  <label key={f.code} className="flex items-center gap-2 text-small text-fg">
                    <input
                      type="checkbox"
                      checked={Boolean(matrix[key])}
                      onChange={(e) => set(key, e.target.checked ? 'all' : '')}
                      className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
                    />
                    {f.label}
                  </label>
                );
              })}
            </div>
          </fieldset>
          <FormError message={save.error instanceof ApiError ? save.error.message : null} />
          {saved && (
            <p
              role="status"
              className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
            >
              {t('roles.savedNow')}
            </p>
          )}
          {editable && (
            <Button
              variant="primary"
              className="self-start"
              disabled={!dirty || save.isPending}
              onClick={() => save.mutate(grants(), { onSuccess: () => setSaved(true) })}
            >
              {t('roles.savePermissions')}
            </Button>
          )}
        </CardContent>
      </Card>
      {preview && <PreviewDialog id={r.id} onClose={() => setPreview(false)} />}
    </div>
  );
}
