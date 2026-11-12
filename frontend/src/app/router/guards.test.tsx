/**
 * Route guard and RBAC navigation tests.
 *
 * Covers: protected route redirection, role-gated routes, and the
 * role-filtered sidebar. The role requirement comes from the shared
 * policy, so the guard and the navigation are exercised against the
 * same table the app uses at runtime.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '@/test/renderApp'
import { RequireAuth, RequireRole } from '@/app/router/guards'
import { AuthenticatedHarness } from '@/app/router/guards.test.harness'
import { Sidebar } from '@/app/layout/Sidebar'
import { PATHS } from '@/app/router/paths'
import { navigationFor } from '@/app/router/policy'
import { __resetStore } from '@/lib/api/tokenStore'
import type { AuthApi } from '@/features/auth/useAuth'
import type { UserRole } from '@/types/api'
import { FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN, makeUser } from '@/test/fixtures'

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

/**
 * A tiny app that exercises the guards.
 */
function GuardedApp() {
  return (
    <Routes>
      <Route path={PATHS.login} element={<div>Login screen</div>} />
      <Route path={PATHS.forbidden} element={<div>Forbidden</div>} />
      <Route element={<RequireAuth />}>
        <Route path={PATHS.home} element={<div>Home</div>} />
        <Route element={<RequireRole section="admin" />}>
          <Route path={PATHS.adminUsers} element={<div>User admin</div>} />
        </Route>
        <Route element={<RequireRole section="manager" />}>
          <Route path={PATHS.managerDashboard} element={<div>Manager</div>} />
        </Route>
        <Route element={<RequireRole section="alerts" />}>
          <Route path={PATHS.alerts} element={<div>Alerts</div>} />
        </Route>
      </Route>
    </Routes>
  )
}

describe('RequireAuth', () => {
  it('redirects an anonymous visitor to the login screen', () => {
    renderWithProviders(<GuardedApp />, {
      initialEntries: [PATHS.home],
      api: makeApi([]),
    })

    expect(screen.getByText('Login screen')).toBeInTheDocument()
    expect(screen.queryByText('Home')).not.toBeInTheDocument()
  })

  it('admits an authenticated user', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.home], api: makeApi(['SOC_ANALYST']) },
    )

    expect(await screen.findByText('Home')).toBeInTheDocument()
  })
})

describe('RequireRole', () => {
  it('blocks a SOC analyst from the SECURITY_ADMIN area', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.adminUsers], api: makeApi(['SOC_ANALYST']) },
    )

    // The user is authenticated, but the role guard denies the admin area
    // and sends them to the forbidden screen.
    expect(await screen.findByText('Forbidden')).toBeInTheDocument()
    expect(screen.queryByText('User admin')).not.toBeInTheDocument()
  })

  it('admits a SECURITY_ADMIN into the admin area', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.adminUsers], api: makeApi(['SECURITY_ADMIN']) },
    )

    expect(await screen.findByText('User admin')).toBeInTheDocument()
  })

  it('blocks a SECURITY_ADMIN from the manager area', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.managerDashboard], api: makeApi(['SECURITY_ADMIN']) },
    )

    expect(await screen.findByText('Forbidden')).toBeInTheDocument()
    expect(screen.queryByText('Manager')).not.toBeInTheDocument()
  })

  it('blocks a plain USER from the alert queue', async () => {
    // The alert queue is an analyst/manager area — a plain user must not
    // reach it even though the route exists.
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.alerts], api: makeApi(['USER']) },
    )

    expect(await screen.findByText('Forbidden')).toBeInTheDocument()
    expect(screen.queryByText('Alerts')).not.toBeInTheDocument()
  })

  it('admits a SECURITY_MANAGER into the alert queue', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.alerts], api: makeApi(['SECURITY_MANAGER']) },
    )

    expect(await screen.findByText('Alerts')).toBeInTheDocument()
  })

  it('sends an anonymous visitor to the login screen, not to forbidden', () => {
    renderWithProviders(<GuardedApp />, {
      initialEntries: [PATHS.adminUsers],
      api: makeApi([]),
    })

    expect(screen.getByText('Login screen')).toBeInTheDocument()
    expect(screen.queryByText('Forbidden')).not.toBeInTheDocument()
  })
})

describe('role-filtered navigation', () => {
  it('filters the navigation down to the roles the user holds', () => {
    const analystOnly = navigationFor(['SOC_ANALYST']).map((i) => i.label)
    expect(analystOnly).toContain('Cảnh báo')
    expect(analystOnly).not.toContain('Người dùng')
    expect(analystOnly).not.toContain('Tổng quan')

    const adminOnly = navigationFor(['SECURITY_ADMIN']).map((i) => i.label)
    expect(adminOnly).toContain('Người dùng')
    expect(adminOnly).toContain('Chính sách')
    expect(adminOnly).not.toContain('Cảnh báo')

    const managerOnly = navigationFor(['SECURITY_MANAGER']).map((i) => i.label)
    expect(managerOnly).toContain('Tổng quan')
    expect(managerOnly).toContain('Cảnh báo')
    expect(managerOnly).not.toContain('Người dùng')
  })

  it('shows no navigation for a user with no roles', () => {
    expect(navigationFor([])).toEqual([])
  })

  it('shows only the links the signed-in role permits', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <Sidebar />
      </AuthenticatedHarness>,
      { api: makeApi(['SECURITY_ADMIN']) },
    )

    expect(await screen.findByRole('link', { name: 'Người dùng' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Tổng quan' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Cảnh báo' })).not.toBeInTheDocument()
  })
})
