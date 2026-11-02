import { cn } from '@/lib/utils';

/** Material Symbols Outlined, weight 400. Decorative unless `label` is given. */
export function Icon({
  name,
  label,
  className,
}: {
  name: string;
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={cn('material-symbols-outlined', className)}
      aria-hidden={label ? undefined : true}
      role={label ? 'img' : undefined}
      aria-label={label}
    >
      {name}
    </span>
  );
}
