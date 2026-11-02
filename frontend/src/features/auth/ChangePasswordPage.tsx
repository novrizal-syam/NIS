import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Navigate, useNavigate } from 'react-router-dom';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError, authApi } from '@/lib/api';
import { AuthLayout, FormError } from './AuthLayout';
import { useAuth } from './AuthProvider';

// Mirrors the backend policy (app/auth/security.validate_password_policy).
const schema = z
  .object({
    current: z.string().min(1, 'password.currentRequired'),
    next: z
      .string()
      .min(10, 'password.tooShort')
      .regex(/[A-Za-z]/, 'password.needsLetterDigit')
      .regex(/\d/, 'password.needsLetterDigit'),
    confirm: z.string(),
  })
  .refine((v) => v.next === v.confirm, { path: ['confirm'], message: 'password.mismatch' });
type Form = z.infer<typeof schema>;

export function ChangePasswordPage() {
  const { t } = useTranslation();
  const { me, acceptToken } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  const forced = me?.pending.includes('change_password') ?? false;
  if (!me) return <Navigate to="/login" replace />;

  const onSubmit = handleSubmit(async (v) => {
    setError(null);
    try {
      const out = await authApi.changePassword(v.current, v.next);
      await acceptToken(out.access_token);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    }
  });
  const err = (key?: string) => (key ? t(key) : undefined);

  return (
    <AuthLayout
      title={t('password.title')}
      subtitle={forced ? t('password.forcedSubtitle') : t('password.subtitle')}
    >
      <form noValidate className="flex flex-col gap-4" onSubmit={onSubmit}>
        <FormError message={error} />
        <Field label={t('password.current')} error={err(errors.current?.message)} required>
          <Input type="password" autoComplete="current-password" {...register('current')} />
        </Field>
        <Field
          label={t('password.new')}
          hint={t('password.policy')}
          error={err(errors.next?.message)}
          required
        >
          <Input type="password" autoComplete="new-password" {...register('next')} />
        </Field>
        <Field label={t('password.confirm')} error={err(errors.confirm?.message)} required>
          <Input type="password" autoComplete="new-password" {...register('confirm')} />
        </Field>
        <Button type="submit" variant="primary" className="mt-2 w-full" disabled={isSubmitting}>
          {t('password.submit')}
        </Button>
      </form>
    </AuthLayout>
  );
}
