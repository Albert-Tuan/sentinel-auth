import { Badge, type BadgeTone } from '@/shared/components/Badge'
import { RISK_LEVELS, type RiskLevelValue } from '@/shared/components/riskLevels'

const RISK_TONE: Record<RiskLevelValue, BadgeTone> = {
  low: 'neutral',
  medium: 'info',
  high: 'warning',
  critical: 'danger',
}

const RISK_LABEL: Record<RiskLevelValue, string> = {
  low: 'Thấp',
  medium: 'Trung bình',
  high: 'Cao',
  critical: 'Nghiêm trọng',
}

export interface RiskBadgeProps {
  /**
   * The risk level. `null` means the alert has not been risk-scored —
   * which is NOT the same as the lowest level, and is rendered as
   * "chưa đánh giá" rather than "thấp".
   */
  riskLevel: string | null | undefined
  className?: string
}

/**
 * The risk level of an alert, as a coloured pill.
 *
 * The colour follows the semantics: neutral → info → warning → danger.
 * The label is always present, so the colour is never the only signal.
 */
export function RiskBadge({ riskLevel, className }: RiskBadgeProps) {
  if (riskLevel === null || riskLevel === undefined || riskLevel === '') {
    return (
      <Badge tone="neutral" className={className}>
        Chưa đánh giá
      </Badge>
    )
  }

  const known = RISK_LEVELS.find((level) => level === riskLevel)
  if (!known) {
    // An unknown level is shown verbatim: the backend may have added a
    // level the frontend does not know yet, and hiding it would mislead
    // the analyst.
    return (
      <Badge tone="neutral" className={className}>
        {riskLevel}
      </Badge>
    )
  }

  return (
    <Badge tone={RISK_TONE[known]} className={className}>
      {RISK_LABEL[known]}
    </Badge>
  )
}
