/**
 * The canonical alert statuses.
 *
 * Mirrors `app/alerts.py::ALERT_STATUSES` and the `chk_alerts_status`
 * CHECK constraint on `alerts.status`.
 *
 * `escalated` is deliberately NOT a status: the backend records an
 * escalation as an `alert_timeline` event, not as an alert status.
 *
 * The list lives in its own module so the badge component file exports
 * only components, and so the filter bar and the badge can never drift
 * apart: they read the SAME vocabulary.
 */
export const ALERT_STATUSES = [
  'open',
  'acknowledged',
  'resolved',
  'false_positive',
] as const
export type AlertStatusValue = (typeof ALERT_STATUSES)[number]
