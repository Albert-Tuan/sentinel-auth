/**
 * E2E-04 — the protective actions.
 *
 * Request a protective action → verify the REAL Core state.
 *
 * The 502 case: the UI must report that the action was NOT applied.
 *
 * ---------------------------------------------------------------------------
 * WHY THE CORE STATE IS CHECKED BEHAVIOURALLY
 * ---------------------------------------------------------------------------
 *
 * `REQUIRE_MFA` sets `users.detection_mfa_once` in the CORE context —
 * a flag no endpoint exposes.  The only honest way to show that the
 * state really changed is to let the SUBJECT try to log in: the next
 * login must be held for an MFA challenge.
 *
 * That is a BEHAVIOURAL proof, and it is what the test uses.  A test
 * that only asserted "the request returned 200" would prove nothing
 * about the Core state.
 *
 * The second half of the scenario is the failure mode that matters most
 * for a security product: when Core CANNOT enforce the action, the
 * backend answers 502, and the UI must say — loudly — that the action
 * was NOT applied.  A UI that reported success would leave a locked-out
 * user believing they were protected when they were not.
 */

import { expect, test } from './support/fixtures'
import { loginAndWait } from './support/login'
import { navigateTo, openAlertDetail } from './support/navigation'
import { createAlert, createOrphanAlert, setMfaGate } from './support/fixtureBridge'
import { probeLogin } from './support/api'

/** The key of the alert with a real subject. */
const ALERT_KEY = 'e2e-04-action'

/** The key of the alert whose subject Core does not know. */
const ORPHAN_KEY = 'e2e-04-orphan'

test.describe('E2E-04 — Protective actions', () => {
  test('applies a protective action and proves the Core state really changed', async ({
    page,
    manifest,
  }) => {
    // The alert this scenario owns, with a REAL subject.
    const alert = await createAlert(ALERT_KEY, 'high', 'open')

    // The one-time MFA gate is re-armed before the action, so the
    // scenario can prove it again on a second run.
    await setMfaGate(alert.subject_username, true)

    await loginAndWait(page, manifest, 'analyst')

    // --- the action ------------------------------------------------------
    await openAlertDetail(page, alert.alert_id, `(e2e-04-action)`)
    await expect(page.getByRole('heading', { name: 'Chi tiết cảnh báo' })).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Hành động bảo vệ' }),
    ).toBeEnabled({ timeout: 15_000 })

    await page.getByRole('button', { name: 'Hành động bảo vệ' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('Chạy hành động bảo vệ?')).toBeVisible()

    await dialog.locator('#alert-action').selectOption('REQUIRE_MFA')
    await dialog.getByLabel('Lý do', { exact: true }).fill('M13.2 E2E-04 — force the MFA.')
    await dialog.getByRole('button', { name: 'Chạy hành động' }).click()

    // The action was accepted: the alert's timeline records it.
    //
    // `.first()` for the same reason as below: every run appends one more
    // event to the same alert.
    await expect(
      page.getByText(/Security action applied: REQUIRE_MFA/).first(),
    ).toBeVisible({ timeout: 20_000 })

    // --- the Core state, proven BEHAVIOURALLY ----------------------------
    //
    // The next login of the SUBJECT must be held for an MFA challenge.
    // The probe goes straight to the backend — the question is about the
    // SERVER's answer, not about what the browser renders.
    const login = await probeLogin(alert.subject_username, 'DemoPass!2026')

    expect(login.mfaRequired).toBe(true)
  })

  test('reports a 502 as "the action was NOT applied"', async ({ page, manifest }) => {
    // The alert whose subject the core context does NOT know.
    const orphan = await createOrphanAlert(ORPHAN_KEY)

    await loginAndWait(page, manifest, 'analyst')

    await openAlertDetail(page, orphan.alert_id, `(e2e-04-orphan)`)
    await expect(page.getByRole('heading', { name: 'Chi tiết cảnh báo' })).toBeVisible()

    await page.getByRole('button', { name: 'Hành động bảo vệ' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    await dialog.locator('#alert-action').selectOption('REQUIRE_MFA')
    await dialog.getByLabel('Lý do').fill('M13.2 E2E-04 — orphan subject, Core cannot enforce.')
    await dialog.getByRole('button', { name: 'Chạy hành động' }).click()

    // -------------------------------------------------------------------------
    // The failure notice.
    //
    // The UI must say — in those words — that the action was NOT applied.
    // A screen that reported "done" would be worse than no screen at all.
    // -------------------------------------------------------------------------
    const notice = page.getByRole('alert').filter({ hasText: 'HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG' })
    await expect(notice).toBeVisible({ timeout: 20_000 })

    // The notice also says what to do about it.
    await expect(notice).toContainText('chưa được áp dụng')

    // The failure was recorded in the timeline, so the SOC can see that
    // the action was requested and did not take effect.
    //
    // `.first()` matters: every run of the scenario appends ONE more
    // failed-action event to the SAME alert, so the timeline legitimately
    // holds several copies of the note.  The assertion is about the
    // presence of the record, not about how many times the suite ran.
    await expect(
      page.getByText(/Security action REQUIRE_MFA was NOT enforced/).first(),
    ).toBeVisible({ timeout: 20_000 })

    // The client keeps working after the failure.
    await navigateTo(page, '/alerts')
    await expect(page.getByRole('heading', { name: 'Hàng đợi cảnh báo' })).toBeVisible()
  })
})
