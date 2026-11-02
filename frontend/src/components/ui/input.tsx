import {
  forwardRef,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';
import { cn } from '@/lib/utils';

const field =
  'w-full rounded-control border border-border bg-surface-raised px-3 text-body text-fg placeholder:text-fg-muted hover:border-fg-muted disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-danger';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(field, 'h-10', className)} {...props} />
  ),
);
Input.displayName = 'Input';

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select ref={ref} className={cn(field, 'h-10 pr-8', className)} {...props} />
  ),
);
Select.displayName = 'Select';

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(field, 'min-h-20 py-2', className)} {...props} />
));
Textarea.displayName = 'Textarea';
