/**
 * E2E-01 — the USER journey.
 *
 * Login → Sessions → Trusted Devices → revoke a session → logout.
 *
 * The account is `demo_user`, the plainest one: it holds only the base
 * role `USER`, so every screen it reaches is a self-service screen.  The
 * journey therefore proves the SELF-SERVICE contract end to end, with
 * the real backend, the real session table and the real device table.
 *
 * ---------------------------------------------------------------------------
 * WHY THE SECOND SESSION IS CREATED FIRST
 * ---------------------------------------------------------------------------
 *
 * The session list is read through TanStack Query with a 30-second
 * `staleTime`.  A second visit to `/sessions` inside that window is
 * answered from the CACHE, not from the backend — so a session created
 * after the first visit would not show up.
 *
 * The test therefore creates the second session BEFORE the first
 * browser opens the list.  Both sessions then exist when the list is
 * fetched, and the list on screen is the backend's real answer.
 *
 * The state this test mutates:
 *
 *   - it revokes ONE session of `demo_user` — a session the test itself
 *     created;
 *   - it trusts a device — a device it names itself.
 *
 * It never touches a seeded row that another scenario owns, so the test
 * is re-runnable on the same demo stack.
 */

import { expect, test } from './support/fixtures'
import { loginAndWait, logoutVia, submitLogin, completeMfaIfRequired } from './support/login'
import { navigateTo, openDirect } from './support/navigation'
import { otpOffset } from './support/otp'
import { currentSessionId, revokeSessionThroughUi, sessionIds } from './support/sessions'

test.describe('E2E-01 — USER', () => {
  test('logs in, reads the sessions and the devices, revokes a session and logs out', async ({
    page,
    manifest,
  }) => {
    const username = manifest.core.users.user.username

    // --- the second session, created FIRST ------------------------------
    //
    // The second browser context signs in before the first one opens the
    // session list, so the list's first fetch already contains it.
    const secondContext = await page.context().browser()!.newContext()
    const secondPage = await secondContext.newPage()
    const secondOffset = otpOffset()
    await submitLogin(secondPage, username, 'DemoPass!2026')
    await completeMfaIfRequired(secondPage, manifest, 'user', secondOffset)
    await expect(secondPage.getByText(username).first()).toBeVisible()

    // --- the login ------------------------------------------------------
    await loginAndWait(page, manifest, 'user')

    // The top bar shows the signed-in account and its roles, so the
    // session is genuinely established.
    await expect(page.getByText(username).first()).toBeVisible()
    await expect(page.getByText('USER').first()).toBeVisible()

    // --- the sessions ---------------------------------------------------
    await navigateTo(page, '/sessions')
    await expect(page.getByRole('heading', { name: 'Phiên đăng nhập' })).toBeVisible()

    // The sessions table is real: it carries the caption the backend's
    // rows are rendered under.
    await expect(page.getByText('Danh sách phiên đăng nhập đang hoạt động')).toBeVisible()

    // The CURRENT session is marked as such.  The badge is the proof
    // that the backend knows which session the caller is.
    await expect(page.getByText('Phiên hiện tại').first()).toBeVisible()

    const ownSessionId = await currentSessionId(page)

    // The second browser knows its own session id.
    await navigateTo(secondPage, '/sessions')
    const secondSessionId = await currentSessionId(secondPage)

    // It is a DIFFERENT session from the first browser's — the point of
    // creating it.
    expect(secondSessionId).not.toBe(ownSessionId)

    // The list belongs to the ACCOUNT, not to the browser: both
    // sessions show up in both browsers.
    const listedIds = await sessionIds(page)
    expect(listedIds).toContain(secondSessionId)
    expect(listedIds).toContain(ownSessionId)

    // --- the devices ----------------------------------------------------
    await navigateTo(page, '/devices')
    await expect(page.getByRole('heading', { name: 'Thiết bị tin cậy' })).toBeVisible()

    // The test trusts a device it names itself, so it can untrust it
    // again without touching a seeded device.
    const deviceMarker = `e2e-01-device-${Date.now()}`
    await page.getByLabel('Tên thiết bị').fill(deviceMarker)
    await page.getByRole('button', { name: 'Tin cậy thiết bị này' }).click()

    await expect(page.getByText(deviceMarker)).toBeVisible({ timeout: 15_000 })

    // The device is now really in the backend's table — the row came
    // from `GET /devices`, not from local state.
    await expect(
      page.locator('table tbody tr').filter({ hasText: deviceMarker }),
    ).toHaveCount(1)

    // --- the revoke ------------------------------------------------------
    //
    // The revoke targets the SECOND session — not the current one — so
    // the browser stays signed in, which is what makes the next step
    // (logout) a separate, observable action.
    await navigateTo(page, '/sessions')
    await expect(page.getByText('Danh sách phiên đăng nhập đang hoạt động')).toBeVisible()

    await revokeSessionThroughUi(page, secondSessionId)

    // The current session survives: the browser is still signed in.
    await expect(page.getByText(username).first()).toBeVisible()
    await expect(
      page.getByRole('button', { name: `Thu hồi phiên ${ownSessionId}` }),
    ).toBeVisible()

    // The revoked session is gone from the ACCOUNT's list — the first
    // browser re-read the list from the backend after the mutation.
    await expect(
      page.getByRole('button', { name: `Thu hồi phiên ${secondSessionId}` }),
    ).toHaveCount(0, { timeout: 15_000 })

    // The revoked session is DEAD, not merely hidden: the second
    // browser still holds the access token of the revoked session, and
    // the backend now refuses it.  The next request it makes therefore
    // fails with a 401 and the application routes it to the login
    // screen.
    await navigateTo(secondPage, '/devices')
    await expect(secondPage).toHaveURL(/\/login/, { timeout: 20_000 })

    // --- the logout ------------------------------------------------------
    await logoutVia(page)
    await expect(page.getByRole('heading', { name: 'Sentinel Auth' })).toBeVisible()

    // The guard really closed: the sessions page is not reachable any
    // more without a session.
    await openDirect(page, '/sessions')
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })

    await secondContext.close()
  })

  test('refuses to reach a guarded page while signed out', async ({ page }) => {
    // The guard sends an anonymous visitor to the login screen.
    await openDirect(page, '/sessions')
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
    await expect(page.getByRole('heading', { name: 'Sentinel Auth' })).toBeVisible()
  })
})
