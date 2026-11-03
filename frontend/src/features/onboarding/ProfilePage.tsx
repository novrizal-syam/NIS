import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
import { AuthLayout, FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, api, fetchBlob } from '@/lib/api';

function ImageField({
  label,
  hint,
  attachmentId,
  userId,
  onUploaded,
}: {
  label: string;
  hint: string;
  attachmentId: string | null;
  userId: string;
  onUploaded: (id: string) => void;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!attachmentId) return;
    let made: string | null = null;
    void fetchBlob(`/attachments/${attachmentId}/content`).then((b) => {
      made = URL.createObjectURL(b);
      setUrl(made);
    });
    return () => {
      if (made) URL.revokeObjectURL(made);
    };
  }, [attachmentId]);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (!['image/jpeg', 'image/png'].includes(file.type))
      return setError(t('onboarding.imageOnly'));
    setBusy(true);
    try {
      const body = new FormData();
      body.append('entity_type', 'user_profile');
      body.append('entity_id', userId);
      body.append('file', file);
      onUploaded((await api<{ id: string }>('/attachments', { method: 'POST', body })).id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-small font-semibold text-fg">{label}</span>
      <div className="flex items-center gap-3">
        <div className="grid h-16 w-24 place-items-center overflow-hidden rounded-control border border-border bg-surface-muted">
          {url ? (
            <img src={url} alt={label} className="max-h-full max-w-full" />
          ) : (
            <Icon name="image" className="text-fg-muted" />
          )}
        </div>
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg"
          className="sr-only"
          aria-label={label}
          onChange={(e) => void upload(e.target.files?.[0])}
        />
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          <Icon name="upload" /> {t('onboarding.choose')}
        </Button>
      </div>
      <p className="text-caption text-fg-muted">{hint}</p>
      <FormError message={error} />
    </div>
  );
}

export function ProfilePage() {
  const { t } = useTranslation();
  const { me, reload } = useAuth();
  const navigate = useNavigate();
  const [phone, setPhone] = useState(me?.phone ?? '');
  const [photo, setPhoto] = useState<string | null>(me?.photo_attachment_id ?? null);
  const [signature, setSignature] = useState<string | null>(me?.signature_attachment_id ?? null);
  const [error, setError] = useState<string | null>(null);
  if (!me) return null;

  const save = async () => {
    setError(null);
    try {
      await api('/auth/profile', {
        method: 'PUT',
        body: JSON.stringify({
          phone,
          photo_attachment_id: photo,
          signature_attachment_id: signature,
        }),
      });
      await reload();
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    }
  };

  return (
    <AuthLayout title={t('onboarding.profileTitle')} subtitle={t('onboarding.profileSubtitle')}>
      <div className="flex flex-col gap-4">
        <FormError message={error} />
        <Field label={t('setup.phone')} hint={t('onboarding.phoneHint')} required>
          <Input
            type="tel"
            autoComplete="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </Field>
        <ImageField
          label={t('onboarding.photo')}
          hint={t('onboarding.photoHint')}
          attachmentId={photo}
          userId={me.id}
          onUploaded={setPhoto}
        />
        <ImageField
          label={t('onboarding.signature')}
          hint={t('onboarding.signatureHint')}
          attachmentId={signature}
          userId={me.id}
          onUploaded={setSignature}
        />
        <Button variant="primary" disabled={phone.trim().length < 8} onClick={() => void save()}>
          {t('onboarding.saveProfile')}
        </Button>
      </div>
    </AuthLayout>
  );
}
