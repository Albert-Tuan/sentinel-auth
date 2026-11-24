/**
 * Regression suite for the M12 review blocker "React auth state is not
 * synchronised with session expiration".
 *
 * When the transport layer loses the session (a refresh that failed for the
 * CURRENT session), the app must react as if the user had logged out:
 *   - the token store is empty,
 *   - the auth state machine is back to `anonymous`,
 *   - the user and the roles are gone,
 *   - a protected route bounces to `/login`,
 *   - the query cache of the old user is cleared.
 *
 * And it must NOT react when the notification is stale: a newer session
 * must survive untouched.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import MockAdapter from 'axios-mock-adapter'
import { screen, waitFor, act } from '@testing-library/react'
import { renderHook } from '@testing-library/react'
import { useEffect, useRef, type ReactNode } from 'react'
import { Route, Routes, useNavigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { renderWithProviders, makeTestQueryClient } from '@/test/renderApp'
import { AuthProvider } from '@/app/providers/AuthProvider'
import { RequireAuth } from '@/app/router/guards'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { PATHS } from '@/app/router/paths'
import { apiClient, __resetClientState } from '@/lib/api/client'
import {
  __resetStore,
  getAccessToken,
  getRefreshToken,
  setSession,
} from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type { AuthApi } from '@/features/auth/useAuth'
import {
  FAKE_ACCESS_TOKEN,
  FAKE_REFRESH_TOKEN,
  makeUser,
} from '@/test/fixtures'

let mock: MockAdapter

beforeEach(() => {
  __resetStore()
  __resetClientState()
  mock = new MockAdapter(apiClient)
})

afterEach(() => {
  mock.restore()
  vi.restoreAllMocks()
})

function makeApi(overrides: Partial<AuthApi> = {}): AuthApi {
  return {
    login: vi.fn().mockResolvedValue({
      access_token: FAKE_ACCESS_TOKEN,
      refresh_token: FAKE_REFRESH_TOKEN,
      mfa_required: false,
      session_id: 'session-1',
    }),
    verifyMfa: vi.fn(),
    fetchCurrentUser: vi.fn().mockResolvedValue(makeUser()),
    bestEffortLogout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

/**
 * A wrapper that provides the real providers around the hook under test.
 *
 * The hook needs the auth context but not a router, so the providers are
 * mounted directly instead of through `renderWithProviders`.
 */
function makeWrapper(api: AuthApi) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={makeTestQueryClient()}>
        <AuthProvider api={api}>{children}</AuthProvider>
      </QueryClientProvider>
    )
  }
}

/**
 * A probe that exposes the auth state and a protected route.
 */
function AuthProbe() {
  const auth = useAuthContext()
  return (
    <>
      <div data-testid="status">{auth.status}</div>
      <div data-testid="user">{auth.user?.username ?? 'none'}</div>
      <div data-testid="roles">{auth.roles.join(',') || 'none'}</div>
      <Routes>
        <Route path={PATHS.login} element={<div>Login screen</div>} />
        <Route element={<RequireAuth />}>
          <Route path={PATHS.alerts} element={<div>Alerts screen</div>} />
        </Route>
      </Routes>
    </>
  )
}

/**
 * Sign the user in on mount, then send them back to the protected route.
 *
 * `RequireAuth` redirects an anonymous visitor to `/login` on its very
 * first render, so the location has to be restored once the session is
 * established. Without that the protected screen would never render.
 */
function SignInHarness({ children }: { children: ReactNode }) {
  const auth = useAuthContext()
  const navigate = useNavigate()
  const { login, status, isAuthenticated } = auth
  const attempted = useRef(false)

  useEffect(() => {
    if (attempted.current) return
    if (status !== 'anonymous') return
    attempted.current = true
    void login('analyst', 'password')
  }, [login, status])

  useEffect(() => {
    if (isAuthenticated) {
      navigate(PATHS.alerts, { replace: true })
    }
  }, [isAuthenticated, navigate])

  return <>{children}</>
}

