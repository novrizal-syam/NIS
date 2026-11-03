import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { Tabs } from '@/components/ui/tabs';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { useRoles } from '@/features/users/api';
import { ApiError, api, postJson } from '@/lib/api';
import { formatDateTime } from '@/lib/format';

interface Rule {
  id: string;
  role_a: string;
  role_b: string;
  role_a_name: string;
  role_b_name: string;
  description: string;
  is_active: boolean;
}
interface ExceptionRow {
  id: string;
  user_name: string;
  email: string;
  pairs: string[][];
  reason: string;
  status: 'pending' | 'approved' | 'rejected' | 'revoked';
  created_at: string;
  last_reviewed_at: string | null;
  review_note: string | null;
  request_id: string | null;
  doc_number: string | null;
}
interface Violation {
  user_id: string;
  full_name: string;
  email: string;
  pair: string[];
  description: string;
}

const TONE: Record<ExceptionRow['status'], StatusTone> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  revoked: 'neutral',
};
const OVERDUE_DAYS = 31;

export function SodPage() {
  const { t } = useTranslation();
  const { can, me } = useAuth();
  const qc = useQueryClient();
  const [tab, setTab] = useState<'register' | 'rules'>('register');
  const rules = useQuery({ queryKey: ['sod', 'rules'], queryFn: () => api<Rule[]>('/sod/rules') });
  const register = useQuery({
    queryKey: ['sod', 'register'],
    queryFn: () => api<{ exceptions: ExceptionRow[]; violations: Violation[] }>('/sod/register'),
  });
  const roles = useRoles();
  const refresh = () => qc.invalidateQueries({ queryKey: ['sod'] });
  const action = useMutation({
    mutationFn: (v: { path: string; body?: unknown; method?: string }) =>
      api(v.path, {
        method: v.method ?? 'POST',
        body: v.body === undefined ? undefined : JSON.stringify(v.body),
      }),
    onSuccess: refresh,
  });
  const addRule = useMutation({
    mutationFn: (v: object) => postJson('/sod/rules', v),
    onSuccess: refresh,
  });
  const [draft, setDraft] = useState({ role_a: '', role_b: '', description: '' });
  const isController = me?.roles.some((r) => r.code === 'lead_controller') ?? false;
  const name = (code: string) => roles.data?.find((r) => r.code === code)?.name ?? code;
  const overdue = (e: ExceptionRow) =>
    e.status === 'approved' &&
    (!e.last_reviewed_at ||
      Date.now() - new Date(e.last_reviewed_at).getTime() > OVERDUE_DAYS * 86_400_000);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-fg-secondary">{t('sod.intro')}</p>
      <Tabs
        label={t('sod.title')}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'register', label: t('sod.register'), badge: register.data?.violations.length },
          { value: 'rules', label: t('sod.rules') },
        ]}
      />
      <FormError message={action.error instanceof ApiError ? action.error.message : null} />

      {tab === 'register' && (
        <>
          {(register.data?.violations.length ?? 0) > 0 && (
            <Card className="border-danger">
              <div className="px-4 pt-3">
                <p className="flex items-center gap-2 text-small font-semibold text-danger">
                  <Icon name="gpp_bad" />{' '}
                  {t('sod.violations', { count: register.data!.violations.length })}
                </p>
              </div>
              <Table>
                <caption className="sr-only">{t('sod.violationsCaption')}</caption>
                <THead>
                  <TR>
                    <TH>{t('users.user')}</TH>
                    <TH>{t('sod.pair')}</TH>
                    <TH>{t('sod.why')}</TH>
                  </TR>
                </THead>
                <TBody>
                  {register.data!.violations.map((v) => (
                    <TR key={`${v.user_id}-${v.pair.join()}`}>
                      <TD>
                        {v.full_name}
                        <span className="block text-caption text-fg-muted">{v.email}</span>
                      </TD>
                      <TD>{v.pair.map(name).join(' + ')}</TD>
                      <TD>{v.description}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </Card>
          )}
          <Card>
            <Table>
              <caption className="sr-only">{t('sod.register')}</caption>
              <THead>
                <TR>
                  <TH>{t('users.user')}</TH>
                  <TH>{t('sod.pair')}</TH>
                  <TH>{t('workflow.reason')}</TH>
                  <TH>{t('master.status')}</TH>
                  <TH>{t('sod.reviewed')}</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {register.data?.exceptions.length === 0 && (
                  <TR>
                    <TD colSpan={6} className="py-6 text-center text-fg-secondary">
                      {t('sod.noExceptions')}
                    </TD>
                  </TR>
                )}
                {register.data?.exceptions.map((e) => (
                  <TR key={e.id}>
                    <TD>
                      {e.user_name}
                      <span className="block text-caption text-fg-muted">{e.email}</span>
                    </TD>
                    <TD>{e.pairs.map((p) => p.map(name).join(' + ')).join('; ')}</TD>
                    <TD className="min-w-48">
                      {e.reason}
                      {e.request_id && (
                        <Link
                          to={`/persetujuan/${e.request_id}`}
                          className="block text-caption font-semibold text-fg-accent underline"
                        >
                          {e.doc_number}
                        </Link>
                      )}
                    </TD>
                    <TD>
                      <StatusPill tone={TONE[e.status]}>{t(`sod.status.${e.status}`)}</StatusPill>
                    </TD>
                    <TD className="whitespace-nowrap">
                      {e.last_reviewed_at ? formatDateTime(e.last_reviewed_at) : '–'}
                      {overdue(e) && (
                        <StatusPill tone="danger" className="ml-1">
                          {t('sod.reviewDue')}
                        </StatusPill>
                      )}
                    </TD>
                    <TD className="whitespace-nowrap text-right">
                      {e.status === 'approved' && isController && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() =>
                            action.mutate({
                              path: `/sod/exceptions/${e.id}/review`,
                              body: { note: '' },
                            })
                          }
                        >
                          {t('sod.markReviewed')}
                        </Button>
                      )}
                      {e.status === 'approved' && can('users', 'admin') && (
                        <Button
                          size="sm"
                          variant="destructive"
                          className="ml-1"
                          onClick={() => action.mutate({ path: `/sod/exceptions/${e.id}/revoke` })}
                        >
                          {t('sod.revoke')}
                        </Button>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Card>
        </>
      )}

      {tab === 'rules' && (
        <>
          {can('users', 'admin') && (
            <Card className="p-4">
              <FormError
                message={addRule.error instanceof ApiError ? addRule.error.message : null}
              />
              <div className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_2fr_auto]">
                {(['role_a', 'role_b'] as const).map((k) => (
                  <Field key={k} label={t(`sod.${k}`)}>
                    <Select
                      value={draft[k]}
                      onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                    >
                      <option value="">{t('master.choose')}</option>
                      {roles.data?.map((r) => (
                        <option key={r.code} value={r.code}>
                          {r.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                ))}
                <Field label={t('sod.why')}>
                  <Input
                    value={draft.description}
                    onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  />
                </Field>
                <Button
                  variant="secondary"
                  disabled={!draft.role_a || !draft.role_b || draft.description.length < 5}
                  onClick={() =>
                    addRule.mutate(draft, {
                      onSuccess: () => setDraft({ role_a: '', role_b: '', description: '' }),
                    })
                  }
                >
                  <Icon name="add" /> {t('sod.addRule')}
                </Button>
              </div>
            </Card>
          )}
          <Card>
            <Table>
              <caption className="sr-only">{t('sod.rules')}</caption>
              <THead>
                <TR>
                  <TH>{t('sod.pair')}</TH>
                  <TH>{t('sod.why')}</TH>
                  <TH>{t('master.status')}</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {rules.data?.map((r) => (
                  <TR key={r.id}>
                    <TD className="font-semibold text-fg">
                      {r.role_a_name} + {r.role_b_name}
                    </TD>
                    <TD>{r.description}</TD>
                    <TD>
                      <StatusPill tone={r.is_active ? 'success' : 'neutral'}>
                        {r.is_active ? t('master.active') : t('master.inactive')}
                      </StatusPill>
                    </TD>
                    <TD className="text-right">
                      {can('users', 'admin') && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            action.mutate({
                              path: `/sod/rules/${r.id}`,
                              method: 'PATCH',
                              body: { is_active: !r.is_active },
                            })
                          }
                        >
                          {r.is_active
                            ? t('users.actions.deactivate')
                            : t('users.actions.activate')}
                        </Button>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Card>
        </>
      )}
    </div>
  );
}
