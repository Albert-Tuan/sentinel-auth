/**
 * The home route.
 *
 * `/` has no content of its own: it sends the user to the screen that
 * matches their role. The redirect is computed from the auth context, so
 * the roles always come from `GET /auth/me`.
 *
 * The landing path itself comes from `@/app/router/policy` — the single
 * source of truth shared with the route guard and the access check — so
 * the home route can never send a user to a screen their roles forbid.
 */

import { Navigate, useLocation } from 'react-router-dom'
import { useAuthContext } from '@/app/providers/useAuthContext'

export function HomeRedirect() {
  const { landingPath, isAuthenticated } = useAuthContext()
  const location = useLocation()

  // An anonymous visitor is bounced to the login screen by `RequireAuth`.
  if (!isAuthenticated) return <Navigate to="/login" replace />

  // Guard against a self-redirect: navigating to the path we are already
  // on would spin the router forever. This can only happen for a session
  // whose roles grant no section at all.
  if (landingPath === location.pathname) return null

  return <Navigate to={landingPath} replace />
}
