/**
 * Route path constants.
 *
 * Centralised so that links, redirects and guards never disagree about a
 * URL.
 *
 * Two kinds of value live here:
 *  - `PATHS.*`      — absolute paths used for links and redirects.
 *  - `PATH_PATTERNS` — React Router patterns that carry a `:param`.
 */

export const PATHS = {
  login: '/login',
  mfa: '/mfa',
  register: '/register',
  trustedDeviceLogin: '/trusted-device',

  home: '/',

  alerts: '/alerts',
  policies: '/policies',

  adminUsers: '/admin/users',
  auditLogs: '/admin/audit-logs',

  sessions: '/sessions',
  devices: '/devices',
  profile: '/profile',

  managerDashboard: '/manager/dashboard',
  managerTrends: '/manager/trends',
  managerAlerts: '/manager/alerts',
  managerSocKpi: '/manager/soc-kpi',
  managerMlStats: '/manager/ml-stats',

  forbidden: '/forbidden',
} as const

/** Route patterns for the detail routes. */
export const PATH_PATTERNS = {
  alertDetail: '/alerts/:alertId',
  policyDetail: '/policies/:policyId',
} as const

/** Build a concrete path from a pattern and its params. */
export function buildPath(pattern: string, params: Record<string, string>): string {
  return pattern.replace(/:([A-Za-z0-9_]+)/g, (_match, key: string) =>
    encodeURIComponent(params[key] ?? ''),
  )
}

/** The alert detail path for a given alert. */
export function alertDetailPath(alertId: string): string {
  return buildPath(PATH_PATTERNS.alertDetail, { alertId })
}

/** The policy detail path for a given policy. */
export function policyDetailPath(policyId: string): string {
  return buildPath(PATH_PATTERNS.policyDetail, { policyId })
}

/** Where an unauthenticated visitor is sent. */
export const DEFAULT_AUTH_REDIRECT = PATHS.login

/** Where a visitor without the required role is sent. */
export const DEFAULT_FORBIDDEN_REDIRECT = PATHS.forbidden
