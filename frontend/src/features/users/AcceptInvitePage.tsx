import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { AuthLayout, FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, postJson } from '@/lib/api';

/** /undangan/:token — the invited user chooses a password and is signed in. */
export function AcceptInvitePage() {
  const { t } = useTranslation();
  const { token = '' } = useParams();
  const { acceptToken } = useAuth();
  const navigate = useNavigate();
  const [pw, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (pw !== confirm) return setError(t('password.mismatch'));
    setBusy(true);
    try {
      const out = await postJson<{ access_token: string }>('/auth/invite/accept', {
        token,
        password: pw,
      });
      await acceptToken(out.access_token);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title={t('users.acceptTitle')} subtitle={t('users.acceptHelp')}>
      <form noValidate className="flex flex-col gap-4" onSubmit={(e) => void submit(e)}>
        <FormError message={error} />
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
        <Button type="submit" variant="primary" className="w-full" disabled={busy}>
          {t('users.acceptSubmit')}
        </Button>
      </form>
    </AuthLayout>
  );
}
