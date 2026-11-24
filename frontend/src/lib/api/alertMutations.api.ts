/**
 * SOC Alert API calls — MUTATIONS (M12 Stage 5).
 *
 * Every call goes through the shared `apiClient`, so the refresh
 * interceptor applies and a 401 triggers exactly one refresh + replay.
 *
 * The read endpoints live in `alerts.api.ts`; this module owns the
 * investigation workflow:
 *
 *   POST /alerts/{id}/acknowledge
 *   POST /alerts/{id}/resolve
 *   POST /alerts/{id}/assign
 *   POST /alerts/{id}/actions
 *   POST /alerts/{id}/timeline
 *
 * Two backend contracts shape the signatures below:
 *
 *   1. **Immutability.** A resolved or false-positive alert cannot be
 *      mutated again; the backend answers 409. The client does not
 *      pre-empt that — it surfaces the server's message.
 *   2. **Protective actions can fail independently of the alert.** A
 *      protective action (revoke sessions, lock the user) is executed by
 *      the Detection Engine inside Core. When that inner call fails the
 *      backend answers **502**, and the action was NOT applied. The
 *      response type therefore keeps the outcome explicit — a caller
 *      must never render a success banner for a 502.
 */

import { apiPost } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type {
  AlertAcknowledgeRequest,
  AlertActionRequest,
  AlertActionResponse,
  AlertAssignRequest,
  AlertItem,
  AlertResolveRequest,
  TimelineEvent,
  TimelineEventCreate,
} from '@/types/api'

/**
 * `POST /alerts/{alert_id}/acknowledge` — take ownership of the alert.
 *
 * The backend moves the status from `open` to `acknowledged`. The notes
 * are optional and are recorded on the alert.
 */
export async function acknowledgeAlert(
  alertId: string,
  payload: AlertAcknowledgeRequest = {},
): Promise<AlertItem> {
  return apiPost<AlertItem>(ENDPOINTS.alerts.acknowledge(alertId), payload)
}

/**
 * `POST /alerts/{alert_id}/resolve` — close the alert.
 *
 * `resolution` must be one of the four canonical values the backend
 * accepts. The alert becomes immutable afterwards: a second resolve
 * answers 409.
 */
export async function resolveAlert(
  alertId: string,
  payload: AlertResolveRequest,
): Promise<AlertItem> {
  return apiPost<AlertItem>(ENDPOINTS.alerts.resolve(alertId), payload)
}

/**
 * `POST /alerts/{alert_id}/assign` — hand the alert to a SOC analyst.
 *
 * `assigned_to_id` is a `soc_analysts.id` UUID, NOT a `users.id`. The
 * backend has no endpoint listing the analysts (documented gap G-1), so
 * the caller must supply a valid UUID — `isUuid()` in
 * `@/shared/utils/uuid` guards it before the request is sent.
 */
export async function assignAlert(
  alertId: string,
  payload: AlertAssignRequest,
): Promise<AlertItem> {
  return apiPost<AlertItem>(ENDPOINTS.alerts.assign(alertId), payload)
}

/**
 * `POST /alerts/{alert_id}/actions` — run a protective action.
 *
 * The action is executed by the Detection Engine inside Core, so it can
 * fail on its own: the backend then answers 502 and the action was NOT
 * applied. The caller MUST distinguish that case from a 200.
 */
export async function runAlertAction(
  alertId: string,
  payload: AlertActionRequest,
): Promise<AlertActionResponse> {
  return apiPost<AlertActionResponse>(
    ENDPOINTS.alerts.actions(alertId),
    payload,
  )
}

/**
 * `POST /alerts/{alert_id}/timeline` — append a timeline event.
 *
 * The backend has no dedicated "add note" route (gap G-9), so an analyst
 * note is written as a `note_added` timeline event. The backend imposes
 * no length limit, so the UI caps the comment at 2000 characters.
 */
export async function addTimelineEvent(
  alertId: string,
  payload: TimelineEventCreate,
): Promise<TimelineEvent> {
  return apiPost<TimelineEvent>(ENDPOINTS.alerts.timeline(alertId), payload)
}
