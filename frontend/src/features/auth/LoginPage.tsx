import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Navigate, useLocation } from 'react-router-dom';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { AuthLayout, FormError } from './AuthLayout';
import { useAuth } from './AuthProvider';

const schema = z.object({
  email: z.string().trim().min(1, 'login.emailRequired').email('login.emailInvalid'),
  password: z.string().min(1, 'login.passwordRequired'),
  totp: z.string().trim().optional(),
});
type LoginForm = z.infer<typeof schema>;

export function LoginPage() {
  const { t } = useTranslation();
  const { status, login } = useAuth();
  const location = useLocation();
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(schema) });

  if (status === 'authenticated') {
    const from = (location.state as { from?: string } | null)?.from ?? '/';
    return <Navigate to={from} replace />;
  }

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await login(values.email, values.password, needTotp ? values.totp : undefined);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'TOTP_REQUIRED') {
        setNeedTotp(true);
        return;
      }
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    }
  });

  const err = (key?: string) => (key ? t(key) : undefined);

  return (
    <AuthLayout title={t('login.title')} subtitle={t('login.subtitle')}>
      <form noValidate className="flex flex-col gap-4" onSubmit={onSubmit}>
        <FormError message={error} />
        <Field label={t('login.email')} error={err(errors.email?.message)} required>
          <Input type="email" autoComplete="username" {...register('email')} />
        </Field>
        <Field label={t('login.password')} error={err(errors.password?.message)} required>
          <Input type="password" autoComplete="current-password" {...register('password')} />
        </Field>
        {needTotp && (
          <Field label={t('login.totp')} hint={t('login.totpHint')} required>
            <Input
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              autoFocus
              {...register('totp')}
            />
          </Field>
        )}
        <Button type="submit" variant="primary" className="mt-2 w-full" disabled={isSubmitting}>
          {isSubmitting ? t('login.submitting') : t('login.submit')}
        </Button>
      </form>
    </AuthLayout>
  );
}
