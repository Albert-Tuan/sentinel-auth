/**
 * E2E-07 — Role Based Access Control.
 *
 * The route guards of the frontend AND the authorization of the
 * backend, for every role of the demo stack.
 *
 * ---------------------------------------------------------------------------
 * WHY BOTH LAYERS ARE TESTED
 * ---------------------------------------------------------------------------
 *
 * The frontend guard and the backend authorization are TWO INDEPENDENT
 * lines of defence, and a test that only exercises one of them proves
 * nothing about the other:
 *
 *   - the frontend guard decides whether the SCREEN is shown;
 *   - the backend decides whether the DATA is served.
 *
 * A guard that let a user open the URL of a section they may not enter
 * would show an empty screen and a 403 in the console — the user sees
 * nothing and cannot tell what happened.  A backend that served the
 * data anyway would leak it.  The scenario therefore checks both:
 * what the user SEES, and what the API ANSWERS.
 *
 * ---------------------------------------------------------------------------
 * WHY THE 401 CASE IS CHECKED AGAINST THE REAL API
 * ---------------------------------------------------------------------------
 *
 * A 401 is the answer to a request without a valid session.  The
 * frontend cannot produce that request through the UI — it would never
 * make it — so the check goes to the API directly, with and without a
 * token.  A test that only checked "the browser was sent to the login
 * screen" would never touch the backend's own answer.
 */

import { expect, test } from './support/fixtures'
import { loginAndWait, logoutVia, passwordOf } from './support/login'
import { navigateClientSide, navigateTo } from './support/navigation'
import { apiRequest } from './support/api'
import { otpOffset, waitForCode } from './support/otp'
import { resetRateLimits } from './support/fixtureBridge'
import type { FixtureManifest } from './support/manifest'

/** A section of the application, with the role that may enter it. */
interface Section {
  /** The section id of the route table. */
  id: string
  /** The path of the section's landing page. */
  path: string
  /** The heading the landing page shows. */
  heading: string
}

/**
 * The sections of the route table, with the roles that may enter them.
 *
 * The table is the SINGLE SOURCE OF TRUTH of the frontend
 * (`src/app/router/policy.ts`), and the backend contracts mirror it
 * one-to-one:
 *
 *   /alerts    → SOC_ANALYST | SECURITY_MANAGER
 *   /policies  → SECURITY_ADMIN | SECURITY_MANAGER
 *   /admin/*   → SECURITY_ADMIN
 *   /manager/* → SECURITY_MANAGER
 *   /sessions, /devices, /profile → every authenticated user
 */
const ROLE_SECTIONS: Section[] = [
  { id: 'alerts', path: '/alerts', heading: 'Hàng đợi cảnh báo' },
  { id: 'policies', path: '/policies', heading: 'Chính sách phát hiện' },
  { id: 'admin', path: '/admin/users', heading: 'Quản lý người dùng' },
  { id: 'manager', path: '/manager/dashboard', heading: 'Bảng điều khiển quản lý' },
]

/** The sections every authenticated user may enter. */
const SELF_SERVICE: Section[] = [
  { id: 'self-service', path: '/sessions', heading: 'Phiên đăng nhập' },
]

