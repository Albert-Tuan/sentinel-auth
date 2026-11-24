/**
 * Real HTTP integration verification.
 *
 * These tests run against the LIVE FastAPI backend (no mocks, no MSW) and
 * exercise the real frontend HTTP stack: `apiClient` (axios + interceptors),
 * `tokenStore`, `auth.api` and the auth state machine in `useAuth`.
 *
 * Run with:
 *   npm run test:integration
 *
 * The backend must be reachable at `M12_API_BASE_URL` (default
 * http://127.0.0.1:8000) and the MFA OTP must be capturable from
 * `M12_OTP_LOG` (a file written by the local SMTP capture sink).
 *
 * Credentials come from the environment. No test credential is hard-coded
 * here — the file must stay free of anything that could be mistaken for a
 * production secret.
 */
import { readFileSync } from 'node:fs'
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'

import {
  apiGet,
  __resetClientState,
} from '@/lib/api/client'
import {
  clearSession,
  getAccessToken,
  getRefreshToken,
  setSession,
  __resetStore,
} from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import {
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  verifyMfa as verifyMfaRequest,
} from '@/lib/api/auth.api'
import { landingPathFor } from '@/features/auth/useAuth'
import { API_ROOT } from '@/test/integration/config'
import { countAudit, resetLoginRateLimit } from '@/test/integration/db'
import type { CurrentUser } from '@/types/api'

const OTP_LOG = process.env.M12_OTP_LOG ?? '/tmp/m12_otp_capture.log'

const USERNAME = process.env.M12_USER ?? 'm12analyst'
const PASSWORD = process.env.M12_PASSWORD ?? ''
const MFA_USERNAME = process.env.M12_MFA_USER ?? 'm12admin'
const MFA_PASSWORD = process.env.M12_MFA_PASSWORD ?? ''

/**
 * Read the most recent OTP captured for a recipient from the SMTP sink log.
 */
function readCapturedOtp(recipient: string): string {
  const raw = readFileSync(OTP_LOG, 'utf8')
  const blocks = raw.split(/^---$/m)
  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    const block = blocks[i]
    if (!block.includes(recipient)) continue
    const match = block.match(/verification code is\s+(\d{6})/i)
    if (match) return match[1]
  }
  throw new Error(`No captured OTP found for ${recipient} in ${OTP_LOG}`)
}

/**
 * The backend rate-limits logins to 5 per minute per IP. The integration
 * suite performs many logins in a short window, so the limiter row is reset
 * between tests. This is test-harness housekeeping only — it changes no
 * application behaviour.
 */

