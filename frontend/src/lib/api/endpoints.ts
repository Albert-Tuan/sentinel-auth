/**
 * Endpoint constants for the Sentinel Auth API.
 *
 * These are the ONLY place where URL paths are written. Keeping them here
 * means the interceptor's "do not refresh" list and the API modules can never
 * drift apart.
 *
 * All paths are relative to the API base URL (see `config.ts`).
 */

/** Browser-callable API roots. */
export const API_ROOTS = {
  auth: '/auth',
  admin: '/admin',
  alerts: '/alerts',
  policies: '/policies',
  devices: '/devices',
  loginAttempts: '/login-attempts',
  manager: '/manager',
} as const

export const ENDPOINTS = {
  auth: {
    login: '/auth/login',
    mfaVerify: '/auth/mfa/verify',
    refresh: '/auth/refresh',
    logout: '/auth/logout',
    logoutAll: '/auth/logout-all',
    me: '/auth/me',
    register: '/auth/register',
    sessions: '/auth/sessions',
    session: (sessionId: string) => `/auth/sessions/${sessionId}`,
  },
  admin: {
    users: '/admin/users',
    userRoles: (userId: string) => `/admin/users/${userId}/roles`,
    userRole: (userId: string, roleId: string) =>
      `/admin/users/${userId}/roles/${roleId}`,
    userLock: (userId: string) => `/admin/users/${userId}/lock`,
    userMfa: (userId: string) => `/admin/users/${userId}/mfa`,
    auditLogs: '/admin/audit-logs',
  },
  alerts: {
    list: '/alerts',
    detail: (alertId: string) => `/alerts/${alertId}`,
    evidence: (alertId: string) => `/alerts/${alertId}/evidence`,
    timeline: (alertId: string) => `/alerts/${alertId}/timeline`,
    acknowledge: (alertId: string) => `/alerts/${alertId}/acknowledge`,
    resolve: (alertId: string) => `/alerts/${alertId}/resolve`,
    assign: (alertId: string) => `/alerts/${alertId}/assign`,
    actions: (alertId: string) => `/alerts/${alertId}/actions`,
  },
  policies: {
    list: '/policies',
    detail: (policyId: string) => `/policies/${policyId}`,
    activate: (policyId: string) => `/policies/${policyId}/activate`,
  },
  devices: {
    list: '/devices',
    check: '/devices/check',
    register: '/devices',
    remove: (deviceId: string) => `/devices/${deviceId}`,
    removeAll: '/devices/all',
    pending: '/devices/pending',
    pendingComplete: (requestId: string) =>
      `/devices/pending/${requestId}/complete`,
    pendingApprove: (requestId: string) =>
      `/devices/pending/${requestId}/approve`,
  },
  loginAttempts: {
    list: '/login-attempts',
  },
  manager: {
    dashboard: '/manager/dashboard',
    trends: '/manager/trends',
    alerts: '/manager/alerts',
    socKpi: '/manager/soc-kpi',
    mlStats: '/manager/ml-stats',
  },
} as const
