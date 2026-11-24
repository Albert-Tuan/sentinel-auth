/**
 * Login-attempt lookups used to enrich the alert queue.
 *
 * `GET /api/v1/alerts` returns the ALERT rows only: the subject of an
 * alert (the username that was attempted, the source IP) lives on the
 * `login_attempts` table, which the queue endpoint does not join.
 *
 * The queue therefore reads the subject from `GET /api/v1/login-attempts`
 * — an existing, read-only endpoint owned by the same Detection database
 * and gated by the same roles (`SOC_ANALYST`, `SECURITY_MANAGER`). No
 * endpoint is invented and nothing is guessed: a subject that cannot be
 * found is rendered as "—", never as an empty string.
 */

import { apiGet } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type { LoginAttemptItem, LoginAttemptListResponse } from '@/types/api'

/** The largest page the backend accepts. */
const MAX_LIMIT = 100
/**
 * How many login-attempt pages may be scanned for one queue render.
 *
 * The scan stops as soon as every wanted id is found, so the common case
 * costs a single request. The cap bounds the worst case (a very large
 * history) so the queue can never turn into an unbounded crawl.
 */
const MAX_PAGES = 5

export interface LoginAttemptSubject {
  username: string | null
  ip_address: string | null
}

/**
 * Look up the subject of every given login attempt.
 *
 * The returned map is keyed by the login-attempt id. Ids that the backend
 * does not know are simply absent from the map — the caller renders them
 * as "no data" rather than inventing a value.
 */
export async function fetchLoginAttemptSubjects(
  loginAttemptIds: string[],
): Promise<Record<string, LoginAttemptSubject>> {
  const wanted = new Set(loginAttemptIds)
  const found: Record<string, LoginAttemptSubject> = {}

  if (wanted.size === 0) return found

  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const response = await apiGet<LoginAttemptListResponse>(
      ENDPOINTS.loginAttempts.list,
      { params: { page, limit: MAX_LIMIT } },
    )

    for (const attempt of response.attempts) {
      if (!wanted.has(attempt.id)) continue
      found[attempt.id] = {
        username: attempt.username_attempted,
        ip_address: attempt.ip_address,
      }
    }

    // Every wanted subject was found — no need to scan further.
    if (Object.keys(found).length === wanted.size) break
    // The backend has no more rows.
    const consumed = page * MAX_LIMIT
    if (response.attempts.length === 0 || consumed >= response.total) break
  }

  return found
}

export type { LoginAttemptItem }