/** Raw HTTP call that bypasses the axios interceptors entirely. */
async function rawPost(path: string, body: unknown, token?: string) {
  const res = await fetch(`${API_ROOT}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  return { status: res.status, data }
}

async function rawGet(path: string, token?: string) {
  const res = await fetch(`${API_ROOT}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  return { status: res.status, data }
}

beforeAll(() => {
  if (!PASSWORD || !MFA_PASSWORD) {
    throw new Error(
      'M12_PASSWORD and M12_MFA_PASSWORD must be provided in the environment.',
    )
  }
})

beforeEach(() => {
  resetLoginRateLimit()
})

describe('real backend — login without MFA', () => {
  it('logs in, stores opaque tokens in memory and returns the current user', async () => {
    __resetStore()
    __resetClientState()

    const response = await loginRequest({
      username: USERNAME,
      password: PASSWORD,
    })

    expect(response.mfa_required).toBe(false)
    expect(response.access_token).not.toBe('')
    expect(response.refresh_token).not.toBe('')
    expect(response.session_id).toBeTruthy()

    // Opaque token: not a JWT.
    expect(response.access_token.split('.')).toHaveLength(1)

    setSession(
      response.access_token,
      response.refresh_token,
      response.session_id,
    )

    const user = await fetchCurrentUser()
    expect(user.username).toBe(USERNAME)
    expect(Array.isArray(user.roles)).toBe(true)
    expect(user.roles.length).toBeGreaterThan(0)

    // The token lives in memory only.
    expect(getAccessToken()).toBe(response.access_token)
    expect(globalThis.localStorage?.getItem?.('access_token') ?? null).toBeNull()
  })

  it('rejects a wrong password with 401 and no tokens', async () => {
    __resetStore()
    __resetClientState()

    const { status } = await rawPost(ENDPOINTS.auth.login, {
      username: USERNAME,
      password: `${PASSWORD}-wrong`,
    })
    expect(status).toBe(401)

    const response = await loginRequest({
      username: USERNAME,
      password: `${PASSWORD}-wrong`,
    }).catch((error: unknown) => error as { kind?: string })

    // The axios client turns the 401 into a normalised ApiError and does
    // NOT attempt a refresh on the login endpoint.
    expect((response as { kind?: string }).kind).toBe('unauthorized')
    expect(getAccessToken()).toBeNull()
  })
})

describe('real backend — MFA handshake', () => {
  it('issues no tokens on the challenge and only authenticates after verification', async () => {
    __resetStore()
    __resetClientState()

    const challenge = await loginRequest({
      username: MFA_USERNAME,
      password: MFA_PASSWORD,
    })

    // Pre-auth contract: NO token is issued.
    expect(challenge.mfa_required).toBe(true)
    expect(challenge.access_token).toBe('')
    expect(challenge.refresh_token).toBe('')
    expect(challenge.session_id).toBeTruthy()

    // The session_id is the MfaTransaction id, not an authenticated session.
    expect(getAccessToken()).toBeNull()

    // A wrong code is rejected.
    await expect(
      verifyMfaRequest({ session_id: challenge.session_id!, mfa_code: '000000' }),
    ).rejects.toMatchObject({ kind: 'unauthorized' })

    // The real OTP arrives over SMTP.
    const otp = readCapturedOtp(`${MFA_USERNAME}@example.com`)

    const verified = await verifyMfaRequest({
      session_id: challenge.session_id!,
      mfa_code: otp,
    })
    expect(verified.access_token).not.toBe('')
    expect(verified.refresh_token).not.toBe('')
    expect(verified.session_id).not.toBe(challenge.session_id)

    setSession(verified.access_token, verified.refresh_token, verified.session_id)
    const user = await fetchCurrentUser()
    expect(user.username).toBe(MFA_USERNAME)
    expect(user.roles).toContain('SECURITY_ADMIN')
  })
})

describe('real backend — refresh token rotation', () => {
  it('rotates BOTH tokens and invalidates the old refresh token', async () => {
    __resetStore()
    __resetClientState()

    const response = await loginRequest({
      username: USERNAME,
      password: PASSWORD,
    })
    setSession(response.access_token, response.refresh_token, response.session_id)

    const rotated = await rawPost(ENDPOINTS.auth.refresh, {
      refresh_token: response.refresh_token,
    })
    expect(rotated.status).toBe(200)
    const rotatedData = rotated.data as {
      access_token: string
      refresh_token: string
    }
    expect(rotatedData.access_token).not.toBe(response.access_token)
    expect(rotatedData.refresh_token).not.toBe(response.refresh_token)

    // The old refresh token is dead — a second use must fail.
    const replay = await rawPost(ENDPOINTS.auth.refresh, {
      refresh_token: response.refresh_token,
    })
    expect(replay.status).toBe(401)

    // The new access token works.
    const me = await rawGet(ENDPOINTS.auth.me, rotatedData.access_token)
    expect(me.status).toBe(200)
  })

  it('triggers EXACTLY ONE refresh for concurrent 401 responses', async () => {
    __resetStore()
    __resetClientState()

    const response = await loginRequest({
      username: USERNAME,
      password: PASSWORD,
    })
    setSession(response.access_token, response.refresh_token, response.session_id)

    const before = countAudit('refresh_session')

    // Poison the access token so every concurrent request 401s, while the
    // refresh token stays valid. The interceptor must collapse them into a
    // single refresh and replay each request once.
    setSession('invalid-access-token', response.refresh_token, response.session_id)

    const results = await Promise.all([
      apiGet<CurrentUser>(ENDPOINTS.auth.me),
      apiGet<CurrentUser>(ENDPOINTS.auth.me),
      apiGet<CurrentUser>(ENDPOINTS.auth.me),
      apiGet<CurrentUser>(ENDPOINTS.auth.me),
      apiGet<CurrentUser>(ENDPOINTS.auth.me),
    ])

    for (const user of results) {
      expect(user.username).toBe(USERNAME)
    }

    const after = countAudit('refresh_session')
    expect(after - before).toBe(1)

    // The rotated pair is what is now held in memory.
    expect(getAccessToken()).not.toBe('invalid-access-token')
    expect(getRefreshToken()).not.toBe(response.refresh_token)
  })

  it('clears the session when the refresh itself fails', async () => {
    __resetStore()
    __resetClientState()

    const response = await loginRequest({
      username: USERNAME,
      password: PASSWORD,
    })
    setSession('invalid-access-token', 'invalid-refresh-token', response.session_id)

    await expect(apiGet<CurrentUser>(ENDPOINTS.auth.me)).rejects.toMatchObject({
      kind: 'unauthorized',
    })

    // The failed refresh tore the session down.
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })
})

describe('real backend — logout', () => {
  it('revokes the session so the token is rejected afterwards', async () => {
    __resetStore()
    __resetClientState()

    const response = await loginRequest({
      username: USERNAME,
      password: PASSWORD,
    })
    setSession(response.access_token, response.refresh_token, response.session_id)

    expect((await rawGet(ENDPOINTS.auth.me, response.access_token)).status).toBe(200)

    const out = await logoutRequest()
    expect(out.status).toBe('ok')

    // The revoked session no longer authenticates.
    const after = await rawGet(ENDPOINTS.auth.me, response.access_token)
    expect(after.status).toBe(401)

    clearSession()
  })
})

describe('real backend — role aware routing', () => {
  it('maps backend roles to the canonical landing route', async () => {
    const analyst = await loginRequest({
      username: USERNAME,
      password: PASSWORD,
    })
    setSession(analyst.access_token, analyst.refresh_token, analyst.session_id)
    const analystUser = await fetchCurrentUser()

    expect(landingPathFor(analystUser.roles)).toBe(
      analystUser.roles.includes('SOC_ANALYST') ? '/alerts' : '/sessions',
    )

    const admin = await loginRequest({
      username: MFA_USERNAME,
      password: MFA_PASSWORD,
    })
    expect(admin.mfa_required).toBe(true)
  })

  it('enforces RBAC server-side: an analyst gets 403 on admin routes', async () => {
    __resetStore()
    __resetClientState()

    const response = await loginRequest({
      username: USERNAME,
      password: PASSWORD,
    })
    setSession(response.access_token, response.refresh_token, response.session_id)

    const forbidden = await rawGet(ENDPOINTS.admin.users, response.access_token)
    expect(forbidden.status).toBe(403)

    const allowed = await rawGet(ENDPOINTS.alerts.list, response.access_token)
    expect(allowed.status).toBe(200)
  })
})

describe('real backend — CORS', () => {
  it('allows the Vite dev origin and rejects an unknown origin', async () => {
    const allowed = await fetch(`${API_ROOT}${ENDPOINTS.auth.me}`, {
      method: 'OPTIONS',
      headers: {
        Origin: 'http://localhost:5173',
        'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'authorization',
      },
    })
    expect(allowed.status).toBeLessThan(400)
    expect(allowed.headers.get('access-control-allow-origin')).toBe(
      'http://localhost:5173',
    )

    const rejected = await fetch(`${API_ROOT}${ENDPOINTS.auth.me}`, {
      method: 'OPTIONS',
      headers: {
        Origin: 'http://evil.example.com',
        'Access-Control-Request-Method': 'GET',
      },
    })
    expect(rejected.headers.get('access-control-allow-origin')).toBeNull()
  })
})
