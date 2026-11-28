/**
 * E2E-02 — the SECURITY_ADMIN journey.
 *
 * Login → a REAL MFA handshake through the SMTP sink → User Management
 * → Audit Logs.
 *
 * ---------------------------------------------------------------------------
 * WHY THE MFA HANDSHAKE IS PROVED, NOT ASSUMED
 * ---------------------------------------------------------------------------
 *
 * The admin account carries the permanent MFA flag, so the login NEVER
 * returns a session on its own: the backend holds it for a challenge
 * and sends a six-digit code through a real SMTP hop into the local
 * sink.  The test reads that code out of the sink and types it into the
 * browser.
 *
 * The test therefore proves three things at once:
 *
 *   1. the challenge screen really appears — the session does not exist
 *      before the code is verified;
 *   2. the code really travels through SMTP — the test reads it from
 *      the sink's log file, not from a mocked response;
 *   3. a WRONG code is refused — which proves the handshake is really
 *      being verified by the backend and is not a formality.
 *
 * The IAM mutation the test performs is on `demo_user`: it grants the
 * `SOC_ANALYST` role and then revokes it again.  The base role `USER`
 * is never touched — the backend refuses to revoke it, and the
 * directory does not even offer it.
 */

import { expect, test } from './support/fixtures'
import { passwordOf } from './support/login'
import { navigateTo } from './support/navigation'
import { otpOffset, waitForCode } from './support/otp'
import { resetRateLimits } from './support/fixtureBridge'

test.describe('E2E-02 — SECURITY_ADMIN', () => {
  test('completes a real MFA handshake, reaches the user directory and the audit log', async ({
    page,
    manifest,
  }) => {
    const admin = manifest.core.users.admin
    const target = manifest.core.users.user

    // --- the login and the challenge ------------------------------------
    //
    // The offset is taken BEFORE the login, so the code read below
    // belongs to THIS login and not to an earlier one.
    const offset = otpOffset()

    // The login endpoint is rate-limited per client IP; the counter of
    // the test client is cleared so the suite does not trip a control
    // that is meant for real traffic.
    await resetRateLimits()

    await page.goto('/login')
    await page.getByLabel('Tên đăng nhập').fill(admin.username)
    await page.getByLabel('Mật khẩu').fill(passwordOf('admin'))
    await page.getByRole('button', { name: 'Đăng nhập' }).click()

    // The challenge screen appears: the account is held.
    const mfaInput = page.locator('#mfa-code')
    await expect(mfaInput).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('heading', { name: 'Xác thực hai yếu tố' })).toBeVisible()

    // The code really arrived through SMTP.
    const recipient = admin.email
    const code = await waitForCode(recipient, offset)

    // A WRONG code is refused: the handshake is verified, not waved
    // through.  Without this check, a test would pass even if the
    // backend accepted any six digits.
    await mfaInput.fill('000000')
    await page.getByRole('button', { name: 'Xác thực' }).click()
    await expect(page.locator('#mfa-code')).toBeVisible({ timeout: 15_000 })

    // The right code is accepted.
    await mfaInput.fill(code)
    await page.getByRole('button', { name: 'Xác thực' }).click()

    await expect(mfaInput).toBeHidden({ timeout: 20_000 })
    await expect(page.getByText(admin.username).first()).toBeVisible({ timeout: 20_000 })

    // The top bar shows the admin's real roles.
    await expect(page.getByText('SECURITY_ADMIN').first()).toBeVisible()

    // --- the user directory ---------------------------------------------
    await navigateTo(page, '/admin/users')
    await expect(page.getByRole('heading', { name: 'Quản lý người dùng' })).toBeVisible()

    // The seeded accounts are really listed.
    await expect(page.getByText(target.username).first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(admin.username).first()).toBeVisible()

    // The MFA flag of the admin is shown as the backend holds it.
    const adminRow = page.locator('table tbody tr').filter({ hasText: admin.username }).first()
    await expect(adminRow.getByText('Bắt buộc').first()).toBeVisible()

    // --- the IAM mutation -----------------------------------------------
    //
    // The role is granted to `demo_user` and then revoked again, so the
    // test leaves the seeded fixtures exactly as it found them.
    const targetRow = page.locator('table tbody tr').filter({ hasText: target.username }).first()

    await targetRow.getByRole('button', { name: 'Cấp vai trò' }).click()

    const grantDialog = page.getByRole('dialog')
    await expect(grantDialog).toBeVisible()
    await grantDialog.locator('select').selectOption('SOC_ANALYST')
    await grantDialog.getByRole('button', { name: 'Cấp vai trò' }).click()

    // The granted role shows up in the row.
    await expect(targetRow.getByText('SOC_ANALYST').first()).toBeVisible({ timeout: 15_000 })

    // The base role is NOT offered for revocation: the backend refuses
    // to revoke it with a 422, and the directory does not pretend
    // otherwise.
    await expect(
      targetRow.getByRole('button', { name: 'Thu hồi vai trò USER của ' + target.username }),
    ).toHaveCount(0)

    // And now it is revoked again.
    await targetRow.getByRole('button', { name: 'Thu hồi vai trò SOC_ANALYST' }).click()

    const revokeDialog = page.getByRole('dialog')
    await expect(revokeDialog).toBeVisible()
    await revokeDialog.getByRole('button', { name: 'Thu hồi vai trò' }).click()

    await expect(
      targetRow.getByText('SOC_ANALYST'),
      'the granted role is still shown after it was revoked',
    ).toHaveCount(0, { timeout: 15_000 })

    // --- the audit log --------------------------------------------------
    await navigateTo(page, '/admin/audit-logs')
    await expect(page.getByRole('heading', { name: 'Nhật ký kiểm toán' })).toBeVisible()

    // The IAM mutations above were audited: the trail names them.
    await expect(page.getByText('assign_role').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('revoke_role').first()).toBeVisible({ timeout: 15_000 })

    // The trail is filterable, and the filter really narrows the list.
    await page.getByLabel('Hành động').fill('assign_role')
    await page.getByRole('button', { name: /Lọc|Tìm|Áp dụng/i }).first().click()

    await expect(page.getByText('assign_role').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('revoke_role')).toHaveCount(0, { timeout: 15_000 })
  })
})
