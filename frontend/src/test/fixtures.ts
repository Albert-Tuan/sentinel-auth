/**
 * Test fixtures.
 *
 * The values here are obviously fake. They exist so the tests exercise the
 * contract shape, not a real credential.
 */

import type { CurrentUser, UserRole } from '@/types/api'

export const FAKE_ACCESS_TOKEN = 'test-access-token-aaaa'
export const FAKE_REFRESH_TOKEN = 'test-refresh-token-bbbb'
export const FAKE_MFA_TRANSACTION_ID = '11111111-2222-3333-4444-555555555555'
export const FAKE_SESSION_ID = '66666666-7777-8888-9999-000000000000'

export function makeUser(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: '99999999-0000-0000-0000-000000000001',
    username: 'analyst',
    email: 'analyst@example.com',
    full_name: 'SOC Analyst',
    status: 'active',
    admin_mfa_required: false,
    roles: ['SOC_ANALYST' as UserRole],
    last_login_at: '2026-01-01T10:00:00.000000+00:00',
    failed_login_count: 0,
    locked_at: null,
    created_at: '2026-01-01T09:00:00.000000+00:00',
    ...overrides,
  }
}
