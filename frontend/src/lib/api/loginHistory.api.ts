/**
 * S-22 — Login History (`/login-history`).
 *
 * The SOC analyst's search over `login_attempts`. The backend owns the
 * whole contract (`app/login_history.py`):
 *
 *   - the endpoint is gated by `SOC_ANALYST` and `SECURITY_MANAGER`;
 *   - the filters are the CANONICAL search criteria — nothing else is
 *     invented here;
 *   - `outcome` accepts only `success` and `failure` (the stored
 *     vocabulary is finer-grained: `mfa_failed` is matched by `failure`);
 *   - `from_date` is inclusive and `to_date` is EXCLUSIVE;
 *   - the ordering is newest first, and the client never re-sorts it.
 *
 * A filter the backend would reject with a 400 is never sent: the
 * dropdowns offer exactly the accepted values.
 */

import { apiGet } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type { LoginAttemptItem, LoginAttemptListResponse } from '@/types/api'

/** The outcome vocabulary the search accepts. */
export const SEARCH_OUTCOMES = ['success', 'failure'] as const
export type SearchOutcome = (typeof SEARCH_OUTCOMES)[number]

/** The risk levels the search accepts. */
export const SEARCH_RISK_LEVELS = [
  'low',
  'medium',
  'high',
  'critical',
] as const
export type SearchRiskLevel = (typeof SEARCH_RISK_LEVELS)[number]

export interface LoginHistoryQuery {
  user_id?: string
  username?: string
  from_date?: string
  to_date?: string
  ip_address?: string
  outcome?: SearchOutcome
  risk_level?: SearchRiskLevel
  page?: number
  limit?: number
}

/**
 * `GET /login-attempts` — the login history.
 *
 * The query parameters are sent only when they carry a value, so an unset
 * filter never reaches the backend as an empty string (which would be
 * rejected by the `min_length` constraint on `username`).
 */
export async function fetchLoginHistory(
  query: LoginHistoryQuery = {},
): Promise<LoginAttemptListResponse> {
  return apiGet<LoginAttemptListResponse>(ENDPOINTS.loginAttempts.list, {
    params: {
      user_id: query.user_id || undefined,
      username: query.username || undefined,
      from_date: query.from_date || undefined,
      to_date: query.to_date || undefined,
      ip_address: query.ip_address || undefined,
      outcome: query.outcome || undefined,
      risk_level: query.risk_level || undefined,
      page: query.page,
      limit: query.limit,
    },
  })
}

export type { LoginAttemptItem }
