import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { Tabs } from '@/components/ui/tabs';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { useOptions } from '@/features/master/api';
import { ApiError } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { RolePicker } from './RolePicker';
import { ActivationLink } from './ActivationLink';
import { EmailStatus } from './EmailStatus';
import { TempPassword } from './TempPassword';
import {
  useAddTemporaryRole,
  useCreateUser,
  useRoles,
  useUpdateUser,
  useUser,
  useUserAction,
  type UserAction,
} from './api';
import { StatusBadge } from './StatusBadge';

const err = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

function DeptEmployee({
  dept,
  emp,
  setDept,
  setEmp,
  disabled,
}: {
  dept: string;
  emp: string;
  setDept: (v: string) => void;
  setEmp: (v: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const depts = useOptions('departments');
  const emps = useOptions('employees');
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label={t('users.department')}>
        <Select value={dept} onChange={(e) => setDept(e.target.value)} disabled={disabled}>
          <option value="">{t('master.none')}</option>
          {depts.data?.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('users.employee')} hint={t('users.employeeHint')}>
        <Select value={emp} onChange={(e) => setEmp(e.target.value)} disabled={disabled}>
          <option value="">{t('master.none')}</option>
          {emps.data?.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}

export function InviteDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { me } = useAuth();
  const create = useCreateUser();
  const [v, setV] = useState({
    email: '',
    full_name: '',
    dept: '',
    emp: '',
    mode: 'invite' as 'invite' | 'password',
  });
  const [roles, setRoles] = useState<string[]>([]);
  const isSA = me?.roles.some((r) => r.code === 'super_admin') ?? false;
  const done = create.data;

  return (
    <Dialog
      open
      onClose={onClose}
      title={t('users.inviteTitle')}
      className="max-w-2xl"
      footer={
        done ? (
          <Button variant="secondary" onClick={onClose}>
            {t('common.close')}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              disabled={create.isPending || !v.email || !v.full_name || roles.length === 0}
              onClick={() =>
                create.mutate({
                  email: v.email,
                  full_name: v.full_name,
                  roles,
                  department_code: v.dept || null,
                  employee_code: v.emp || null,
                  mode: v.mode,
                })
              }
            >
              {v.mode === 'invite' ? t('users.sendInvite') : t('users.createWithPassword')}
            </Button>
          </>
        )
      }
    >
      {done ? (
        done.temporary_password ? (
          <TempPassword value={done.temporary_password} />
        ) : done.activation_link ? (
          <ActivationLink link={done.activation_link} />
        ) : (
          <p
            role="status"
            className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
          >
            {t('users.inviteSent', { email: v.email })}
          </p>
        )
      ) : (
        <div className="flex flex-col gap-4">
          <FormError message={err(create.error, t('auth.unexpected'))} />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('setup.adminName')} required>
              <Input
                value={v.full_name}
                onChange={(e) => setV({ ...v, full_name: e.target.value })}
              />
            </Field>
            <Field label={t('login.email')} required>
              <Input
                type="email"
                value={v.email}
                onChange={(e) => setV({ ...v, email: e.target.value })}
              />
            </Field>
          </div>
          <DeptEmployee
            dept={v.dept}
            emp={v.emp}
            setDept={(d) => setV({ ...v, dept: d })}
            setEmp={(x) => setV({ ...v, emp: x })}
          />
          <RolePicker value={roles} onChange={setRoles} canGrantSuperAdmin={isSA} />
          <fieldset className="flex flex-col gap-1">
            <legend className="mb-1 text-small font-semibold text-fg">{t('users.how')}</legend>
            {(['invite', 'password'] as const).map((m) => (
              <label key={m} className="flex items-center gap-2 text-small text-fg">
                <input
                  type="radio"
                  name="mode"
                  checked={v.mode === m}
                  onChange={() => setV({ ...v, mode: m })}
                  className="accent-[rgb(var(--brand-ink))]"
                />
                {t(`users.mode.${m}`)}
              </label>
            ))}
          </fieldset>
        </div>
      )}
    </Dialog>
  );
}

export function UserDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const { me, can } = useAuth();
  const user = useUser(id);
  const update = useUpdateUser(id);
  const action = useUserAction(id);
  const [tab, setTab] = useState<'profile' | 'roles' | 'sessions' | 'history'>('profile');
  const [draft, setDraft] = useState<{
    full_name: string;
    dept: string;
    emp: string;
    roles: string[];
  } | null>(null);
  const [temp, setTemp] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [sodConflict, setSodConflict] = useState(false);
  const [sodReason, setSodReason] = useState('');
  const u = user.data;
  const isSA = me?.roles.some((r) => r.code === 'super_admin') ?? false;
  useEffect(() => {
    if (u && !draft) {
      setDraft({
        full_name: u.full_name,
        dept: u.department_code ?? '',
        emp: u.employee_code ?? '',
        roles: u.roles,
      });
    }
  }, [u, draft]);
  const canEdit = can('users', 'edit');
  const canAdmin = can('users', 'admin');

  const run = (a: UserAction) =>
    action.mutate(a, {
      onSuccess: (res) => {
        if (res && 'temporary_password' in res && res.temporary_password)
          setTemp(res.temporary_password);
        setLink(res && 'activation_link' in res ? (res.activation_link ?? null) : null);
        setNotice(t(`users.done.${a}`));
      },
    });

  return (
    <Dialog
      open
      onClose={onClose}
      title={u ? u.full_name : t('common.loading')}
      description={u?.email}
      className="max-w-3xl"
    >
      {u && draft && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={u.status} />
            <StatusPill tone={u.totp_enabled ? 'success' : 'neutral'}>
              {u.totp_enabled ? t('users.totpOn') : t('users.totpOff')}
            </StatusPill>
            <span className="text-small text-fg-secondary">
              {t('users.lastLogin')}: {u.last_login_at ? formatDateTime(u.last_login_at) : '–'}
            </span>
            <span className="inline-flex items-center gap-1 text-small text-fg-secondary">
              {t('users.lastEmail')}: <EmailStatus value={u.last_email} withTime />
            </span>
          </div>
          <Tabs
            label={u.full_name}
            value={tab}
            onChange={setTab}
            items={[
              { value: 'profile', label: t('users.tabProfile') },
              { value: 'roles', label: t('users.roles') },
              { value: 'sessions', label: t('users.tabSessions'), badge: u.sessions.length },
              { value: 'history', label: t('master.tabHistory') },
            ]}
          />
          <FormError message={err(update.error ?? action.error, t('auth.unexpected'))} />
          {notice && !action.error && (
            <p
              role="status"
              className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
            >
              {notice}
            </p>
          )}
          {temp && <TempPassword value={temp} />}
          {link && <ActivationLink link={link} />}

          {tab === 'profile' && (
            <div className="flex flex-col gap-4">
              <Field label={t('setup.adminName')}>
                <Input
                  value={draft.full_name}
                  disabled={!canEdit}
                  onChange={(e) => setDraft({ ...draft, full_name: e.target.value })}
                />
              </Field>
              <DeptEmployee
                dept={draft.dept}
                emp={draft.emp}
                disabled={!canEdit}
                setDept={(d) => setDraft({ ...draft, dept: d })}
                setEmp={(x) => setDraft({ ...draft, emp: x })}
              />
              {canEdit && (
                <Button
                  variant="primary"
                  className="self-start"
                  disabled={update.isPending}
                  onClick={() =>
                    update.mutate(
                      {
                        full_name: draft.full_name,
                        department_code: draft.dept || null,
                        employee_code: draft.emp || null,
                      },
                      { onSuccess: () => setNotice(t('users.saved')) },
                    )
                  }
                >
                  {t('master.save')}
                </Button>
              )}
              {canAdmin && (
                <div className="flex flex-wrap gap-2 border-t border-border pt-3">
                  {u.status === 'invited' && (
                    <Button size="sm" variant="secondary" onClick={() => run('invite')}>
                      {t('users.actions.invite')}
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => run('reset-password')}>
                    {t('users.actions.reset-password')}
                  </Button>
                  {u.status === 'locked' && (
                    <Button size="sm" variant="secondary" onClick={() => run('unlock')}>
                      {t('users.actions.unlock')}
                    </Button>
                  )}
                  {u.totp_enabled && (
                    <Button size="sm" variant="secondary" onClick={() => run('reset-2fa')}>
                      {t('users.actions.reset-2fa')}
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => run('force-logout')}>
                    {t('users.actions.force-logout')}
                  </Button>
                  {u.status === 'inactive' ? (
                    <Button size="sm" variant="secondary" onClick={() => run('activate')}>
                      {t('users.actions.activate')}
                    </Button>
                  ) : (
                    <Button size="sm" variant="destructive" onClick={() => run('deactivate')}>
                      {t('users.actions.deactivate')}
                    </Button>
                  )}
                </div>
              )}
            </div>
          )}

          {tab === 'roles' && (
            <div className="flex flex-col gap-3">
              {u.assignments.some((a) => a.valid_until) && (
                <ul className="flex flex-col gap-1 rounded-control border border-border p-2 text-small">
                  {u.assignments
                    .filter((a) => a.valid_until)
                    .map((a) => (
                      <li key={a.code} className="flex flex-wrap items-center gap-2">
                        <StatusPill tone="info">{a.name}</StatusPill>
                        <span className="text-fg-secondary">
                          {a.valid_from &&
                            t('roles.since_label', { date: formatDateTime(a.valid_from) })}{' '}
                          {t('roles.until_label', { date: formatDateTime(a.valid_until!) })}
                          {a.reason && ` · ${a.reason}`}
                        </span>
                      </li>
                    ))}
                </ul>
              )}
              <RolePicker
                value={draft.roles}
                onChange={(r) => setDraft({ ...draft, roles: r })}
                canGrantSuperAdmin={isSA}
                disabled={!canEdit}
              />
              {sodConflict && (
                <Field label={t('workflow.reason')} hint={t('sod.conflictHelp')} required>
                  <Textarea
                    rows={2}
                    value={sodReason}
                    onChange={(e) => setSodReason(e.target.value)}
                  />
                </Field>
              )}
              {canEdit && (
                <Button
                  variant="primary"
                  className="self-start"
                  disabled={
                    update.isPending ||
                    draft.roles.length === 0 ||
                    (sodConflict && sodReason.trim().length < 10)
                  }
                  onClick={() =>
                    update.mutate(
                      { roles: draft.roles, ...(sodConflict ? { sod_reason: sodReason } : {}) },
                      {
                        onSuccess: (res) => {
                          setSodConflict(false);
                          setSodReason('');
                          setNotice(
                            'pending_approval' in res
                              ? t('sod.pending', { number: res.pending_approval })
                              : t('users.saved'),
                          );
                        },
                        onError: (e) => {
                          if (e instanceof ApiError && e.code === 'SOD_CONFLICT')
                            setSodConflict(true);
                        },
                      },
                    )
                  }
                >
                  {sodConflict ? t('sod.submitException') : t('users.saveRoles')}
                </Button>
              )}
            </div>
          )}

          {tab === 'roles' && canEdit && <TemporaryRoleForm userId={u.id} isSA={isSA} />}

          {tab === 'sessions' && (
            <ul className="flex flex-col gap-2">
              {u.sessions.length === 0 && (
                <li className="text-small text-fg-secondary">{t('users.noSessions')}</li>
              )}
              {u.sessions.map((s) => (
                <li
                  key={s.family_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-border px-3 py-2 text-small"
                >
                  <span>
                    <span className="block font-semibold text-fg">
                      {s.user_agent ?? t('users.unknownDevice')}
                    </span>
                    <span className="text-fg-secondary">
                      {s.ip ?? '–'} · {t('users.signedIn')} {formatDateTime(s.signed_in_at)} ·{' '}
                      {t('users.lastActive')} {formatDateTime(s.last_active_at)}
                    </span>
                  </span>
                  {canAdmin && (
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => action.mutate({ revoke: s.family_id })}
                    >
                      {t('users.endSession')}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {tab === 'history' && <HistoryPanel entityType="user" entityId={u.id} />}
        </div>
      )}
    </Dialog>
  );
}

function TemporaryRoleForm({ userId, isSA }: { userId: string; isSA: boolean }) {
  const { t } = useTranslation();
  const roles = useRoles();
  const add = useAddTemporaryRole(userId);
  const [v, setV] = useState({ role: '', from: '', until: '', reason: '' });
  const toIso = (d: string) => (d ? new Date(`${d}T00:00:00+07:00`).toISOString() : null);
  return (
    <fieldset className="flex flex-col gap-3 border-t border-border pt-3">
      <legend className="text-small font-semibold text-fg">{t('roles.temporary')}</legend>
      <p className="text-caption text-fg-muted">{t('roles.temporaryHelp')}</p>
      <FormError message={err(add.error, t('auth.unexpected'))} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t('users.role')}>
          <Select value={v.role} onChange={(e) => setV({ ...v, role: e.target.value })}>
            <option value="">{t('master.choose')}</option>
            {roles.data
              ?.filter((r) => r.is_active && (isSA || r.code !== 'super_admin'))
              .map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
          </Select>
        </Field>
        <Field label={t('roles.from')}>
          <Input
            type="date"
            value={v.from}
            onChange={(e) => setV({ ...v, from: e.target.value })}
          />
        </Field>
        <Field label={t('roles.until')} required>
          <Input
            type="date"
            value={v.until}
            onChange={(e) => setV({ ...v, until: e.target.value })}
          />
        </Field>
      </div>
      <Field label={t('workflow.reason')} required>
        <Input value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />
      </Field>
      <Button
        variant="secondary"
        className="self-start"
        disabled={!v.role || !v.until || v.reason.trim().length < 5 || add.isPending}
        onClick={() =>
          add.mutate(
            {
              role: v.role,
              valid_from: toIso(v.from),
              valid_until: toIso(v.until)!,
              reason: v.reason,
            },
            { onSuccess: () => setV({ role: '', from: '', until: '', reason: '' }) },
          )
        }
      >
        {t('roles.addTemporary')}
      </Button>
    </fieldset>
  );
}
