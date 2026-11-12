/**
 * Auth API calls.
 *
 * These calls use the shared `apiClient` so the refresh interceptor applies.
 * The handshake endpoints (login, MFA verify, refresh) are on the client's
 * no-refresh list, so a 401 from them surfaces directly to the caller
 * instead of triggering a refresh.
 */

import { apiClient, apiDelete, apiGet, apiPost } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type {
  CurrentUser,
  LoginRequest,
  LoginResponse,
  LogoutResponse,
  MfaVerifyRequest,
  MfaVerifyResponse,
  RefreshResponse,
  SessionList,
  UserRegisterRequest,
  UserRegisterResponse,
} from '@/types/api'

/**
 * `POST /auth/login`
 *
 * When the account requires MFA the response carries
 * `mfa_required: true`, empty tokens and a `session_id` that is an
 * `MfaTransaction` id — NOT an authenticated session.
 */
export async function login(request: LoginRequest): Promise<LoginResponse> {
  return apiPost<LoginResponse>(ENDPOINTS.auth.login, request)
}

/**
 * `POST /auth/mfa/verify`
 *
 * Completes the MFA handshake and returns the real session tokens.
 */
export async function verifyMfa(
  request: MfaVerifyRequest,
): Promise<MfaVerifyResponse> {
  return apiPost<MfaVerifyResponse>(ENDPOINTS.auth.mfaVerify, request)
}

/**
 * `POST /auth/refresh`
 *
 * Rotates the token pair. The backend invalidates the old refresh token.
 */
export async function refresh(refreshToken: string): Promise<RefreshResponse> {
  return apiPost<RefreshResponse>(ENDPOINTS.auth.refresh, {
    refresh_token: refreshToken,
  })
}

/**
 * `GET /auth/me` — the canonical source of the current user's roles.
 */
export async function fetchCurrentUser(): Promise<CurrentUser> {
  return apiGet<CurrentUser>(ENDPOINTS.auth.me)
}

/**
 * `POST /auth/logout` — revokes the current session on the server.
 */
export async function logout(): Promise<LogoutResponse> {
  return apiPost<LogoutResponse>(ENDPOINTS.auth.logout)
}

/**
 * `POST /auth/logout-all` — revokes every session of the current user.
 */
export async function logoutAll(): Promise<LogoutResponse> {
  return apiPost<LogoutResponse>(ENDPOINTS.auth.logoutAll)
}

/**
 * `GET /auth/sessions` — the user's active sessions.
 */
export async function fetchSessions(): Promise<SessionList> {
  return apiGet<SessionList>(ENDPOINTS.auth.sessions)
}

/**
 * `DELETE /auth/sessions/{session_id}` — revoke one session.
 *
 * Revoking the CURRENT session kills the access token the client is
 * holding, so the caller must tear the local session down as well.
 */
export async function revokeSession(sessionId: string): Promise<void> {
  await apiDelete<void>(ENDPOINTS.auth.session(sessionId))
}

/**
 * `POST /auth/register`
 */
export async function register(
  request: UserRegisterRequest,
): Promise<UserRegisterResponse> {
  return apiPost<UserRegisterResponse>(ENDPOINTS.auth.register, request)
}

/**
 * Raw axios access for the logout call, so a failing logout never blocks
 * the local session teardown.
 */
export async function bestEffortLogout(): Promise<void> {
  try {
    await apiClient.post(ENDPOINTS.auth.logout)
  } catch {
    // The local session is cleared regardless; a failed server-side
    // revoke must not strand the user in a half-logged-out state.
  }
}
