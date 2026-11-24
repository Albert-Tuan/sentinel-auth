import { Badge, type BadgeTone } from '@/shared/components/Badge'
import {
  ALERT_STATUSES,
  type AlertStatusValue,
} from '@/shared/components/alertStatuses'

const STATUS_TONE: Record<AlertStatusValue, BadgeTone> = {
  open: 'danger',
  acknowledged: 'warning',
  resolved: 'success',
  false_positive: 'neutral',
}

const STATUS_LABEL: Record<AlertStatusValue, string> = {
  open: 'Mở',
  acknowledged: 'Đã xác nhận',
  resolved: 'Đã xử lý',
  false_positive: 'Báo động giả',
}

export interface StatusBadgeProps {
  status: string | null | undefined
  className?: string
}

/**
 * The status of an alert, as a coloured pill.
 *
 * An unknown status is shown verbatim rather than folded into a known
 * one, so a backend status the frontend does not know yet can never be
 * displayed as something it is not.
 */
export function StatusBadge({ status, className }: StatusBadgeProps) {
  if (status === null || status === undefined || status === '') {
    return (
      <Badge tone="neutral" className={className}>
        Không rõ
      </Badge>
    )
  }

  const known = ALERT_STATUSES.find((candidate) => candidate === status)
  if (!known) {
    return (
      <Badge tone="neutral" className={className}>
        {status}
      </Badge>
    )
  }

  return (
    <Badge tone={STATUS_TONE[known]} className={className}>
      {STATUS_LABEL[known]}
    </Badge>
  )
}