test.describe('E2E-07 — RBAC', () => {
  test('hides the sections a role may not enter and shows the forbidden screen', async ({
    page,
    manifest,
  }) => {
    await loginAndWait(page, manifest, 'user')

    // The plain user reaches the self-service screens.
    for (const section of SELF_SERVICE) {
      await navigateTo(page, section.path)
      await expect(page.getByRole('heading', { name: section.heading })).toBeVisible({
        timeout: 20_000,
      })
    }

    // The sidebar offers NOTHING of the guarded sections: a link that
    // would answer 403 is not shown in the first place.
    for (const section of ROLE_SECTIONS) {
      await expect(
        page.locator(`a[href="${section.path}"]`),
        `the sidebar offers '${section.path}' to a plain USER`,
      ).toHaveCount(0)
    }

    // --- and the URL is refused too ----------------------------------
    //
    // A hidden link is not a guard.  The URL is opened from INSIDE the
    // document — a reload would drop the in-memory session and the
    // authentication guard would catch the visitor first — and the ROLE
    // guard has to send the user to the forbidden screen.
    for (const section of ROLE_SECTIONS) {
      await navigateClientSide(page, section.path)

      await expect(page).toHaveURL(/\/forbidden/, { timeout: 20_000 })
      await expect(
        page.getByRole('heading', { name: 'Không đủ quyền truy cập' }),
      ).toBeVisible()
    }
  })

  test('lets each privileged role into its own sections and refuses the others', async ({
    page,
    manifest,
  }) => {
    // The analyst enters the alert queue and nothing else.
    await loginAndWait(page, manifest, 'analyst')

    await navigateTo(page, '/alerts')
    await expect(page.getByRole('heading', { name: 'Hàng đợi cảnh báo' })).toBeVisible({
      timeout: 20_000,
    })

    for (const section of [
      ROLE_SECTIONS.find((entry) => entry.id === 'policies')!,
      ROLE_SECTIONS.find((entry) => entry.id === 'admin')!,
      ROLE_SECTIONS.find((entry) => entry.id === 'manager')!,
    ]) {
      await navigateClientSide(page, section.path)
      await expect(page).toHaveURL(/\/forbidden/, { timeout: 20_000 })
    }

    // The refusal does not end the session: the analyst is still signed
    // in and can go back to a screen it may use.  The forbidden screen
    // has no shell of its own, so the way back is the self-service
    // section.
    await navigateClientSide(page, '/sessions')
    await expect(page.getByRole('heading', { name: 'Phiên đăng nhập' })).toBeVisible({
      timeout: 20_000,
    })

    // --- the manager -------------------------------------------------
    //
    // The forbidden screen has no shell of its own, so the way back to
    // a screen with the top bar is the self-service section.
    await navigateClientSide(page, '/sessions')
    await logoutVia(page)
    await loginAndWait(page, manifest, 'manager')

    for (const section of [
      ROLE_SECTIONS.find((entry) => entry.id === 'alerts')!,
      ROLE_SECTIONS.find((entry) => entry.id === 'policies')!,
      ROLE_SECTIONS.find((entry) => entry.id === 'manager')!,
    ]) {
      await navigateTo(page, section.path)
      await expect(page.getByRole('heading', { name: section.heading })).toBeVisible({
        timeout: 20_000,
      })
    }

    await navigateClientSide(page, '/admin/users')
    await expect(page).toHaveURL(/\/forbidden/, { timeout: 20_000 })

    // --- the admin ---------------------------------------------------
    await navigateClientSide(page, '/sessions')
    await logoutVia(page)
    await loginAndWait(page, manifest, 'admin')

    for (const section of [
      ROLE_SECTIONS.find((entry) => entry.id === 'policies')!,
      ROLE_SECTIONS.find((entry) => entry.id === 'admin')!,
    ]) {
      await navigateTo(page, section.path)
      await expect(page.getByRole('heading', { name: section.heading })).toBeVisible({
        timeout: 20_000,
      })
    }

    await navigateClientSide(page, '/alerts')
    await expect(page).toHaveURL(/\/forbidden/, { timeout: 20_000 })
  })

  test('answers 401 without a token and 403 with the wrong role', async ({
    manifest,
  }) => {
    // --- 401: no session at all -------------------------------------
    for (const path of [
      '/admin/users',
      '/alerts',
      '/manager/dashboard',
      '/auth/sessions',
    ]) {
      const anonymous = await apiRequest(path)
      expect(anonymous.status, `${path} answered ${anonymous.raw}`).toBe(401)
    }

    // --- 403: a valid session of the wrong role ----------------------
    const userToken = await tokenFor(manifest, 'user')

    for (const path of ['/admin/users', '/alerts', '/manager/dashboard']) {
      const wrongRole = await apiRequest(path, { token: userToken })
      expect(wrongRole.status, `${path} answered ${wrongRole.raw}`).toBe(403)
    }

    // --- and 200 with the right role ---------------------------------
    const analystToken = await tokenFor(manifest, 'analyst')

    const allowed = await apiRequest('/alerts', { token: analystToken })
    expect(allowed.status, allowed.raw).toBe(200)

    const stillForbidden = await apiRequest('/admin/users', { token: analystToken })
    expect(stillForbidden.status, stillForbidden.raw).toBe(403)

    // --- a GARBAGE token is a 401, not a 403 -------------------------
    //
    // The distinction matters: a malformed token is an UNAUTHENTICATED
    // request, while a valid token of a wrong role is an unauthorized
    // one.  A backend that answered 403 for both would tell a client
    // with an expired session that it needs different roles — and the
    // client would then try to log in with a role it does not have.
    const garbage = await apiRequest('/alerts', { token: 'not-a-real-token' })
    expect(garbage.status, garbage.raw).toBe(401)
  })
})

/**
 * The bearer token of a demo account.
 *
 * The account is held for an MFA challenge by the risk gate on a fresh
 * device, so the helper completes the handshake through the SMTP sink —
 * exactly the way the browser does.
 */
async function tokenFor(
  manifest: FixtureManifest,
  key: 'user' | 'analyst' | 'admin' | 'manager',
): Promise<string> {
  const account = manifest.core.users[key]
  const offset = otpOffset()

  await resetRateLimits()

  const login = await apiRequest('/auth/login', {
    method: 'POST',
    body: { username: account.username, password: passwordOf(key) },
  })

  const body = (login.body ?? {}) as Record<string, unknown>
  if (!body.mfa_required) {
    return String(body.access_token ?? '')
  }

  const code = await waitForCode(account.email, offset)
  const verified = await apiRequest('/auth/mfa/verify', {
    method: 'POST',
    body: { session_id: body.session_id, mfa_code: code },
  })

  expect(verified.status, verified.raw).toBe(200)
  return String((verified.body as Record<string, unknown>).access_token ?? '')
}
