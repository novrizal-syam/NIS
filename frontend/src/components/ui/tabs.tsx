import { cn } from '@/lib/utils';

export function Tabs<T extends string>({
  value,
  onChange,
  items,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  items: { value: T; label: string; badge?: number }[];
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 border-b border-border">
      {items.map((it) => (
        <button
          key={it.value}
          type="button"
          role="tab"
          aria-selected={value === it.value}
          onClick={() => onChange(it.value)}
          className={cn(
            '-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-small font-semibold',
            value === it.value
              ? 'border-brand-gold text-fg'
              : 'border-transparent text-fg-secondary hover:text-fg',
          )}
        >
          {it.label}
          {it.badge !== undefined && it.badge > 0 && (
            <span className="rounded-pill bg-brand-gold px-1.5 text-caption font-bold text-on-gold">
              {it.badge}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
