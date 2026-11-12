/**
 * S-07 — the Profile screen.
 *
 * The screen is read-only and reads everything from the auth context, which
 * is fed by `GET /auth/me`. The test therefore signs the user in through
 * the real provider so the screen sees a populated context.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'

import { __resetClientState } from '@/lib/api/client'
import { __resetStore } from '@/lib/api/tokenStore'
import { renderWithProviders } from '@/test/renderApp'
import { FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN, makeUser } from '@/test/fixtures'

import { ProfilePage } from '@/features/profile/pages/ProfilePage'
import { AuthenticatedHarness } from '@/app/router/guards.test.harness'
import type { AuthApi } from '@/features/auth/useAuth'

beforeEach(() => {
  __resetStore()
  __resetClientState()
})

function makeApi(): AuthApi {
  return {
    login: vi.fn().mockResolvedValue({
      access_token: FAKE_ACCESS_TOKEN,
      refresh_token: FAKE_REFRESH_TOKEN,
      mfa_required: false,
      session_id: 'session-1',
    }),
    verifyMfa: vi.fn(),
    fetchCurrentUser: vi.fn().mockResolvedValue(makeUser()),
    bestEffortLogout: vi.fn().mockResolvedValue(undefined),
  }
}

describe('S-07 Profile', () => {
  it('shows the account fields and the roles from the backend', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <ProfilePage />
      </AuthenticatedHarness>,
      { api: makeApi() },
    )

    expect(await screen.findByText('Hồ sơ')).toBeInTheDocument()
    expect(screen.getByText('analyst')).toBeInTheDocument()
    expect(screen.getByText('analyst@example.com')).toBeInTheDocument()
    expect(screen.getByText('SOC Analyst')).toBeInTheDocument()

    // The role badge comes from /auth/me, never from the client.
    expect(screen.getByText('SOC_ANALYST')).toBeInTheDocument()
    expect(screen.getByText('Đang hoạt động')).toBeInTheDocument()
  })

  it('shows the MFA requirement flag as reported by the backend', async () => {
    const api = makeApi()
    api.fetchCurrentUser = vi
      .fn()
      .mockResolvedValue(makeUser({ admin_mfa_required: true }))

    renderWithProviders(
      <AuthenticatedHarness>
        <ProfilePage />
      </AuthenticatedHarness>,
      { api },
    )

    expect(await screen.findByText('Hồ sơ')).toBeInTheDocument()
    expect(screen.getByText('Có')).toBeInTheDocument()
  })
})
