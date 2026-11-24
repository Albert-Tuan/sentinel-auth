/**
 * Axios client with the M12 refresh-token lifecycle.
 *
 * Design
 * ------
 * 1. **Single-flight refresh.** A module-scoped `refreshPromise` holds the
 *    in-flight refresh request. Concurrent 401s all await the same promise,
 *    so exactly ONE `POST /auth/refresh` is sent. This matters because the
 *    backend ROTATES the refresh token: the old hash is overwritten, so a
 *    second refresh with the same token would fail with 401 and log the user
 *    out spuriously.
 *
 * 2. **Retry exactly once.** The original request is replayed once with the
 *    new access token. A `_retry` flag on the request config guarantees the
 *    replay itself can never trigger another refresh — no infinite loop.
 *
 * 3. **No refresh on auth endpoints.** `POST /auth/login`,
 *    `POST /auth/mfa/verify` and `POST /auth/refresh` never go through the
 *    refresh path. The same rule applies to the PUBLIC trusted-device
 *    endpoints (`POST /devices/pending`, `POST /devices/pending/{id}/complete`):
 *    the caller has no session yet, so a 401 there means "wrong credentials"
 *    or "not approved yet". The AUTHENTICATED trusted-device endpoint
 *    (`POST /devices/pending/{id}/approve`) is NOT on that list and is
 *    therefore allowed to refresh and replay.
 *
 * 4. **Epoch guard.** The store's epoch is captured before a refresh starts.
 *    If the session changed (logout, or a new login) while the refresh was in
 *    flight, the response is DISCARDED — a stale refresh can never write
 *    tokens into a newer session.
 *
 * 5. **Epoch-bound single flight.** The in-flight refresh promise is bound
 *    to the epoch it was started for. A request that belongs to a NEW
 *    session never reuses the promise of an OLDER session: it starts its
 *    own refresh. The mutex is released only by the promise that owns it,
 *    so a late-settling old promise can never unlock a newer one.
 *
 * 6. **Failure clears the session — but only the CURRENT one.** A failed
 *    refresh clears the auth state and notifies the app, which routes the
 *    user back to the login screen. The clear is guarded by the same epoch
 *    check as the success path: a refresh that failed for a SUPERSEDED
 *    session must not destroy the session that replaced it.
 */

import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ApiError, apiErrorFromResponse, toApiError } from '@/lib/errors'
import {
  clearSession,
  getAccessToken,
  getEpoch,
  getRefreshToken,
  updateTokens,
} from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { API_BASE_URL } from '@/lib/config'

/** Marker so a replayed request is never refreshed a second time. */
interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
  /** Set to skip the refresh path entirely for a specific request. */
  _skipRefresh?: boolean
  /**
   * The access token this request was sent with.
   *
   * It is the evidence that decides whether a 401 needs a refresh at all:
   * if the store already holds a DIFFERENT token, another flow has
   * refreshed the session in the meantime and this request only has to
   * be replayed with the new token.
   */
  _sentAccessToken?: string | null
  /**
   * The session epoch at the moment this request went out.
   *
   * Together with `_sentAccessToken` it distinguishes "the session was
   * refreshed under me" (same epoch, different token) from "the session
   * was replaced" (different epoch) - only the first may be replayed with
   * the token the store holds now.
   */
  _sentEpoch?: number
}

/**
 * Paths that must never trigger a refresh: the auth handshake itself.
 * A 401 from these means "wrong credentials", not "expired token".
 */
const NO_REFRESH_PATHS = new Set<string>([
  ENDPOINTS.auth.login,
  ENDPOINTS.auth.mfaVerify,
  ENDPOINTS.auth.refresh,
  ENDPOINTS.auth.register,
  // The trusted-device handshake is public: the caller has no session yet,
  // so a 401 means "wrong credentials" or "not approved yet".
  ENDPOINTS.devices.pending,
])

/**
 * PUBLIC trusted-device sub-paths that must never trigger a refresh.
 *
 * The trusted-device completion endpoint carries the request id in the URL
 * (`/devices/pending/{id}/complete`), so an exact match is impossible — the
 * shape is matched instead. A 401 from it means "the account is not active",
 * NOT "the access token expired", so refreshing would be wrong.
 *
 * `/devices/pending/{id}/approve` is deliberately NOT listed: the backend
 * guards it with `get_current_auth_context`, so a 401 there genuinely means
 * an expired access token and the request MUST be able to refresh and replay.
 */
const NO_REFRESH_PUBLIC_PATHS: RegExp[] = [
  /^\/devices\/pending\/[^/]+\/complete$/,
]

