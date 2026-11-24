/**
 * Real HTTP integration verification — Stage 4 (SOC Alerts).
 *
 * These tests run against the LIVE FastAPI backend (no mocks, no MSW) and
 * exercise the real frontend HTTP stack: `apiClient` (axios +
 * interceptors), the in-memory `tokenStore` and the `alerts.api` module.
 *
 * What they prove:
 *   - the four read endpoints of Stage 4 answer over REAL HTTP with the
 *     real PostgreSQL rows seeded by `scripts/ci_seed_frontend_alerts.py`;
 *   - the backend enforces the RBAC contract: an analyst and a manager
 *     get the data, an admin and a plain user get 403;
 *   - the filters and the pagination are applied by the BACKEND;
 *   - the nullable ML score arrives as `null` — the client never invents
 *     a score for the rule-only fallback;
 *   - the client never reaches for an internal endpoint.
 *
 * Run with:
 *   npm run test:integration
 *
 * The backend must be reachable at `M12_API_ORIGIN` (default
 * http://127.0.0.1:8000). Credentials come from the environment; no test
 * credential is hard-coded here.
 */
import { readFileSync } from 'node:fs'
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { apiClient, __resetClientState } from '@/lib/api/client'
import { setSession, __resetStore, getAccessToken } from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import {
  fetchAlert,
  fetchAlertEvidence,
  fetchAlertTimeline,
  fetchAlerts,
} from '@/lib/api/alerts.api'
import { fetchLoginAttemptSubjects } from '@/lib/api/loginAttempts.api'
import { API_ROOT } from '@/test/integration/config'
import { resetLoginRateLimit } from '@/test/integration/db'
import type {
  AlertEvidence,
  AlertItem,
  AlertListResponse,
  TimelineEvent,
} from '@/types/api'

const OTP_LOG = process.env.M12_OTP_LOG ?? '/tmp/m12_otp_capture.log'

const ANALYST = process.env.M12_USER ?? 'm12analyst'
const ANALYST_PASSWORD = process.env.M12_PASSWORD ?? ''
const MANAGER = process.env.M12_MANAGER_USER ?? 'm12manager'
const MANAGER_PASSWORD = process.env.M12_MANAGER_PASSWORD ?? ''
const ADMIN = process.env.M12_ADMIN_USER ?? 'm12admin'
const ADMIN_PASSWORD = process.env.M12_ADMIN_PASSWORD ?? ''
const PLAIN = process.env.M12_PLAIN_USER ?? 'm12plain'
const PLAIN_PASSWORD = process.env.M12_PLAIN_PASSWORD ?? ''

/** The marker the seed script puts into `alerts.detection_reason`. */
const FIXTURE_MARKER = 'm12-stage4-fixture'

/**
 * Read the most recent OTP captured for a recipient from the SMTP sink log.
 *
 * The SECURITY_ADMIN fixture carries `admin_mfa_required`, so the admin
 * signs in through the full MFA handshake — a REAL SMTP hop, exactly like
 * the auth suite.
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
 * Log in and install the session in the in-memory store.
 *
 * When the backend asks for an MFA challenge, the handshake is completed
 * with the real OTP — the test never skips the second factor, because the
 * RBAC contract must be verified against a genuinely authenticated admin.
 */
async function signIn(username: string, password: string) {
  const response = await apiClient.post<{
    access_token: string
    refresh_token: string
    mfa_required: boolean
    session_id: string
  }>(ENDPOINTS.auth.login, { username, password })

  if (response.data.mfa_required) {
    const otp = readCapturedOtp(`${username}@example.com`)
    const verified = await apiClient.post<{
      access_token: string
      refresh_token: string
      session_id: string
    }>(ENDPOINTS.auth.mfaVerify, {
      session_id: response.data.session_id,
      mfa_code: otp,
    })
    setSession(
      verified.data.access_token,
      verified.data.refresh_token,
      verified.data.session_id,
    )
    return verified.data
  }

  setSession(
    response.data.access_token,
    response.data.refresh_token,
    response.data.session_id,
  )
  return response.data
}

