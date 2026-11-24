import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cn } from '@/shared/utils/cn'

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  loading?: boolean
  fullWidth?: boolean
}

/**
 * The standard button.
 *
 * Geometry follows the Sentinel Telemetry Operator design system:
 * rectangular, 0px radius, 1px solid border. The heights are 36px
 * (standard) and the destructive action is a solid red block, because
 * "revoke session" and "isolate host" must never look like a default
 * action.
 *
 * It forwards its ref so a dialog can move focus onto it.
 */
const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary:
    'bg-primary text-on-primary border-primary hover:bg-secondary hover:border-secondary disabled:bg-degraded disabled:border-degraded disabled:text-text-muted',
  secondary:
    'bg-transparent text-text border-border-strong hover:bg-surface-raised hover:border-primary disabled:text-degraded disabled:border-border',
  danger:
    'bg-danger text-white border-danger hover:bg-danger/85 disabled:bg-degraded disabled:border-degraded disabled:text-text-muted',
  ghost:
    'bg-transparent text-text-muted border-transparent hover:bg-surface-raised hover:text-text disabled:text-degraded',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = 'primary',
      loading = false,
      fullWidth = false,
      className,
      children,
      disabled,
      type = 'button',
      ...rest
    },
    ref,
  ) {
    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        className={cn(
          'label-ops inline-flex items-center justify-center gap-2 border px-4 py-2 transition-colors disabled:cursor-not-allowed',
          VARIANT_CLASS[variant],
          fullWidth && 'w-full',
          className,
        )}
        {...rest}
      >
        {loading && (
          <span
            aria-hidden="true"
            className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
          />
        )}
        {children}
      </button>
    )
  },
)
