import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

/** Shown exactly once after 2FA is enabled; the user must confirm they saved them. */
export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(false);
  const download = () => {
    const blob = new Blob([`${t('recovery.fileHeader')}\n\n${codes.join('\n')}\n`], {
      type: 'text/plain',
    });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'kode-pemulihan-nustrad-erp.txt';
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-fg-body">{t('recovery.help')}</p>
      <ol className="grid grid-cols-2 gap-2 rounded-card border border-border bg-surface-muted p-4 font-mono text-body text-fg">
        {codes.map((c) => (
          <li key={c} className="tabular-nums">
            {c}
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={download}>
          <Icon name="download" /> {t('recovery.download')}
        </Button>
        <Button
          variant="secondary"
          onClick={() => void navigator.clipboard?.writeText(codes.join('\n'))}
        >
          <Icon name="content_copy" /> {t('recovery.copy')}
        </Button>
      </div>
      <label className="flex items-center gap-2 text-small font-semibold text-fg">
        <input
          type="checkbox"
          checked={saved}
          onChange={(e) => setSaved(e.target.checked)}
          className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
        />
        {t('recovery.confirm')}
      </label>
      <Button variant="primary" disabled={!saved} onClick={onDone}>
        {t('recovery.continue')}
      </Button>
    </div>
  );
}
