/**
 * Auth state machine tests.
 *
 * Covers: login success, login failure, MFA required, MFA verification
 * success, MFA verification failure, and the role-aware landing route.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useAuth, landingPathFor, authReducer, initialAuthState } from '@/features/auth/useAuth'
import { getAccessToken, getRefreshToken, __resetStore } from '@/lib/api/tokenStore'
import { ApiError } from '@/lib/errors'
import {
  FAKE_ACCESS_TOKEN,
  FAKE_REFRESH_TOKEN,
  FAKE_MFA_TRANSACTION_ID,
  FAKE_SESSION_ID,
  makeUser,
} from '@/test/fixtures'
import type { AuthApi } from '@/features/auth/useAuth'
import type { UserRole } from '@/types/api'

beforeEach(() => {
  __resetStore()
})

function makeApi(overrides: Partial<AuthApi> = {}): AuthApi {
  return {
    login: vi.fn(),
    verifyMfa: vi.fn(),
    fetchCurrentUser: vi.fn().mockResolvedValue(makeUser()),
    bestEffortLogout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('useAuth — login', () => {
  it('authenticates on valid credentials and stores the tokens in memory', async () => {
    const api = makeApi({
      login: vi.fn().mockResolvedValue({
        access_token: FAKE_ACCESS_TOKEN,
        refresh_token: FAKE_REFRESH_TOKEN,
        mfa_required: false,
        session_id: FAKE_SESSION_ID,
      }),
    })

    const { result } = renderHook(() => useAuth({ api }))

    await act(async () => {
      const ok = await result.current.login('analyst', 'correct-password')
      expect(ok).toBe(true)
    })

    await waitFor(() => {
      expect(result.current.isAuthenticated).toBe(true)
    })
    expect(result.current.status).toBe('authenticated')
    expect(result.current.user?.username).toBe('analyst')
    // The tokens live in the in-memory store, and nowhere else.
    expect(getAccessToken()).toBe(FAKE_ACCESS_TOKEN)
    expect(getRefreshToken()).toBe(FAKE_REFRESH_TOKEN)
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })

  it('surfaces a failure and stays anonymous on invalid credentials', async () => {
    const api = makeApi({
      login: vi.fn().mockRejectedValue(
        new ApiError({
          kind: 'unauthorized',
          status: 401,
          userMessage: 'Tên đăng nhập hoặc mật khẩu không đúng.',
        }),
      ),
    })

    const { result } = renderHook(() => useAuth({ api }))

    await act(async () => {
      const ok = await result.current.login('analyst', 'wrong-password')
      expect(ok).toBe(false)
    })

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.status).toBe('error')
    expect(result.current.error?.userMessage).toBe(
      'Tên đăng nhập hoặc mật khẩu không đúng.',
    )
    expect(getAccessToken()).toBeNull()
  })

  it('reports a 429 rate limit distinctly', async () => {
    const api = makeApi({
      login: vi.fn().mockRejectedValue(
        new ApiError({
          kind: 'rate_limited',
          status: 429,
          userMessage: 'Quá nhiều yêu cầu đăng nhập.',
        }),
      ),
    })

    const { result } = renderHook(() => useAuth({ api }))
    await act(async () => {
      await result.current.login('analyst', 'password')
    })

    expect(result.current.error?.kind).toBe('rate_limited')
    expect(result.current.isAuthenticated).toBe(false)
  })
})

describe('useAuth — MFA', () => {
  it('does NOT authenticate when MFA is required', async () => {
    const api = makeApi({
      login: vi.fn().mockResolvedValue({
        access_token: '',
        refresh_token: '',
        mfa_required: true,
        session_id: FAKE_MFA_TRANSACTION_ID,
      }),
    })

    const { result } = renderHook(() => useAuth({ api }))

    await act(async () => {
      const ok = await result.current.login('admin', 'password')
      expect(ok).toBe(true)
    })

    // The critical invariant: an MFA challenge is NOT an authenticated session.
    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.status).toBe('mfa_required')
    expect(result.current.isMfaPending).toBe(true)
    expect(result.current.user).toBeNull()
    // The held id is the MFA transaction, and no token was installed.
    expect(result.current.state.mfaTransactionId).toBe(FAKE_MFA_TRANSACTION_ID)
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
    // /auth/me must not have been called yet.
    expect(api.fetchCurrentUser).not.toHaveBeenCalled()
  })

  it('authenticates after a successful MFA verification', async () => {
    const api = makeApi({
      login: vi.fn().mockResolvedValue({
        access_token: '',
        refresh_token: '',
        mfa_required: true,
        session_id: FAKE_MFA_TRANSACTION_ID,
      }),
      verifyMfa: vi.fn().mockResolvedValue({
        access_token: FAKE_ACCESS_TOKEN,
        refresh_token: FAKE_REFRESH_TOKEN,
        session_id: FAKE_SESSION_ID,
      }),
    })

    const { result } = renderHook(() => useAuth({ api }))

    await act(async () => {
      await result.current.login('admin', 'password')
    })
    expect(result.current.isAuthenticated).toBe(false)

    await act(async () => {
      const ok = await result.current.verifyMfa('123456')
      expect(ok).toBe(true)
    })

    await waitFor(() => {
      expect(result.current.isAuthenticated).toBe(true)
    })
    // The MFA transaction id was sent, not a session id.
    expect(api.verifyMfa).toHaveBeenCalledWith({
      session_id: FAKE_MFA_TRANSACTION_ID,
      mfa_code: '123456',
    })
    expect(getAccessToken()).toBe(FAKE_ACCESS_TOKEN)
  })

  it('stays on the MFA challenge when verification fails', async () => {
    const api = makeApi({
      login: vi.fn().mockResolvedValue({
        access_token: '',
        refresh_token: '',
        mfa_required: true,
        session_id: FAKE_MFA_TRANSACTION_ID,
      }),
      verifyMfa: vi.fn().mockRejectedValue(
        new ApiError({
          kind: 'unauthorized',
          status: 401,
          userMessage: 'Mã xác thực không đúng.',
        }),
      ),
    })

    const { result } = renderHook(() => useAuth({ api }))

    await act(async () => {
      await result.current.login('admin', 'password')
    })
    await act(async () => {
      const ok = await result.current.verifyMfa('000000')
      expect(ok).toBe(false)
    })

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.status).toBe('mfa_required')
    expect(result.current.error?.userMessage).toBe('Mã xác thực không đúng.')
    expect(getAccessToken()).toBeNull()
  })
})

describe('useAuth — roles and logout', () => {
  it('takes the roles from /auth/me, never from the client', async () => {
    const api = makeApi({
      login: vi.fn().mockResolvedValue({
        access_token: FAKE_ACCESS_TOKEN,
        refresh_token: FAKE_REFRESH_TOKEN,
        mfa_required: false,
        session_id: FAKE_SESSION_ID,
      }),
      fetchCurrentUser: vi.fn().mockResolvedValue(
        makeUser({ roles: ['SECURITY_MANAGER' as UserRole] }),
      ),
    })

    const { result } = renderHook(() => useAuth({ api }))
    await act(async () => {
      await result.current.login('manager', 'password')
    })

    expect(result.current.roles).toEqual(['SECURITY_MANAGER'])
    expect(result.current.hasRole('SECURITY_MANAGER')).toBe(true)
    expect(result.current.hasRole('SECURITY_ADMIN')).toBe(false)
    expect(result.current.hasAnyRole(['SECURITY_ADMIN', 'SECURITY_MANAGER'])).toBe(
      true,
    )
    expect(result.current.landingPath).toBe('/manager/dashboard')
  })

  it('clears the session and the query cache on logout', async () => {
    const api = makeApi({
      login: vi.fn().mockResolvedValue({
        access_token: FAKE_ACCESS_TOKEN,
        refresh_token: FAKE_REFRESH_TOKEN,
        mfa_required: false,
        session_id: FAKE_SESSION_ID,
      }),
    })

    const { result } = renderHook(() => useAuth({ api }))
    await act(async () => {
      await result.current.login('analyst', 'password')
    })
    expect(getAccessToken()).toBe(FAKE_ACCESS_TOKEN)

    await act(async () => {
      await result.current.logout()
    })

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.status).toBe('anonymous')
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
    expect(api.bestEffortLogout).toHaveBeenCalled()
  })
})

describe('useAuth — loginWithTokens', () => {
  it('installs a session obtained outside the login handshake', async () => {
    const api = makeApi()

    const { result } = renderHook(() => useAuth({ api }))

    await act(async () => {
      const ok = await result.current.loginWithTokens(
        'trusted-access',
        'trusted-refresh',
        'session-trusted',
      )
      expect(ok).toBe(true)
    })

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))
    expect(getAccessToken()).toBe('trusted-access')
    expect(getRefreshToken()).toBe('trusted-refresh')
    // The roles still come from the server, never from the token.
    expect(api.fetchCurrentUser).toHaveBeenCalled()
    expect(result.current.user?.username).toBe('analyst')
  })

  it('refuses an empty token and stays anonymous', async () => {
    const api = makeApi()
    const { result } = renderHook(() => useAuth({ api }))

    await act(async () => {
      const ok = await result.current.loginWithTokens('', '', null)
      expect(ok).toBe(false)
    })

    expect(result.current.isAuthenticated).toBe(false)
    expect(getAccessToken()).toBeNull()
    expect(api.fetchCurrentUser).not.toHaveBeenCalled()
  })

  it('clears the session when the user lookup fails', async () => {
    const api = makeApi({
      fetchCurrentUser: vi.fn().mockRejectedValue(new Error('boom')),
    })
    const { result } = renderHook(() => useAuth({ api }))

    await act(async () => {
      const ok = await result.current.loginWithTokens(
        'trusted-access',
        'trusted-refresh',
        'session-trusted',
      )
      expect(ok).toBe(false)
    })

    expect(result.current.isAuthenticated).toBe(false)
    expect(getAccessToken()).toBeNull()
  })

  it('does not let a late /auth/me response resurrect a logged-out session', async () => {
    // The trusted-device poll can resolve long after the user navigated
    // away. If the session was ended in the meantime, the stale response
    // must NOT dispatch LOGIN_SUCCESS.
    let release: (() => void) | null = null
    const api = makeApi({
      fetchCurrentUser: vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            release = () => resolve(makeUser())
          }),
      ),
    })

    const { result } = renderHook(() => useAuth({ api }))

    let pending: Promise<boolean> | null = null
    await act(async () => {
      pending = result.current.loginWithTokens(
        'trusted-access',
        'trusted-refresh',
        'session-trusted',
      )
    })

    // The user logs out while `/auth/me` is still in flight.
    await act(async () => {
      await result.current.logout()
    })

    await act(async () => {
      release?.()
      const ok = await pending
      expect(ok).toBe(false)
    })

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.status).not.toBe('authenticated')
    expect(getAccessToken()).toBeNull()
  })

  it('does not let a late /auth/me failure clear a newer session', async () => {
    let reject: ((error: Error) => void) | null = null
    const api = makeApi({
      fetchCurrentUser: vi.fn().mockImplementation(
        () =>
          new Promise((_resolve, rejectFn) => {
            reject = rejectFn
          }),
      ),
    })

    const { result } = renderHook(() => useAuth({ api }))

    let pending: Promise<boolean> | null = null
    await act(async () => {
      pending = result.current.loginWithTokens(
        'trusted-access',
        'trusted-refresh',
        'session-trusted',
      )
    })

    // A DIFFERENT login supersedes the trusted-device one while the first
    // `/auth/me` is still in flight.
    const newer = makeApi()
    const { result: newerResult } = renderHook(() => useAuth({ api: newer }))
    await act(async () => {
      const ok = await newerResult.current.loginWithTokens(
        'newer-access',
        'newer-refresh',
        'session-newer',
      )
      expect(ok).toBe(true)
    })

    await act(async () => {
      reject?.(new Error('stale failure'))
      const ok = await pending
      expect(ok).toBe(false)
    })

    // The stale failure must NOT have cleared the newer session.
    expect(getAccessToken()).toBe('newer-access')
    expect(getRefreshToken()).toBe('newer-refresh')
  })
})

describe('landingPathFor', () => {
  it('routes each role to its own landing page', () => {
    expect(landingPathFor(['SECURITY_MANAGER'])).toBe('/manager/dashboard')
    expect(landingPathFor(['SECURITY_ADMIN'])).toBe('/admin/users')
    expect(landingPathFor(['SOC_ANALYST'])).toBe('/alerts')
    expect(landingPathFor(['USER'])).toBe('/sessions')
    expect(landingPathFor([])).toBe('/')
  })

  it('prefers the most privileged role when several are held', () => {
    expect(
      landingPathFor(['SOC_ANALYST', 'SECURITY_MANAGER']),
    ).toBe('/manager/dashboard')
  })
})

describe('authReducer', () => {
  it('returns to anonymous after a session-expired transition', () => {
    const next = authReducer(
      { ...initialAuthState, status: 'authenticated', user: makeUser() },
      { type: 'SESSION_EXPIRED' },
    )
    expect(next.status).toBe('anonymous')
    expect(next.user).toBeNull()
  })

  it('keeps the MFA transaction id on a verification failure', () => {
    const next = authReducer(
      {
        ...initialAuthState,
        status: 'verifying_mfa',
        mfaTransactionId: FAKE_MFA_TRANSACTION_ID,
      },
      {
        type: 'MFA_FAILURE',
        error: new ApiError({ kind: 'unauthorized', userMessage: 'no' }),
      },
    )
    expect(next.status).toBe('mfa_required')
    expect(next.mfaTransactionId).toBe(FAKE_MFA_TRANSACTION_ID)
  })
})
