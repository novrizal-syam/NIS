import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';

const schema = z.object({
  email: z.string().trim().min(1, 'login.emailRequired').email('login.emailInvalid'),
  password: z.string().min(1, 'login.passwordRequired'),
});
type LoginForm = z.infer<typeof schema>;

/** Placeholder: real authentication arrives in phase 01. */
export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({ resolver: zodResolver(schema) });

  const err = (key?: string) => (key ? t(key) : undefined);

  return (
    <div className="grid min-h-screen bg-surface lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <section className="flex flex-col justify-between bg-brand-ink p-8 text-sidebar-fg md:p-12">
        <img
          src="/brand/nustrad-logo-reverse.svg"
          alt="Nustrad"
          className="h-12 w-auto self-start md:h-14"
        />
        <p className="mt-10 font-heading text-section-title tracking-[0.18em] text-brand-gold lg:mt-0">
          {t('app.tagline')}
        </p>
      </section>

      <main className="flex items-center justify-center p-6 md:p-12">
        <div className="w-full max-w-sm">
          <p className="eyebrow">
            {t('login.tenant')} · {t('app.tenant')}
          </p>
          <h1 className="mt-2 text-page-title">{t('login.title')}</h1>
          <p className="mt-1 text-body text-fg-secondary">{t('login.subtitle')}</p>

          <form
            noValidate
            className="mt-6 flex flex-col gap-4"
            onSubmit={handleSubmit(() => navigate('/'))}
          >
            <Field label={t('login.email')} error={err(errors.email?.message)} required>
              <Input type="email" autoComplete="username" {...register('email')} />
            </Field>
            <Field label={t('login.password')} error={err(errors.password?.message)} required>
              <Input type="password" autoComplete="current-password" {...register('password')} />
            </Field>
            <Button type="submit" variant="primary" className="mt-2 w-full">
              {t('login.submit')}
            </Button>
          </form>
          <p className="mt-6 text-small text-fg-muted">{t('login.placeholderNote')}</p>
        </div>
      </main>
    </div>
  );
}
