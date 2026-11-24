import type { ReactNode } from 'react'

export interface EmptyStateProps {
  title: string
  description?: string
  action?: ReactNode
}

/**
 * The standard empty-state panel.
 *
 * A dashed 1px border on the sunken canvas, centred copy. The design
 * system reserves it for "there is genuinely nothing here" — never for
 * an error (that is `ErrorState`) and never for a degraded source (that
 * carries its own amber banner).
 */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="border border-dashed border-border bg-surface-sunken p-8 text-center">
      <p className="heading-ops text-text-muted">{title}</p>
      {description && (
        <p className="mt-1 text-sm text-degraded">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
