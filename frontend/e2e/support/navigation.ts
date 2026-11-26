/**
 * The navigation helpers.
 *
 * ---------------------------------------------------------------------------
 * WHY THE TESTS NAVIGATE THROUGH THE LINKS
 * ---------------------------------------------------------------------------
 *
 * The session store of the application is IN-MEMORY ONLY: the access
 * token lives in a module-scoped object, never in `localStorage`, never
 * in a cookie.  A full page reload therefore signs the user OUT — by
 * design, and the security review asked for exactly that.
 *
 * That means `page.goto('/sessions')` would reload the document, drop
 * the token and land on the login screen.  A test that navigated that
 * way would never reach the sessions page at all.
 *
 * The tests therefore navigate the way a USER navigates: they click the
 * links of the application.  React Router handles the transition on the
 * client, the in-memory token survives, and the screen the test asserts
 * on is the one the user really sees.
 *
 * The one place a full reload is correct is the very first navigation:
 * before the login there is no session to lose, so `/login` is opened
 * directly.
 */

import { expect, type Locator, type Page } from '@playwright/test'

/**
 * Navigate to a path THROUGH THE APPLICATION, keeping the session.
 *
 * The path is matched against the links the application renders, so a
 * link that the role policy hides simply is not there — and the helper
 * says so instead of hanging.
 */
export async function navigateTo(page: Page, path: string): Promise<void> {
  const link = page.locator(`a[href="${path}"]`).first()
  await expect(
    link,
    `the application renders no link to '${path}'. The role of the signed-in user may not grant access to it.`,
  ).toBeVisible({ timeout: 15_000 })

  await link.click()
  await expect(page).toHaveURL(new RegExp(`${path.replace(/\//g, '\\/')}($|\\?)`), {
    timeout: 15_000,
  })
}

/**
 * Open a path directly, as a full page load.
 *
 * ONLY for a path that is safe to reload — the login screen, or a
 * guarded path when the test EXPECTS the guard to send the visitor
 * back to the login screen.
 */
export async function openDirect(page: Page, path: string): Promise<void> {
  await page.goto(path)
}

/**
 * Navigate to a path WITHOUT reloading the document.
 *
 * ---------------------------------------------------------------------------
 * WHY THE GUARD CANNOT BE TESTED WITH A RELOAD
 * ---------------------------------------------------------------------------
 *
 * The session store of the application is IN-MEMORY ONLY, so a reload
 * signs the user out.  A `page.goto('/admin/users')` would therefore
 * never reach the ROLE guard: the AUTHENTICATION guard would catch the
 * visitor first and send it to the login screen — which is a correct
 * behaviour, but the wrong thing to assert.
 *
 * To reach the role guard the test has to navigate the way the
 * application navigates: inside the document, with the session intact.
 * There is no link to a section the role may not enter — that is the
 * point of hiding it — so the navigation is performed through the
 * history API and the `popstate` event, which is exactly what the
 * router listens to.
 */
export async function navigateClientSide(page: Page, path: string): Promise<void> {
  await page.evaluate((target) => {
    window.history.pushState({}, '', target)
    window.dispatchEvent(new PopStateEvent('popstate', { state: {} }))
  }, path)

  // The helper does NOT assert the resulting URL on purpose: the guard
  // may send the visitor to the forbidden screen, and that IS the
  // outcome the caller wants to check.  The caller therefore decides
  // what the destination has to be — and its assertion waits for the
  // redirect to have happened.
}

