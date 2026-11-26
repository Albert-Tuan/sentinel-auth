/**
 * E2E-05 — Policy Management.
 *
 * Create → Edit Draft → Activate → immutability → 409 concurrency.
 *
 * ---------------------------------------------------------------------------
 * WHY THE SCENARIO OWNS ITS OWN POLICY
 * ---------------------------------------------------------------------------
 *
 * A policy that has been ACTIVATED is frozen for ever: `activated_at`
 * is set and the backend answers 409 for every later edit.  A test that
 * activated a SEEDED policy would therefore work exactly once, and the
 * second run of the suite would fail on a state it did not create.
 *
 * The scenario therefore creates its own policy through the REAL
 * `POST /policies` endpoint, and removes it before the next run with
 * `scripts/e2e_fixtures.py`.  The seeded policies of the demo stack are
 * never touched — so a defect in the cleanup of the seeded data would
 * still be visible, which is the point of not resetting the stack.
 *
 * ---------------------------------------------------------------------------
 * WHY THE 409 CASE IS PROVED AGAINST THE LIVE BACKEND
 * ---------------------------------------------------------------------------
 *
 * The concurrency token is `expected_updated_at`: the client sends back
 * the `updated_at` it last read, and the backend refuses the write when
 * the policy changed in the meantime.  A test that only asserted "the
 * save returned 409" would prove nothing — the test must show that the
 * conflict really came from a STALE token, and that a write carrying the
 * FRESH token succeeds.
 *
 * The stale write is therefore made against the LIVE backend with a
 * deliberately outdated token, and the answer is checked twice: the
 * status is 409, and the body names the concurrency rule.
 */

import { expect, test } from './support/fixtures'
import { loginAndWait, passwordOf } from './support/login'
import { navigateTo } from './support/navigation'
import { deletePolicy, resetRateLimits, restoreActivePolicy } from './support/fixtureBridge'
import { apiRequest } from './support/api'
import { otpOffset, waitForCode } from './support/otp'
import type { FixtureManifest } from './support/manifest'

/** The version of the policy this scenario owns. */
const POLICY_VERSION = 'v13.2'

/** The rules of the policy — one usable rule is enough for the backend. */
const RULES = [
  {
    name: 'e2e_unusual_hour',
    field: 'hour_of_day',
    operator: 'not_between',
    value: [7, 22],
    weight: 0.3,
    score: 0.8,
    enabled: true,
  },
]

const CONFIG = {
  weights: { rule: 0.4, ml: 0.6 },
  thresholds: { low: 0.25, medium: 0.5, high: 0.75 },
}