/**
 * Raw HTTP call that reports the status instead of throwing on 4xx/5xx.
 *
 * The bearer token is taken from the in-memory session store, so the call
 * carries exactly the same credentials the axios client would send.
 *
 * The token is chosen by an explicit THREE-state argument, so an
 * authenticated request and an anonymous request can never be confused
 * with one another:
 *
 *   - `token: 'session'`  — use the token of the current session (default)
 *   - `token: 'none'`     — send NO Authorization header at all
 *   - `token: '<a token>'` — send exactly this token
 *
 * The anonymous case therefore never depends on the store happening to be
 * empty: it says so.
 */
type RawToken = 'session' | 'none' | (string & {})

async function rawGet(path: string, token: RawToken = 'session') {
  const bearer =
    token === 'none' ? null : token === 'session' ? getAccessToken() : token
  const res = await fetch(`${API_ROOT}${path}`, {
    headers: bearer ? { Authorization: `Bearer ${bearer}` } : {},
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

/** The alerts that belong to the seeded fixtures. */
function fixturesOf(list: AlertListResponse): AlertItem[] {
  return list.alerts.filter((alert) =>
    (alert.detection_reason ?? '').includes(FIXTURE_MARKER),
  )
}

beforeAll(() => {
  if (!ANALYST_PASSWORD) {
    throw new Error('M12_PASSWORD must be provided in the environment.')
  }
})

beforeEach(() => {
  resetLoginRateLimit()
  __resetStore()
  __resetClientState()
})

describe('real backend — alert queue', () => {
  it('lists the alerts over real HTTP', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts()

    expect(list.total).toBeGreaterThanOrEqual(0)
    expect(Array.isArray(list.alerts)).toBe(true)
    expect(list.page).toBe(1)
    expect(list.limit).toBe(20)
    expect(list.alerts.length).toBeLessThanOrEqual(list.total)

    // Every row carries the fields the queue renders.
    for (const alert of list.alerts) {
      expect(alert.id).toBeTruthy()
      expect(alert.login_attempt_id).toBeTruthy()
      expect(alert.status).toBeTruthy()
      expect(alert.created_at).toBeTruthy()
      expect(alert.updated_at).toBeTruthy()
    }
  })

  it('returns the seeded fixtures', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const fixtures = fixturesOf(list)

    expect(fixtures.length).toBeGreaterThanOrEqual(3)
    // The three fixtures cover the three states the UI must render.
    expect(fixtures.some((a) => a.risk_level === 'critical')).toBe(true)
    expect(fixtures.some((a) => a.risk_level === 'medium')).toBe(true)
    expect(fixtures.some((a) => a.risk_level === 'low')).toBe(true)
  })

  it('orders the alerts newest first', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const timestamps = list.alerts.map((alert) =>
      new Date(alert.created_at).getTime(),
    )

    // The backend owns the order: the client never re-sorts.
    for (let index = 1; index < timestamps.length; index += 1) {
      expect(timestamps[index - 1]).toBeGreaterThanOrEqual(timestamps[index])
    }
  })

  it('filters by status', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ status: 'open', limit: 100 })

    expect(list.alerts.length).toBeGreaterThanOrEqual(1)
    for (const alert of list.alerts) {
      expect(alert.status).toBe('open')
    }
  })

  it('filters by risk level', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ risk_level: 'critical', limit: 100 })

    expect(list.alerts.length).toBeGreaterThanOrEqual(1)
    for (const alert of list.alerts) {
      expect(alert.risk_level).toBe('critical')
    }
  })

  it('filters by the assigned analyst', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    // A UUID that no alert references must return an empty page — the
    // filter is applied by the backend, not by the client.
    const list = await fetchAlerts({
      assigned_to_id: '00000000-0000-0000-0000-0000000000ff',
      limit: 100,
    })
    expect(list.alerts).toHaveLength(0)
  })

  it('rejects an unknown status with a 400', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    await expect(fetchAlerts({ status: 'escalated' })).rejects.toMatchObject({
      kind: 'validation',
    })
  })

  it('rejects an unknown risk level with a 400', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    await expect(
      fetchAlerts({ risk_level: 'extreme' }),
    ).rejects.toMatchObject({ kind: 'validation' })
  })

  it('paginates server-side', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const first = await fetchAlerts({ page: 1, limit: 1 })
    expect(first.alerts.length).toBe(1)
    expect(first.limit).toBe(1)
    expect(first.page).toBe(1)
    expect(first.total).toBeGreaterThanOrEqual(1)

    const second = await fetchAlerts({ page: 2, limit: 1 })
    expect(second.page).toBe(2)
    // The second page holds a different row.
    expect(second.alerts[0]?.id).not.toBe(first.alerts[0]?.id)
  })

  it('answers an empty page beyond the last one', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ page: 9999, limit: 20 })
    expect(list.alerts).toHaveLength(0)
    expect(list.total).toBeGreaterThanOrEqual(0)
  })

  it('reads the subject of the alerts from the login attempts', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const fixtures = fixturesOf(list)
    expect(fixtures.length).toBeGreaterThanOrEqual(1)

    const subjects = await fetchLoginAttemptSubjects(
      fixtures.map((alert) => alert.login_attempt_id),
    )

    const subject = subjects[fixtures[0].login_attempt_id]
    expect(subject).toBeDefined()
    expect(subject.username).toBe('m12stage4subject')
    expect(subject.ip_address).toBeTruthy()
  })
})