/**
 * Open a queue row, without depending on its PIXEL POSITION.
 *
 * ---------------------------------------------------------------------------
 * WHY THE ROW IS NOT CLICKED BY ITS COORDINATES
 * ---------------------------------------------------------------------------
 *
 * The queue enriches its rows with a SECOND request: the subject (the
 * username and the IP) lives on the login attempt, which the queue
 * endpoint does not join.  Until that request answers, the subject
 * cells render an em dash; afterwards they render the values — and a
 * row that carries the values is TALLER than a row that does not.
 *
 * That reflow is enough to make a coordinate-based click miss:
 *
 *   - the click is dispatched as a `mousedown` and a `mouseup` on the
 *     SAME coordinates, with a `click` in between;
 *   - if the enrichment lands between the two, every row below it
 *     moves by its own height;
 *   - the `mousedown` therefore lands on one row and the `mouseup` on
 *     another one, and the browser resolves the `click` to the
 *     COMMON ANCESTOR of the two — the `<tbody>`;
 *   - the `click` never reaches the row, the application's own
 *     handler never runs, and the screen stays on the queue.
 *
 * The race is not a defect of the application: a human clicks a row
 * once, and the enrichment has long landed by then.  It IS a defect of
 * a test that clicks the instant the row appears.
 *
 * ---------------------------------------------------------------------------
 * WHY THE ROW IS ACTIVATED WITH THE KEYBOARD INSTEAD
 * ---------------------------------------------------------------------------
 *
 * The row IS a control: `DataTable` renders it with `role="button"`,
 * `tabIndex={0}` and a handler for Enter and Space, so it can be
 * operated without a mouse.  Activating it that way dispatches the
 * event ON THE ROW ELEMENT — there is no coordinate, so no reflow can
 * turn the click into a miss.
 *
 * The same handler runs, the same navigation happens, and the scenario
 * still exercises the real application.
 */
async function activateRow(row: Locator): Promise<void> {
  await row.focus()
  await row.press('Enter')
}

/**
 * Open the detail of ONE alert through the queue.
 *
 * ---------------------------------------------------------------------------
 * WHY A DETAIL PAGE CANNOT BE REACHED BY LINK
 * ---------------------------------------------------------------------------
 *
 * The queue renders its rows as clickable `<tr>` elements, not as
 * anchors: there is NO `a[href="/alerts/<id>"]` anywhere in the DOM.
 * A detail page is therefore reached the way a user reaches it — by
 * clicking the row of the alert in the queue.
 *
 * The row is identified by the FIXTURE MARKER the row carries, not by
 * its position: the queue is paginated and sorted by the backend, so
 * "the third row" is not a stable identity.
 *
 * The row is ACTIVATED, not clicked by its coordinates — see
 * `activateRow` for why a pixel click cannot survive the queue's own
 * enrichment reflow.
 *
 * ---------------------------------------------------------------------------
 * WHY THE SEARCH SPANS SEVERAL PAGES
 * ---------------------------------------------------------------------------
 *
 * The queue is paginated and sorted newest-first, and the demo stack
 * keeps producing alerts of its own — every login that the risk gate
 * holds creates one.  A fixture created minutes ago can therefore sit
 * on page three, and a scenario that only looked at page one would
 * fail for a reason that has nothing to do with the behaviour under
 * test.
 *
 * The search therefore walks the pages, exactly as an analyst would
 * scroll down looking for the alert.  The walk is BOUNDED: a marker
 * that is nowhere in the queue is a failure, not an endless scroll.
 */
export async function openAlertDetail(
  page: Page,
  alertId: string,
  marker: string,
): Promise<void> {
  await navigateTo(page, '/alerts')

  const rows = page.locator('table tbody tr')
  await expect(rows.first()).toBeVisible({ timeout: 15_000 })

  const maxPages = 25

  for (let index = 0; index < maxPages; index += 1) {
    const row = rows.filter({ hasText: marker }).first()

    if (await row.count()) {
      await activateRow(row)
      await expect(page).toHaveURL(new RegExp(`/alerts/${alertId}($|\\?)`), {
        timeout: 15_000,
      })
      return
    }

    // The next page button is disabled on the last page.
    const next = page.getByRole('button', { name: 'Sau', exact: true })
    if (await next.isDisabled()) break

    const firstRowBefore = await rows.first().innerText()
    await next.click()

    // The table is replaced while the new page loads, so the wait is on
    // the CONTENT changing — a fixed sleep would be a flaky wait.
    await expect
      .poll(async () => rows.first().innerText().catch(() => ''), {
        timeout: 20_000,
      })
      .not.toBe(firstRowBefore)
  }

  throw new Error(
    `the queue renders no row carrying the marker '${marker}' within ${maxPages} pages.`,
  )
}
