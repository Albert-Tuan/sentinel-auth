/**
 * The login helpers.
 *
 * Every helper here drives the REAL browser against the REAL backend.
 * The login is a genuine round trip: the form is filled, the button is
 * pressed, the application performs the request, and the MFA code — when
 * the backend asks for one — is read out of the SMTP sink.
 *
 * Nothing is stubbed.  A test that signed the user in by injecting a
 * token would never touch the login screen, the MFA handshake or the
 * risk gate, and those are exactly the things E2E-02 and E2E-08 are
 * about.
 */

import { expect, type Page } from '@playwright/test'

import { otpOffset, waitForCode } from './otp'
import { emailOf, type AccountKey, type FixtureManifest } from './manifest'
import { resetRateLimits } from './fixtureBridge'

/**
 * The demo password.
 *
 * `scripts/demo_seed_demo.py` hashes `DEFAULT_DEMO_PASSWORD` when the
 * environment does not supply a per-account one, so the seeded accounts
 * all carry this password unless the seeding run overrode it.
 */
export const DEFAULT_DEMO_PASSWORD = 'DemoPass!2026'

/** The password of a demo account. */
export function passwordOf(key: AccountKey): string {
  const override = {
    user: process.env.DEMO_USER_PASSWORD,
    analyst: process.env.DEMO_ANALYST_PASSWORD,
    admin: process.env.DEMO_ADMIN_PASSWORD,
    manager: process.env.DEMO_MANAGER_PASSWORD,
  }[key]
  return override?.trim() || DEFAULT_DEMO_PASSWORD
}

/**
 * Perform the login form.
 *
 * The helper returns as soon as the MFA screen appears OR the session
 * is established.  The caller decides what happens next: a test that
 * expects the MFA handshake completes it, a test that expects a plain
 * login simply waits for the landing page.
 */
export async function submitLogin(
  page: Page,
  username: string,
  password: string,
): Promise<void> {
  // The login endpoint is rate-limited per client IP.  Every scenario
  // logs in from the same loopback address, so the counter is cleared
  // BEFORE the login — the limiter itself stays exactly as it is.
  await resetRateLimits()

  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sentinel Auth' })).toBeVisible()

  await page.getByLabel('Tên đăng nhập').fill(username)
  await page.getByLabel('Mật khẩu').fill(password)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()
}

/**
 * Perform the login form WITHOUT reloading the document.
 *
 * ---------------------------------------------------------------------------
 * WHY THE RELOAD-FREE VARIANT EXISTS
 * ---------------------------------------------------------------------------
 *
 * `submitLogin` opens `/login` with `page.goto`, which is a FULL page
 * load: the document is replaced and every JavaScript context of the
 * page is DESTROYED.
 *
 * That is fine for a scenario that starts from scratch — and fatal for
 * a RACE scenario.  A race needs a request that is still in flight
 * while the session is replaced; a full reload would destroy the
 * context that request runs in, and the promise that observes it.
 *
 * The helper therefore navigates the way the APPLICATION navigates: the
 * router is already on `/login` after a logout, so the form is filled
 * in place.  No document is replaced, and the contexts survive.
 */
export async function submitLoginWithoutReload(
  page: Page,
  username: string,
  password: string,
): Promise<void> {
  await resetRateLimits()

  // The login screen must already be on screen.  The caller navigates
  // there through the application, so the document is never replaced.
  await expect(page.getByRole('heading', { name: 'Sentinel Auth' })).toBeVisible({
    timeout: 15_000,
  })

  await page.getByLabel('Tên đăng nhập').fill(username)
  await page.getByLabel('Mật khẩu').fill(password)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()
}

/**
 * Complete the MFA challenge, if the backend asks for one.
 *
 * The offset is taken BEFORE the login, so only the code of THIS login
 * is considered.  A code that belongs to an earlier login would be
 * rejected by the API — and the failure would look like a broken MFA
 * implementation rather than a stale read.
 *
 * @returns true when a challenge was answered, false when none was asked for.
 */