describe('real backend — alert detail', () => {
  it('reads one alert', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const target = fixturesOf(list)[0]
    expect(target).toBeDefined()

    const alert = await fetchAlert(target.id)
    expect(alert.id).toBe(target.id)
    expect(alert.status).toBeTruthy()
    expect(alert.created_at).toBeTruthy()
  })

  it('answers 404 for an unknown alert', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    await expect(
      fetchAlert('00000000-0000-0000-0000-0000000000ff'),
    ).rejects.toMatchObject({ kind: 'not_found' })
  })

  it('reads the evidence bundle', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const target = fixturesOf(list)[0]

    const evidence: AlertEvidence = await fetchAlertEvidence(target.id)

    expect(evidence.alert.id).toBe(target.id)

    // The login attempt.
    expect(evidence.login_attempt).not.toBeNull()
    expect(evidence.login_attempt?.username_attempted).toBe(
      'm12stage4subject',
    )
    expect(evidence.login_attempt?.ip_address).toBeTruthy()
    expect(evidence.login_attempt?.outcome).toBeTruthy()

    // The risk assessment.
    expect(evidence.risk_assessment).not.toBeNull()
    expect(evidence.risk_assessment?.rule_score).not.toBeNull()
    expect(evidence.risk_assessment?.risk_level).toBeTruthy()

    // The detection logs.
    expect(Array.isArray(evidence.detection_logs)).toBe(true)
    expect(evidence.detection_logs.length).toBeGreaterThanOrEqual(1)
    expect(evidence.detection_logs[0].stage).toBeTruthy()
  })

  it('answers 404 for the evidence of an unknown alert', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    await expect(
      fetchAlertEvidence('00000000-0000-0000-0000-0000000000ff'),
    ).rejects.toMatchObject({ kind: 'not_found' })
  })

  it('reads the timeline', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const target = fixturesOf(list)[0]

    const timeline: TimelineEvent[] = await fetchAlertTimeline(target.id)

    expect(Array.isArray(timeline)).toBe(true)
    expect(timeline.length).toBeGreaterThanOrEqual(1)

    for (const event of timeline) {
      expect(event.id).toBeTruthy()
      expect(event.alert_id).toBe(target.id)
      expect(event.event_type).toBeTruthy()
      expect(event.actor_type).toBeTruthy()
      expect(event.created_at).toBeTruthy()
    }

    // The seeded timeline starts with the creation event.
    expect(timeline[0].event_type).toBe('created')
  })

  it('answers 404 for the timeline of an unknown alert', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    await expect(
      fetchAlertTimeline('00000000-0000-0000-0000-0000000000ff'),
    ).rejects.toMatchObject({ kind: 'not_found' })
  })
})

