/**
 * SOC Alert API calls — READ ONLY (M12 Stage 4).
 *
 * Every call goes through the shared `apiClient`, so the refresh
 * interceptor applies and a 401 triggers exactly one refresh + replay.
 *
 * The endpoints are read-only on purpose: Stage 5 owns the mutations
 * (acknowledge, resolve, assign, actions, add timeline note). This module
 * therefore exposes ONLY the four GET endpoints of Stage 4:
 *
 *   GET /alerts
 *   GET /alerts/{id}
 *   GET /alerts/{id}/evidence
 *   GET /alerts/{id}/timeline
 *
 * The backend owns the ordering (newest first) and the pagination: the
 * client sends `page`/`limit` and renders what comes back. It never
 * re-sorts the result.
 */

import { apiGet } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type {
  AlertEvidence,
  AlertItem,
  AlertListResponse,
  TimelineEvent,
} from '@/types/api'

/**
 * The query the alert queue can apply.
 *
 * `status` and `risk_level` are validated by the BACKEND against its
 * canonical vocabularies; an unknown value comes back as a 400, not as an
 * empty list. `assigned_to_id` is a `soc_analysts.id` UUID.
 */
export interface AlertListQuery {
  status?: string
  risk_level?: string
  assigned_to_id?: string
  page?: number
  limit?: number
}

/**
 * `GET /alerts` — the alert queue.
 *
 * The query parameters are sent only when they carry a value, so an unset
 * filter never reaches the backend as an empty string.
 */
export async function fetchAlerts(
  query: AlertListQuery = {},
): Promise<AlertListResponse> {
  return apiGet<AlertListResponse>(ENDPOINTS.alerts.list, {
    params: {
      status: query.status || undefined,
      risk_level: query.risk_level || undefined,
      assigned_to_id: query.assigned_to_id || undefined,
      page: query.page,
      limit: query.limit,
    },
  })
}

/** `GET /alerts/{alert_id}` — the alert overview. */
export async function fetchAlert(alertId: string): Promise<AlertItem> {
  return apiGet<AlertItem>(ENDPOINTS.alerts.detail(alertId))
}

/**
 * `GET /alerts/{alert_id}/evidence` — the full investigation bundle.
 *
 * The bundle carries the alert, the login attempt, the risk assessment,
 * the detection logs and the timeline. Its `login_attempt` and
 * `risk_assessment` members are null when the underlying record does not
 * exist.
 */
export async function fetchAlertEvidence(
  alertId: string,
): Promise<AlertEvidence> {
  return apiGet<AlertEvidence>(ENDPOINTS.alerts.evidence(alertId))
}

/** `GET /alerts/{alert_id}/timeline` — the timeline events, oldest first. */
export async function fetchAlertTimeline(
  alertId: string,
): Promise<TimelineEvent[]> {
  return apiGet<TimelineEvent[]>(ENDPOINTS.alerts.timeline(alertId))
}
