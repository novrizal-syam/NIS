import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError, postJson } from '@/lib/api';
import { AuthLayout, FormError } from './AuthLayout';

/** /reset-password?token=… from the email (60 minutes, single use). */
export function ResetPasswordPage() {
  const { t } = useTranslation();
  const [search] = useSearchParams();
  const token = search.get('token') ?? '';
  const [pw, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (pw !== confirm) return setError(t('password.mismatch'));
    try {
      await postJson('/auth/reset-password', { token, password: pw });
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    }
  };

  return (
    <AuthLayout title={t('reset.title')} subtitle={t('reset.subtitle')}>
      {done ? (
        <div className="flex flex-col gap-4">
          <p
            role="status"
            className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
          >
            {t('reset.done')}
          </p>
          <Link to="/login" className="text-small font-semibold text-fg-accent underline">
            {t('reset.toLogin')}
          </Link>
        </div>
      ) : (
        <form noValidate className="flex flex-col gap-4" onSubmit={(e) => void submit(e)}>
          <FormError message={!token ? t('reset.noToken') : error} />
          <Field label={t('password.new')} hint={t('password.policy')} required>
            <Input
              type="password"
              autoComplete="new-password"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
            />
          </Field>
          <Field label={t('password.confirm')} required>
            <Input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </Field>
          <Button type="submit" variant="primary" className="w-full" disabled={!token || !pw}>
            {t('reset.submit')}
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
