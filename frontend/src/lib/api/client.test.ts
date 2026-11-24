/**
 * Refresh-token lifecycle tests.
 *
 * Covers: concurrent 401 -> exactly one refresh, refresh token rotation,
 * refresh failure, retry-once behaviour, no refresh on the auth endpoints,
 * the logout/refresh race, and the "reload requires login again" rule.
 *
 * The "stale refresh" block is the regression suite for the M12 review
 * blockers: a refresh that fails for a SUPERSEDED session must never clear
 * the session that replaced it.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import MockAdapter from 'axios-mock-adapter'
import {
  apiClient,
  __resetClientState,
  onSessionExpired,
} from '@/lib/api/client'
import {
  __resetStore,
  getAccessToken,
  getRefreshToken,
  setSession,
} from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/errors'
import {
  FAKE_ACCESS_TOKEN,
  FAKE_REFRESH_TOKEN,
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

describe('request interceptor', () => {
  it('attaches the bearer token to every request', async () => {
    setSession('token-123', 'refresh-123')
    let seen: string | undefined
    mock.onGet('/alerts').reply((config) => {
      seen = config.headers?.Authorization as string
      return [200, {}]
    })

    await apiClient.get('/alerts')

    expect(seen).toBe('Bearer token-123')
  })
})

describe('single-flight refresh', () => {
  it('issues exactly ONE refresh for many concurrent 401s', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)

    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      refreshCalls += 1
      // Hold the response open so every 401 lands while it is in flight.
      await new Promise((resolve) => setTimeout(resolve, 20))
      return [200, { access_token: 'new-access', refresh_token: 'new-refresh' }]
    })

    // Every protected call answers 401 until the retry succeeds.
    mock.onGet('/alerts').reply((config) => {
      const auth = config.headers?.Authorization as string
      if (auth === 'Bearer new-access') return [200, { alerts: [] }]
      return [401, { detail: 'Invalid token' }]
    })

    const results = await Promise.all([
      apiClient.get('/alerts'),
      apiClient.get('/alerts'),
      apiClient.get('/alerts'),
      apiClient.get('/alerts'),
      apiClient.get('/alerts'),
    ])

    expect(refreshCalls).toBe(1)
    for (const result of results) {
      expect(result.status).toBe(200)
    }
    // Both tokens were rotated together.
    expect(getAccessToken()).toBe('new-access')
    expect(getRefreshToken()).toBe('new-refresh')
  })

  it('does NOT refresh again when a late 401 arrives after the first refresh settled', async () => {
    // Regression test for the M12 CI race.
    //
    // The single-flight mutex is released as soon as the first refresh
    // settles.  A 401 that reaches the interceptor AFTER that point finds
    // the mutex free and used to start a SECOND refresh.  That second
    // refresh reads the ALREADY ROTATED refresh token, succeeds and
    // rotates the token again - so the backend records two refresh
    // sessions where exactly one was intended.
    //
    // The race only shows up when the 401s arrive far enough apart, which
    // is why it escaped the unit suite (its mock holds the refresh
    // response open, so every 401 always lands while the refresh is in
    // flight) and only appeared on a slow CI runner.
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)

    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      refreshCalls += 1
      return [
        200,
        {
          access_token: `new-access-${refreshCalls}`,
          refresh_token: `new-refresh-${refreshCalls}`,
        },
      ]
    })

    // The SECOND request answers 401 only AFTER the first refresh has
    // settled, so it reaches the interceptor with the mutex already free.
    // Both requests were sent with the SAME original token.
    const releaseLateResponse: { current: (() => void) | null } = { current: null }
    const lateResponseGate = new Promise<void>((resolve) => {
      releaseLateResponse.current = resolve
    })
    let callIndex = 0
    mock.onGet('/alerts').reply(async (config) => {
      const auth = config.headers?.Authorization as string
      if (auth?.startsWith('Bearer new-access-')) return [200, { alerts: [] }]
      callIndex += 1
      if (callIndex === 1) return [401, { detail: 'expired' }]
      // The late 401: it waits until the first refresh has finished.
      await lateResponseGate
      return [401, { detail: 'expired' }]
    })

    const first = apiClient.get('/alerts')
    const late = apiClient.get('/alerts')

    // Let the first request complete its whole 401 -> refresh -> replay
    // cycle, then release the late 401.
    await first
    releaseLateResponse.current?.()

    const results = await Promise.all([first, late])

    expect(refreshCalls).toBe(1)
    for (const result of results) {
      expect(result.status).toBe(200)
    }
    expect(getAccessToken()).toBe('new-access-1')
  })

  it('replays a late 401 with the current token instead of refreshing again', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)

    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      refreshCalls += 1
      return [
        200,
        {
          access_token: `new-access-${refreshCalls}`,
          refresh_token: `new-refresh-${refreshCalls}`,
        },
      ]
    })

    const releaseLateResponse: { current: (() => void) | null } = { current: null }
    const lateResponseGate = new Promise<void>((resolve) => {
      releaseLateResponse.current = resolve
    })
    let callIndex = 0
    mock.onGet('/alerts').reply(async (config) => {
      const auth = config.headers?.Authorization as string
      if (auth?.startsWith('Bearer new-access-')) return [200, { alerts: [] }]
      callIndex += 1
      if (callIndex === 1) return [401, { detail: 'expired' }]
      await lateResponseGate
      return [401, { detail: 'expired' }]
    })

    const first = apiClient.get('/alerts')
    const late = apiClient.get('/alerts')
    await first
    releaseLateResponse.current?.()
    await late

    // The late 401 found the session already refreshed, so it replayed
    // with the current token instead of rotating it a second time.
    expect(refreshCalls).toBe(1)
    expect(getRefreshToken()).toBe('new-refresh-1')
  })

  it('rotates BOTH tokens on a successful refresh', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    mock.onPost(ENDPOINTS.auth.refresh).reply(200, {
      access_token: 'rotated-access',
      refresh_token: 'rotated-refresh',
    })
    mock.onGet('/alerts').reply((config) => {
      const auth = config.headers?.Authorization as string
      return auth === 'Bearer rotated-access'
        ? [200, {}]
        : [401, { detail: 'expired' }]
    })

    await apiClient.get('/alerts')

    expect(getAccessToken()).toBe('rotated-access')
    expect(getRefreshToken()).toBe('rotated-refresh')
  })
})

describe('refresh failure', () => {
  it('clears the session and notifies the app when the refresh fails', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)

    mock.onPost(ENDPOINTS.auth.refresh).reply(401, {
      detail: 'Invalid refresh token',
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    await expect(apiClient.get('/alerts')).rejects.toBeInstanceOf(ApiError)

    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
    expect(expired).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  it('does not retry the original request after a failed refresh', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    let alertCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(401, { detail: 'nope' })
    mock.onGet('/alerts').reply(() => {
      alertCalls += 1
      return [401, { detail: 'expired' }]
    })

    await expect(apiClient.get('/alerts')).rejects.toBeInstanceOf(ApiError)
    // The original request was attempted once, not replayed.
    expect(alertCalls).toBe(1)
  })
})

describe('retry-once behaviour', () => {
  it('replays the original request exactly once', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    let alertCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(200, {
      access_token: 'new-access',
      refresh_token: 'new-refresh',
    })
    mock.onGet('/alerts').reply(() => {
      alertCalls += 1
      return [401, { detail: 'expired' }]
    })

    await expect(apiClient.get('/alerts')).rejects.toBeInstanceOf(ApiError)
    // 1 original + 1 replay. No infinite loop.
    expect(alertCalls).toBe(2)
  })

  it('does not refresh again when the replay also returns 401', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    let refreshCalls = 0
    let alertCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [200, { access_token: 'new-access', refresh_token: 'new-refresh' }]
    })
    mock.onGet('/alerts').reply(() => {
      alertCalls += 1
      return [401, { detail: 'still expired' }]
    })

    await expect(apiClient.get('/alerts')).rejects.toBeInstanceOf(ApiError)
    expect(refreshCalls).toBe(1)
    expect(alertCalls).toBe(2)
  })
})

describe('no-refresh endpoints', () => {
  it('never refreshes on a failed login', async () => {
    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [200, { access_token: 'x', refresh_token: 'y' }]
    })
    mock.onPost(ENDPOINTS.auth.login).reply(401, { detail: 'bad credentials' })

    await expect(
      apiClient.post(ENDPOINTS.auth.login, { username: 'a', password: 'b' }),
    ).rejects.toBeInstanceOf(ApiError)

    expect(refreshCalls).toBe(0)
  })

  it('never refreshes on a failed MFA verification', async () => {
    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [200, { access_token: 'x', refresh_token: 'y' }]
    })
    mock.onPost(ENDPOINTS.auth.mfaVerify).reply(401, { detail: 'bad code' })

    await expect(
      apiClient.post(ENDPOINTS.auth.mfaVerify, {
        session_id: 's',
        mfa_code: '000000',
      }),
    ).rejects.toBeInstanceOf(ApiError)

    expect(refreshCalls).toBe(0)
  })

  it('never refreshes on a failed refresh call itself', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [401, { detail: 'Invalid refresh token' }]
    })

    await expect(
      apiClient.post(ENDPOINTS.auth.refresh, { refresh_token: 'x' }),
    ).rejects.toBeInstanceOf(ApiError)

    expect(refreshCalls).toBe(1)
  })
})

describe('trusted-device no-refresh boundary', () => {
  const REQUEST_ID = 'cccccccc-0000-0000-0000-000000000001'

  it('never refreshes on the PUBLIC completion endpoint', async () => {
    // `POST /devices/pending/{id}/complete` is public on the backend: the
    // caller has no session yet. A 401 there means "the account is not
    // active", NOT "the access token expired" — refreshing would be wrong.
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [200, { access_token: 'x', refresh_token: 'y' }]
    })
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(401, {
      detail: 'Account is not active',
    })

    await expect(
      apiClient.post(ENDPOINTS.devices.pendingComplete(REQUEST_ID)),
    ).rejects.toBeInstanceOf(ApiError)

    expect(refreshCalls).toBe(0)
    // The session is untouched: a public 401 must not log the user out.
    expect(getAccessToken()).toBe(FAKE_ACCESS_TOKEN)
  })

  it('never refreshes on the PUBLIC approval-request endpoint', async () => {
    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [200, { access_token: 'x', refresh_token: 'y' }]
    })
    mock.onPost(ENDPOINTS.devices.pending).reply(401, {
      detail: 'Invalid credentials',
    })

    await expect(
      apiClient.post(ENDPOINTS.devices.pending, {
        username: 'a',
        password: 'b',
      }),
    ).rejects.toBeInstanceOf(ApiError)

    expect(refreshCalls).toBe(0)
  })

  it('DOES refresh on the AUTHENTICATED approval endpoint', async () => {
    // `POST /devices/pending/{id}/approve` is guarded by
    // `get_current_auth_context` on the backend, so a 401 genuinely means an
    // expired access token. The request must refresh and replay.
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [200, { access_token: 'new-access', refresh_token: 'new-refresh' }]
    })
    mock.onPost(ENDPOINTS.devices.pendingApprove(REQUEST_ID)).reply((config) => {
      const auth = config.headers?.Authorization as string
      return auth === 'Bearer new-access'
        ? [200, { request_id: REQUEST_ID, device_id: 'd', status: 'approved' }]
        : [401, { detail: 'Invalid token' }]
    })

    const response = await apiClient.post(
      ENDPOINTS.devices.pendingApprove(REQUEST_ID),
    )

    expect(refreshCalls).toBe(1)
    expect(response.status).toBe(200)
    expect(getAccessToken()).toBe('new-access')
  })
})

describe('logout / refresh race', () => {
  it('does not let an in-flight refresh write tokens into a new session', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)

    // The refresh is slow, so the logout happens while it is in flight.
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30))
      return [200, { access_token: 'stale-access', refresh_token: 'stale-refresh' }]
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    const pending = apiClient.get('/alerts').catch((error) => error)

    // The user logs out while the refresh is still running.
    await new Promise((resolve) => setTimeout(resolve, 5))
    __resetStore()

    const outcome = await pending
    expect(outcome).toBeInstanceOf(ApiError)
    // The stale refresh must NOT have restored a session.
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })

  it('discards a refresh result that belongs to a superseded session', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30))
      return [200, { access_token: 'stale-access', refresh_token: 'stale-refresh' }]
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    const pending = apiClient.get('/alerts').catch((error) => error)
    await new Promise((resolve) => setTimeout(resolve, 5))
    // A NEW session starts (a fresh login) while the old refresh is in flight.
    setSession('brand-new-access', 'brand-new-refresh')

    await pending

    // The new session's tokens are untouched.
    expect(getAccessToken()).toBe('brand-new-access')
    expect(getRefreshToken()).toBe('brand-new-refresh')
  })
})

/**
 * Regression suite for the M12 review blockers.
 *
 * A refresh that fails for a session that has SINCE been replaced must not
 * destroy the newer session. This holds for every failure mode: HTTP 401,
 * network error and timeout.
 */
