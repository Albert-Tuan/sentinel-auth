/**
 * Authentication state machine.
 *
 * States
 * ------
 *   anonymous        no session, no MFA challenge in progress
 *   authenticating   a login request is in flight
 *   mfa_required     login succeeded but MFA must be completed
 *                    (an MfaTransaction id is held, NOT a session)
 *   verifying_mfa    an MFA verification request is in flight
 *   authenticated    a real session exists; the user has been fetched
 *   error            the last transition failed
 *
 * Transitions
 * -----------
 *   anonymous --login()--> authenticating
 *   authenticating --mfa_required--> mfa_required
 *   authenticating --tokens--> authenticated
 *   authenticating --failure--> error -> anonymous
 *   mfa_required --verify()--> verifying_mfa
 *   verifying_mfa --tokens--> authenticated
 *   verifying_mfa --failure--> error -> mfa_required
 *   authenticated --logout()/expired--> anonymous
 *
 * The invariant that matters most: **the app is only ever "authenticated"
 * when a real, non-empty access token is held AND the current user has been
 * fetched from `/auth/me`.** An `mfa_required` login response never enters
 * the authenticated state, even though the HTTP call succeeded.
 */

import { useCallback, useMemo, useReducer } from 'react'
import {
  bestEffortLogout,
  fetchCurrentUser,
  login as loginRequest,
  verifyMfa as verifyMfaRequest,
} from '@/lib/api/auth.api'
import { clearSession, getEpoch, getSession, setSession } from '@/lib/api/tokenStore'
import { landingPathFor } from '@/app/router/policy'
import { ApiError, toApiError } from '@/lib/errors'
import type { CurrentUser, UserRole } from '@/types/api'

export type AuthStatus =
  | 'anonymous'
  | 'authenticating'
  | 'mfa_required'
  | 'verifying_mfa'
  | 'authenticated'
  | 'error'

export interface AuthState {
  status: AuthStatus
  /** The authenticated user. Null unless `status === 'authenticated'`. */
  user: CurrentUser | null
  /**
   * The pending MFA transaction id. This is an `MfaTransaction` id, NOT an
   * authenticated session id. Only meaningful in `mfa_required` /
   * `verifying_mfa`.
   */
  mfaTransactionId: string | null
  /** The last error, cleared on the next successful transition. */
  error: ApiError | null
}

export type AuthAction =
  | { type: 'LOGIN_START' }
  | { type: 'LOGIN_MFA_REQUIRED'; transactionId: string }
  | { type: 'LOGIN_SUCCESS'; user: CurrentUser }
  | { type: 'LOGIN_FAILURE'; error: ApiError }
  | { type: 'MFA_START' }
  | { type: 'MFA_SUCCESS'; user: CurrentUser }
  | { type: 'MFA_FAILURE'; error: ApiError }
  | { type: 'LOGOUT' }
  | { type: 'SESSION_EXPIRED' }
  | { type: 'CLEAR_ERROR' }

export const initialAuthState: AuthState = {
  status: 'anonymous',
  user: null,
  mfaTransactionId: null,
  error: null,
}

export function authReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case 'LOGIN_START':
      return {
        status: 'authenticating',
        user: null,
        mfaTransactionId: null,
        error: null,
      }

    case 'LOGIN_MFA_REQUIRED':
      // NOT authenticated: no tokens were issued.
      return {
        status: 'mfa_required',
        user: null,
        mfaTransactionId: action.transactionId,
        error: null,
      }

    case 'LOGIN_SUCCESS':
      return {
        status: 'authenticated',
        user: action.user,
        mfaTransactionId: null,
        error: null,
      }

    case 'LOGIN_FAILURE':
      return {
        status: 'error',
        user: null,
        mfaTransactionId: null,
        error: action.error,
      }

    case 'MFA_START':
      return { ...state, status: 'verifying_mfa', error: null }

    case 'MFA_SUCCESS':
      return {
        status: 'authenticated',
        user: action.user,
        mfaTransactionId: null,
        error: null,
      }

    case 'MFA_FAILURE':
      // Stay on the MFA screen so the user can retype the code.
      return { ...state, status: 'mfa_required', error: action.error }

    case 'LOGOUT':
    case 'SESSION_EXPIRED':
      return {
        status: 'anonymous',
        user: null,
        mfaTransactionId: null,
        error: null,
      }

    case 'CLEAR_ERROR':
      return { ...state, error: null }

    default:
      return state
  }
}

