/**
 * Stage 4 — RBAC of the SOC alert screens.
 *
 * The route policy is the SINGLE source of truth (`@/app/router/policy`),
 * and the backend enforces the same allow-list (`app/alerts.py`:
 * `require_roles("SOC_ANALYST", "SECURITY_MANAGER")`). These tests pin
 * the frontend half of that contract:
 *
 *   SOC_ANALYST     → allowed
 *   SECURITY_MANAGER→ allowed
 *   SECURITY_ADMIN  → denied (an admin is NOT a SOC role)
 *   USER            → denied
 *   anonymous       → redirected to /login
 *
 * The policy table is not modified: these tests only assert that the
 * existing, centralised policy produces the right outcome.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'

import { renderWithProviders } from '@/test/renderApp'
import { RequireAuth, RequireRole } from '@/app/router/guards'
import { AuthenticatedHarness } from '@/app/router/guards.test.harness'
import { PATHS, PATH_PATTERNS } from '@/app/router/paths'
import {
  canAccessPath,
  landingPathFor,
  navigationFor,
  sectionRoles,
} from '@/app/router/policy'
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

/** An app that mounts the alert routes behind the real guards. */
function GuardedAlertsApp() {
  return (
    <Routes>
      <Route path={PATHS.login} element={<div>Login screen</div>} />
      <Route path={PATHS.forbidden} element={<div>Forbidden screen</div>} />
      <Route element={<RequireAuth />}>
        <Route element={<RequireRole section="alerts" />}>
          <Route path={PATHS.alerts} element={<div>Alert queue screen</div>} />
          <Route
            path={PATH_PATTERNS.alertDetail}
            element={<div>Alert detail screen</div>}
          />
        </Route>
      </Route>
    </Routes>
  )
}

describe('SOC alert route policy', () => {
  it('grants the alert section to SOC_ANALYST and SECURITY_MANAGER only', () => {
    expect(sectionRoles('alerts')).toEqual([
      'SOC_ANALYST',
      'SECURITY_MANAGER',
    ])
  })

  it('keeps the alert routes out of reach of the other roles', () => {
    expect(canAccessPath(PATHS.alerts, ['SOC_ANALYST'])).toBe(true)
    expect(canAccessPath(PATHS.alerts, ['SECURITY_MANAGER'])).toBe(true)
    expect(canAccessPath(PATHS.alerts, ['SECURITY_ADMIN'])).toBe(false)
    expect(canAccessPath(PATHS.alerts, ['USER'])).toBe(false)
    expect(canAccessPath(PATHS.alerts, [])).toBe(false)
  })

  it('keeps the alert DETAIL route under the same policy', () => {
    expect(canAccessPath('/alerts/abc-123', ['SOC_ANALYST'])).toBe(true)
    expect(canAccessPath('/alerts/abc-123', ['SECURITY_MANAGER'])).toBe(true)
    expect(canAccessPath('/alerts/abc-123', ['SECURITY_ADMIN'])).toBe(false)
    expect(canAccessPath('/alerts/abc-123', ['USER'])).toBe(false)
  })

  it('does not leak the alert queue to a SECURITY_ADMIN', () => {
    // An admin is not a SOC role: the backend answers 403 for
    // `GET /alerts`, so the frontend must not offer the screen.
    expect(canAccessPath(PATHS.alerts, ['SECURITY_ADMIN'])).toBe(false)
    expect(
      navigationFor(['SECURITY_ADMIN']).map((entry) => entry.path),
    ).not.toContain(PATHS.alerts)
  })

  it('offers the alert queue to a SOC_ANALYST and to a SECURITY_MANAGER', () => {
    expect(
      navigationFor(['SOC_ANALYST']).map((entry) => entry.path),
    ).toContain(PATHS.alerts)
    expect(
      navigationFor(['SECURITY_MANAGER']).map((entry) => entry.path),
    ).toContain(PATHS.alerts)
  })

  it('lands a SOC_ANALYST on the alert queue', () => {
    expect(landingPathFor(['SOC_ANALYST'])).toBe(PATHS.alerts)
  })
})

describe('SOC alert route guards', () => {
  it('admits a SOC_ANALYST into the alert queue', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedAlertsApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.alerts], api: makeApi(['SOC_ANALYST']) },
    )

    expect(await screen.findByText('Alert queue screen')).toBeInTheDocument()
  })

  it('admits a SECURITY_MANAGER into the alert queue', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedAlertsApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.alerts], api: makeApi(['SECURITY_MANAGER']) },
    )

    expect(await screen.findByText('Alert queue screen')).toBeInTheDocument()
  })

  it('admits a SOC_ANALYST into the alert detail', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedAlertsApp />
      </AuthenticatedHarness>,
      {
        initialEntries: ['/alerts/abc-123'],
        api: makeApi(['SOC_ANALYST']),
      },
    )

    expect(await screen.findByText('Alert detail screen')).toBeInTheDocument()
  })

  it('denies a SECURITY_ADMIN the alert queue', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedAlertsApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.alerts], api: makeApi(['SECURITY_ADMIN']) },
    )

    expect(await screen.findByText('Forbidden screen')).toBeInTheDocument()
    expect(screen.queryByText('Alert queue screen')).not.toBeInTheDocument()
  })

  it('denies a SECURITY_ADMIN the alert detail', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedAlertsApp />
      </AuthenticatedHarness>,
      {
        initialEntries: ['/alerts/abc-123'],
        api: makeApi(['SECURITY_ADMIN']),
      },
    )

    expect(await screen.findByText('Forbidden screen')).toBeInTheDocument()
    expect(screen.queryByText('Alert detail screen')).not.toBeInTheDocument()
  })

  it('denies a plain USER the alert queue', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedAlertsApp />
      </AuthenticatedHarness>,
      { initialEntries: [PATHS.alerts], api: makeApi(['USER']) },
    )

    expect(await screen.findByText('Forbidden screen')).toBeInTheDocument()
    expect(screen.queryByText('Alert queue screen')).not.toBeInTheDocument()
  })

  it('denies a plain USER the alert detail', async () => {
    renderWithProviders(
      <AuthenticatedHarness>
        <GuardedAlertsApp />
      </AuthenticatedHarness>,
      {
        initialEntries: ['/alerts/abc-123'],
        api: makeApi(['USER']),
      },
    )

    expect(await screen.findByText('Forbidden screen')).toBeInTheDocument()
    expect(screen.queryByText('Alert detail screen')).not.toBeInTheDocument()
  })

  it('sends an anonymous visitor to the login screen', () => {
    renderWithProviders(<GuardedAlertsApp />, {
      initialEntries: [PATHS.alerts],
      api: makeApi([]),
    })

    expect(screen.getByText('Login screen')).toBeInTheDocument()
    expect(screen.queryByText('Forbidden screen')).not.toBeInTheDocument()
  })

  it('sends an anonymous visitor to the login screen from the detail route', () => {
    renderWithProviders(<GuardedAlertsApp />, {
      initialEntries: ['/alerts/abc-123'],
      api: makeApi([]),
    })

    expect(screen.getByText('Login screen')).toBeInTheDocument()
    expect(screen.queryByText('Alert detail screen')).not.toBeInTheDocument()
  })
})