describe('stale refresh failure (Case A / B)', () => {
  it('Case A: a 401 on a stale refresh leaves the new session intact', async () => {
    // Session A is installed.
    setSession('session-a-access', 'session-a-refresh')

    // The refresh of session A is held open.
    const releaseRefreshHolder: { current: (() => void) | null } = { current: null }
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      await new Promise<void>((resolve) => {
        releaseRefreshHolder.current = resolve
      })
      return [401, { detail: 'Invalid refresh token' }]
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)

    const pending = apiClient.get('/alerts').catch((error) => error)

    // Wait until the refresh is really in flight.
    await vi.waitFor(() => {
      expect(releaseRefreshHolder.current).not.toBeNull()
    })

    // Session B is established while the refresh of session A is running.
    setSession('session-b-access', 'session-b-refresh')

    // Now the stale refresh fails with a 401.
    releaseRefreshHolder.current?.()

    const outcome = await pending
    expect(outcome).toBeInstanceOf(ApiError)

    // Session B survives untouched.
    expect(getAccessToken()).toBe('session-b-access')
    expect(getRefreshToken()).toBe('session-b-refresh')
    // And no expiration was announced for the live session.
    expect(expired).not.toHaveBeenCalled()
    unsubscribe()
  })

  it('Case B: a network error on a stale refresh leaves the new session intact', async () => {
    setSession('session-a-access', 'session-a-refresh')

    const releaseRefreshHolder: { current: (() => void) | null } = { current: null }
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      await new Promise<void>((resolve) => {
        releaseRefreshHolder.current = resolve
      })
      // A network error carries no response at all.
      throw Object.assign(new Error('Network Error'), { isAxiosError: true })
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)

    const pending = apiClient.get('/alerts').catch((error) => error)

    await vi.waitFor(() => {
      expect(releaseRefreshHolder.current).not.toBeNull()
    })

    setSession('session-b-access', 'session-b-refresh')
    releaseRefreshHolder.current?.()

    const outcome = await pending
    expect(outcome).toBeInstanceOf(ApiError)

    expect(getAccessToken()).toBe('session-b-access')
    expect(getRefreshToken()).toBe('session-b-refresh')
    expect(expired).not.toHaveBeenCalled()
    unsubscribe()
  })

  it('Case B: a timeout on a stale refresh leaves the new session intact', async () => {
    setSession('session-a-access', 'session-a-refresh')

    const releaseRefreshHolder: { current: (() => void) | null } = { current: null }
    mock.onPost(ENDPOINTS.auth.refresh).reply(async () => {
      await new Promise<void>((resolve) => {
        releaseRefreshHolder.current = resolve
      })
      throw Object.assign(new Error('timeout of 20000ms exceeded'), {
        code: 'ECONNABORTED',
        isAxiosError: true,
      })
    })
    mock.onGet('/alerts').reply(401, { detail: 'expired' })

    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)

    const pending = apiClient.get('/alerts').catch((error) => error)

    await vi.waitFor(() => {
      expect(releaseRefreshHolder.current).not.toBeNull()
    })

    setSession('session-b-access', 'session-b-refresh')
    releaseRefreshHolder.current?.()

    const outcome = await pending
    expect(outcome).toBeInstanceOf(ApiError)

    expect(getAccessToken()).toBe('session-b-access')
    expect(getRefreshToken()).toBe('session-b-refresh')
    expect(expired).not.toHaveBeenCalled()
    unsubscribe()
  })

  it('Case D: a new session does not reuse the old session refresh promise', async () => {
    setSession('session-a-access', 'session-a-refresh')

    let refreshCalls = 0
    const releaseRefreshHolder: { current: (() => void) | null } = { current: null }
    mock.onPost(ENDPOINTS.auth.refresh).reply(async (config) => {
      refreshCalls += 1
      const body = JSON.parse(config.data as string) as {
        refresh_token: string
      }
      if (body.refresh_token === 'session-a-refresh') {
        await new Promise<void>((resolve) => {
          releaseRefreshHolder.current = resolve
        })
        return [200, { access_token: 'a2', refresh_token: 'a2-refresh' }]
      }
      return [200, { access_token: 'b2', refresh_token: 'b2-refresh' }]
    })
    mock.onGet('/alerts').reply((config) => {
      const auth = config.headers?.Authorization as string
      if (auth === 'Bearer b2') return [200, { alerts: [] }]
      return [401, { detail: 'expired' }]
    })

    const pendingA = apiClient.get('/alerts').catch((error) => error)

    await vi.waitFor(() => {
      expect(releaseRefreshHolder.current).not.toBeNull()
    })

    // Session B is established: its own request must trigger its OWN
    // refresh instead of waiting on the promise of session A.
    setSession('session-b-access', 'session-b-refresh')
    const pendingB = apiClient.get('/alerts')

    await expect(pendingB).resolves.toMatchObject({ status: 200 })
    expect(refreshCalls).toBe(2)

    // Session A's refresh settles afterwards and changes nothing.
    releaseRefreshHolder.current?.()
    await pendingA

    expect(getAccessToken()).toBe('b2')
    expect(getRefreshToken()).toBe('b2-refresh')
  })

  it('does not let a late-settling old refresh unlock a newer one', async () => {
    setSession('session-a-access', 'session-a-refresh')

    const releaseAHolder: { current: (() => void) | null } = { current: null }
    mock.onPost(ENDPOINTS.auth.refresh).reply(async (config) => {
      const body = JSON.parse(config.data as string) as { refresh_token: string }
      if (body.refresh_token === 'session-a-refresh') {
        await new Promise<void>((resolve) => {
          releaseAHolder.current = resolve
        })
        return [200, { access_token: 'a2', refresh_token: 'a2-refresh' }]
      }
      return [200, { access_token: 'b2', refresh_token: 'b2-refresh' }]
    })
    mock.onGet('/alerts').reply((config) => {
      const auth = config.headers?.Authorization as string
      if (auth === 'Bearer b2') return [200, { alerts: [] }]
      return [401, { detail: 'expired' }]
    })

    const pendingA = apiClient.get('/alerts').catch((error) => error)
    await vi.waitFor(() => {
      expect(releaseAHolder.current).not.toBeNull()
    })

    setSession('session-b-access', 'session-b-refresh')
    await expect(apiClient.get('/alerts')).resolves.toMatchObject({ status: 200 })

    // The stale promise settles now — it must not release the mutex that
    // belongs to the newer session.
    releaseAHolder.current?.()
    await pendingA

    // A further 401 must still be able to refresh: the mutex is free.
    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [200, { access_token: 'b3', refresh_token: 'b3-refresh' }]
    })
    mock.onGet('/alerts').reply((config) => {
      const auth = config.headers?.Authorization as string
      if (auth === 'Bearer b3') return [200, { alerts: [] }]
      return [401, { detail: 'expired' }]
    })

    await expect(apiClient.get('/alerts')).resolves.toMatchObject({ status: 200 })
    expect(refreshCalls).toBe(1)
    expect(getAccessToken()).toBe('b3')
  })
})

