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
 * 5. **Failure clears the session.** A failed refresh clears the auth state
 *    and notifies the app, which routes the user back to the login screen.
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
type SessionExpiredListener = () => void
const sessionExpiredListeners = new Set<SessionExpiredListener>()

/** Subscribe to session-expiry events. Returns an unsubscribe function. */
export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener)
  return () => {
    sessionExpiredListeners.delete(listener)
  }
}

function notifySessionExpired(): void {
  for (const listener of [...sessionExpiredListeners]) {
    try {
      listener()
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
 * The in-flight refresh request. Shared by every concurrent 401.
 */
let refreshPromise: Promise<string> | null = null

/**
 * Perform the refresh, deduplicating concurrent callers.
 *
 * @returns the new access token
 */
function performRefresh(): Promise<string> {
  if (refreshPromise) return refreshPromise

  const epochAtStart = getEpoch()
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
      // that session is alive and must stay alive.
      if (error instanceof StaleSessionError) {
        throw new ApiError({
          kind: 'unauthorized',
          userMessage: 'Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập lại.',
        })
      }
      // The refresh failed for the CURRENT session: the session is gone.
      clearSession()
      notifySessionExpired()
      throw toApiError(error)
    })
    .finally(() => {
      // Release the mutex so the next 401 can start a fresh refresh.
      if (refreshPromise === promise) refreshPromise = null
    })

  refreshPromise = promise
  return promise
}

/**
 * Test helper: reset the module state between tests.
 */
export function __resetClientState(): void {
  refreshPromise = null
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
