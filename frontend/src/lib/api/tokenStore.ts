/**
 * In-memory session store.
 *
 * Tokens live in a module-scoped object and NOWHERE else:
 *  - not localStorage
 *  - not sessionStorage
 *  - not cookies
 *  - not a query string
 *
 * Consequence: a full page reload clears the session and the user must log in
 * again. That is the accepted trade-off for the M12 demo, and it is the
 * behaviour the security review asked for.
 *
 * The store also carries a monotonically increasing `sessionEpoch`. Every
 * login/logout bumps it, which lets in-flight refresh responses detect that
 * they belong to a stale session and drop their tokens instead of
 * overwriting the new session's tokens.
 */

export interface StoredSession {
  accessToken: string
  refreshToken: string
  /** The authenticated session id returned by `/auth/me` or MFA verify. */
  sessionId: string | null
}

let current: StoredSession | null = null
let epoch = 0

/** The current epoch. Increments on every session boundary change. */
export function getEpoch(): number {
  return epoch
}

/** The current session, or null when unauthenticated. */
export function getSession(): StoredSession | null {
  return current
}

/** The current access token, or null. */
export function getAccessToken(): string | null {
  return current?.accessToken ?? null
}

/** The current refresh token, or null. */
export function getRefreshToken(): string | null {
  return current?.refreshToken ?? null
}

/** True when a session with a non-empty access token exists. */
export function hasSession(): boolean {
  return Boolean(current?.accessToken)
}

/**
 * Install a new session.
 *
 * @param sessionId the authenticated session id, when known
 * @param bumpEpoch set false to avoid invalidating in-flight work that
 *        legitimately belongs to this same session (a token rotation).
 */
export function setSession(
  accessToken: string,
  refreshToken: string,
  sessionId: string | null = null,
  bumpEpoch = true,
): void {
  current = { accessToken, refreshToken, sessionId }
  if (bumpEpoch) epoch += 1
}

/**
 * Update only the tokens, keeping the session id and the epoch.
 * Used by the refresh rotation, which must not invalidate in-flight work.
 */
export function updateTokens(accessToken: string, refreshToken: string): void {
  if (!current) {
    current = { accessToken, refreshToken, sessionId: null }
    return
  }
  current = { ...current, accessToken, refreshToken }
}

/**
 * Clear the session and bump the epoch.
 */
export function clearSession(): void {
  current = null
  epoch += 1
}

/**
 * True when a session-expired notification about `expiredEpoch` still
 * describes the current situation.
 *
 * The notification is actionable ONLY when the expired session was the one
 * that was cleared and nothing has replaced it since:
 *   - the store must be empty (`current === null`) — if a session exists, a
 *     NEWER session replaced the expired one and the notification is stale,
 *   - the epoch must be exactly one past the expired one — the clear that
 *     produced the notification.
 *
 * A consumer that ignores a non-actionable notification will not tear down
 * a live session.
 */
export function isExpiredSessionCurrent(expiredEpoch: number): boolean {
  return current === null && epoch === expiredEpoch + 1
}

/**
 * Test helper: reset the store to a pristine state.
 */
export function __resetStore(): void {
  current = null
  epoch = 0
}
