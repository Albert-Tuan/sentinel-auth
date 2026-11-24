/**
 * The home route redirect and the deep-link behaviour.
 *
 * `/` must land the user on their role's landing page. The redirect has to
 * survive the race between the login handler's own navigation and the
 * `<Navigate>` that the login page renders once the session is established.
 *
 * This file also covers the DEEP-LINK scenarios the role policy has to
 * get right:
 *
 *   - an anonymous visitor who deep-links into a restricted area is sent to
 *     the login screen with the destination remembered;
 *   - after signing in with a role that may NOT reach that destination,
 *     the user lands on their own landing page — never on `/forbidden`
 *     and never in a redirect loop;
 *   - signing out and signing in again with a different role lands on the
 *     new role's landing page.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'

import { renderRouter } from '@/test/renderApp'
import { PATHS } from '@/app/router/paths'
import { __resetStore } from '@/lib/api/tokenStore'
import { FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN, makeUser } from '@/test/fixtures'
import type { AuthApi } from '@/features/auth/useAuth'
import type { UserRole } from '@/types/api'

beforeEach(() => {
  __resetStore()
})

function makeApi(roles: UserRole[]): AuthApi {
  return {
    login: vi.fn().mockResolvedValue({
      access_token: FAKE_ACCESS_TOKEN,
      refresh_token: FAKE_REFRESH_TOKEN,
      mfa_required: false,
      session_id: 'session-1',
    }),
    verifyMfa: vi.fn(),
    fetchCurrentUser: vi.fn().mockResolvedValue(makeUser({ roles })),
    bestEffortLogout: vi.fn().mockResolvedValue(undefined),
  }
}

async function signIn(username = 'user') {
  const user = (await import('@testing-library/user-event')).default.setup()
  await user.type(screen.getByLabelText('Tên đăng nhập'), username)
  await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
  await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))
}

describe('login redirect', () => {
  it('lands a SOC analyst on the alert queue, not on the forbidden screen', async () => {
    const { router } = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['SOC_ANALYST', 'USER']),
    })

    await signIn('analyst')

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/alerts'),
    )
  })

  it('sends a SECURITY_ADMIN to the admin area, not to the forbidden screen', async () => {
    const { router } = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['SECURITY_ADMIN', 'USER']),
    })

    await signIn('admin')

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/admin/users'),
    )
  })

  it('sends a SECURITY_MANAGER to the manager area', async () => {
    const { router } = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['SECURITY_MANAGER', 'USER']),
    })

    await signIn('manager')

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/manager/dashboard'),
    )
  })

  it('sends a plain USER to a page they can reach, not to the forbidden screen', async () => {
    const { router } = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['USER']),
    })

    await signIn('plain')

    // A plain user has no alerts permission, so they stay on a page they
    // can actually reach.
    await waitFor(() =>
      expect(router.state.location.pathname).not.toBe(PATHS.forbidden),
    )
    expect(router.state.location.pathname).toBe('/sessions')
  })

  it('does not restore a destination the signed-in role cannot reach', async () => {
    // The user was bounced off the admin area earlier; the remembered
    // destination must not send them back to a 403 page.
    const { router } = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['SOC_ANALYST', 'USER']),
    })

    await signIn('analyst')

    await waitFor(() => expect(router.state.location.pathname).toBe('/alerts'))
    expect(router.state.location.pathname).not.toBe(PATHS.forbidden)
  })
})

describe('deep links', () => {
  it('sends an anonymous visitor to the login screen and remembers the destination', async () => {
    const { router } = renderRouter({
      initialEntries: [PATHS.adminUsers],
      api: makeApi(['SECURITY_ADMIN', 'USER']),
    })

    await waitFor(() =>
      expect(router.state.location.pathname).toBe(PATHS.login),
    )
    expect(router.state.location.state).toEqual({ from: PATHS.adminUsers })
  })

  it('restores a deep link the signed-in role may reach', async () => {
    const { router } = renderRouter({
      initialEntries: [PATHS.adminUsers],
      api: makeApi(['SECURITY_ADMIN', 'USER']),
    })

    await waitFor(() =>
      expect(router.state.location.pathname).toBe(PATHS.login),
    )

    await signIn('admin')

    await waitFor(() =>
      expect(router.state.location.pathname).toBe(PATHS.adminUsers),
    )
  })

  it('falls back to the landing page when the deep link is out of reach', async () => {
    const { router } = renderRouter({
      initialEntries: [PATHS.adminUsers],
      api: makeApi(['SOC_ANALYST', 'USER']),
    })

    await waitFor(() =>
      expect(router.state.location.pathname).toBe(PATHS.login),
    )

    await signIn('analyst')

    // The analyst may not open the admin area: the remembered destination
    // is dropped and the landing page is used instead.
    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/alerts'),
    )
    expect(router.state.location.pathname).not.toBe(PATHS.forbidden)
  })

  it('shows the 404 page for a path the app does not have', async () => {
    // An unknown URL is not part of the protected tree, so it renders the
    // 404 page instead of bouncing the visitor through the login screen.
    const { router } = renderRouter({
      initialEntries: ['/does-not-exist'],
      api: makeApi(['SOC_ANALYST', 'USER']),
    })

    expect(
      await screen.findByText('Không tìm thấy trang'),
    ).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/does-not-exist')
    expect(router.state.location.pathname).not.toBe(PATHS.forbidden)
  })

  it('does not send a signed-in user back to the login screen', async () => {
    // A remembered `/login` destination would bounce the user straight out
    // again, so the policy replaces it with the landing page.
    const { router } = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['SOC_ANALYST', 'USER']),
    })

    await signIn('analyst')

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/alerts'),
    )
    expect(router.state.location.pathname).not.toBe(PATHS.login)
  })
})

describe('role switching', () => {
  it('lands on the new role landing page after a role change', async () => {
    const first = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['SECURITY_ADMIN', 'USER']),
    })

    await signIn('admin')
    await waitFor(() =>
      expect(first.router.state.location.pathname).toBe('/admin/users'),
    )
    first.unmount()

    // The user signs out and signs in again with a DIFFERENT role. The
    // landing page must follow the new role, not the old one.
    __resetStore()

    const second = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['SOC_ANALYST', 'USER']),
    })

    await signIn('analyst')

    await waitFor(() =>
      expect(second.router.state.location.pathname).toBe('/alerts'),
    )
    expect(second.router.state.location.pathname).not.toBe(PATHS.forbidden)
  })

  it('does not carry the previous role landing page into the new session', async () => {
    const first = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['SECURITY_MANAGER', 'USER']),
    })

    await signIn('manager')
    await waitFor(() =>
      expect(first.router.state.location.pathname).toBe('/manager/dashboard'),
    )
    first.unmount()

    __resetStore()

    const second = renderRouter({
      initialEntries: [PATHS.login],
      api: makeApi(['USER']),
    })

    await signIn('plain')

    await waitFor(() =>
      expect(second.router.state.location.pathname).toBe('/sessions'),
    )
    expect(second.router.state.location.pathname).not.toBe(
      '/manager/dashboard',
    )
    expect(second.router.state.location.pathname).not.toBe(PATHS.forbidden)
  })
})
