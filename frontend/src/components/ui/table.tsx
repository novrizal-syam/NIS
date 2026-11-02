import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn('w-full border-collapse text-table', className)} {...props} />
    </div>
  );
}

export function THead(props: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className="bg-surface-muted" {...props} />;
}

export function TBody(props: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...props} />;
}

export function TR({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn('border-b border-border last:border-0 hover:bg-surface-muted/60', className)}
      {...props}
    />
  );
}

/** `numeric` right-aligns with tabular numbers (BRAND.md · Type). */
export function TH({
  className,
  numeric,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <th
      scope="col"
      className={cn(
        'whitespace-nowrap border-b border-border px-3 py-2 text-left text-small font-semibold text-fg-secondary',
        numeric && 'num text-right',
        className,
      )}
      {...props}
    />
  );
}

export function TD({
  className,
  numeric,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <td
      className={cn('px-3 py-2 text-fg-body', numeric && 'num text-right tabular-nums', className)}
      {...props}
    />
  );
}