describe('Case C — the current session expires', () => {
  it('makes the token store and the React auth state anonymous', async () => {
    const api = makeApi()
    const { result } = renderHook(() => useAuthContext(), {
      wrapper: makeWrapper(api),
    })

    // Sign in through the state machine.
    await act(async () => {
      await result.current.login('analyst', 'password')
    })
    expect(result.current.status).toBe('authenticated')
    expect(result.current.roles).toEqual(['SOC_ANALYST'])

    // The refresh of the CURRENT session fails with a 401.
    mock.onPost(ENDPOINTS.auth.refresh).reply(401, {
      detail: 'Invalid refresh token',
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    await act(async () => {
      await apiClient.get('/alerts').catch(() => undefined)
    })

    // The token store is anonymous.
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
    // The React auth state follows.
    await waitFor(() => {
      expect(result.current.status).toBe('anonymous')
    })
    expect(result.current.user).toBeNull()
    expect(result.current.roles).toEqual([])
  })

  it('bounces a protected route to the login screen and clears the query cache', async () => {
    const api = makeApi()
    const { queryClient } = renderWithProviders(
      <SignInHarness>
        <AuthProbe />
      </SignInHarness>,
      {
        api,
        initialEntries: [PATHS.alerts],
      },
    )

    // The user is signed in: the protected route renders.
    await waitFor(() => {
      expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
    })
    await waitFor(() => {
      expect(screen.getByText('Alerts screen')).toBeInTheDocument()
    })

    // Seed the query cache with user-scoped data.
    queryClient.setQueryData(['alerts', 'list'], { alerts: ['secret'] })
    expect(queryClient.getQueryData(['alerts', 'list'])).toEqual({
      alerts: ['secret'],
    })

    // The refresh of the CURRENT session fails.
    mock.onPost(ENDPOINTS.auth.refresh).reply(401, {
      detail: 'Invalid refresh token',
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    await act(async () => {
      await apiClient.get('/alerts').catch(() => undefined)
    })

    // The protected route bounced to the login screen.
    await waitFor(() => {
      expect(screen.getByText('Login screen')).toBeInTheDocument()
    })
    expect(screen.queryByText('Alerts screen')).not.toBeInTheDocument()
    // The user and the roles are gone.
    expect(screen.getByTestId('status')).toHaveTextContent('anonymous')
    expect(screen.getByTestId('user')).toHaveTextContent('none')
    expect(screen.getByTestId('roles')).toHaveTextContent('none')
    // The stale, user-scoped cache is gone.
    expect(queryClient.getQueryData(['alerts', 'list'])).toBeUndefined()
  })

  it('does not log the user out twice', async () => {
    const api = makeApi()
    let bestEffortLogoutCalls = 0
    api.bestEffortLogout = vi.fn().mockImplementation(async () => {
      bestEffortLogoutCalls += 1
    })

    const { result } = renderHook(() => useAuthContext(), {
      wrapper: makeWrapper(api),
    })

    await act(async () => {
      await result.current.login('analyst', 'password')
    })

    mock.onPost(ENDPOINTS.auth.refresh).reply(401, { detail: 'nope' })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    await act(async () => {
      await apiClient.get('/alerts').catch(() => undefined)
    })

    await waitFor(() => {
      expect(result.current.status).toBe('anonymous')
    })

    // The expiration did NOT trigger a server-side logout, and the user is
    // not logged out a second time.
    expect(bestEffortLogoutCalls).toBe(0)
    expect(result.current.status).toBe('anonymous')
    expect(result.current.user).toBeNull()
  })

  it('does not tear down a session that was established concurrently', async () => {
    const api = makeApi()
    const { result } = renderHook(() => useAuthContext(), {
      wrapper: makeWrapper(api),
    })

    await act(async () => {
      await result.current.login('analyst', 'password')
    })
    expect(result.current.status).toBe('authenticated')

    // The refresh of the CURRENT session is held open.
    const releaseRefreshHolder: { current: (() => void) | null } = { current: null }
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      await new Promise<void>((resolve) => {
        releaseRefreshHolder.current = resolve
      })
      return [401, { detail: 'Invalid refresh token' }]
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    const pending = apiClient.get('/alerts').catch((error) => error)

    await vi.waitFor(() => {
      expect(releaseRefreshHolder.current).not.toBeNull()
    })

    // A NEW session is established while the old refresh is in flight.
    await act(async () => {
      await result.current.login('analyst', 'password')
    })
    setSession('new-access', 'new-refresh')

    // The stale refresh now fails.
    releaseRefreshHolder.current?.()
    await pending

    // The new session survives: the React state is still authenticated and
    // the token store still holds the new tokens.
    await waitFor(() => {
      expect(result.current.status).toBe('authenticated')
    })
    expect(getAccessToken()).toBe('new-access')
    expect(getRefreshToken()).toBe('new-refresh')
  })
})

describe('Case E — no regression on the normal flows', () => {
  it('keeps the session on a successful refresh and token rotation', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    mock.onPost(ENDPOINTS.auth.refresh).reply(200, {
      access_token: 'rotated-access',
      refresh_token: 'rotated-refresh',
    })
    mock.onGet('/alerts').reply((config) => {
      const auth = config.headers?.Authorization as string
      return auth === 'Bearer rotated-access'
        ? [200, { alerts: [] }]
        : [401, { detail: 'expired' }]
    })

    await expect(apiClient.get('/alerts')).resolves.toMatchObject({ status: 200 })
    expect(getAccessToken()).toBe('rotated-access')
    expect(getRefreshToken()).toBe('rotated-refresh')
  })

  it('leaves the MFA state machine alone', async () => {
    const api = makeApi({
      login: vi.fn().mockResolvedValue({
        access_token: '',
        refresh_token: '',
        mfa_required: true,
        session_id: 'mfa-transaction-1',
      }),
    })

    const { result } = renderHook(() => useAuthContext(), {
      wrapper: makeWrapper(api),
    })

    await act(async () => {
      await result.current.login('admin', 'password')
    })

    // The MFA challenge is pending and nothing was installed.
    expect(result.current.status).toBe('mfa_required')
    expect(result.current.state.mfaTransactionId).toBe('mfa-transaction-1')
    expect(getAccessToken()).toBeNull()
  })
})
