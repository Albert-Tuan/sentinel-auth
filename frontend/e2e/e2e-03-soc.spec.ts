/**
 * E2E-03 — the SOC_ANALYST journey.
 *
 * Alert Queue → filter → Alert Detail → Evidence → Timeline →
 * Acknowledge → Resolve.
 *
 * ---------------------------------------------------------------------------
 * WHY THE TEST WORKS ON ITS OWN ALERT
 * ---------------------------------------------------------------------------
 *
 * The alert lifecycle is TERMINAL: a resolved alert is immutable and the
 * backend answers 409 for every later mutation.  A test that resolved a
 * SEEDED alert would therefore work exactly once, and the second run of
 * the suite would fail on a state it did not create.
 *
 * The test therefore works on an alert IT owns: `scripts/e2e_fixtures.py`
 * writes it into the demo detection database with a deterministic id, and
 * the row is re-armed to `open` BEFORE the test runs.  The seeded
 * fixtures are never touched, so a defect in the cleanup of the seeded
 * data would still be visible — which is the point of not resetting the
 * stack between tests.
 *
 * The alert is created with a REAL subject (`demo_user`), so the
 * investigation the analyst performs is on a genuine row with genuine
 * evidence.
 */

import { expect, test } from './support/fixtures'
import { loginAndWait } from './support/login'
import { navigateTo, openAlertDetail } from './support/navigation'
import { createAlert } from './support/fixtureBridge'

/** The key of the alert this scenario owns. */
const ALERT_KEY = 'e2e-03-soc'

test.describe('E2E-03 — SOC_ANALYST', () => {
  test('filters the queue, investigates an alert, acknowledges and resolves it', async ({
    page,
    manifest,
  }) => {
    // The alert this scenario owns, re-armed to `open`.
    const alert = await createAlert(ALERT_KEY, 'critical', 'open')

    await loginAndWait(page, manifest, 'analyst')

    // --- the queue ------------------------------------------------------
    await navigateTo(page, '/alerts')
    await expect(page.getByRole('heading', { name: 'Hàng đợi cảnh báo' })).toBeVisible()

    // The queue really carries the seeded alerts.
    await expect(page.getByText('Danh sách cảnh báo an ninh')).toBeVisible()
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 15_000 })

    // --- the filter -----------------------------------------------------
    //
    // The URL is the state of the queue, so a filter is checked by the
    // URL AND by the request the backend answered.
    //
    // The request is captured BEFORE the filter is applied: the listener
    // has to be in place before the request goes out, or the test would
    // wait for a request that already happened.
    const filteredRequest = page.waitForRequest(
      (request) =>
        request.url().includes('/api/v1/alerts') &&
        request.url().includes('status=open') &&
        request.url().includes('risk_level=critical'),
      { timeout: 20_000 },
    )

    await page.locator('#alert-filter-status').selectOption('open')
    await expect(page).toHaveURL(/status=open/, { timeout: 15_000 })

    // The risk filter narrows the result further, and it too lands in
    // the URL.
    await page.locator('#alert-filter-risk').selectOption('critical')
    await expect(page).toHaveURL(/risk_level=critical/, { timeout: 15_000 })

    // The filter really reached the BACKEND.
    const listRequest = await filteredRequest
    expect(listRequest.url()).toContain('status=open')
    expect(listRequest.url()).toContain('risk_level=critical')

    /**
     * Wait for the filtered table.
     *
     * A filter change replaces the query key, and TanStack Query reports
     * the new key as PENDING until it answers.  The screen therefore
     * renders NO table at all for a moment.  Counting the rows
     * immediately would read zero — not because the filter matched
     * nothing, but because the table was not on the screen yet.
     */
    const rows = page.locator('table tbody tr')
    await expect(rows.first()).toBeVisible({ timeout: 15_000 })

    const rowCount = await rows.count()
    expect(rowCount).toBeGreaterThan(0)

    // Every row the backend returned really is a CRITICAL, OPEN alert.
    //
    // The badges are checked INSIDE the row: the filter dropdowns carry
    // options with the very same labels ("Mở", "Nghiêm trọng"), and a
    // page-wide check would match those instead of the rows.
    for (let index = 0; index < rowCount; index += 1) {
      const row = rows.nth(index)
      await expect(row.getByText('Nghiêm trọng')).toBeVisible()
      await expect(row.getByText('Mở', { exact: true })).toBeVisible()
    }

    // --- the alert detail -----------------------------------------------
    //
    // The alert under investigation is the one this scenario owns.  The
    // row is a control rather than a link: the table renders the rows
    // as clickable `<tr role="button">` elements.
    //
    // The lookup walks the pages of the queue, because the demo stack
    // keeps producing alerts of its own and the fixture can therefore
    // sit on a later page than the first one.
    await openAlertDetail(page, alert.alert_id, '(e2e-03-soc)')

    await expect(page.getByRole('heading', { name: 'Chi tiết cảnh báo' })).toBeVisible()

    // --- the evidence ----------------------------------------------------
    await expect(page.locator('#alert-evidence-heading')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Bằng chứng' })).toBeVisible()

    // The evidence really loaded from the backend.
    //
    // `.first()` matters: React's StrictMode renders the tree twice in
    // development, so the same label can appear twice in the DOM.  A
    // strict locator would fail on the ambiguity — and the ambiguity
    // says nothing about the behaviour under test.
    await expect(page.getByText('Mã lần đăng nhập').first()).toBeVisible({
      timeout: 15_000,
    })

    // --- the timeline ----------------------------------------------------
    await expect(page.locator('#alert-timeline-heading')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Dòng thời gian' })).toBeVisible()

    // --- the acknowledge -------------------------------------------------
    const acknowledge = page.getByRole('button', { name: 'Xác nhận cảnh báo' })
    await expect(acknowledge).toBeEnabled()

    await acknowledge.click()

    // The alert is now acknowledged: the status badge on the page says
    // so.  The backend answers 409 for a second acknowledge, which is
    // why the button is disabled afterwards.
    await expect(page.getByText('Đã xác nhận').first()).toBeVisible({ timeout: 15_000 })
    await expect(acknowledge).toBeDisabled({ timeout: 15_000 })

    // --- the resolve -----------------------------------------------------
    await page.getByRole('button', { name: 'Xử lý cảnh báo' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('Xử lý cảnh báo?')).toBeVisible()

    await dialog.locator('#alert-resolution').selectOption('true_attack')
    await dialog.getByRole('button', { name: 'Xử lý' }).click()

    // The alert is resolved, and it is now FROZEN: the screen says so.
    await expect(page.getByText('Đã xử lý').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/đã được xử lý và bị đóng băng/)).toBeVisible({
      timeout: 15_000,
    })

    // Every mutation control is disabled on a resolved alert.
    await expect(page.getByRole('button', { name: 'Xác nhận cảnh báo' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Xử lý cảnh báo' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Giao cho analyst' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Hành động bảo vệ' })).toBeDisabled()
  })
})
