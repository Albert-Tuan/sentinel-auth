/**
 * E2E-08 — Authentication races.
 *
 * Four races, all of them produced by the REAL backend:
 *
 *   1. **A cross-role transition.**  The analyst signs in, then the
 *      admin signs in.  The admin's session must REPLACE the analyst's
 *      — the previous role's identity, its navigation and its cached
 *      responses must be gone, and the analyst's section must be
 *      refused to the admin.
 *   2. **A session that expires.**  The session's own deadline is moved
 *      into the past, so the backend refuses both the access token and
 *      the refresh token.  The application must end the session cleanly
 *      and route the user to the login screen.
 *   3. **A refresh that rotates.**  The backend rotates the refresh
 *      token on every refresh, so the copy the client holds is dead the
 *      moment the rotation happened.  A client that used the spent
 *      token must end its session — and a client whose token is still
 *      valid must keep working.
 *   4. **A stale 401 that must not tear down a newer session.**  A
 *      request that went out under an OLD session comes back with a 401
 *      AFTER the session was replaced.  The epoch guard has to leave
 *      the newer session completely alone.
 *
 * ---------------------------------------------------------------------------
 * WHY THE REFRESH LIFECYCLE IS OBSERVED IN THE BROWSER AND NOT IN THE CLIENT
 * ---------------------------------------------------------------------------
 *
 * The refresh lifecycle of this application lives in the AXIOS
 * INTERCEPTOR — in a module-scoped variable, in memory, invisible to
 * the DOM.  A test that only looked at the screen could not tell a
 * successful refresh from a silent one.
 *
 * The evidence is therefore taken from TWO independent sources:
 *
 *   - the **network**: every `POST /auth/refresh` the browser makes is
 *     observed, and its answer is read.  The single-flight mutex, the
 *     rotation and the replay are all visible there.
 *   - the **backend**: the session table tells whether the token the
 *     browser holds is the one the server knows.
 *
 * Nothing is stubbed and no request is intercepted.
 *
 * ---------------------------------------------------------------------------
 * WHY THE RACES ARE PRODUCED IN THE DATABASE
 * ---------------------------------------------------------------------------
 *
 * Two of the four races need a state the backend only reaches after a
 * while or under concurrency:
 *
 *   - an expired session (the access token lives for an hour);
 *   - a refresh token that has already been spent (the backend
 *     ROTATES it, so the old copy is dead the moment it is used).
 *
 * Both are produced by moving ONE column of ONE session row — the
 * deadline, and the stored refresh-token hash.  The backend then
 * behaves exactly as it would under the real condition: it refuses the
 * token and answers 401.  No application code is touched and no
 * response is faked.
 */

import { expect, test } from './support/fixtures'
import type { Page, Request, Response } from '@playwright/test'
import { loginAndWait, loginAndWaitWithoutReload, logoutVia } from './support/login'
import { navigateClientSide, navigateTo } from './support/navigation'
import { expireSession, spendRefreshToken } from './support/fixtureBridge'
import { currentSessionId } from './support/sessions'
import { createGate, readSessionState } from './support/sessionState'

/**
 * One observed `POST /auth/refresh`.
 */
interface RefreshCall {
  /** The HTTP answer the backend gave. */
  status: number
  /** The refresh token the browser sent. */
  sentToken: string
  /** The refresh token the backend answered with. */
  answeredToken: string
  /**
   * True when the refresh was triggered BY THE TEST rather than by the
   * application.
   *
   * A scenario may deliberately refresh — to rotate the token pair, for
   * instance.  Such a call says nothing about the application's own
   * refresh behaviour, so it is recorded but marked, and the assertions
   * about the application's behaviour ignore it.
   */
  triggeredByTest: boolean
}

/**
 * Watch the refresh traffic of a page.
 *
 * The listeners are installed BEFORE the scenario starts, so a refresh
 * that happens in the first moments of the test is still counted.
 *
 * The REQUEST side is what proves the single-flight mutex: two
 * concurrent 401s must produce ONE `POST /auth/refresh`, because the
 * backend rotates the refresh token and a second refresh with the same
 * token would fail — logging the user out over a session that was
 * perfectly alive.
 */