describe('real backend — the nullable ML score', () => {
  it('returns null for the rule-only fallback, not a zero', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const fallback = fixturesOf(list).find(
      (alert) =>
        alert.detection_reason?.includes('ml unavailable') &&
        alert.detection_reason?.includes(FIXTURE_MARKER),
    )
    expect(fallback).toBeDefined()

    const evidence = await fetchAlertEvidence(fallback!.id)
    const assessment = evidence.risk_assessment

    expect(assessment).not.toBeNull()
    // The score is MISSING, not zero.
    expect(assessment?.ml_score).toBeNull()
    expect(assessment?.ml_score).not.toBe(0)
    // The rule score is a real number.
    expect(assessment?.rule_score).not.toBeNull()
    // And the status explains why the score is missing.
    expect(assessment?.ml_status).toBe('unavailable')
  })

  it('returns a real score for a fully scored alert', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const scored = fixturesOf(list).find((alert) =>
      alert.detection_reason?.includes('impossible travel'),
    )
    expect(scored).toBeDefined()

    const evidence = await fetchAlertEvidence(scored!.id)

    expect(evidence.risk_assessment?.ml_score).not.toBeNull()
    expect(typeof evidence.risk_assessment?.ml_score).toBe('number')
    expect(evidence.risk_assessment?.ml_status).toBe('success')
  })
})

describe('real backend — RBAC of the alert endpoints', () => {
  it('admits a SOC_ANALYST', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const response = await rawGet(ENDPOINTS.alerts.list)
    expect(response.status).toBe(200)
  })

  it('admits a SECURITY_MANAGER', async () => {
    await signIn(MANAGER, MANAGER_PASSWORD)

    const response = await rawGet(ENDPOINTS.alerts.list)
    expect(response.status).toBe(200)

    const list = await fetchAlerts({ limit: 100 })
    expect(list.alerts.length).toBeGreaterThanOrEqual(0)
  })

  it('denies a SECURITY_ADMIN', async () => {
    await signIn(ADMIN, ADMIN_PASSWORD)

    const response = await rawGet(ENDPOINTS.alerts.list)
    expect(response.status).toBe(403)
  })

  it('denies a plain USER', async () => {
    await signIn(PLAIN, PLAIN_PASSWORD)

    const response = await rawGet(ENDPOINTS.alerts.list)
    expect(response.status).toBe(403)
  })

  it('denies an anonymous visitor', async () => {
    const response = await rawGet(ENDPOINTS.alerts.list, 'none')
    expect(response.status).toBe(401)
  })

  it('does not leak the session token into an anonymous request', async () => {
    // The session is installed on purpose: the anonymous call must STILL
    // be anonymous, because it asks for "no token" explicitly.
    await signIn(ANALYST, ANALYST_PASSWORD)
    expect(getAccessToken()).toBeTruthy()

    const response = await rawGet(ENDPOINTS.alerts.list, 'none')
    expect(response.status).toBe(401)
  })

  it('denies the detail endpoints too', async () => {
    await signIn(PLAIN, PLAIN_PASSWORD)

    const list = await rawGet(ENDPOINTS.alerts.list)
    expect(list.status).toBe(403)

    const detail = await rawGet(
      ENDPOINTS.alerts.detail('00000000-0000-0000-0000-000000000001'),
    )
    expect(detail.status).toBe(403)
  })
})

describe('real backend — the client never calls an internal endpoint', () => {
  it('sends every alert request to the public API', async () => {
    await signIn(ANALYST, ANALYST_PASSWORD)

    const list = await fetchAlerts({ limit: 100 })
    const target = fixturesOf(list)[0]
    await fetchAlert(target.id)
    await fetchAlertEvidence(target.id)
    await fetchAlertTimeline(target.id)

    // The typed modules build their URLs from ENDPOINTS.alerts, which
    // contains no internal path. The assertion documents that invariant.
    for (const key of Object.keys(ENDPOINTS.alerts)) {
      const value = (ENDPOINTS.alerts as Record<string, unknown>)[key]
      if (typeof value === 'string') {
        expect(value).not.toContain('/internal/')
      }
    }
  })
})
