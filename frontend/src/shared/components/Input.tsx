import { useId, type InputHTMLAttributes } from 'react'
import { cn } from '@/shared/utils/cn'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  /** Validation message rendered under the field. */
  error?: string
  hint?: string
}

/**
 * A single-line field.
 *
 * The design system puts the label OUTSIDE and ABOVE the control, in
 * uppercase with wide tracking, and gives the input a recessed surface
 * (`--color-surface-sunken`) so it reads as a hole in the panel rather
 * than a raised card.
 */
export function Input({ label, error, hint, className, id, ...rest }: InputProps) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const errorId = `${inputId}-error`
  const hintId = `${inputId}-hint`

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label htmlFor={inputId} className="label-ops text-text-muted">
          {label}
        </label>
      )}
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : hint ? hintId : undefined}
        className={cn(
          'telemetry w-full border bg-surface-sunken px-3 py-2 text-sm text-text outline-none placeholder:text-degraded focus:border-primary disabled:text-degraded',
          error ? 'border-danger' : 'border-border',
          className,
        )}
        {...rest}
      />
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
}
