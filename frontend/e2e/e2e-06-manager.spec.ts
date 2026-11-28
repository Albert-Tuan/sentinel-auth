/**
 * E2E-06 — the SECURITY_MANAGER analytics.
 *
 * All five analytics screens, plus the two contracts that separate a
 * working screen from a lying one:
 *
 *   - **a `null` metric is not a zero.**  The backend uses `null` for
 *     both an empty population and a missing source, so the screen must
 *     render "không có dữ liệu" and never a `0`;
 *   - **a degraded payload is not an error.**  A source that is down
 *     makes the payload HTTP 200 with the affected section `null`, and
 *     the screen must say WHICH source is down.  Only an endpoint that
 *     consumes ONE source answers 503.
 *
 * ---------------------------------------------------------------------------
 * WHY THE FAILURE IS A REAL FAULT
 * ---------------------------------------------------------------------------
 *
 * The degraded/503 contract is proved by BREAKING the ML source for
 * real: the table the ML statistics are computed from is renamed, so
 * the read fails with a genuine database error.  Nothing is mocked and
 * no application code is touched.
 *
 * That matters because the alternative — faking a network failure — would
 * only prove that the frontend can render a payload someone handed it.
 * Breaking the source proves that the FACADE classifies the failure
 * correctly and that the screen reacts to the classification.
 *
 * The restore runs in an `afterEach` hook, so a failed scenario never
 * leaves the demo stack degraded.
 */

import { expect, test } from './support/fixtures'
import { loginAndWait } from './support/login'
import { navigateTo } from './support/navigation'
import { breakMlSource, restoreMlSource } from './support/fixtureBridge'
import { apiRequest } from './support/api'
import { otpOffset, waitForCode } from './support/otp'
import { resetRateLimits } from './support/fixtureBridge'
import { passwordOf } from './support/login'
import type { FixtureManifest } from './support/manifest'

/** The five analytics screens of the SECURITY_MANAGER role. */
const SCREENS = [
  { path: '/manager/dashboard', heading: 'Bảng điều khiển quản lý' },
  { path: '/manager/trends', heading: 'Xu hướng an ninh' },
  { path: '/manager/alerts', heading: 'Phân tích cảnh báo' },
  { path: '/manager/soc-kpi', heading: 'KPI SOC' },
  { path: '/manager/ml-stats', heading: 'Thống kê máy học' },
] as const

/**
 * The label of every KPI on the SOC board.
 *
 * The mapping lets the test address the tile of ONE KPI, so the
 * assertion cannot be satisfied by another number that happens to sit
 * on the same screen.
 */
const KPI_LABELS: Record<string, string> = {
  mtta_seconds: 'MTTA',
  mttr_seconds: 'MTTR',
  alerts_per_analyst: 'Cảnh báo / analyst',
  audit_events: 'Sự kiện kiểm toán',
  acknowledgement_rate: 'Tỉ lệ xác nhận',
  resolution_rate: 'Tỉ lệ xử lý',
  false_positive_rate: 'Tỉ lệ báo động giả',
  escalation_rate: 'Tỉ lệ escalate',
  enforcement_attempted: 'Số lần thực thi',
  enforcement_succeeded: 'Số lần thành công',
  enforcement_success_rate: 'Tỉ lệ thành công',
  ml_fallback_count: 'Fallback ML',
  mfa_enrollment_rate: 'Tỉ lệ bật MFA',
  forced_mfa_users: 'Người dùng bắt buộc MFA',
  ml_assessments: 'Số lần đánh giá ML',
}

