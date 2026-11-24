import type { ReactNode } from 'react'
import { cn } from '@/shared/utils/cn'

export type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

export interface BadgeProps {
  children: ReactNode
  tone?: BadgeTone
  className?: string
}

/**
 * A telemetry chip.
 *
 * The Sentinel Telemetry Operator design system defines badges as
 * MONOSPACED UPPERCASE text inside a 1px border, with a 10%-alpha fill of
 * the same colour. There is no radius and no soft shadow.
 *
 * The tone carries the meaning, so the label itself stays short and the
 * colour is never the only signal.
 */
const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: 'bg-degraded/10 text-text-muted border-degraded/60',
  success: 'bg-success/10 text-success border-success',
  warning: 'bg-warning/10 text-warning border-warning',
  danger: 'bg-danger text-white border-danger',
  info: 'bg-secondary/10 text-secondary border-secondary',
}

export function Badge({ children, tone = 'neutral', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'label-ops inline-flex items-center border px-2 py-0.5',
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
