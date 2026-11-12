import type { ReactNode } from 'react'
import { cn } from '@/shared/utils/cn'

export type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

export interface BadgeProps {
  children: ReactNode
  tone?: BadgeTone
  className?: string
}

const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: 'bg-slate-100 text-slate-700',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-800',
  danger: 'bg-red-50 text-red-700',
  info: 'bg-indigo-50 text-indigo-700',
}

/**
 * A small status pill.
 *
 * The tone carries the meaning, so the label itself stays short and the
 * colour is never the only signal.
 */
export function Badge({ children, tone = 'neutral', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
