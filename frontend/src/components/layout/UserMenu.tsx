import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Icon } from '@/components/ui/icon';
import { LANGUAGES, type Language } from '@/i18n';
import { cn } from '@/lib/utils';
import { useTheme, type ThemeChoice } from '@/theme/ThemeProvider';

const THEMES: { value: ThemeChoice; key: string; icon: string }[] = [
  { value: 'light', key: 'topbar.themeLight', icon: 'light_mode' },
  { value: 'dark', key: 'topbar.themeDark', icon: 'dark_mode' },
  { value: 'system', key: 'topbar.themeSystem', icon: 'contrast' },
];

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; icon?: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-caption uppercase text-fg-muted">{label}</legend>
      <div className="grid auto-cols-fr grid-flow-col gap-1 rounded-control bg-surface-muted p-1">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={value === o.value}
            onClick={() => onChange(o.value)}
            className={cn(
              'flex h-8 items-center justify-center gap-1 rounded-control text-small font-medium',
              value === o.value
                ? 'bg-surface-raised text-fg ring-1 ring-border-strong'
                : 'text-fg-secondary hover:text-fg',
            )}
          >
            {o.icon && <Icon name={o.icon} className="text-[16px]" />}
            {o.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export function UserMenu() {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-label={t('topbar.userMenu')}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="flex h-10 items-center gap-2 rounded-control px-1.5 hover:bg-surface-muted"
      >
        <span className="grid h-8 w-8 place-items-center rounded-full bg-brand-ink ring-1 ring-border">
          <img src="/brand/nustrad-monogram-gold.svg" alt="" className="h-5 w-5" />
        </span>
        <span className="hidden text-left md:block">
          <span className="block text-small font-semibold text-fg">{t('topbar.demoUser')}</span>
          <span className="block text-caption text-fg-muted">{t('topbar.demoRole')}</span>
        </span>
        <Icon name="expand_more" className="hidden text-fg-muted md:inline" />
      </button>

      {open && (
        <div
          id={panelId}
          className="absolute right-0 z-30 mt-2 w-72 rounded-card border border-border bg-surface-raised p-4 shadow-lg"
        >
          <div className="mb-4">
            <p className="text-body font-semibold text-fg">{t('topbar.demoUser')}</p>
            <p className="text-small text-fg-secondary">
              {t('topbar.role')}: {t('topbar.demoRole')}
            </p>
            <p className="mt-1 text-caption text-fg-muted">{t('topbar.roleSwitchHint')}</p>
          </div>
          <div className="flex flex-col gap-4">
            <Segmented
              label={t('topbar.theme')}
              value={theme}
              onChange={setTheme}
              options={THEMES.map((o) => ({ value: o.value, label: t(o.key), icon: o.icon }))}
            />
            <Segmented<Language>
              label={t('topbar.language')}
              value={(i18n.resolvedLanguage as Language) ?? 'id'}
              onChange={(lng) => void i18n.changeLanguage(lng)}
              options={LANGUAGES.map((l) => ({ value: l, label: l.toUpperCase() }))}
            />
            <button
              type="button"
              onClick={() => navigate('/login')}
              className="flex h-9 items-center gap-2 rounded-control px-2 text-small font-medium text-fg hover:bg-surface-muted"
            >
              <Icon name="logout" />
              {t('topbar.signOut')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
