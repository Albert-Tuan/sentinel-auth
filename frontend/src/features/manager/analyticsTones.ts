/**
 * The semantic colour of a risk level.
 *
 * The mapping is by MEANING, never by a fixed palette order: "critical"
 * is always the danger colour, "high" always the warning colour. A
 * palette-ordered mapping would make a critical alert render in the
 * calm colour as soon as a new level was added to the vocabulary.
 *
 * It lives in its own module because a component file may only export
 * components (the React Fast Refresh rule), and every other module in
 * `features/` follows that rule.
 */

export type AnalyticsTone = 'primary' | 'secondary' | 'warning' | 'danger'

/**
 * The tone of a risk level.
 */
export function toneForRisk(level: string): AnalyticsTone {
  switch (level) {
    case 'critical':
      return 'danger'
    case 'high':
      return 'warning'
    case 'medium':
      return 'secondary'
    default:
      return 'primary'
  }
}
