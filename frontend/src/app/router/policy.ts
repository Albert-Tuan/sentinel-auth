/**
 * The single source of truth for route authorization.
 *
 * Before this module the app carried THREE parallel copies of the same
 * information:
 *
 *   - `routes.tsx`      — a `<RequireRole roles={[...]}/>` per branch
 *   - `access.ts`       — a prefix → role allow-list
 *   - `navigation.ts`   — a role allow-list per menu item
 *
 * Any of them could drift from the others, and the drift was visible to
 * the user: the route table let ANY authenticated user open `/alerts`
 * while the sidebar and the access check hid it from everyone but the
 * analyst and the manager. This module replaces all three with ONE
 * table — `SECTIONS` — and every consumer derives its behaviour from it:
 *
 *   - `RequireRole`           → `sectionRoles(id)`
 *   - `HomeRedirect`          → `landingPathFor(roles)`
 *   - `resolvePostLoginPath`  → `canAccessPath(path, roles)`
 *   - the sidebar / navigation → `navigationFor(roles)`
 *
 * The role assignments mirror the BACKEND contracts one-to-one. The
 * frontend never widens them: a section may only be entered by a user
 * whose roles (from `GET /auth/me`) intersect the section's roles.
 *
 *   /alerts    → SOC_ANALYST | SECURITY_MANAGER   (app/alerts.py)
 *   /policies  → SECURITY_ADMIN | SECURITY_MANAGER (app/detection.py)
 *   /admin/*   → SECURITY_ADMIN                   (app/iam.py)
 *   /manager/* → SECURITY_MANAGER                 (app/manager.py)
 *   /sessions, /devices, /profile → every authenticated user
 */

import { PATHS, PATH_PATTERNS } from '@/app/router/paths'
import { UserRole } from '@/types/api'

/** One entry of the sidebar / mobile navigation. */
export interface NavigationEntry {
  label: string
  path: string
}

/**
 * One route of a section.
 *
 * `page` is the key the route table hands to the page factory. The
 * concrete React components for the self-service screens are bound in
 * `routes.tsx`; everything else is still a placeholder.
 */
export interface SectionRoute {
  path: string
  page: string
}

/**
 * A group of routes that share the same access requirement.
 *
 * A section is the unit of authorization: the requirement is declared
 * ONCE here and is consumed by the route guard, the access check and the
 * navigation builder.
 */
export interface SectionPolicy {
  /** Stable identifier used by the route table and the tests. */
  id: string
  /**
   * The path prefixes this section owns. A path belongs to the section
   * whose prefix matches it exactly or as a path segment (`/alerts`
   * matches `/alerts` and `/alerts/abc`, but not `/alertsomething`).
   */
  prefixes: string[]
  /** The concrete routes of the section. */
  routes: SectionRoute[]
  /**
   * How the section is gated.
   *
   *   - `roles`      — a user needs at least one of `roles`.
   *   - `any-session`— every authenticated user may enter; `roles` then
   *                    only decides whether the entries appear in the
   *                    navigation.
   */
  access: 'roles' | 'any-session'
  /** The roles that grant entry (or that see the navigation entries). */
  roles: UserRole[]
  /** The navigation entries the section contributes. */
  nav: NavigationEntry[]
  /** The landing path of the section. */
  landing: string
  /**
   * Landing priority. The highest-priority section the user may enter
   * provides the landing path. Higher wins.
   */
  landingPriority: number
}

/** Every role the backend can assign. */
export const ALL_ROLES: UserRole[] = [
  UserRole.USER,
  UserRole.SOC_ANALYST,
  UserRole.SECURITY_ADMIN,
  UserRole.SECURITY_MANAGER,
]

/**
 * The role table.
 *
 * ORDER MATTERS for two things:
 *   - the navigation entries are rendered in this order;
 *   - `landingPriority` decides which section a user lands on.
 */