/** Notified when the session dies, so the app can route to the login screen. */
type SessionExpiredListener = (epoch: number) => void
const sessionExpiredListeners = new Set<SessionExpiredListener>()

/**
 * Subscribe to session-expiry events. Returns an unsubscribe function.
 *
 * The listener receives the epoch of the session that expired. A consumer
 * that is told about an epoch that is no longer current must NOT act on it:
 * a newer session has already replaced the expired one.
 */
export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener)
  return () => {
    sessionExpiredListeners.delete(listener)
  }
}

function notifySessionExpired(epoch: number): void {
  for (const listener of [...sessionExpiredListeners]) {
    try {
      listener(epoch)
    } catch {
      // A misbehaving listener must not break the interceptor.
    }
  }
}

/**
 * Raised when a refresh response belongs to a session that has since been
 * replaced. It is handled separately from a genuine refresh failure: the
 * current session must NOT be cleared.
 */
class StaleSessionError extends Error {
  constructor() {
    super('The refresh response belongs to a superseded session')
    this.name = 'StaleSessionError'
  }
}

/**
 * The in-flight refresh request, shared by every concurrent 401 of the SAME
 * session, plus the epoch that refresh belongs to.
 *
 * The epoch is what binds the promise to a session: a request that belongs
 * to a newer session must not reuse the promise of an older one.
 */
let refreshPromise: Promise<string> | null = null
let refreshEpoch: number | null = null

/**
 * Perform the refresh, deduplicating concurrent callers.
 *
 * The single-flight mutex is scoped to ONE session: it is only reused while
 * the epoch it was started for is still the current one. When a new session
 * is established the old promise is dropped from the mutex (it keeps
 * running, but nobody waits on it any more) and a fresh refresh is started.
 *
 * @returns the new access token
 */
function performRefresh(): Promise<string> {
  const epochAtStart = getEpoch()

  // Reuse the in-flight refresh ONLY when it belongs to the current
  // session. A promise from a superseded session is never reused.
  if (refreshPromise && refreshEpoch === epochAtStart) {
    return refreshPromise
  }

  const refreshToken = getRefreshToken()

  if (!refreshToken) {
    return Promise.reject(
      new ApiError({
        kind: 'unauthorized',
        userMessage: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
      }),
    )
  }

  const promise = apiClient
    .post<{ access_token: string; refresh_token: string }>(
      ENDPOINTS.auth.refresh,
      { refresh_token: refreshToken },
      {
        headers: { 'Content-Type': 'application/json' },
        // Belt and braces: the refresh endpoint is on the no-refresh list,
        // and this flag makes the intent explicit at the call site.
        _skipRefresh: true,
      } as AxiosRequestConfig,
    )
    .then((response) => {
      // The session may have been replaced while we were refreshing.
      // Discard the result rather than clobbering the new session.
      if (getEpoch() !== epochAtStart) {
        throw new StaleSessionError()
      }
      const accessToken = response.data?.access_token
      const newRefreshToken = response.data?.refresh_token
      if (!accessToken || !newRefreshToken) {
        throw new ApiError({
          kind: 'unauthorized',
          userMessage: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
        })
      }
      // Rotation: BOTH tokens are replaced. The old refresh token is dead.
      updateTokens(accessToken, newRefreshToken)
      return accessToken
    })
    .catch((error: unknown) => {
      // A stale refresh must NOT clear the session that superseded it —
      // that session is alive and must stay alive. This holds for EVERY
      // failure mode: HTTP 401, network error, timeout, malformed body.
      if (error instanceof StaleSessionError || getEpoch() !== epochAtStart) {
        throw new ApiError({
          kind: 'unauthorized',
          userMessage: 'Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập lại.',
        })
      }
      // The refresh failed for the CURRENT session: the session is gone.
      clearSession()
      notifySessionExpired(epochAtStart)
      throw toApiError(error)
    })
    .finally(() => {
      // Release the mutex so the next 401 can start a fresh refresh.
      // Only the promise that OWNS the mutex may release it: a late-settling
      // old promise must never unlock a newer refresh.
      if (refreshPromise === promise) {
        refreshPromise = null
        refreshEpoch = null
      }
    })

  refreshPromise = promise
  refreshEpoch = epochAtStart
  return promise
}

/**
 * Test helper: reset the module state between tests.
 */
export function __resetClientState(): void {
  refreshPromise = null
  refreshEpoch = null
}

/**
 * The shared Axios instance.
 */
export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20_000,
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
  // The API authenticates with a bearer header, not cookies. Never send
  // cookies cross-origin, and never let the browser attach them.
  withCredentials: false,
})

