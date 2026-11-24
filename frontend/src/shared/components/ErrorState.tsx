import type { ReactNode } from 'react'

export interface ErrorStateProps {
  title?: string
  message: string
  action?: ReactNode
}

/**
 * The standard error panel.
 *
 * The design system gives an error a RED LEFT BORDER rather than a red
 * fill: the operator must be able to read the message, and a saturated
 * background would fight the text.
 *
 * The message must already be safe to display — pass `ApiError.userMessage`,
 * never a raw backend payload.
 */
export function ErrorState({
  title = 'Không thể tải dữ liệu',
  message,
  action,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="border border-l-4 border-border border-l-danger bg-surface-raised p-4 text-sm text-text"
    >
      <p className="heading-ops text-danger">{title}</p>
      <p className="mt-1 text-text-muted">{message}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}
