import { useTranslation } from 'react-i18next';
import { useRoles } from './api';

/** Checkbox list of active roles; Super Admin only selectable by Super Admins. */
export function RolePicker({
  value,
  onChange,
  canGrantSuperAdmin,
  disabled,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  canGrantSuperAdmin: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const roles = useRoles();
  const toggle = (code: string) =>
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code]);
  return (
    <fieldset disabled={disabled}>
      <legend className="mb-2 text-small font-semibold text-fg">{t('users.roles')}</legend>
      <div className="grid max-h-64 gap-1 overflow-y-auto rounded-control border border-border p-2 sm:grid-cols-2">
        {roles.data
          ?.filter((r) => r.is_active)
          .map((r) => (
            <label
              key={r.code}
              className="flex items-center gap-2 rounded-control px-2 py-1 text-small hover:bg-surface-muted"
            >
              <input
                type="checkbox"
                checked={value.includes(r.code)}
                disabled={r.code === 'super_admin' && !canGrantSuperAdmin}
                onChange={() => toggle(r.code)}
                className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
              />
              <span className="text-fg">{r.name}</span>
              {r.requires_2fa && <span className="text-caption text-fg-muted">2FA</span>}
            </label>
          ))}
      </div>
    </fieldset>
  );
}
