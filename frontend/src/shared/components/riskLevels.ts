/**
 * The canonical risk levels.
 *
 * Mirrors `app/alerts.py::RISK_LEVELS` and the `chk_alerts_risk_level`
 * CHECK constraint on `alerts.risk_level`.
 *
 * The list lives in its own module so the badge component file exports
 * only components, and so the filter bar and the badge can never drift
 * apart: they read the SAME vocabulary.
 */
export const RISK_LEVELS = ['low', 'medium', 'high', 'critical'] as const
export type RiskLevelValue = (typeof RISK_LEVELS)[number]