describe('epoch guard (a request from a replaced session)', () => {
  /**
   * Wait until the request has actually LEFT the client.
   *
   * The request interceptor runs on a microtask, so a request created and
   * then immediately followed by `setSession()` would go out with the NEW
   * token - it would be a request of the new session, not a stale one.
   * The scenario under test needs the request to carry session A's token
   * and to still be in flight when session B is established.
   */
  const waitForRequestToLeave = async (): Promise<void> => {
    await vi.waitFor(() => {
      expect(mock.history.get.length).toBeGreaterThan(0)
    })
  }

  /**
   * A request that was sent under session A must not touch session B.
   *
   * The epoch is bumped by every session boundary change, so the guard can
   * tell "this request belongs to an older session" from "this request
   * belongs to the current session but its token was rotated".
   *
   * Before the guard, a late 401 from session A fell through to
   * `performRefresh()`, which reads the CURRENT refresh token - session
   * B's. That rotated B's session, and if the refresh failed it cleared B
   * and announced the expiry, which logs B out and wipes B's query cache.
   */
  it('never refreshes and never replays a request from a replaced session', async () => {
    setSession('session-a-access', 'session-a-refresh')

    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [200, { access_token: 'rotated', refresh_token: 'rotated-refresh' }]
    })

    // The 401 for session A is held back until session B exists.
    const releaseLateResponse: { current: (() => void) | null } = { current: null }
    const lateResponseGate = new Promise<void>((resolve) => {
      releaseLateResponse.current = resolve
    })
    mock.onGet('/alerts').reply(async () => {
      await lateResponseGate
      return [401, { detail: 'expired' }]
    })

    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)

    const pending = apiClient.get('/alerts').catch((error) => error)

    // The request is now genuinely on the wire with session A's token.
    await waitForRequestToLeave()

    // Session B replaces session A while the request is still in flight.
    setSession('session-b-access', 'session-b-refresh')

    // Now the late 401 for session A arrives.
    releaseLateResponse.current?.()
    const outcome = await pending

    // The request fails with the 401 it actually received.
    expect(outcome).toBeInstanceOf(ApiError)
    expect((outcome as ApiError).kind).toBe('unauthorized')

    // Session B was never refreshed.
    expect(refreshCalls).toBe(0)

    // Session B is still authenticated and its tokens are untouched.
    expect(getAccessToken()).toBe('session-b-access')
    expect(getRefreshToken()).toBe('session-b-refresh')

    // No expiry was announced, so B's query cache is not cleared and B is
    // not logged out.
    expect(expired).not.toHaveBeenCalled()

    unsubscribe()
  })

  it('does not refresh the new session when a tokenless request 401s late', async () => {
    // The scenario that actually tears down the live session.
    //
    // The request went out BEFORE any session existed, so it carried no
    // access token.  The user then logged in (session B).  When the stale
    // 401 arrives, there is no token to compare against, so without the
    // epoch guard the request falls through to `performRefresh()` - which
    // reads the CURRENT refresh token and rotates session B.
    __resetStore()

    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [
        200,
        { access_token: 'b-rotated-access', refresh_token: 'b-rotated-refresh' },
      ]
    })

    const releaseLateResponse: { current: (() => void) | null } = { current: null }
    const lateResponseGate = new Promise<void>((resolve) => {
      releaseLateResponse.current = resolve
    })
    mock.onGet('/alerts').reply(async () => {
      await lateResponseGate
      return [401, { detail: 'expired' }]
    })

    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)

    const pending = apiClient.get('/alerts').catch((error) => error)

    // The request is on the wire, without any token.
    await waitForRequestToLeave()

    // The user logs in while the request is still in flight.
    setSession('session-b-access', 'session-b-refresh')

    releaseLateResponse.current?.()
    const outcome = await pending

    expect(outcome).toBeInstanceOf(ApiError)
    expect((outcome as ApiError).kind).toBe('unauthorized')

    // Session B was never refreshed.
    expect(refreshCalls).toBe(0)

    // Session B keeps its tokens and stays authenticated.
    expect(getAccessToken()).toBe('session-b-access')
    expect(getRefreshToken()).toBe('session-b-refresh')
    expect(expired).not.toHaveBeenCalled()

    unsubscribe()
  })

  it('does not log the new session out when the refresh would have failed', async () => {
    // The proof that the guard matters: WITHOUT it, the late 401 of a
    // tokenless request would refresh session B with B's own refresh
    // token.  A refresh that fails clears the session and announces the
    // expiry, which tears down the live session - the user is logged out
    // over a request that belonged to nobody.
    __resetStore()

    // B's refresh token is already dead, so a refresh of B would fail
    // with a 401 - exactly the situation the guard has to prevent.
    mock.onPost(ENDPOINTS.auth.refresh).reply(401, {
      detail: 'Invalid refresh token',
    })

    const releaseLateResponse: { current: (() => void) | null } = { current: null }
    const lateResponseGate = new Promise<void>((resolve) => {
      releaseLateResponse.current = resolve
    })
    mock.onGet('/alerts').reply(async () => {
      await lateResponseGate
      return [401, { detail: 'expired' }]
    })

    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)

    const pending = apiClient.get('/alerts').catch((error) => error)
    await waitForRequestToLeave()
    setSession('session-b-access', 'session-b-dead-refresh')
    releaseLateResponse.current?.()
    await pending

    // Session B is still alive.
    expect(getAccessToken()).toBe('session-b-access')
    expect(getRefreshToken()).toBe('session-b-dead-refresh')
    expect(expired).not.toHaveBeenCalled()

    unsubscribe()
  })

  it('does not replay a replaced session request with the current token', async () => {
    setSession('session-a-access', 'session-a-refresh')

    let replayedWith: string | undefined
    const releaseLateResponse: { current: (() => void) | null } = { current: null }
    const lateResponseGate = new Promise<void>((resolve) => {
      releaseLateResponse.current = resolve
    })
    mock.onGet('/alerts').reply(async (config) => {
      const auth = config.headers?.Authorization as string
      if (auth === 'Bearer session-b-access') {
        replayedWith = auth
        return [200, { alerts: [] }]
      }
      await lateResponseGate
      return [401, { detail: 'expired' }]
    })

    const pending = apiClient.get('/alerts').catch((error) => error)
    await waitForRequestToLeave()
    setSession('session-b-access', 'session-b-refresh')
    releaseLateResponse.current?.()
    const outcome = await pending

    // The request was NOT replayed under session B's identity.
    expect(outcome).toBeInstanceOf(ApiError)
    expect(replayedWith).toBeUndefined()
  })

  it('still refreshes and retries for a request of the CURRENT session', async () => {
    // The guard must not break the normal path: a request of the current
    // session whose token was rotated still refreshes once and retries.
    setSession('current-access', 'current-refresh')

    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [
        200,
        { access_token: 'rotated-access', refresh_token: 'rotated-refresh' },
      ]
    })
    mock.onGet('/alerts').reply((config) => {
      const auth = config.headers?.Authorization as string
      return auth === 'Bearer rotated-access'
        ? [200, { alerts: [] }]
        : [401, { detail: 'expired' }]
    })

    await expect(apiClient.get('/alerts')).resolves.toMatchObject({ status: 200 })
    expect(refreshCalls).toBe(1)
    expect(getAccessToken()).toBe('rotated-access')
  })

  it('still replays a same-session late 401 with the current token', async () => {
    // The late-401 optimisation for the SAME session must survive the
    // guard: a rotated token is replayed, never refreshed twice.
    setSession('current-access', 'current-refresh')

    let refreshCalls = 0
    mock.onPost(ENDPOINTS.auth.refresh).reply(() => {
      refreshCalls += 1
      return [
        200,
        { access_token: `rotated-access-${refreshCalls}`, refresh_token: 'r' },
      ]
    })

    const releaseLateResponse: { current: (() => void) | null } = { current: null }
    const lateResponseGate = new Promise<void>((resolve) => {
      releaseLateResponse.current = resolve
    })
    let callIndex = 0
    mock.onGet('/alerts').reply(async (config) => {
      const auth = config.headers?.Authorization as string
      if (auth?.startsWith('Bearer rotated-access-')) return [200, { alerts: [] }]
      callIndex += 1
      if (callIndex === 1) return [401, { detail: 'expired' }]
      await lateResponseGate
      return [401, { detail: 'expired' }]
    })

    const first = apiClient.get('/alerts')
    const late = apiClient.get('/alerts')
    await first
    releaseLateResponse.current?.()
    await late

    expect(refreshCalls).toBe(1)
  })
})

