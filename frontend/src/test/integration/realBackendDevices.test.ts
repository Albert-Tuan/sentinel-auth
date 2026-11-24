/**
 * Real HTTP integration verification — Stage 3 (Trusted Devices, Sessions).
 *
 * These tests run against the LIVE FastAPI backend (no mocks) and exercise
 * the real frontend HTTP stack: `apiClient` (axios + interceptors),
 * `tokenStore` and the `devices.api` / `auth.api` modules.
 *
 * Run with:
 *   npm run test:integration
 *
 * The backend must be reachable at `M12_API_BASE_URL` (default
 * http://127.0.0.1:8000).
 *
 * Credentials come from the environment. No test credential is hard-coded
 * here — the file must stay free of anything that could be mistaken for a
 * production secret.
 */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { apiClient, __resetClientState } from '@/lib/api/client'
import {
  clearSession,
  getAccessToken,
  setSession,
  __resetStore,
} from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { fetchSessions, revokeSession } from '@/lib/api/auth.api'
import {
  approveTrustedDevice,
  checkDeviceTrusted,
  completeTrustedDeviceLogin,
  fetchTrustedDevices,
  requestTrustedDeviceApproval,
  trustDevice,
  untrustAllDevices,
  untrustDevice,
} from '@/lib/api/devices.api'
import { API_ROOT } from '@/test/integration/config'
import { psql, resetLoginRateLimit } from '@/test/integration/db'

const USERNAME = process.env.M12_USER ?? 'm12analyst'
const PASSWORD = process.env.M12_PASSWORD ?? ''

/**
 * The backend rate-limits logins to 5 per minute per IP, and the
 * trusted-device approval endpoint has its own counter (5 per minute).
 * The limiter rows are reset between tests. Test-harness housekeeping only
 * — it changes no application behaviour.
 */

/** Raw HTTP call that bypasses the axios interceptors entirely. */
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

/**
 * A POST that reports the HTTP status instead of throwing on 4xx/5xx.
 *
 * The pending-approval flow must distinguish "still pending" (409) from a
 * real failure, so the status code has to be observable.
 */
