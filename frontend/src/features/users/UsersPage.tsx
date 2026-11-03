import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, downloadFile } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useImportUsers, useRoles, useUsers, type UserStatus } from './api';
import { ActivationLink } from './ActivationLink';
import { EmailStatus } from './EmailStatus';
import { StatusBadge } from './StatusBadge';
import { InviteDialog, UserDialog } from './UserDialogs';

const STATUSES: UserStatus[] = ['active', 'invited', 'locked', 'inactive'];
const TEMPLATE =
  '﻿email;full_name;roles;department_code;employee_code\nnama@gek.co.id;Nama Lengkap;engineer|procurement_officer;OPS;\n';

function ImportUsersDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const run = useImportUsers();
  const [file, setFile] = useState<File | null>(null);
  const template = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([TEMPLATE], { type: 'text/csv' }));
    a.download = 'template-pengguna.csv';
    a.click();
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('users.importTitle')}
      description={t('users.importHelp')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.close')}
          </Button>
          <Button
            variant="primary"
            disabled={!file || run.isPending}
            onClick={() => file && run.mutate(file)}
          >
            {t('master.importRun')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Button variant="secondary" className="self-start" onClick={template}>
          <Icon name="download" /> {t('master.template')}
        </Button>
        <label className="flex flex-col gap-1.5 text-small font-semibold text-fg">
          {t('users.importFile')}
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-small text-fg-body"
          />
        </label>
        <FormError message={run.error instanceof ApiError ? run.error.message : null} />
        {run.data?.ok && (
          <p
            role="status"
            className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
          >
            {t('users.importDone', { count: run.data.created })}
          </p>
        )}
        {run.data?.activation_links?.map((l) => (
          <div key={l.email} className="flex flex-col gap-1">
            <span className="text-small font-semibold text-fg">{l.email}</span>
            <ActivationLink link={l.activation_link} />
          </div>
        ))}
        {run.data && !run.data.ok && (
          <>
            <FormError message={t('master.importFailed', { count: run.data.errors.length })} />
            <ul className="max-h-48 overflow-auto text-small">
              {run.data.errors.map((e, i) => (
                <li key={i}>
                  {t('master.row')} {e.row}: {e.field ? `${e.field} – ` : ''}
                  {e.message}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Dialog>
  );
}

export function UsersPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const roles = useRoles();
  const [q, setQ] = useState('');
  const [role, setRole] = useState('');
  const [status, setStatus] = useState<UserStatus | ''>('');
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [importing, setImporting] = useState(false);
  const users = useUsers({ q, role, status, page });
  const data = users.data;

  return (
    <div className="flex flex-col gap-4">
      {data?.active_super_admins === 1 && (
        <p
          role="note"
          className="flex items-start gap-2 rounded-control border border-warning bg-warning-tint px-3 py-2 text-small text-warning"
        >
          <Icon name="warning" /> {t('users.oneSuperAdmin')}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={status === s}
            onClick={() => {
              setStatus(status === s ? '' : s);
              setPage(1);
            }}
            className={cn(
              'rounded-card border bg-surface-raised px-3 py-2 text-left',
              status === s ? 'border-border-strong' : 'border-border',
            )}
          >
            <span className="block text-caption uppercase text-fg-muted">
              {t(`users.status.${s}`)}
            </span>
            <span className="font-heading text-section-title tabular-nums text-fg">
              {data?.counts[s] ?? '–'}
            </span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('users.searchPlaceholder')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        <Field label={t('users.role')} className="w-full sm:w-56">
          <Select
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t('master.all')}</option>
            {roles.data?.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </Select>
        </Field>
        {can('users', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile('/users/export', 'pengguna.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
        {can('users', 'create') && (
          <>
            <Button variant="secondary" onClick={() => setImporting(true)}>
              <Icon name="upload" /> {t('users.import')}
            </Button>
            <Button variant="primary" onClick={() => setInviting(true)}>
              <Icon name="person_add" /> {t('users.invite')}
            </Button>
          </>
        )}
      </div>

      <Card>
        <Table>
          <caption className="sr-only">{t('users.caption')}</caption>
          <THead>
            <TR>
              <TH>{t('users.user')}</TH>
              <TH>{t('users.roles')}</TH>
              <TH>{t('users.department')}</TH>
              <TH>{t('master.status')}</TH>
              <TH>2FA</TH>
              <TH>{t('users.lastLogin')}</TH>
              <TH>{t('users.lastEmail')}</TH>
            </TR>
          </THead>
          <TBody>
            {data?.items.length === 0 && (
              <TR>
                <TD colSpan={7} className="py-8 text-center text-fg-secondary">
                  {t('users.empty')}
                </TD>
              </TR>
            )}
            {data?.items.map((u) => (
              <TR key={u.id}>
                <TD className="min-w-48">
                  <button
                    type="button"
                    onClick={() => setOpen(u.id)}
                    className="text-left font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {u.full_name}
                  </button>
                  <span className="block text-caption text-fg-muted">
                    {u.email}
                    {u.is_demo && ` · ${t('master.demo')}`}
                  </span>
                </TD>
                <TD className="min-w-48">{u.role_names.join(', ')}</TD>
                <TD>{u.department_code ?? '–'}</TD>
                <TD>
                  <StatusBadge status={u.status} />
                </TD>
                <TD>{u.totp_enabled ? t('master.yes') : t('master.no')}</TD>
                <TD className="whitespace-nowrap">
                  {u.last_login_at ? formatDateTime(u.last_login_at) : '–'}
                </TD>
                <TD>
                  <EmailStatus value={u.last_email} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
      </Card>

      {open && <UserDialog id={open} onClose={() => setOpen(null)} />}
      {inviting && <InviteDialog onClose={() => setInviting(false)} />}
      {importing && <ImportUsersDialog onClose={() => setImporting(false)} />}
    </div>
  );
}
