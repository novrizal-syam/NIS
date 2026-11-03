import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { useRoles } from '@/features/users/api';
import { ApiError } from '@/lib/api';
import { useCreateRole } from './api';

function NewRoleDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const roles = useRoles();
  const create = useCreateRole();
  const navigate = useNavigate();
  const [v, setV] = useState({
    code: '',
    name: '',
    description: '',
    requires_2fa: false,
    clone_from: '',
  });
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('roles.newTitle')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={create.isPending || !v.code || !v.name}
            onClick={() =>
              create.mutate(
                { ...v, clone_from: v.clone_from || null },
                { onSuccess: (r) => navigate(`/pengaturan/peran/${r.id}`) },
              )
            }
          >
            {t('roles.create')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FormError message={create.error instanceof ApiError ? create.error.message : null} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('roles.code')} hint={t('roles.codeHint')} required>
            <Input
              value={v.code}
              onChange={(e) => setV({ ...v, code: e.target.value.toLowerCase() })}
            />
          </Field>
          <Field label={t('roles.name')} required>
            <Input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
          </Field>
        </div>
        <Field label={t('roles.description')}>
          <Input
            value={v.description}
            onChange={(e) => setV({ ...v, description: e.target.value })}
          />
        </Field>
        <Field label={t('roles.cloneFrom')} hint={t('roles.cloneHint')}>
          <Select value={v.clone_from} onChange={(e) => setV({ ...v, clone_from: e.target.value })}>
            <option value="">{t('roles.empty')}</option>
            {roles.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </Select>
        </Field>
        <label className="flex items-center gap-2 text-small font-semibold text-fg">
          <input
            type="checkbox"
            checked={v.requires_2fa}
            onChange={(e) => setV({ ...v, requires_2fa: e.target.checked })}
            className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
          />
          {t('roles.requires2fa')}
        </label>
      </div>
    </Dialog>
  );
}

export function RolesPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const roles = useRoles();
  const [creating, setCreating] = useState(false);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-body text-fg-secondary">{t('roles.intro')}</p>
        {can('users', 'admin') && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Icon name="add" /> {t('roles.newTitle')}
          </Button>
        )}
      </div>
      <Card>
        <Table>
          <caption className="sr-only">{t('roles.caption')}</caption>
          <THead>
            <TR>
              <TH>{t('roles.name')}</TH>
              <TH>{t('roles.type')}</TH>
              <TH>2FA</TH>
              <TH numeric>{t('roles.users')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {roles.data?.map((r) => (
              <TR key={r.id}>
                <TD>
                  <Link
                    to={`/pengaturan/peran/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.name}
                  </Link>
                  <span className="block text-caption text-fg-muted">{r.code}</span>
                </TD>
                <TD>
                  <StatusPill tone={r.is_system ? 'neutral' : 'info'}>
                    {r.is_system ? t('roles.system') : t('roles.custom')}
                  </StatusPill>
                  {r.is_external && (
                    <span className="ml-2 text-caption text-fg-muted">{t('roles.external')}</span>
                  )}
                </TD>
                <TD>{r.requires_2fa ? t('master.yes') : t('master.no')}</TD>
                <TD numeric>{r.user_count}</TD>
                <TD>
                  <StatusPill tone={r.is_active ? 'success' : 'neutral'}>
                    {r.is_active ? t('master.active') : t('master.inactive')}
                  </StatusPill>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
      {creating && <NewRoleDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
