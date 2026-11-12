/**
 * Refresh-token lifecycle tests.
 *
 * Covers: concurrent 401 -> exactly one refresh, refresh token rotation,
 * refresh failure, retry-once behaviour, no refresh on the auth endpoints,
 * the logout/refresh race, and the "reload requires login again" rule.
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

describe('error normalisation', () => {
  it('maps status codes to the right error kind', async () => {
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