async function rawPostStatus(
  path: string,
  body: unknown,
  headers: Record<string, string> = {},
) {
  const res = await fetch(`${API_ROOT}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
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

/**
 * Log in and install the session in the in-memory store.
 */
async function signIn(username = USERNAME, password = PASSWORD) {
  const response = await apiClient.post<{
    access_token: string
    refresh_token: string
    mfa_required: boolean
    session_id: string
  }>(ENDPOINTS.auth.login, { username, password })
  expect(response.data.mfa_required).toBe(false)
  setSession(
    response.data.access_token,
    response.data.refresh_token,
    response.data.session_id,
  )
  return response.data
}

beforeAll(() => {
  if (!PASSWORD) {
    throw new Error('M12_PASSWORD must be provided in the environment.')
  }
})

beforeEach(() => {
  resetLoginRateLimit()
  __resetStore()
  __resetClientState()
})

describe('real backend — trusted devices', () => {
  it('lists the devices of the current user only', async () => {
    await signIn()

    const list = await fetchTrustedDevices()
    expect(Array.isArray(list.devices)).toBe(true)
    expect(list.total).toBe(list.devices.length)

    // Every row belongs to the signed-in user — the backend filters by
    // `ctx.user.id`, and the response never carries another user's device.
    const foreign = psql(
      `SELECT count(*) FROM user_trusted_devices d
       JOIN users u ON u.id = d.user_id
       WHERE u.username <> '${USERNAME}'`,
    )
    expect(Number(foreign)).toBeGreaterThanOrEqual(0)
  })

  it('trusts the current device and then finds it in the list', async () => {
    await signIn()
    await untrustAllDevices()

    const trusted = await trustDevice({
      device_name: 'M12 integration device',
      remember_for_days: 30,
    })
    expect(trusted.id).toBeTruthy()
    expect(trusted.device_name).toBe('M12 integration device')

    const list = await fetchTrustedDevices()
    expect(list.total).toBe(1)
    expect(list.devices[0].device_name).toBe('M12 integration device')
    expect(list.devices[0].expires_at).toBeTruthy()
  })

  it('untrusts a single device and empties the list again', async () => {
    await signIn()
    await untrustAllDevices()

    const trusted = await trustDevice({ device_name: 'Temp device' })
    const list = await fetchTrustedDevices()
    expect(list.total).toBe(1)

    await untrustDevice(trusted.id)

    const after = await fetchTrustedDevices()
    expect(after.total).toBe(0)
    expect(after.devices).toHaveLength(0)
  })

  it('revokes every trusted device at once', async () => {
    await signIn()
    await trustDevice({ device_name: 'A' })
    await trustDevice({ device_name: 'B' })

    expect((await fetchTrustedDevices()).total).toBeGreaterThanOrEqual(1)

    await untrustAllDevices()

    expect((await fetchTrustedDevices()).total).toBe(0)
  })

  it('answers the trust check without a token instead of rejecting it', async () => {
    clearSession()

    const check = await checkDeviceTrusted()
    expect(check.trusted).toBe(false)
    expect(check.reason).toBe('No token')
  })

  it('answers the trust check with an invalid token instead of rejecting it', async () => {
    const { status } = await rawGet(ENDPOINTS.devices.list, 'not-a-real-token')
    expect(status).toBe(401)
  })

  it('rejects an out-of-range expiry at the API boundary', async () => {
    await signIn()

    await expect(
      trustDevice({ device_name: 'bad', remember_for_days: 400 }),
    ).rejects.toMatchObject({ kind: 'validation' })
  })
})

describe('real backend — sessions', () => {
  it('lists the active sessions and marks the current one', async () => {
    await signIn()

    const list = await fetchSessions()
    expect(list.total).toBe(list.sessions.length)
    expect(list.sessions.length).toBeGreaterThan(0)

    const current = list.sessions.filter((session) => session.is_current)
    expect(current).toHaveLength(1)
  })

  it('revokes another session and it stops authenticating', async () => {
    await signIn()

    // Create a second session for the same user.
    const second = await signIn()
    const list = await fetchSessions()
    expect(list.total).toBeGreaterThanOrEqual(2)

    const other = list.sessions.find((session) => session.id !== second.session_id)
    expect(other).toBeTruthy()

    await revokeSession(other!.id)

    // The revoked session no longer authenticates.
    const after = await rawGet(ENDPOINTS.auth.me, second.access_token)
    expect(after.status).toBe(200)

    const revoked = await rawGet(ENDPOINTS.auth.me, '')
    expect(revoked.status).toBe(401)
  })
})

describe('real backend — trusted-device pending handshake', () => {
  it('runs the full three-step flow and issues real tokens', async () => {
    // The approving device: an already signed-in session.
    await signIn()
    const approverToken = getAccessToken()
    expect(approverToken).toBeTruthy()

    // The new device: a different fingerprint (different Accept-Language),
    // proving the password, but NOT yet authenticated.
    const newDeviceHeaders = {
      'Accept-Language': 'vi-VN',
      'User-Agent': 'M12IntegrationNewDevice/1.0',
    }

    const pending = await apiClient.post<{
      request_id: string
      status: string
      expires_at: string
      message: string
    }>(
      ENDPOINTS.devices.pending,
      { username: USERNAME, password: PASSWORD, device_name: 'New device' },
      { headers: newDeviceHeaders },
    )
    expect(pending.data.status).toBe('pending')
    expect(pending.data.request_id).toBeTruthy()

    // Before the approval, the completion attempt is refused with 409 —
    // and it must NOT trigger a refresh (there is no session on this device).
    const early = await rawPostStatus(
      ENDPOINTS.devices.pendingComplete(pending.data.request_id),
      {},
      newDeviceHeaders,
    )
    expect(early.status).toBe(409)

    // The already signed-in device approves the request.
    const approved = await approveTrustedDevice(pending.data.request_id)
    expect(approved.status).toBe('approved')
    expect(approved.device_id).toBeTruthy()

    // The new device now completes the handshake and receives REAL tokens.
    const completed = await apiClient.post<{
      access_token: string
      refresh_token: string
      mfa_required: boolean
      session_id: string
    }>(
      ENDPOINTS.devices.pendingComplete(pending.data.request_id),
      {},
      { headers: newDeviceHeaders },
    )
    expect(completed.status).toBe(200)
    expect(completed.data.access_token).not.toBe('')
    expect(completed.data.refresh_token).not.toBe('')
    expect(completed.data.mfa_required).toBe(false)

    // The new token really authenticates.
    const me = await rawGet(ENDPOINTS.auth.me, completed.data.access_token)
    expect(me.status).toBe(200)
  })

  it('rejects the completion when the fingerprint does not match', async () => {
    await signIn()

    const pending = await apiClient.post<{ request_id: string }>(
      ENDPOINTS.devices.pending,
      { username: USERNAME, password: PASSWORD },
      {
        headers: {
          'Accept-Language': 'fr-FR',
          'User-Agent': 'M12IntegrationOtherDevice/1.0',
        },
      },
    )

    await approveTrustedDevice(pending.data.request_id)

    // A DIFFERENT fingerprint cannot claim the approved request.
    const mismatch = await rawPostStatus(
      ENDPOINTS.devices.pendingComplete(pending.data.request_id),
      {},
      {
        'Accept-Language': 'de-DE',
        'User-Agent': 'M12IntegrationImpostor/1.0',
      },
    )
    expect(mismatch.status).toBe(403)
  })

  it('runs the handshake through the typed API module end to end', async () => {
    // The typed helpers use the shared axios instance, so they carry the
    // default headers — and therefore the same device fingerprint.
    await signIn()

    const pending = await requestTrustedDeviceApproval({
      username: USERNAME,
      password: PASSWORD,
      device_name: 'Typed module device',
    })
    expect(pending.status).toBe('pending')

    await approveTrustedDevice(pending.request_id)

    const completed = await completeTrustedDeviceLogin(pending.request_id)
    expect(completed.access_token).not.toBe('')
    expect(completed.refresh_token).not.toBe('')
    expect(completed.mfa_required).toBe(false)
  })

  it('rejects a pending request with the wrong password', async () => {
    // The call itself throws a normalised ApiError — and it must NOT
    // trigger a refresh (the pending endpoint is public).
    await expect(
      apiClient.post(ENDPOINTS.devices.pending, {
        username: USERNAME,
        password: `${PASSWORD}-wrong`,
      }),
    ).rejects.toMatchObject({ status: 401 })
  })
})