export const SECTIONS: SectionPolicy[] = [
  {
    id: 'alerts',
    prefixes: ['/alerts'],
    routes: [
      { path: PATHS.alerts, page: 'alerts' },
      { path: PATH_PATTERNS.alertDetail, page: 'alert-detail' },
    ],
    access: 'roles',
    roles: [UserRole.SOC_ANALYST, UserRole.SECURITY_MANAGER],
    nav: [{ label: 'Cảnh báo', path: PATHS.alerts }],
    landing: PATHS.alerts,
    landingPriority: 20,
  },
  {
    id: 'policies',
    prefixes: ['/policies'],
    routes: [
      { path: PATHS.policies, page: 'policies' },
      { path: PATH_PATTERNS.policyDetail, page: 'policy-detail' },
    ],
    access: 'roles',
    roles: [UserRole.SECURITY_ADMIN, UserRole.SECURITY_MANAGER],
    nav: [{ label: 'Chính sách', path: PATHS.policies }],
    landing: PATHS.policies,
    landingPriority: 25,
  },
  {
    id: 'admin',
    prefixes: ['/admin'],
    routes: [
      { path: PATHS.adminUsers, page: 'admin-users' },
      { path: PATHS.auditLogs, page: 'audit-logs' },
    ],
    access: 'roles',
    roles: [UserRole.SECURITY_ADMIN],
    nav: [
      { label: 'Người dùng', path: PATHS.adminUsers },
      { label: 'Nhật ký kiểm toán', path: PATHS.auditLogs },
    ],
    landing: PATHS.adminUsers,
    landingPriority: 30,
  },
  {
    id: 'self-service',
    prefixes: [PATHS.sessions, PATHS.devices, PATHS.profile],
    routes: [
      { path: PATHS.sessions, page: 'sessions' },
      { path: PATHS.devices, page: 'devices' },
      { path: PATHS.profile, page: 'profile' },
    ],
    access: 'any-session',
    roles: [...ALL_ROLES],
    nav: [
      { label: 'Phiên đăng nhập', path: PATHS.sessions },
      { label: 'Thiết bị tin cậy', path: PATHS.devices },
      { label: 'Hồ sơ', path: PATHS.profile },
    ],
    landing: PATHS.sessions,
    landingPriority: 10,
  },
  {
    id: 'manager',
    prefixes: ['/manager'],
    routes: [
      { path: PATHS.managerDashboard, page: 'manager-dashboard' },
      { path: PATHS.managerTrends, page: 'manager-trends' },
      { path: PATHS.managerAlerts, page: 'manager-alerts' },
      { path: PATHS.managerSocKpi, page: 'manager-soc-kpi' },
      { path: PATHS.managerMlStats, page: 'manager-ml-stats' },
    ],
    access: 'roles',
    roles: [UserRole.SECURITY_MANAGER],
    nav: [
      { label: 'Tổng quan', path: PATHS.managerDashboard },
      { label: 'Xu hướng', path: PATHS.managerTrends },
      { label: 'Phân tích cảnh báo', path: PATHS.managerAlerts },
      { label: 'KPI SOC', path: PATHS.managerSocKpi },
      { label: 'Thống kê ML', path: PATHS.managerMlStats },
    ],
    landing: PATHS.managerDashboard,
    landingPriority: 40,
  },
]

/**
 * The public routes. They are reachable without a session, so they are
 * never part of a section and never a remembered destination: sending a
 * signed-in user back to `/login` would bounce them straight out again.
 */
export const PUBLIC_PATHS: string[] = [
  PATHS.login,
  PATHS.mfa,
  PATHS.trustedDeviceLogin,
  PATHS.forbidden,
]

/** The section with the given id. Throws when the id is unknown. */
export function section(id: string): SectionPolicy {
  const found = SECTIONS.find((candidate) => candidate.id === id)
  if (!found) {
    throw new Error(`unknown route section: ${id}`)
  }
  return found
}

/** The roles allowed to enter the section with the given id. */
export function sectionRoles(id: string): UserRole[] {
  return section(id).roles
}

/** Strip the query string and the fragment from a path. */
function pathnameOf(path: string): string {
  return path.split('?')[0].split('#')[0]
}

