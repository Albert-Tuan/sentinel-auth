/**
 * Route guards.
 *
 * `RequireAuth` protects a route: it sends anonymous visitors to the login
 * screen and remembers where they wanted to go.
 *
 * `RequireRole` protects a section by role: it sends users without the
 * role to the "forbidden" screen.
 *
 * The guard does not carry a role list of its own. It is given the ID of a
 * section and reads the requirement from `policy.ts`, the single source of
 * truth. The guard, the access check and the navigation therefore always
 * agree on who may enter what.
 *
 * Both guards read the roles from the auth context, which sources them
 * from `GET /auth/me`. The role is never inferred from the URL or from
 * anything the client stores.
 */

import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { DEFAULT_AUTH_REDIRECT, DEFAULT_FORBIDDEN_REDIRECT } from '@/app/router/paths'
import { sectionRoles } from '@/app/router/policy'

export interface RequireRoleProps {
  /** The id of the section this guard protects. */
  section: string
  /** Where to send a user who lacks the role. */
  redirectTo?: string
}

/**
 * Require an authenticated session.
 */
export function RequireAuth() {
  const { isAuthenticated } = useAuthContext()
  const location = useLocation()

  if (!isAuthenticated) {
    // Remember the intended destination so the login flow can restore it.
    return (
      <Navigate
        to={DEFAULT_AUTH_REDIRECT}
        replace
        state={{ from: location.pathname + location.search }}
      />
    )
  }

  return <Outlet />
}

/**
 * Require one of the roles of a section.
 */
export function RequireRole({ section, redirectTo }: RequireRoleProps) {
  const { isAuthenticated, hasAnyRole } = useAuthContext()
  const location = useLocation()

  if (!isAuthenticated) {
    return (
      <Navigate
        to={DEFAULT_AUTH_REDIRECT}
        replace
        state={{ from: location.pathname + location.search }}
      />
    )
  }

  if (!hasAnyRole(sectionRoles(section))) {
    return <Navigate to={redirectTo ?? DEFAULT_FORBIDDEN_REDIRECT} replace />
  }

  return <Outlet />
}
