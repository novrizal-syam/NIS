import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Icon } from '@/components/ui/icon';
import { FormError } from '@/features/auth/AuthLayout';
import { ApiError, downloadFile, fetchBlob } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import {
  ACCEPT,
  MAX_BYTES,
  useArchive,
  useAttachments,
  useUpload,
  useVersions,
  type Attachment,
} from './api';

const sizeText = (n: number) =>
  n >= 1024 * 1024
    ? `${(n / 1024 / 1024).toLocaleString('id-ID', { maximumFractionDigits: 1 })} MB`
    : `${Math.max(1, Math.round(n / 1024)).toLocaleString('id-ID')} KB`;

function Preview({ att, onClose }: { att: Attachment; onClose: () => void }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const versions = useVersions(att.id);

  useEffect(() => {
    let revoke: string | null = null;
    fetchBlob(`/attachments/${att.id}/content`)
      .then((blob) => {
        revoke = URL.createObjectURL(blob);
        setUrl(revoke);
      })
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : t('auth.unexpected')),
      );
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [att.id, t]);

  return (
    <Dialog
      open
      onClose={onClose}
      title={att.filename}
      description={t('dms.versionOf', { v: att.version, n: att.versions })}
      className="max-w-4xl"
    >
      <div className="flex flex-col gap-3">
        <FormError message={error} />
        {url &&
          (att.content_type === 'application/pdf' ? (
            <iframe
              src={url}
              title={att.filename}
              className="h-[65vh] w-full rounded-control border border-border"
            />
          ) : (
            <img src={url} alt={att.filename} className="mx-auto max-h-[65vh] rounded-control" />
          ))}
        {(versions.data?.length ?? 0) > 1 && (
          <div>
            <p className="eyebrow mb-1">{t('dms.versions')}</p>
            <ul className="flex flex-col gap-1 text-small">
              {versions.data?.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-fg">v{v.version}</span>
                  <span className="text-fg-secondary">
                    {v.uploaded_by} · {formatDateTime(v.uploaded_at)} · {sizeText(v.size)}
                  </span>
                  <Button
                    size="sm"
                    variant="link"
                    onClick={() =>
                      void downloadFile(`/attachments/${v.id}/content?download=true`, v.filename)
                    }
                  >
                    {t('dms.download')}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Dialog>
  );
}

/** Attachments (PDF/JPG/PNG ≤ 20 MB, versioned) on any record. */
export function AttachmentsPanel({
  entityType,
  entityId,
  canWrite,
}: {
  entityType: string;
  entityId: string;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const list = useAttachments(entityType, entityId);
  const upload = useUpload(entityType, entityId);
  const archive = useArchive();
  const input = useRef<HTMLInputElement>(null);
  const [replaces, setReplaces] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Attachment | null>(null);

  const pick = (group?: string) => {
    setReplaces(group);
    input.current?.click();
  };
  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (file.size > MAX_BYTES) return setError(t('dms.tooLarge'));
    try {
      await upload.mutateAsync({ file, replaces });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    } finally {
      if (input.current) input.current.value = '';
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        aria-label={t('dms.chooseFile')}
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      <FormError message={error} />
      {canWrite && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" disabled={upload.isPending} onClick={() => pick()}>
            <Icon name="attach_file" /> {upload.isPending ? t('dms.uploading') : t('dms.upload')}
          </Button>
          <span className="text-caption text-fg-muted">{t('dms.rules')}</span>
        </div>
      )}
      {list.data?.length === 0 && <p className="text-small text-fg-secondary">{t('dms.empty')}</p>}
      <ul className="flex flex-col gap-2">
        {list.data?.map((a) => (
          <li
            key={a.id}
            className="flex flex-wrap items-center gap-3 rounded-control border border-border px-3 py-2"
          >
            <Icon
              name={a.content_type === 'application/pdf' ? 'picture_as_pdf' : 'image'}
              className="text-fg-secondary"
            />
            <div className="min-w-0 flex-1">
              <button
                type="button"
                onClick={() => setPreview(a)}
                className="block max-w-full truncate text-left text-small font-semibold text-fg hover:underline"
              >
                {a.filename}
              </button>
              <span className="text-caption text-fg-muted">
                v{a.version} · {sizeText(a.size)} · {a.uploaded_by} ·{' '}
                {formatDateTime(a.uploaded_at)}
              </span>
            </div>
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="ghost"
                aria-label={t('dms.downloadFile', { name: a.filename })}
                onClick={() =>
                  void downloadFile(`/attachments/${a.id}/content?download=true`, a.filename)
                }
              >
                <Icon name="download" />
              </Button>
              {canWrite && (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('dms.newVersionOf', { name: a.filename })}
                    onClick={() => pick(a.group_id)}
                  >
                    <Icon name="upload_file" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('dms.archiveFile', { name: a.filename })}
                    onClick={() => archive.mutate(a.id)}
                  >
                    <Icon name="archive" />
                  </Button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
      {preview && <Preview att={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}