// ---------------------------------------------------------------------------
// Request interceptor — attach the bearer token
// ---------------------------------------------------------------------------
apiClient.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token && !config.headers.get('Authorization')) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  // Record the token this request actually went out with.  The response
  // interceptor compares it against the store to detect that another flow
  // already refreshed the session.
  const retryable = config as RetryableRequestConfig
  if (retryable._sentAccessToken === undefined) {
    retryable._sentAccessToken = token
    retryable._sentEpoch = getEpoch()
  }
  return config
})

// ---------------------------------------------------------------------------
// Response interceptor — normalise errors, refresh once, replay once
// ---------------------------------------------------------------------------
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryableRequestConfig | undefined

    if (!config) {
      throw toApiError(error)
    }

    const status = error.response?.status
    const url = config.url ?? ''
    const mayRefresh =
      status === 401 &&
      !config._retry &&
      !config._skipRefresh &&
      !NO_REFRESH_PATHS.has(url) &&
      !NO_REFRESH_PUBLIC_PATHS.some((pattern) => pattern.test(url))

    if (!mayRefresh) {
      throw normalise(error)
    }

    // Mark before refreshing so the replay can never loop.
    config._retry = true

    // The request belongs to a session that has since been REPLACED.
    //
    // The epoch is bumped by every session boundary change (a new login,
    // a logout), so `_sentEpoch !== getEpoch()` means the request went
    // out under an OLDER session than the one the store holds now.
    //
    // Such a request must not touch the current session AT ALL:
    //   - it must not replay with the current access token, because that
    //     would run the old request's body under the new user's identity;
    //   - it must not refresh, because `performRefresh` reads the CURRENT
    //     refresh token and would rotate the NEW session.  If that refresh
    //     then failed, `performRefresh` would clear the session and notify
    //     the app - logging the new user out over a stale request.
    //
    // The request is therefore failed with the 401 it actually received.
    // The current session is left completely untouched: its tokens, its
    // expiry state and its React Query cache all survive.
    if (
      config._sentEpoch !== undefined &&
      config._sentEpoch !== getEpoch()
    ) {
      throw new ApiError({
        kind: 'unauthorized',
        status: 401,
        userMessage: 'Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập lại.',
      })
    }

    // A 401 only means "this request's token is stale".  If the store
    // already holds a DIFFERENT access token, another flow has refreshed
    // the session in the meantime and there is nothing left to refresh:
    // this request only has to be replayed with the token that is now
    // current.
    //
    // Without this check a late-arriving 401 would start a SECOND
    // refresh: the single-flight mutex is released as soon as the first
    // refresh settles, so a 401 that reaches the interceptor after that
    // point would find the mutex free and refresh again.  The second
    // refresh would read the ALREADY ROTATED refresh token, succeed, and
    // rotate the token a second time - a race that only shows up when the
    // 401s arrive far enough apart (a slow runner, a loaded CI machine).
    //
    // The epoch guard above has already proved the request belongs to the
    // CURRENT session, so the token in the store is the token of the
    // session this request was sent for.
    const currentAccessToken = getAccessToken()
    if (
      config._sentAccessToken !== undefined &&
      config._sentAccessToken !== null &&
      currentAccessToken !== null &&
      currentAccessToken !== config._sentAccessToken
    ) {
      config.headers = config.headers ?? ({} as never)
      config.headers.set('Authorization', `Bearer ${currentAccessToken}`)
      return await apiClient.request(config)
    }

    try {
      const accessToken = await performRefresh()
      // Replay the original request exactly once, with the new token.
      config.headers = config.headers ?? ({} as never)
      config.headers.set('Authorization', `Bearer ${accessToken}`)
      return await apiClient.request(config)
    } catch (refreshError) {
      // The refresh failed. The session was already cleared by
      // `performRefresh`. Surface the auth failure to the caller.
      throw refreshError instanceof ApiError
        ? refreshError
        : toApiError(refreshError)
    }
  },
)

/**
 * Convert an Axios failure into an `ApiError`.
 */
export function normalise(error: AxiosError): ApiError {
  if (error.response) {
    return apiErrorFromResponse(
      error.response.status,
      error.response.data,
      error,
    )
  }
  return toApiError(error)
}

/**
 * Perform a request and return the parsed body.
 */
export async function apiGet<T>(
  url: string,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await apiClient.get<T>(url, config)
  return response.data
}

export async function apiPost<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await apiClient.post<T>(url, data, config)
  return response.data
}

export async function apiPut<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await apiClient.put<T>(url, data, config)
  return response.data
}

export async function apiDelete<T>(
  url: string,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await apiClient.delete<T>(url, config)
  return response.data
}
