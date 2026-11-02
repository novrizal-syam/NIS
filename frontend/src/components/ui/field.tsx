import { useId, type ReactElement, cloneElement } from 'react';
import { cn } from '@/lib/utils';

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  className?: string;
  children: ReactElement<Record<string, unknown>>;
}

/** Label + control + hint/error, wired with aria attributes. */
export function Field({ label, hint, error, required, className, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <label htmlFor={id} className="text-small font-semibold text-fg">
        {label}
        {required && (
          <span aria-hidden="true" className="ml-0.5 text-danger">
            *
          </span>
        )}
      </label>
      {cloneElement(children, {
        id,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : undefined,
        'aria-required': required || undefined,
      })}
      {hint && !error && (
        <p id={hintId} className="text-small text-fg-secondary">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-small font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