describe('error normalisation', () => {  it('maps status codes to the right error kind', async () => {
    const cases: Array<[number, string]> = [
      [400, 'validation'],
      [422, 'validation'],
      [401, 'unauthorized'],
      [403, 'forbidden'],
      [404, 'not_found'],
      [409, 'conflict'],
      [410, 'gone'],
      [423, 'locked'],
      [429, 'rate_limited'],
      [502, 'dependency_unavailable'],
      [503, 'dependency_unavailable'],
      [500, 'server'],
    ]

    for (const [status, kind] of cases) {
      mock.onGet('/probe').reply(() => [status, { detail: 'x' }])
      const error = await apiClient.get('/probe').catch((e) => e)
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).kind).toBe(kind)
    }
  })

  it('extracts field issues from a 422 body', async () => {
    mock.onGet('/probe').reply(422, {
      detail: [
        { loc: ['body', 'username'], msg: 'Field required', type: 'missing' },
      ],
    })
    const error = (await apiClient.get('/probe').catch((e) => e)) as ApiError
    expect(error.issues).toEqual([
      { field: 'username', message: 'Field required' },
    ])
    expect(error.issueFor('username')?.message).toBe('Field required')
  })
})

describe('token storage', () => {
  it('never writes tokens to localStorage or sessionStorage', () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
    expect(document.cookie).not.toContain(FAKE_ACCESS_TOKEN)
    expect(document.cookie).not.toContain(FAKE_REFRESH_TOKEN)
  })

  it('does not survive a reload — the store starts empty', async () => {
    setSession(FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN)
    expect(getAccessToken()).toBe(FAKE_ACCESS_TOKEN)

    // Simulate a page reload: a fresh module state.
    __resetStore()
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })
})
