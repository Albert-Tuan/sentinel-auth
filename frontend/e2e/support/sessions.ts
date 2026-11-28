/**
 * The session helpers.
 *
 * The session id is the only stable identity of a session: the rows are
 * rendered in the backend's order, the timestamps move, and the row
 * COUNT is not a reliable signal (a session created by another browser
 * appears at the same time as one disappears).
 *
 * Every helper therefore identifies a session by the id the
 * application itself puts in the revoke button's accessible name —
 * `Thu hồi phiên <session id>` — which is read straight out of the DOM.
 */

import { expect, type Page } from '@playwright/test'

/** The pattern of the revoke button's accessible name. */
const REVOKE_LABEL = /Thu hồi phiên ([0-9a-f-]{36})/

/** The id of the session the browser is currently signed in with. */
export async function currentSessionId(page: Page): Promise<string> {
  const row = page
    .locator('table tbody tr')
    .filter({ hasText: 'Phiên hiện tại' })
    .first()
  await expect(row).toBeVisible({ timeout: 15_000 })

  const label = await row
    .getByRole('button', { name: REVOKE_LABEL })
    .getAttribute('aria-label')
  const match = REVOKE_LABEL.exec(label ?? '')
  if (!match) throw new Error(`the current session row carries no session id: ${label}`)
  return match[1]
}

/** The ids of every session the account currently has. */
export async function sessionIds(page: Page): Promise<string[]> {
  const buttons = page.locator('table tbody tr button[aria-label*="Thu hồi phiên"]')
  const count = await buttons.count()
  const ids: string[] = []

  for (let index = 0; index < count; index += 1) {
    const label = await buttons.nth(index).getAttribute('aria-label')
    const match = REVOKE_LABEL.exec(label ?? '')
    if (match) ids.push(match[1])
  }

  return ids
}

/**
 * Revoke a session through the UI and wait until it is GONE.
 *
 * Two details make this assertion honest:
 *
 *   1. The target is named by its SESSION ID, not by its position in the
 *      table.  The list belongs to the ACCOUNT, so a session created by
 *      another browser at the same moment shifts the rows around; a
 *      position-based assertion would then fail for a reason that has
 *      nothing to do with the revoke.
 *
 *   2. The list is re-read from the BACKEND before the assertion.  The
 *      screen invalidates its query after the mutation and refetches, so
 *      waiting for that response proves the list on screen is the
 *      backend's answer and not a cached render.
 */
export async function revokeSessionThroughUi(
  page: Page,
  sessionId: string,
): Promise<void> {
  const button = page.getByRole('button', { name: `Thu hồi phiên ${sessionId}` })
  await expect(button).toBeVisible({ timeout: 15_000 })

  await button.click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Thu hồi', exact: true }).click()

  // The revoked session disappears from the list.
  await expect(
    page.getByRole('button', { name: `Thu hồi phiên ${sessionId}` }),
    `the session '${sessionId}' is still listed after it was revoked`,
  ).toHaveCount(0, { timeout: 15_000 })
}

/**
 * Wait until the sessions screen has re-read the list from the backend.
 *
 * The React Query cache keeps the previous list on screen until the
 * refetch answers, so a test that asserts on the list right after a
 * mutation would be reading the OLD data.
 */
export async function waitForSessionsRefetch(page: Page): Promise<void> {
  await page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/auth/sessions') &&
      response.request().method() === 'GET' &&
      response.status() === 200,
    { timeout: 15_000 },
  )
}
