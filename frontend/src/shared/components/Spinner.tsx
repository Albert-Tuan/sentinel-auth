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
      className="flex items-center gap-2 text-sm text-slate-500"
    >
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600"
      />
      <span>{label}</span>
    </div>
  )
}