test.describe('E2E-05 — Policy Management', () => {
  /**
   * Put the demo stack back the way the scenario found it.
   *
   * `afterEach` runs after EVERY test — including a failed one — so a
   * scenario that dies half-way through still leaves the demo with
   * exactly one active policy.  Without this, a failed run would leave
   * the E2E policy in service and the demo would keep scoring logins
   * with a policy the demo stack never wrote.
   */
  test.afterEach(async () => {
    await restoreActivePolicy()
  })

  test('creates a draft policy, edits it, activates it and proves it is frozen', async ({
    page,
    manifest,
  }) => {
    // The scenario owns its policy.  A policy that was activated in an
    // earlier run is removed, so the scenario starts from the "never
    // activated" state it needs.
    await deletePolicy(POLICY_VERSION)

    await loginAndWait(page, manifest, 'admin')

    // --- create --------------------------------------------------------
    //
    // The creation goes through the REAL backend endpoint, so the policy
    // the test then edits is a policy the backend really owns.
    //
    // The token is fetched ONCE: every fetch performs a full MFA
    // handshake, and a handshake per assertion would be both slow and
    // noisy in the SMTP sink.
    const token = await adminToken(manifest)

    const created = await apiRequest('/policies', {
      method: 'POST',
      token,
      body: {
        version: POLICY_VERSION,
        name: 'M13.2 E2E-05 policy',
        description: 'The policy the M13.2 browser scenario owns.',
        rules: RULES,
        config: CONFIG,
      },
    })

    expect(created.status, created.raw).toBe(201)
    const policy = created.body as Record<string, unknown>
    const policyId = String(policy.id)

    // A new policy is ALWAYS inactive: activation is a separate step, so
    // a half-finished policy can never influence the scoring of a login.
    expect(policy.is_active).toBe(false)
    expect(policy.activated_at).toBeNull()

    // The policy is in the registry, and it is a DRAFT.
    await navigateTo(page, '/policies')
    await expect(page.getByRole('heading', { name: 'Chính sách phát hiện' })).toBeVisible()
    await expect(page.getByText('M13.2 E2E-05 policy').first()).toBeVisible({ timeout: 15_000 })

    // The lifecycle badge of THAT policy says DRAFT.
    //
    // The check is EXACT and is scoped to the card of the policy: the
    // status filter dropdown carries an option with a very similar
    // label ("Bản nháp (DRAFT)"), and a loose page-wide match would
    // find the option instead of the badge.
    const ownCard = page.locator('article').filter({ hasText: 'M13.2 E2E-05 policy' }).first()
    await expect(ownCard.getByText('BẢN NHÁP', { exact: true })).toBeVisible()

    // --- edit the draft -------------------------------------------------
    await navigateTo(page, `/policies/${policyId}`)
    await expect(page.getByRole('heading', { name: 'M13.2 E2E-05 policy' })).toBeVisible()

    // The draft is editable, so the editor is NOT in read-only mode.
    const nameInput = page.locator('#policy-name')
    await expect(nameInput).toBeEnabled({ timeout: 15_000 })

    await nameInput.fill('M13.2 E2E-05 policy — edited')
    await page.getByRole('button', { name: 'Lưu thay đổi' }).click()

    // The edit really reached the backend: the detail endpoint reports
    // the new name.
    await expect
      .poll(
        async () => {
          const response = await apiRequest(`/policies/${policyId}`, { token })
          return (response.body as Record<string, unknown>)?.name
        },
        { timeout: 20_000 },
      )
      .toBe('M13.2 E2E-05 policy — edited')

    // --- activate -------------------------------------------------------
    await page.getByRole('button', { name: 'Kích hoạt chính sách' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('Kích hoạt chính sách?')).toBeVisible()
    await dialog.getByRole('button', { name: 'Kích hoạt' }).click()

    // The policy is now in service.
    await expect
      .poll(
        async () => {
          const response = await apiRequest(`/policies/${policyId}`, { token })
          return (response.body as Record<string, unknown>)?.is_active
        },
        { timeout: 20_000 },
      )
      .toBe(true)

    // --- the immutability -----------------------------------------------
    //
    // The policy that was just activated is IN SERVICE, and the editor is
    // read-only: the rules of a policy in service are referenced by the
    // risk assessments it produced, so they may not be rewritten.
    await expect(page.getByText('ĐANG ÁP DỤNG', { exact: true }).first()).toBeVisible({
      timeout: 15_000,
    })
    await expect(page.locator('#policy-name')).toBeDisabled()
    await expect(page.getByText('Chế độ chỉ đọc')).toBeVisible()

    // The seeded policy of the demo stack was deactivated by the
    // activation — that is what "only one policy may be in service"
    // means — and it is now FROZEN rather than active.
    await navigateTo(page, '/policies')
    const seededCard = page
      .locator('article')
      .filter({ hasText: 'M13 demo active policy' })
      .first()
    await expect(seededCard.getByText('ĐÃ ĐÓNG BĂNG', { exact: true })).toBeVisible({
      timeout: 15_000,
    })

    // The BACKEND refuses the edit as well — the screen is not the only
    // line of defence.
    const frozenWrite = await apiRequest(`/policies/${policyId}`, {
      method: 'PUT',
      token,
      body: {
        name: 'a write that must be refused',
        expected_updated_at: policy.updated_at,
      },
    })

    expect(frozenWrite.status).toBe(409)
    expect(String(frozenWrite.raw)).toContain('Policy is immutable')
  })

  test('refuses a stale write with 409 and accepts the fresh token', async ({
    manifest,
  }) => {
    await deletePolicy(POLICY_VERSION)

    const token = await adminToken(manifest)

    const created = await apiRequest('/policies', {
      method: 'POST',
      token,
      body: {
        version: POLICY_VERSION,
        name: 'M13.2 E2E-05 concurrency policy',
        rules: RULES,
        config: CONFIG,
      },
    })
    expect(created.status, created.raw).toBe(201)

    const policy = created.body as Record<string, unknown>
    const policyId = String(policy.id)
    const staleToken = String(policy.updated_at)

    // Somebody else writes first.  This is the "concurrent writer" the
    // optimistic-concurrency token is there to detect.
    const first = await apiRequest(`/policies/${policyId}`, {
      method: 'PUT',
      token,
      body: {
        name: 'M13.2 E2E-05 concurrency policy — first writer',
        expected_updated_at: staleToken,
      },
    })
    expect(first.status, first.raw).toBe(200)

    // The second writer still holds the OLD token.  The backend must
    // refuse it — otherwise the first writer's change would be silently
    // discarded.
    const second = await apiRequest(`/policies/${policyId}`, {
      method: 'PUT',
      token,
      body: {
        name: 'M13.2 E2E-05 concurrency policy — second writer',
        expected_updated_at: staleToken,
      },
    })

    expect(second.status).toBe(409)
    expect(String(second.raw)).toContain('Policy was modified by someone else')

    // The refused write really changed nothing: the first writer's name
    // is still the one the backend holds.
    const after = await apiRequest(`/policies/${policyId}`, { token })
    const afterBody = after.body as Record<string, unknown>
    expect(afterBody.name).toBe('M13.2 E2E-05 concurrency policy — first writer')

    // And the FRESH token works: the conflict is about the stale token,
    // not about the endpoint refusing every write.
    const fresh = await apiRequest(`/policies/${policyId}`, {
      method: 'PUT',
      token,
      body: {
        name: 'M13.2 E2E-05 concurrency policy — re-read writer',
        expected_updated_at: afterBody.updated_at,
      },
    })
    expect(fresh.status, fresh.raw).toBe(200)
  })
})

/**
 * The bearer token of the demo admin.
 *
 * The admin account carries the permanent MFA flag, so a plain login
 * does not return a token — the handshake has to be completed.  The
 * helper therefore performs the handshake through the SMTP sink, exactly
 * like the browser does.
 */
async function adminToken(manifest: FixtureManifest): Promise<string> {
  const admin = manifest.core.users.admin
  const offset = otpOffset()
  await resetRateLimits()

  const login = await apiRequest('/auth/login', {
    method: 'POST',
    body: { username: admin.username, password: passwordOf('admin') },
  })

  const body = (login.body ?? {}) as Record<string, unknown>
  if (!body.mfa_required) {
    return String(body.access_token ?? '')
  }

  const code = await waitForCode(admin.email, offset)
  const verified = await apiRequest('/auth/mfa/verify', {
    method: 'POST',
    body: { session_id: body.session_id, mfa_code: code },
  })

  expect(verified.status, verified.raw).toBe(200)
  return String((verified.body as Record<string, unknown>).access_token ?? '')
}