/**
 * The role-aware landing route.
 *
 * The role comes from `/auth/me`, never guessed from the UI. When the user
 * holds no recognised role the home route is used as the safe default.
 *
 * The implementation lives in `@/app/router/policy` — the single source of
 * truth — so the landing path can never disagree with the route guard or
 * with the access check.
 */
export { landingPathFor } from '@/app/router/policy'

export interface AuthApi {
  login: typeof loginRequest
  verifyMfa: typeof verifyMfaRequest
  fetchCurrentUser: typeof fetchCurrentUser
  bestEffortLogout: typeof bestEffortLogout
}

export const defaultAuthApi: AuthApi = {
  login: loginRequest,
  verifyMfa: verifyMfaRequest,
  fetchCurrentUser,
  bestEffortLogout,
}

export interface UseAuthOptions {
  /** Injected for tests. Defaults to the real API calls. */
  api?: AuthApi
}

/**
 * The auth state machine hook.
 */
export function useAuth(options: UseAuthOptions = {}) {
  const api = options.api ?? defaultAuthApi
  const [state, dispatch] = useReducer(authReducer, initialAuthState)

  /**
   * Install a freshly minted session and confirm it against `GET /auth/me`.
   *
   * The epoch guard is the point of this helper. `GET /auth/me` is
   * asynchronous: while it is in flight the user can log out, or start a
   * different login. A stale response must then be DISCARDED:
   *   - it must not install the old session (that would resurrect a session
   *     the user already ended),
   *   - it must not clear the newer session (that would log out a user who
   *     is legitimately signed in),
   *   - it must not dispatch `LOGIN_SUCCESS` (the UI would show an
   *     authenticated user with no tokens).
   *
   * The epoch is read AFTER `setSession` because installing a session is
   * itself a session boundary and therefore bumps the epoch.
   */
  const establishSession = useCallback(
    async (
      accessToken: string,
      refreshToken: string,
      sessionId: string | null,
      onSuccess: (user: CurrentUser) => AuthAction,
      onFailure: (error: ApiError) => AuthAction,
    ): Promise<boolean> => {
      setSession(accessToken, refreshToken, sessionId)
      const epochAtInstall = getEpoch()
      try {
        const user = await api.fetchCurrentUser()
        if (getEpoch() !== epochAtInstall) {
          // The session was replaced while `/auth/me` was in flight.
          return false
        }
        dispatch(onSuccess(user))
        return true
      } catch (error) {
        if (getEpoch() !== epochAtInstall) {
          // A superseded session must not be cleared by a stale error.
          return false
        }
        clearSession()
        dispatch(onFailure(toApiError(error)))
        return false
      }
    },
    [api],
  )

  const login = useCallback(
    async (username: string, password: string): Promise<boolean> => {
      dispatch({ type: 'LOGIN_START' })
      try {
        const response = await api.login({ username, password })

        if (response.mfa_required) {
          // The backend issued NO tokens. The `session_id` here is an
          // MfaTransaction id — it is NOT an authenticated session.
          // The user must complete MFA before we treat them as logged in.
          dispatch({
            type: 'LOGIN_MFA_REQUIRED',
            transactionId: response.session_id ?? '',
          })
          return true
        }

        // Defensive: a non-MFA response must still carry real tokens.
        if (!response.access_token || !response.refresh_token) {
          dispatch({
            type: 'LOGIN_FAILURE',
            error: new ApiError({
              kind: 'unauthorized',
              userMessage: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
            }),
          })
          return false
        }

        return await establishSession(
          response.access_token,
          response.refresh_token,
          response.session_id ?? null,
          (user) => ({ type: 'LOGIN_SUCCESS', user }),
          (error) => ({ type: 'LOGIN_FAILURE', error }),
        )
      } catch (error) {
        dispatch({ type: 'LOGIN_FAILURE', error: toApiError(error) })
        return false
      }
    },
    [api, establishSession],
  )

  const verifyMfa = useCallback(
    async (code: string): Promise<boolean> => {
      const transactionId = state.mfaTransactionId
      if (!transactionId) {
        dispatch({
          type: 'MFA_FAILURE',
          error: new ApiError({
            kind: 'validation',
            userMessage:
              'Phiên xác thực hai yếu tố đã hết hạn. Vui lòng đăng nhập lại.',
          }),
        })
        return false
      }

      dispatch({ type: 'MFA_START' })
      try {
        const response = await api.verifyMfa({
          session_id: transactionId,
          mfa_code: code,
        })
        if (!response.access_token || !response.refresh_token) {
          dispatch({
            type: 'MFA_FAILURE',
            error: new ApiError({
              kind: 'unauthorized',
              userMessage: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
            }),
          })
          return false
        }
        return await establishSession(
          response.access_token,
          response.refresh_token,
          response.session_id ?? null,
          (user) => ({ type: 'MFA_SUCCESS', user }),
          (error) => ({ type: 'MFA_FAILURE', error }),
        )
      } catch (error) {
        dispatch({ type: 'MFA_FAILURE', error: toApiError(error) })
        return false
      }
    },
    [api, establishSession, state.mfaTransactionId],
  )

  const cancelMfa = useCallback(() => {
    clearSession()
    dispatch({ type: 'LOGOUT' })
  }, [])

  /**
   * Install a session that was obtained OUTSIDE the normal login handshake.
   *
   * The trusted-device flow (`POST /devices/pending/{id}/complete`) returns
   * real tokens directly, so there is no login/MFA round-trip to perform.
   * The user is still fetched from `/auth/me` — the roles are never taken
   * from the token.
   *
   * The epoch guard (see `establishSession`) matters most here: the tokens
   * come from a poll that can resolve long after the user navigated away,
   * logged out, or signed in again elsewhere. A late response must never
   * install or clear a session that is no longer current.
   */
  const loginWithTokens = useCallback(
    async (
      accessToken: string,
      refreshToken: string,
      sessionId: string | null,
    ): Promise<boolean> => {
      if (!accessToken || !refreshToken) {
        dispatch({
          type: 'LOGIN_FAILURE',
          error: new ApiError({
            kind: 'unauthorized',
            userMessage: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
          }),
        })
        return false
      }

      return await establishSession(
        accessToken,
        refreshToken,
        sessionId,
        (user) => ({ type: 'LOGIN_SUCCESS', user }),
        (error) => ({ type: 'LOGIN_FAILURE', error }),
      )
    },
    [establishSession],
  )

  const logout = useCallback(async () => {
    // Revoke server-side first, but never let a failure block the local
    // teardown: the user must end up logged out either way.
    await api.bestEffortLogout()
    clearSession()
    dispatch({ type: 'LOGOUT' })
  }, [api])

  const clearError = useCallback(() => {
    dispatch({ type: 'CLEAR_ERROR' })
  }, [])

  const roles = useMemo(() => state.user?.roles ?? [], [state.user])

  const hasRole = useCallback(
    (role: UserRole) => roles.includes(role),
    [roles],
  )

  const hasAnyRole = useCallback(
    (allowed: UserRole[]) => allowed.some((role) => roles.includes(role)),
    [roles],
  )

  const isAuthenticated = state.status === 'authenticated'
  const isMfaPending =
    state.status === 'mfa_required' || state.status === 'verifying_mfa'
  const isLoading =
    state.status === 'authenticating' || state.status === 'verifying_mfa'

  const landingPath = useMemo(() => landingPathFor(roles), [roles])

  return {
    state,
    status: state.status,
    user: state.user,
    roles,
    isAuthenticated,
    isMfaPending,
    isLoading,
    error: state.error,
    sessionId: getSession()?.sessionId ?? null,
    hasRole,
    hasAnyRole,
    landingPath,
    login,
    loginWithTokens,
    verifyMfa,
    cancelMfa,
    logout,
    clearError,
  }
}

export type UseAuthReturn = ReturnType<typeof useAuth>
