import type { ReactNode } from 'react'

export interface ErrorStateProps {
  title?: string
  message: string
  action?: ReactNode
}

/**
 * The standard error panel.
 *
 * The message must already be safe to display — pass `ApiError.userMessage`,
 * never a raw backend payload.
 */
export function ErrorState({
  title = 'Đã xảy ra lỗi',
  message,
  action,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-1">{message}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}
