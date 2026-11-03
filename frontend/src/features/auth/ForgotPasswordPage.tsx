import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError, postJson } from '@/lib/api';
import { AuthLayout, FormError } from './AuthLayout';

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      setDone((await postJson<{ message: string }>('/auth/forgot-password', { email })).message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title={t('forgot.title')} subtitle={t('forgot.subtitle')}>
      {done ? (
        <div className="flex flex-col gap-4">
          <p
            role="status"
            className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
          >
            {done}
          </p>
          <Link to="/login" className="text-small font-semibold text-fg-accent underline">
            {t('forgot.back')}
          </Link>
        </div>
      ) : (
        <form noValidate className="flex flex-col gap-4" onSubmit={(e) => void submit(e)}>
          <FormError message={error} />
          <Field label={t('login.email')} required>
            <Input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Button
            type="submit"
            variant="primary"
            className="w-full"
            disabled={busy || !email.includes('@')}
          >
            {t('forgot.submit')}
          </Button>
          <Link to="/login" className="text-small font-semibold text-fg-accent underline">
            {t('forgot.back')}
          </Link>
        </form>
      )}
    </AuthLayout>
  );
}
