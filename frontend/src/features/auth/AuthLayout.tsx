import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

/** Split layout from BRAND.md: ink panel with reverse logo and tagline, form on white. */
export function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
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
          <h1 className="mt-2 text-page-title">{title}</h1>
          {subtitle && <p className="mt-1 text-body text-fg-secondary">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </main>
    </div>
  );
}

export function FormError({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="rounded-control border border-danger bg-danger-tint px-3 py-2 text-small font-medium text-danger"
    >
      {message}
    </p>
  );
}
