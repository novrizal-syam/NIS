import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, api, postJson } from '@/lib/api';

interface DemoStatus {
  present: boolean;
  counts: Record<string, number>;
}

const CONFIRM_WORD = 'HAPUS';

interface TestResult {
  status: 'sent' | 'failed' | 'not_configured';
  error: string | null;
  to: string;
}

/** Super Admin: check the email configuration by sending a message to themselves. */
function EmailCard() {
  const { t } = useTranslation();
  const status = useQuery({
    queryKey: ['admin', 'email'],
    queryFn: () => api<{ provider: string | null }>('/admin/email/status'),
  });
  const test = useMutation({ mutationFn: () => postJson<TestResult>('/admin/email/test') });
  const r = test.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('settings.emailTitle')}</CardTitle>
        <CardDescription>{t('settings.emailHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-body text-fg-body">
          {t('settings.emailProvider')}:{' '}
          <span className="font-semibold text-fg">
            {status.data ? (status.data.provider ?? t('settings.emailNone')) : '…'}
          </span>
        </p>
        <FormError message={test.error instanceof ApiError ? test.error.message : null} />
        {r && (
          <p
            role="status"
            className={
              r.status === 'sent'
                ? 'rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success'
                : 'rounded-control bg-warning-tint px-3 py-2 text-small font-medium text-warning'
            }
          >
            {t('settings.emailResult', { to: r.to, status: t(`email.status.${r.status}`) })}
            {r.error ? ` – ${r.error}` : ''}
          </p>
        )}
        <Button
          variant="secondary"
          className="self-start"
          disabled={test.isPending}
          onClick={() => test.mutate()}
        >
          <Icon name="send" /> {t('settings.emailTest')}
        </Button>
      </CardContent>
    </Card>
  );
}

/** Settings. More sections arrive with phase 01a; demo removal is Super Admin only. */
export function SettingsPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const isSuperAdmin = me?.roles.some((r) => r.code === 'super_admin') ?? false;
  const status = useQuery({
    queryKey: ['admin', 'demo'],
    queryFn: () => api<DemoStatus>('/admin/demo'),
    enabled: isSuperAdmin,
  });
  const remove = useMutation({
    mutationFn: () => postJson<{ removed: Record<string, number> }>('/admin/demo/remove'),
    onSuccess: () => qc.invalidateQueries(),
  });
  const [confirming, setConfirming] = useState(false);
  const [word, setWord] = useState('');

  if (!isSuperAdmin) return <p className="text-body text-fg-secondary">{t('settings.more')}</p>;
  const total = Object.values(status.data?.counts ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <EmailCard />
      <Card>
        <CardHeader>
          <CardTitle>{t('settings.demoTitle')}</CardTitle>
          <CardDescription>{t('settings.demoHelp')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {remove.data && (
            <p
              role="status"
              className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
            >
              {t('settings.demoRemoved', {
                count: Object.values(remove.data.removed).reduce((a, b) => a + b, 0),
              })}
            </p>
          )}
          {status.data && (
            <p className="text-body text-fg-body">
              {status.data.present
                ? t('settings.demoPresent', { count: total })
                : t('settings.demoNone')}
            </p>
          )}
          {status.data?.present && (
            <ul className="grid grid-cols-2 gap-x-6 text-small text-fg-secondary sm:grid-cols-3">
              {Object.entries(status.data.counts)
                .filter(([, n]) => n > 0)
                .map(([table, n]) => (
                  <li key={table} className="flex justify-between gap-2">
                    <span>{table}</span>
                    <span className="tabular-nums text-fg">{n}</span>
                  </li>
                ))}
            </ul>
          )}
          <Button
            variant="destructive"
            className="self-start"
            disabled={!status.data?.present}
            onClick={() => setConfirming(true)}
          >
            <Icon name="delete_forever" /> {t('settings.demoRemove')}
          </Button>
        </CardContent>
      </Card>

      <Dialog
        open={confirming}
        onClose={() => {
          setConfirming(false);
          setWord('');
          remove.reset();
        }}
        title={t('settings.demoConfirmTitle')}
        description={t('settings.demoConfirmHelp', { word: CONFIRM_WORD })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={word !== CONFIRM_WORD || remove.isPending}
              onClick={() =>
                remove.mutate(undefined, {
                  onSuccess: () => {
                    setConfirming(false);
                    setWord('');
                  },
                })
              }
            >
              {t('settings.demoRemove')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <FormError message={remove.error instanceof ApiError ? remove.error.message : null} />
          <Field label={t('settings.demoConfirmLabel', { word: CONFIRM_WORD })} required>
            <Input value={word} onChange={(e) => setWord(e.target.value)} autoComplete="off" />
          </Field>
        </div>
      </Dialog>
    </div>
  );
}