test.describe('E2E-06 — SECURITY_MANAGER analytics', () => {
  /**
   * The ML source is restored after EVERY test — including a failed
   * one — so a scenario that dies half-way through never leaves the
   * demo stack without its ML statistics.
   */
  test.afterEach(async () => {
    await restoreMlSource()
  })

  test('shows all five analytics screens with a readable envelope', async ({
    page,
    manifest,
  }) => {
    await loginAndWait(page, manifest, 'manager')

    for (const screen of SCREENS) {
      await navigateTo(page, screen.path)
      await expect(
        page.getByRole('heading', { name: screen.heading }),
      ).toBeVisible({ timeout: 20_000 })

      // Every screen shows the EFFECTIVE window: the backend applies a
      // default window when the caller sends none, so "last 24 hours"
      // and "last 30 days" must be visible on the screen.
      await expect(page.getByText('CỬA SỔ PHÂN TÍCH')).toBeVisible()
      await expect(page.getByText('SINH LÚC')).toBeVisible()
    }
  })

  test('renders a null metric as "no data" and never as a zero', async ({
    page,
    manifest,
  }) => {
    await loginAndWait(page, manifest, 'manager')

    // The API is the authority on what is `null` and what is `0`.
    const token = await managerToken(manifest)

    const kpi = await apiRequest('/manager/soc-kpi', { token })
    expect(kpi.status, kpi.raw).toBe(200)
    const kpis = (kpi.body as Record<string, Record<string, unknown>>).kpis

    // The backend uses `null` for a KPI over an EMPTY population, and a
    // real number — including a real ZERO — for a KPI that was
    // measured.  The two are different facts.
    const nullKeys = Object.entries(kpis)
      .filter(([, value]) => value === null)
      .map(([key]) => key)

    const zeroKeys = Object.entries(kpis)
      .filter(([, value]) => value === 0)
      .map(([key]) => key)

    await navigateTo(page, '/manager/soc-kpi')
    await expect(page.getByRole('heading', { name: 'KPI SOC' })).toBeVisible({
      timeout: 20_000,
    })

    // --- a measured ZERO is shown as a zero --------------------------
    //
    // The tile of a KPI is addressed through its own label, so the
    // assertion cannot be satisfied by some other number on the board.
    for (const key of zeroKeys) {
      const label = KPI_LABELS[key]
      if (!label) continue

      const tile = page.getByText(label, { exact: true }).locator('..')

      // The zero is on the screen.
      await expect(tile.getByText('0', { exact: true })).toBeVisible()

      // And it is NOT the "no data" marker: a zero is a measurement.
      await expect(tile.getByText('— không có dữ liệu')).toHaveCount(0)
    }

    // --- a null KPI is shown as "no data" ----------------------------
    for (const key of nullKeys) {
      const label = KPI_LABELS[key]
      if (!label) continue

      const tile = page.getByText(label, { exact: true }).locator('..')
      await expect(tile.getByText('— không có dữ liệu')).toBeVisible()
    }

    // --- and the board as a whole -------------------------------------
    //
    // The count of the markers has to agree with the API: one marker
    // per null KPI, and none for a KPI that was measured.  A screen
    // that rendered every zero as "no data" would break this.
    const markers = await page.getByText('— không có dữ liệu').count()
    expect(markers).toBe(nullKeys.length)
  })

  test('degrades to a 200 payload when a source is down, and answers 503 when every source is', async ({
    page,
    manifest,
  }) => {
    await loginAndWait(page, manifest, 'manager')

    const token = await managerToken(manifest)

    // --- the healthy state --------------------------------------------
    const healthy = await apiRequest('/manager/dashboard', { token })
    expect(healthy.status, healthy.raw).toBe(200)
    expect((healthy.body as Record<string, unknown>).degraded).toBe(false)

    // --- the broken source ---------------------------------------------
    await breakMlSource()

    // The DASHBOARD consumes three sources, so one broken source
    // leaves a VALID payload: HTTP 200, `degraded: true`, and the
    // broken section `null`.
    const degraded = await apiRequest('/manager/dashboard', { token })
    expect(degraded.status, degraded.raw).toBe(200)

    const degradedBody = degraded.body as Record<string, unknown>
    expect(degradedBody.degraded).toBe(true)
    expect(degradedBody.ml).toBeNull()

    const sources = degradedBody.sources as Record<string, { status: string; detail: string }>
    expect(sources.ml.status).toBe('unavailable')
    expect(sources.ml.detail).toBe('database_error')

    // The sections that do NOT depend on the broken source are still
    // present: a degraded payload is not an empty payload.
    expect(degradedBody.core).not.toBeNull()
    expect(degradedBody.detection).not.toBeNull()

    // --- the screen reacts to the degradation --------------------------
    //
    // The screen is reloaded so the analytics are fetched AGAIN.  The
    // query cache of the application keeps a successful payload for
    // 30 seconds, so a screen that was already open would keep showing
    // the healthy numbers — and the test would then prove nothing.
    //
    // A reload drops the in-memory session, so the manager signs in
    // again.  That is not a workaround: it is the same journey a user
    // takes when the dashboard has to be re-read.
    await page.reload()
    await loginAndWait(page, manifest, 'manager')

    await expect(
      page.getByRole('heading', { name: 'Bảng điều khiển quản lý' }),
    ).toBeVisible({ timeout: 20_000 })

    // The banner names the degraded mode and the source that is down.
    // The reason code is the CLOSED vocabulary of the facade
    // ("database_error"), and the badge names the source next to it.
    await expect(page.getByText('DEGRADED_MODE')).toBeVisible()
    await expect(page.getByText('ML: database_error')).toBeVisible()

    // The broken section renders the "no data" panel, NOT zeros.
    await expect(
      page.getByText('Nguồn dữ liệu của phần này không khả dụng'),
    ).toBeVisible()

    // --- and a single-source endpoint answers 503 ----------------------
    //
    // `/manager/ml-stats` consumes the ML source ONLY, so the very same
    // fault is a 503 there — and there is nothing to render.
    const mlStats = await apiRequest('/manager/ml-stats', { token })
    expect(mlStats.status).toBe(503)
    expect(String(mlStats.raw)).toContain('analytics sources unavailable')

    // The screen shows the failure state — and the query cache of the
    // application holds a successful payload for 30 seconds, so the
    // screen has to be re-read rather than re-rendered.
    await page.reload()
    await loginAndWait(page, manifest, 'manager')
    await navigateTo(page, '/manager/ml-stats')

    await expect(
      page.getByText('Không thể tải thống kê máy học'),
    ).toBeVisible({ timeout: 20_000 })
  })
})

/**
 * The bearer token of the demo manager.
 *
 * The manager account is held for an MFA challenge by the risk gate on
 * a fresh device, so the helper completes the handshake through the SMTP
 * sink — exactly the way the browser does.
 */
async function managerToken(manifest: FixtureManifest): Promise<string> {
  const manager = manifest.core.users.manager
  const offset = otpOffset()

  await resetRateLimits()

  const login = await apiRequest('/auth/login', {
    method: 'POST',
    body: { username: manager.username, password: passwordOf('manager') },
  })

  const body = (login.body ?? {}) as Record<string, unknown>
  if (!body.mfa_required) {
    return String(body.access_token ?? '')
  }

  const code = await waitForCode(manager.email, offset)
  const verified = await apiRequest('/auth/mfa/verify', {
    method: 'POST',
    body: { session_id: body.session_id, mfa_code: code },
  })

  expect(verified.status, verified.raw).toBe(200)
  return String((verified.body as Record<string, unknown>).access_token ?? '')
}
