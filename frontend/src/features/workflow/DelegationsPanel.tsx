import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input, Select } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError } from '@/lib/api';
import { formatDate } from '@/lib/format';
import {
  useCreateDelegation,
  useDelegations,
  useRevokeDelegation,
  useUserLookup,
  type UserLookup,
} from './api';

const todayIso = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

export function DelegationsPanel() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const list = useDelegations();
  const create = useCreateDelegation();
  const revoke = useRevokeDelegation();

  const [search, setSearch] = useState('');
  const [delegate, setDelegate] = useState<UserLookup | null>(null);
  const [role, setRole] = useState('');
  const [start, setStart] = useState(todayIso());
  const [end, setEnd] = useState(todayIso());
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const lookup = useUserLookup(delegate ? '' : search);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!delegate) return setError(t('workflow.delegation.pickDelegate'));
    if (reason.trim().length < 3) return setError(t('workflow.delegation.reasonRequired'));
    try {
      await create.mutateAsync({
        delegate_id: delegate.id,
        role_code: role || null,
        start_date: start,
        end_date: end,
        reason,
      });
      setDelegate(null);
      setSearch('');
      setReason('');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card>
        <CardHeader>
          <CardTitle>{t('workflow.delegation.new')}</CardTitle>
          <p className="text-small text-fg-secondary">{t('workflow.delegation.help')}</p>
        </CardHeader>
        <CardContent>
          <form noValidate onSubmit={(e) => void submit(e)} className="flex flex-col gap-3">
            <FormError message={error} />
            {delegate ? (
              <div className="flex items-center justify-between gap-2 rounded-control border border-border px-3 py-2">
                <span className="text-small">
                  <span className="font-semibold text-fg">{delegate.full_name}</span>
                  <span className="block text-fg-secondary">{delegate.email}</span>
                </span>
                <Button size="sm" variant="ghost" onClick={() => setDelegate(null)}>
                  {t('common.change')}
                </Button>
              </div>
            ) : (
              <div className="flex flex-col gap-1">
                <Field label={t('workflow.delegation.delegate')} required>
                  <Input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder={t('workflow.delegation.searchUser')}
                  />
                </Field>
                {(lookup.data ?? [])
                  .filter((u) => u.id !== me?.id)
                  .map((u) => (
                    <button
                      key={u.id}
                      type="button"
                      onClick={() => setDelegate(u)}
                      className="rounded-control px-3 py-1.5 text-left text-small hover:bg-surface-muted"
                    >
                      <span className="font-semibold text-fg">{u.full_name}</span> · {u.email}
                    </button>
                  ))}
              </div>
            )}
            <Field label={t('workflow.delegation.role')}>
              <Select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="">{t('workflow.delegation.allRoles')}</option>
                {me?.roles.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.name}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('workflow.delegation.start')} required>
                <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              </Field>
              <Field label={t('workflow.delegation.end')} required>
                <Input
                  type="date"
                  value={end}
                  min={start}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </Field>
            </div>
            <Field label={t('workflow.reason')} required>
              <Input value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Button type="submit" variant="secondary" disabled={create.isPending}>
              {t('workflow.delegation.save')}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <Table>
          <caption className="sr-only">{t('workflow.delegation.list')}</caption>
          <THead>
            <TR>
              <TH>{t('workflow.delegation.from')}</TH>
              <TH>{t('workflow.delegation.to')}</TH>
              <TH>{t('workflow.delegation.role')}</TH>
              <TH>{t('workflow.delegation.period')}</TH>
              <TH>{t('workflow.col.status')}</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {(list.data ?? []).length === 0 && (
              <TR>
                <TD colSpan={6} className="py-6 text-center text-fg-secondary">
                  {t('workflow.delegation.empty')}
                </TD>
              </TR>
            )}
            {list.data?.map((d) => (
              <TR key={d.id}>
                <TD>{d.delegator_name}</TD>
                <TD>{d.delegate_name}</TD>
                <TD>
                  {d.role_code
                    ? (me?.roles.find((r) => r.code === d.role_code)?.name ?? d.role_code)
                    : t('workflow.delegation.allRoles')}
                </TD>
                <TD className="whitespace-nowrap">
                  {formatDate(d.start_date)} – {formatDate(d.end_date)}
                </TD>
                <TD>
                  <StatusPill tone={d.active ? 'success' : 'neutral'}>
                    {d.active ? t('workflow.delegation.active') : t('workflow.delegation.inactive')}
                  </StatusPill>
                </TD>
                <TD className="text-right">
                  {d.can_revoke && (
                    <Button size="sm" variant="destructive" onClick={() => revoke.mutate(d.id)}>
                      {t('workflow.delegation.revoke')}
                    </Button>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </div>
  );
}
