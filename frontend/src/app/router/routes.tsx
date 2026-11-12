/**
 * The route table.
 *
 * Routes are grouped into two trees:
 *  - the public tree (login, MFA, trusted-device) — reachable without a
 *    session
 *  - the protected tree — behind `<RequireAuth>`, with the role-restricted
 *    sections behind `<RequireRole>`
 *
 * The route table holds no business logic, and — more importantly — no
 * role list of its own. Every section is taken from `policy.ts`, the
 * single source of truth: the guard, the access check and the navigation
 * all read the same table, so they cannot drift apart.
 *
 * Each role-restricted section renders its own `<AppShell/>`, because
 * React Router only nests an outlet one level deep per branch.
 */

import type { RouteObject } from 'react-router-dom'
import { RequireAuth, RequireRole } from '@/app/router/guards'
import { PATHS } from '@/app/router/paths'
import { SECTIONS, type SectionPolicy } from '@/app/router/policy'
import { AppShell } from '@/app/layout/AppShell'
import { LoginPage } from '@/features/auth/pages/LoginPage'
import { MfaVerifyPage } from '@/features/auth/pages/MfaVerifyPage'
import { NotFoundPage } from '@/features/auth/pages/NotFoundPage'
import { ForbiddenPage } from '@/features/auth/pages/ForbiddenPage'
import { PlaceholderPage } from '@/app/layout/PlaceholderPage'
import { HomeRedirect } from '@/app/router/HomeRedirect'
import { SessionsPage } from '@/features/sessions/pages/SessionsPage'
import { TrustedDevicesPage } from '@/features/devices/pages/TrustedDevicesPage'
import { TrustedDeviceLoginPage } from '@/features/devices/pages/TrustedDeviceLoginPage'
import { ProfilePage } from '@/features/profile/pages/ProfilePage'

export type PageFactory = (key: string) => React.ReactNode

const defaultFactory: PageFactory = (key) => <PlaceholderPage title={key} />

/**
 * The screens that are already implemented.
 *
 * Everything else falls back to the placeholder factory. The map is keyed
 * by the `page` key declared in `policy.ts`, so a new section never needs
 * a change here to be routable.
 */
const IMPLEMENTED_PAGES: Record<string, React.ReactNode> = {
  sessions: <SessionsPage />,
  devices: <TrustedDevicesPage />,
  profile: <ProfilePage />,
}

/**
 * Build the route table.
 *
 * @param createPage a factory for the feature screens. It is injected so the
 *        test suite can render the router without pulling in every feature.
 */
export function buildRoutes(createPage: PageFactory = defaultFactory): RouteObject[] {
  return [
    // --- public -----------------------------------------------------------
    { path: PATHS.login, element: <LoginPage /> },
    { path: PATHS.mfa, element: <MfaVerifyPage /> },
    { path: PATHS.trustedDeviceLogin, element: <TrustedDeviceLoginPage /> },
    { path: PATHS.forbidden, element: <ForbiddenPage /> },

    // --- protected -------------------------------------------------------
    {
      element: <RequireAuth />,
      children: [
        { path: PATHS.home, element: <HomeRedirect /> },
        ...SECTIONS.map((section) => buildSection(section, createPage)),
      ],
    },

    { path: '*', element: <NotFoundPage /> },
  ]
}

/**
 * Build the routes of one section.
 *
 * The section's own policy decides whether a `<RequireRole>` guard is
 * needed: a section whose access is `any-session` needs none.
 */
function buildSection(
  section: SectionPolicy,
  createPage: PageFactory,
): RouteObject {
  const children: RouteObject[] = section.routes.map((route) => ({
    path: route.path,
    element: IMPLEMENTED_PAGES[route.page] ?? createPage(route.page),
  }))

  const shell: RouteObject = {
    element: <AppShell />,
    children,
  }

  if (section.access === 'any-session') {
    return shell
  }

  return {
    element: <RequireRole section={section.id} />,
    children: [shell],
  }
}
