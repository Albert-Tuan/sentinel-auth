export interface SpinnerProps {
  label?: string
}

/**
 * The standard loading indicator.
 */
export function Spinner({ label = 'Đang tải...' }: SpinnerProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-2 text-sm text-text-muted"
    >
      <span
        aria-hidden="true"
        className="h-3 w-3 animate-spin rounded-full border-2 border-border border-t-primary"
      />
      <span>{label}</span>
    </div>
  )
}