/**
 * The section that owns a path, or `null` when the path belongs to no
 * section (the public tree, or an unknown URL).
 *
 * The longest matching prefix wins, so `/manager/alerts` belongs to the
 * manager section even though `/alerts` is also a prefix somewhere.
 */
export function sectionForPath(
  path: string | null | undefined,
): SectionPolicy | null {
  if (!path) return null
  const pathname = pathnameOf(path)

  let best: SectionPolicy | null = null
  let bestLength = -1

  for (const candidate of SECTIONS) {
    for (const prefix of candidate.prefixes) {
      const matches =
        pathname === prefix || pathname.startsWith(`${prefix}/`)
      if (matches && prefix.length > bestLength) {
        best = candidate
        bestLength = prefix.length
      }
    }
  }

  return best
}

/**
 * May a user holding these roles be sent to this path?
 *
 * A path that belongs to no section is open to every authenticated user.
 * The check is a pure function of the section table, so it can never
 * disagree with the route guard.
 */
export function canAccessPath(
  path: string | null | undefined,
  roles: UserRole[],
): boolean {
  if (!path) return false

  const owner = sectionForPath(path)
  if (!owner) return true

  if (owner.access === 'any-session') return true

  return owner.roles.some((role) => roles.includes(role))
}

/** Convert a React Router pattern into a regular expression source. */
function patternToRegExpSource(pattern: string): string {
  return pattern
    .split('/')
    .map((segment) =>
      segment.startsWith(':')
        ? '[^/]+'
        : segment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
    )
    .join('/')
}

/**
 * Is the path one of the app's own routes?
 *
 * Used to reject a remembered destination that points at a URL the app
 * does not have: the user would land on the 404 page instead of a screen
 * they can use.
 */
export function isKnownPath(path: string | null | undefined): boolean {
  if (!path) return false
  const pathname = pathnameOf(path)

  if (pathname === PATHS.home) return true
  if (PUBLIC_PATHS.includes(pathname)) return true

  for (const candidate of SECTIONS) {
    for (const route of candidate.routes) {
      const regexp = new RegExp(`^${patternToRegExpSource(route.path)}$`)
      if (regexp.test(pathname)) return true
    }
  }

  return false
}

/**
 * The landing path for a set of roles.
 *
 * The highest-priority section the user may enter wins. When the user
 * holds no known role the home route is returned: it is the only route
 * that needs no role at all.
 */
export function landingPathFor(roles: UserRole[]): string {
  let best: SectionPolicy | null = null

  for (const candidate of SECTIONS) {
    const reachable =
      candidate.access === 'any-session'
        ? roles.length > 0
        : candidate.roles.some((role) => roles.includes(role))
    if (!reachable) continue
    if (!best || candidate.landingPriority > best.landingPriority) {
      best = candidate
    }
  }

  return best ? best.landing : PATHS.home
}

/**
 * The navigation entries a user may see.
 *
 * The entries come from the sections the user's roles allow, so a link is
 * never shown for a screen the user would get a 403 for.
 */
export function navigationFor(roles: UserRole[]): NavigationEntry[] {
  if (roles.length === 0) return []

  const items: NavigationEntry[] = []
  for (const candidate of SECTIONS) {
    if (candidate.access === 'roles') {
      if (!candidate.roles.some((role) => roles.includes(role))) continue
    }
    items.push(...candidate.nav)
  }
  return items
}

/**
 * Where to send the user after a successful login.
 *
 * The remembered destination wins only when it is a real route AND the
 * signed-in roles allow it. Otherwise the role-aware landing page does.
 * The result is always reachable, so the login flow can never end on the
 * forbidden screen or in a redirect loop.
 */
export function resolvePostLoginPath(
  remembered: string | null | undefined,
  roles: UserRole[],
): string {
  const landing = landingPathFor(roles)

  if (!remembered) return landing

  const pathname = pathnameOf(remembered)

  // The public tree is never restored: `/login` would bounce the
  // signed-in user straight back out.
  if (PUBLIC_PATHS.includes(pathname)) return landing

  if (!isKnownPath(remembered)) return landing
  if (!canAccessPath(remembered, roles)) return landing

  return remembered
}
