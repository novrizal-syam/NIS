import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

// Primary = gold fill with on-gold label; at most one primary button per view (BRAND.md).
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-control text-body font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 [&_.material-symbols-outlined]:text-[18px]',
  {
    variants: {
      variant: {
        primary: 'bg-brand-gold text-on-gold hover:bg-brand-gold/85',
        secondary: 'border border-border-strong bg-transparent text-fg hover:bg-surface-muted',
        ghost: 'bg-transparent text-fg hover:bg-surface-muted',
        destructive: 'border border-danger bg-transparent text-danger hover:bg-danger-tint',
        link: 'h-auto px-0 text-fg-accent underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 px-3 text-small',
        md: 'h-10 px-4',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, type, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp
        ref={ref}
        type={asChild ? undefined : (type ?? 'button')}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = 'Button';

export { buttonVariants };