export async function completeMfaIfRequired(
  page: Page,
  manifest: FixtureManifest,
  key: AccountKey,
  offset: number,
): Promise<boolean> {
  const mfaInput = page.locator('#mfa-code')

  /**
   * Wait for EITHER of two outcomes, and for no other.
   *
   * The obvious "did the login button disappear?" check does not work:
   * the login screen swaps the form for a spinner the moment the
   * request goes out, so the button detaches while the request is still
   * in flight.  That would make the helper report "logged in" while the
   * MFA screen was about to appear.
   *
   * The URL is the honest signal: the application either moves to the
   * landing path (the session is established) or to `/mfa` (a challenge
   * is pending).
   */
  const outcome = await Promise.race([
    mfaInput
      .waitFor({ state: 'visible', timeout: 20_000 })
      .then(() => 'mfa' as const),
    page
      .waitForURL(
        (url) => url.pathname !== '/login' && url.pathname !== '/mfa',
        { timeout: 20_000 },
      )
      .then(() => 'landed' as const),
  ])

  if (outcome === 'landed') return false

  const recipient = emailOf(manifest, key)
  const code = await waitForCode(recipient, offset)
  await mfaInput.fill(code)
  await page.getByRole('button', { name: 'Xác thực' }).click()

  // The challenge screen must be gone: the MFA verify call has to
  // succeed before the session exists.
  await expect(page).not.toHaveURL(/\/mfa$/, { timeout: 20_000 })
  return true
}

/**
 * Log a demo account in, through the real form and the real MFA
 * handshake.
 *
 * @returns the offset of the OTP log taken BEFORE the login, so a caller
 *          that needs the code can read it.
 */
export async function loginAs(
  page: Page,
  manifest: FixtureManifest,
  key: AccountKey,
): Promise<number> {
  const username = manifest.core.users[key].username
  const password = passwordOf(key)

  // The offset is taken BEFORE the login is triggered: only a code
  // written after this point belongs to this login.
  const offset = otpOffset()

  await submitLogin(page, username, password)
  await completeMfaIfRequired(page, manifest, key, offset)

  return offset
}

/**
 * Log a demo account in and wait for the landing page.
 *
 * The landing path is role-dependent: an analyst lands on the alert
 * queue, an admin on the user directory, a manager on the dashboard.
 * The helper waits for the top bar, which every guarded page renders
 * and which carries the signed-in username — a stronger signal than the
 * sidebar, whose visibility depends on the viewport.
 */
export async function loginAndWait(
  page: Page,
  manifest: FixtureManifest,
  key: AccountKey,
): Promise<void> {
  await loginAs(page, manifest, key)
  await expect(
    page.getByText(manifest.core.users[key].username).first(),
  ).toBeVisible({ timeout: 20_000 })
}

/**
 * Log a demo account in WITHOUT reloading the document, and wait for
 * the landing page.
 *
 * The helper is the reload-free counterpart of `loginAndWait`: it
 * performs the real form submission and the real MFA handshake, but it
 * never replaces the document.  A race scenario needs that, because a
 * full reload destroys the JavaScript contexts of the page — including
 * the context of a request that is still in flight.
 *
 * The login screen must ALREADY be on screen: the caller navigates
 * there through the application.
 */
export async function loginAndWaitWithoutReload(
  page: Page,
  manifest: FixtureManifest,
  key: AccountKey,
): Promise<void> {
  const username = manifest.core.users[key].username
  const password = passwordOf(key)

  const offset = otpOffset()

  await submitLoginWithoutReload(page, username, password)
  await completeMfaIfRequired(page, manifest, key, offset)

  await expect(page.getByText(username).first()).toBeVisible({ timeout: 20_000 })
}

/**
 * Log the current user out through the real UI.
 *
 * The selector is EXACT on purpose.  The sessions screen carries a
 * "Đăng xuất khỏi mọi thiết bị" button, and a loose regex would match
 * that one instead of the top bar's logout — silently revoking EVERY
 * session of the account instead of the current one.
 */
export async function logoutVia(page: Page): Promise<void> {
  const logout = page.getByRole('button', { name: 'Đăng xuất', exact: true })
  await logout.click()
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
}