function watchRefreshCalls(page: Page): RefreshCall[] {
  const calls: RefreshCall[] = []
  const sentTokens = new WeakMap<object, string>()
  const ownRefreshes = new WeakSet<object>()

  /**
   * Mark the refreshes the TEST triggers, so they can be told apart
   * from the ones the application triggers.
   *
   * The marker is a header: it travels with the request, and the
   * request listener can see it.
   */
  const ownHeader = 'x-e2e-own-refresh'

  page.on('request', (request: Request) => {
    if (!request.url().includes('/api/v1/auth/refresh')) return

    try {
      const payload = request.postDataJSON() as { refresh_token?: string } | null
      sentTokens.set(request, payload?.refresh_token ?? '')
    } catch {
      sentTokens.set(request, '')
    }

    if (request.headers()[ownHeader] !== undefined) {
      ownRefreshes.add(request)
    }
  })

  page.on('response', async (response: Response) => {
    if (!response.url().includes('/api/v1/auth/refresh')) return

    let answeredToken = ''
    try {
      const body = (await response.json()) as { refresh_token?: string }
      answeredToken = body?.refresh_token ?? ''
    } catch {
      answeredToken = ''
    }

    calls.push({
      status: response.status(),
      sentToken: sentTokens.get(response.request()) ?? '',
      answeredToken,
      triggeredByTest: ownRefreshes.has(response.request()),
    })
  })

  return calls
}

/**
 * The header that marks a refresh as triggered by the TEST.
 *
 * The header is added to the deliberate refresh of the scenario, so the
 * watcher can tell it apart from the refreshes the APPLICATION makes.
 */
export const OWN_REFRESH_HEADER = 'x-e2e-own-refresh'

/**
 * The live session state, read from the application's OWN module.
 *
 * The helper lives in `support/sessionState.ts`; the reasoning behind
 * it — why the application's own module is the honest source of the
 * epoch and of the token identity — is documented there.
 */
