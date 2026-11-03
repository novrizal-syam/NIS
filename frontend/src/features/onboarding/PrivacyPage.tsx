import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { AuthLayout, FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, api, postJson } from '@/lib/api';

export function PrivacyPage() {
  const { t } = useTranslation();
  const { reload } = useAuth();
  const navigate = useNavigate();
  const notice = useQuery({
    queryKey: ['privacy'],
    queryFn: () => api<{ version: string; text: string }>('/auth/privacy'),
  });
  const [read, setRead] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = async () => {
    if (!notice.data) return;
    setError(null);
    try {
      await postJson('/auth/privacy/accept', { version: notice.data.version });
      await reload();
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    }
  };

  return (
    <AuthLayout title={t('onboarding.privacyTitle')} subtitle={t('onboarding.privacySubtitle')}>
      <div className="flex flex-col gap-4">
        <FormError message={error} />
        <div
          tabIndex={0}
          role="document"
          aria-label={t('onboarding.privacyTitle')}
          className="max-h-80 overflow-y-auto whitespace-pre-line rounded-card border border-border bg-surface-muted p-4 text-small text-fg-body"
        >
          {notice.data?.text ?? t('common.loading')}
        </div>
        <p className="text-caption text-fg-muted">
          {t('onboarding.version')} {notice.data?.version}
        </p>
        <label className="flex items-center gap-2 text-small font-semibold text-fg">
          <input
            type="checkbox"
            checked={read}
            onChange={(e) => setRead(e.target.checked)}
            className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
          />
          {t('onboarding.privacyRead')}
        </label>
        <Button variant="primary" disabled={!read || !notice.data} onClick={() => void accept()}>
          {t('onboarding.agree')}
        </Button>
      </div>
    </AuthLayout>
  );
}
