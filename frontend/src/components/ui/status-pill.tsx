import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

const pill = cva(
  'inline-flex items-center gap-1.5 whitespace-nowrap rounded-pill px-2.5 py-0.5 text-small font-semibold',
  {
    variants: {
      tone: {
        neutral: 'bg-surface-muted text-fg-secondary ring-1 ring-inset ring-border',
        success: 'bg-success-tint text-success',
        warning: 'bg-warning-tint text-warning',
        danger: 'bg-danger-tint text-danger',
        info: 'bg-info-tint text-info',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
);

export type StatusTone = NonNullable<VariantProps<typeof pill>['tone']>;

export function StatusPill({
  tone,
  className,
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof pill>) {
  return (
    <span className={cn(pill({ tone }), className)} {...props}>
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}
