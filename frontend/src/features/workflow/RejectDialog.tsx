import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Textarea } from '@/components/ui/input';
import { FormError } from '@/features/auth/AuthLayout';

/** Reject needs a reason (returned to the requester). Also used for "withdraw". */
export function ReasonDialog({
  open,
  title,
  description,
  confirmLabel,
  required = true,
  onClose,
  onConfirm,
  busy,
  error,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  required?: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
  busy?: boolean;
  error?: string | null;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const missing = required && reason.trim() === '';

  const close = () => {
    setReason('');
    setTouched(false);
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={() => {
              setTouched(true);
              if (!missing) onConfirm(reason.trim());
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <FormError message={error} />
        <Field
          label={t('workflow.reason')}
          required={required}
          error={touched && missing ? t('workflow.reasonRequired') : undefined}
        >
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={4} />
        </Field>
      </div>
    </Dialog>
  );
}