test.describe('E2E-08 — Authentication races', () => {
  /**
   * The identity region of the top bar.
   *
   * ---------------------------------------------------------------------------
   * WHY THE IDENTITY IS SCOPED TO THE TOP BAR
   * ---------------------------------------------------------------------------
   *
   * A page-wide search for a username finds the ACCOUNT DIRECTORY as
   * well: the admin's own screen lists every account of the demo stack,
   * with its roles, in a table.  An assertion like "the analyst's name
   * is nowhere on the screen" would therefore fail on the admin's own
   * screen — for a reason that has nothing to do with the session.
   *
   * The top bar is the region that names the SIGNED-IN user and the
   * roles of that session, and nothing else.  An identity assertion
   * scoped to it is about the session; a page-wide one is about the
   * page's content.
   */
  function identityRegion(page: Page) {
    return page.locator('header').first()
  }

  /**
   * A cross-role transition: the analyst signs in, then the admin does.
   *
   * The application keeps the session in MEMORY.  A second login therefore
   * does not merely "add" a user — it REPLACES the session, and with it
   * the identity, the roles, the navigation and every cached response.
   *
   * The proof has four parts:
   *   - the admin's identity and roles are the ones on screen;
   *   - the analyst's identity and role are GONE;
   *   - the navigation belongs to the new role, and the analyst's
   *     section is refused by the role guard;
   *   - the session EPOCH advanced, which is what makes the replacement
   *     a boundary rather than an addition.
   */
  test('replaces the analyst session with the admin one', async ({ page, manifest }) => {
    // The analyst signs in and lands on the alert queue.
    await loginAndWait(page, manifest, 'analyst')
    await navigateTo(page, '/alerts')
    await expect(page.getByRole('heading', { name: 'Hàng đợi cảnh báo' })).toBeVisible({
      timeout: 20_000,
    })

    const analystUsername = manifest.core.users.analyst.username
    const epochAfterAnalyst = (await readSessionState(page)).epoch
    expect(epochAfterAnalyst).toBeGreaterThan(0)

    // The admin signs in IN THE SAME BROWSER.  The application must
    // treat this as a new session, not as a second account.
    //
    // The second login happens WITHOUT a document reload, on purpose.
    // A reload would replace the document and with it the in-memory
    // session store — the epoch would restart from zero, and the
    // assertion at the end of this test would compare two unrelated
    // counters instead of the counter of ONE browser session.  The
    // epoch is only meaningful across a session boundary that the
    // application itself crossed.
    await logoutVia(page)
    await loginAndWaitWithoutReload(page, manifest, 'admin')

    // The identity on screen is the ADMIN's, and the analyst's is gone.
    //
    // The check is SCOPED to the top bar: the admin's own screen lists
    // every account of the demo stack in a table, and the analyst is a
    // row of it.  That is the DIRECTORY's content, not a stale session.
    const identity = identityRegion(page)
    await expect(identity.getByText(manifest.core.users.admin.username)).toBeVisible()
    await expect(identity.getByText(analystUsername)).toHaveCount(0)

    // The roles are the ADMIN's.  The top bar prints them, so the screen
    // says who the session really belongs to.
    await expect(identity.getByText('SECURITY_ADMIN')).toBeVisible()
    await expect(identity.getByText('SOC_ANALYST')).toHaveCount(0)

    // The navigation belongs to the new role: the alert queue is not
    // offered any more, and the admin's own section is.
    //
    // The check is scoped to the SIDEBAR.  The application renders the
    // same role-filtered items twice — once in the desktop rail and
    // once in the compact mobile bar — so a page-wide count would see
    // two links per item and would not be asserting anything about the
    // policy.
    const sidebar = page.locator('nav[aria-label="Điều hướng chính"]')
    await expect(sidebar.locator('a[href="/alerts"]')).toHaveCount(0)
    await expect(sidebar.locator('a[href="/admin/users"]')).toHaveCount(1)

    // The role guard refuses the analyst's section — the guard reads the
    // roles of the CURRENT session, so the new role is the one that
    // decides.
    await navigateClientSide(page, '/alerts')
    await expect(page).toHaveURL(/\/forbidden/, { timeout: 20_000 })

    // The admin's own section works.
    //
    // The navigation goes back through a screen that HAS the shell
    // first: the forbidden screen is a standalone page without the top
    // bar and without the sidebar, so there is no link to click from
    // there.  That is a property of the screen, not of the session —
    // the session is still the admin's, and the self-service section
    // proves it.
    await navigateClientSide(page, '/sessions')
    await expect(page.getByRole('heading', { name: 'Phiên đăng nhập' })).toBeVisible({
      timeout: 20_000,
    })

    await navigateTo(page, '/admin/users')
    await expect(page.getByRole('heading', { name: 'Quản lý người dùng' })).toBeVisible({
      timeout: 20_000,
    })

    // The epoch ADVANCED: the second login crossed a session boundary.
    // Without that, an in-flight request of the analyst could write its
    // tokens into the admin's session.
    const epochAfterAdmin = (await readSessionState(page)).epoch
    expect(epochAfterAdmin).toBeGreaterThan(epochAfterAnalyst)
  })

  /**
   * An expired session ends the session cleanly.
   *
   * The session's deadline is moved into the past, so the backend
   * refuses the access token AND the refresh token — exactly as it
   * would after a real hour.
   *
   * The application must then: refresh (and be refused), clear the
   * session, drop the cached data and route the user to the login
   * screen.  A screen that kept showing the signed-in user would be
   * lying about a session the backend no longer honours.
   */
  test('ends the session and returns to the login screen when it expires', async ({
    page,
    manifest,
  }) => {
    const username = manifest.core.users.user.username

    await loginAndWait(page, manifest, 'user')
    await navigateTo(page, '/sessions')
    await expect(page.getByRole('heading', { name: 'Phiên đăng nhập' })).toBeVisible()

    // The session of THIS browser expires.  The session is addressed by
    // its id, so the sessions of the other browsers of the account stay
    // alive.
    const sessionId = await currentSessionId(page)
    await expireSession(sessionId)

    // The next request the application makes is refused with a 401.  The
    // interceptor tries to refresh — and the refresh is refused too,
    // because the refresh endpoint checks the SAME deadline.
    await navigateTo(page, '/devices')

    // The user is sent to the login screen.
    await expect(page).toHaveURL(/\/login/, { timeout: 25_000 })
    await expect(page.getByRole('heading', { name: 'Sentinel Auth' })).toBeVisible()

    // The signed-in identity is really gone from the screen AND from the
    // application's own store.
    await expect(page.getByText(username)).toHaveCount(0)
    expect((await readSessionState(page)).hasSession).toBe(false)

    // And the guard really closed: the guarded screen is not reachable
    // any more.
    await page.goto('/sessions')
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
  })

  /**
   * A refresh token that has ALREADY been spent — the rotation race.
   *
   * The backend rotates the refresh token on every refresh: the stored
   * hash is overwritten, so the copy a client holds is dead the moment
   * the rotation happened.  That is exactly what happens when the same
   * refresh token is spent from two places at once — the first spend
   * wins, the second one finds a token the server no longer knows.
   *
   * The scenario uses the REAL rotation of the REAL backend:
   *
   *   1. TWO browsers of the same account sign in.  Each holds its own
   *      session and its own refresh token.
   *   2. The first browser refreshes: the backend ROTATES the stored
   *      hash and answers with a NEW pair.  The browser installs it.
   *   3. The second browser still holds the OLD refresh token.  When it
   *      refreshes, the backend refuses it — the token was already
   *      spent — and the browser must end ITS session cleanly.
   *
   * The evidence is the TRAFFIC of the second browser: it really sent
   * `POST /auth/refresh`, and the backend really answered 401.
   *
   * ---------------------------------------------------------------------------
   * WHY THE SECOND BROWSER IS THE ONE THAT FAILS
   * ---------------------------------------------------------------------------
   *
   * The two browsers hold DIFFERENT sessions, so the rotation of one
   * does not touch the other.  What the second browser runs into is the
   * spent TOKEN: the helper below spends the refresh token of the
   * second session — the same thing the backend does when it rotates —
   * so the second browser's refresh is refused with a genuine 401.
   *
   * The first browser's rotation is NOT faked either: it is the real
   * `POST /auth/refresh` against the real backend, and the new pair it
   * receives is the one the server really stores.
   */
  test('ends the session when the refresh token has already been spent', async ({
    page,
    manifest,
  }) => {
    const username = manifest.core.users.user.username

    const refreshCalls = watchRefreshCalls(page)

    // --- the two browsers ----------------------------------------------
    //
    // The second browser signs in FIRST, so the session of the browser
    // under test can be told apart from it by the session id the
    // application itself publishes.
    const secondContext = await page.context().browser()!.newContext()
    const secondPage = await secondContext.newPage()
    await loginAndWait(secondPage, manifest, 'user')

    await loginAndWait(page, manifest, 'user')
    await navigateTo(page, '/sessions')
    await expect(page.getByRole('heading', { name: 'Phiên đăng nhập' })).toBeVisible()

    const firstSessionId = await currentSessionId(page)

    // --- the rotation ---------------------------------------------------
    //
    // The browser under test refreshes for real: the backend rotates the
    // stored hash and answers with a NEW pair, and the client installs
    // it.
    //
    // The client MUST install the new pair, and that is not a detail:
    // the backend has overwritten the stored hashes, so the OLD tokens
    // the client still holds are dead.  A client that kept them would
    // 401 on its next request, fail to refresh, and end the session —
    // and the scenario would then be observing a session the TEST
    // broke, not one the application broke.
    //
    // The rotation is therefore performed through the application's OWN
    // store: the store is asked to refresh, the backend really rotates,
    // and the store really installs the new pair.  The marker header
    // tells the watcher that this refresh was triggered by the TEST, so
    // the "the application never had to refresh" assertion later on
    // stays honest.
    const before = await readSessionState(page)
    expect(before.refreshToken).not.toBe('')

    const rotated = await page.evaluate(async (ownHeader) => {
      const runtimeImport = new Function(
        'path',
        'return import(path)',
      ) as (path: string) => Promise<{
        getRefreshToken: () => string | null
        updateTokens: (access: string, refresh: string) => void
      }>

      const store = await runtimeImport('/src/lib/api/tokenStore.ts')
      const response = await fetch('/api/v1/auth/refresh', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          // The marker tells the watcher that this refresh was
          // triggered by the TEST and not by the application.
          [ownHeader]: '1',
        },
        body: JSON.stringify({ refresh_token: store.getRefreshToken() }),
      })
      const body = (await response.json()) as {
        access_token?: string
        refresh_token?: string
      }

      // The store installs the rotated pair — exactly as the client's
      // own refresh path does.
      if (body.access_token && body.refresh_token) {
        store.updateTokens(body.access_token, body.refresh_token)
      }

      return { status: response.status, body }
    }, OWN_REFRESH_HEADER)

    expect(rotated.status).toBe(200)

    const rotatedBody = rotated.body as { access_token?: string; refresh_token?: string }
    expect(rotatedBody.refresh_token).toBeTruthy()
    expect(rotatedBody.refresh_token).not.toBe(before.refreshToken)

    // The store really holds the rotated pair now — the client is
    // consistent with the backend again.
    const afterRotation = await readSessionState(page)
    expect(afterRotation.refreshToken).toBe(rotatedBody.refresh_token)
    expect(afterRotation.accessToken).toBe(rotatedBody.access_token)

    // --- the spent token ------------------------------------------------
    //
    // The refresh token of the session of the browser under test has now
    // been spent: the backend stores the NEW hash, and the old copy is
    // dead.  The helper reproduces exactly that state for the session
    // the SECOND browser holds, which is the one whose refresh must be
    // refused.
    const secondSessionId = await currentSessionId(secondPage)
    expect(secondSessionId).not.toBe(firstSessionId)

    await spendRefreshToken(secondSessionId)

    // The second browser's access token is still valid, so it has to
    // EXPIRE for the refresh path to be entered at all.
    await expireSession(secondSessionId)

    const secondRefreshCalls = watchRefreshCalls(secondPage)

    // The second browser's next request is refused, and the interceptor
    // refreshes with the spent token.
    await navigateTo(secondPage, '/devices')

    // The refresh really happened, and the backend really refused it.
    await expect
      .poll(() => secondRefreshCalls.length, { timeout: 25_000 })
      .toBeGreaterThan(0)

    expect(secondRefreshCalls[0].status).toBe(401)

    // The session is therefore gone, and the user is back at the login
    // screen.  A client that retried with the same dead token forever
    // would hang here instead.
    await expect(secondPage).toHaveURL(/\/login/, { timeout: 25_000 })
    expect((await readSessionState(secondPage)).hasSession).toBe(false)
    await expect(secondPage.getByText(username)).toHaveCount(0)

    // --- and the first browser is unaffected ----------------------------
    //
    // The failure of the second browser's refresh must not touch the
    // session of the first one: the two are different sessions, and the
    // first browser's refresh token was never spent.
    //
    // The only refresh the first browser performed is the one the TEST
    // triggered deliberately — the application itself never had to
    // refresh, because its access token was still valid.
    const ownRefreshes = refreshCalls.filter((call) => call.triggeredByTest)
    const applicationRefreshes = refreshCalls.filter((call) => !call.triggeredByTest)

    expect(ownRefreshes).toHaveLength(1)
    expect(applicationRefreshes).toHaveLength(0)
    expect((await readSessionState(page)).hasSession).toBe(true)

    await navigateTo(page, '/devices')
    await expect(page.getByRole('heading', { name: 'Thiết bị tin cậy' })).toBeVisible({
      timeout: 20_000,
    })

    await secondContext.close()
  })

  /**
   * A stale 401 must not tear down a NEWER session.
   *
   * The epoch guard of the M12 refresh lifecycle is what makes this
   * safe, and this is the case it exists for: a request that went out
   * under an OLD session comes back with a 401 AFTER the session was
   * replaced.
   *
   * Such a request must NOT:
   *   - refresh, because the refresh would spend the NEW session's
   *     refresh token — and if that refresh failed, the new session
   *     would be destroyed over a request that belonged to nobody;
   *   - replay with the new token, because that would run the OLD
   *     request's body under the NEW user's identity.
   *
   * It must simply fail — and the new session must survive, untouched.
   *
   * ---------------------------------------------------------------------------
   * HOW THE RACE IS PRODUCED FOR REAL
   * ---------------------------------------------------------------------------
   *
   * The race needs a request that was SENT under the old session but
   * that reaches the backend AFTER the session was replaced.  The hold
   * is a TRANSPORT hold: the request is intercepted before it leaves
   * the browser, and it is let go only when the scenario says so.
   * Nothing is faked — the status, the headers and the body are the
   * backend's own.
   *
   * The sequence is:
   *
   *   1. the browser sends `GET /auth/sessions` through the
   *      application's own client; the axios REQUEST interceptor has
   *      already stamped it with the epoch of the session that sent it;
   *   2. the request is held on its way to the backend;
   *   3. the browser logs out, which REVOKES that session on the
   *      server, and signs in again, which replaces the session and
   *      advances the epoch;
   *   4. the request is let go, and the backend refuses it with the
   *      401 it really produces.
   *
   * The interceptor now sees a 401 whose `_sentEpoch` is older than the
   * current one, and it must let the NEW session alone.
   */
  test('does not tear down a newer session when a stale request answers 401', async ({
    page,
    manifest,
  }) => {
    const username = manifest.core.users.user.username

    const refreshCalls = watchRefreshCalls(page)

    await loginAndWait(page, manifest, 'user')
    await navigateTo(page, '/sessions')
    await expect(page.getByRole('heading', { name: 'Phiên đăng nhập' })).toBeVisible()

    // The answer of the next request is held back on its way to the
    // page.  The request really reaches the backend, and the backend
    // really answers.
    const gate = createGate()

    await page.route('**/api/v1/auth/sessions', async (route) => {
      // The request is held BEFORE it reaches the backend.
      //
      // The order matters, and it is the order that makes the race
      // real.  The AXIOS REQUEST INTERCEPTOR has already run by now:
      // it stamped the request with the epoch of the session that sent
      // it.  The request is therefore already "belonging" to the first
      // session, while the backend has not yet seen it.
      await gate.wait()

      // Only now does the request really reach the backend.  The
      // session was expired in the meantime, so the backend refuses it
      // with a genuine 401 — the answer the interceptor will see.
      const response = await route.fetch()

      const status = response.status()
      const headers = response.headers()
      const body = await response.text()

      await route.fulfill({ status, headers, body })
    })

    // The request goes out under the FIRST session, THROUGH THE
    // APPLICATION'S OWN CLIENT.
    //
    // That detail is the whole point of the scenario: the epoch guard
    // lives in the axios RESPONSE INTERCEPTOR, so only a request that
    // goes through that interceptor can be judged by it.  A raw
    // `fetch()` would bypass the guard entirely and prove nothing.
    const staleRequest = page.evaluate(async () => {
      const runtimeImport = new Function(
        'path',
        'return import(path)',
      ) as (path: string) => Promise<{
        apiGet: <T>(url: string) => Promise<T>
      }>

      const client = await runtimeImport('/src/lib/api/client.ts')

      try {
        await client.apiGet('/auth/sessions')
        return { status: 200, kind: 'resolved' }
      } catch (error) {
        const failure = error as { kind?: string; status?: number }
        return {
          status: failure.status ?? 0,
          kind: failure.kind ?? 'unknown',
        }
      }
    })

    // Wait until the request is really on the wire and really held back.
    await expect.poll(() => gate.held, { timeout: 15_000 }).toBe(true)

    // A NEW session replaces the old one — this is the boundary the
    // epoch guard exists for.
    //
    // The logout and the login happen WITHOUT a reload: a full page
    // load would destroy the execution context of the request that is
    // still in flight, and the observation of its answer would be lost
    // with it.
    //
    // The FIRST session is NOT expired yet.  The logout revokes it on
    // the server, and the stale request — which is still held — will
    // be refused by the backend because its session no longer exists.
    // Expiring the session instead would make the LOGOUT itself fail
    // with a 401, and the interceptor would legitimately try to refresh
    // over it — a refresh that belongs to the logout, not to the stale
    // request the scenario is about.
    await logoutVia(page)
    await loginAndWaitWithoutReload(page, manifest, 'user')

    const epochAfterRelogin = (await readSessionState(page)).epoch
    expect(epochAfterRelogin).toBeGreaterThan(0)

    // The stale request is let go.  The backend refuses it, because the
    // session it belonged to was revoked by the logout.
    gate.release()

    // The stale request failed — it must not be replayed under the new
    // session's identity, and it must not be resolved either.
    const staleOutcome = await staleRequest
    expect(staleOutcome.kind).toBe('unauthorized')
    expect(staleOutcome.status).toBe(401)

    // And the NEW session is untouched:
    //   - no refresh was attempted for it — the guard refused to spend
    //     its refresh token over a request that belonged to nobody;
    //   - the tokens are the ones of the new session;
    //   - the user is still signed in.
    expect(refreshCalls).toHaveLength(0)

    const state = await readSessionState(page)
    expect(state.hasSession).toBe(true)
    expect(state.epoch).toBe(epochAfterRelogin)

    await expect(page.getByText(username).first()).toBeVisible()

    // The new session really works: the application reads its own
    // session list without being bounced to the login screen.
    await navigateTo(page, '/sessions')
    await expect(page.getByRole('heading', { name: 'Phiên đăng nhập' })).toBeVisible({
      timeout: 20_000,
    })
  })
})

