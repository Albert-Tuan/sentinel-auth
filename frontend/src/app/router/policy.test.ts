/**
 * The route authorization policy.
 *
 * This is the single source of truth, so the tests here are the ones
 * that prove the app's role behaviour:
 *
 *   - each of the four backend roles sees exactly the sections it may;
 *   - the navigation, the route guard and the post-login redirect agree;
 *   - a deep link to a forbidden screen ends on the landing page, never
 *     on `/forbidden` and never in a redirect loop.
 */

import { describe, expect, it } from 'vitest'

import {
  ALL_ROLES,
  PUBLIC_PATHS,
  SECTIONS,
  canAccessPath,
  isKnownPath,
  landingPathFor,
  navigationFor,
  resolvePostLoginPath,
  section,
  sectionForPath,
  sectionRoles,
} from '@/app/router/policy'
import { PATHS } from '@/app/router/paths'
import type { UserRole } from '@/types/api'

const USER: UserRole[] = ['USER']
const ANALYST: UserRole[] = ['SOC_ANALYST', 'USER']
const ADMIN: UserRole[] = ['SECURITY_ADMIN', 'USER']
const MANAGER: UserRole[] = ['SECURITY_MANAGER', 'USER']

describe('the policy table', () => {
  it('declares every backend role', () => {
    expect(ALL_ROLES).toEqual([
      'USER',
      'SOC_ANALYST',
      'SECURITY_ADMIN',
      'SECURITY_MANAGER',
    ])
  })

  it('mirrors the backend role assignments', () => {
    // app/alerts.py
    expect(sectionRoles('alerts')).toEqual([
      'SOC_ANALYST',
      'SECURITY_MANAGER',
    ])
    // app/detection.py
    expect(sectionRoles('policies')).toEqual([
      'SECURITY_ADMIN',
      'SECURITY_MANAGER',
    ])
    // app/iam.py
    expect(sectionRoles('admin')).toEqual(['SECURITY_ADMIN'])
    // app/manager.py
    expect(sectionRoles('manager')).toEqual(['SECURITY_MANAGER'])
  })

  it('gives every section a unique id, a landing path and routes', () => {
    const ids = SECTIONS.map((candidate) => candidate.id)
    expect(new Set(ids).size).toBe(ids.length)

    for (const candidate of SECTIONS) {
      expect(candidate.routes.length).toBeGreaterThan(0)
      expect(candidate.landing).toBeTruthy()
      // Every route of a section must be covered by one of its prefixes.
      for (const route of candidate.routes) {
        expect(sectionForPath(route.path)?.id).toBe(candidate.id)
      }
    }
  })

  it('exposes the public routes separately from the sections', () => {
    for (const publicPath of PUBLIC_PATHS) {
      expect(sectionForPath(publicPath)).toBeNull()
    }
  })

  it('throws for an unknown section id', () => {
    expect(() => section('does-not-exist')).toThrow(/unknown route section/)
  })
})

describe('canAccessPath — USER', () => {
  it('reaches every self-service screen', () => {
    expect(canAccessPath(PATHS.sessions, USER)).toBe(true)
    expect(canAccessPath(PATHS.devices, USER)).toBe(true)
    expect(canAccessPath(PATHS.profile, USER)).toBe(true)
  })

  it('cannot reach the analyst, admin or manager sections', () => {
    expect(canAccessPath(PATHS.alerts, USER)).toBe(false)
    expect(canAccessPath(PATHS.adminUsers, USER)).toBe(false)
    expect(canAccessPath(PATHS.auditLogs, USER)).toBe(false)
    expect(canAccessPath(PATHS.policies, USER)).toBe(false)
    expect(canAccessPath(PATHS.managerDashboard, USER)).toBe(false)
  })
})

describe('canAccessPath — SOC_ANALYST', () => {
  it('reaches the alert queue and the self-service screens', () => {
    expect(canAccessPath(PATHS.alerts, ANALYST)).toBe(true)
    expect(canAccessPath('/alerts/abc-123', ANALYST)).toBe(true)
    expect(canAccessPath(PATHS.sessions, ANALYST)).toBe(true)
    expect(canAccessPath(PATHS.devices, ANALYST)).toBe(true)
    expect(canAccessPath(PATHS.profile, ANALYST)).toBe(true)
  })

  it('cannot reach the admin, policy or manager sections', () => {
    expect(canAccessPath(PATHS.adminUsers, ANALYST)).toBe(false)
    expect(canAccessPath(PATHS.auditLogs, ANALYST)).toBe(false)
    expect(canAccessPath(PATHS.policies, ANALYST)).toBe(false)
    expect(canAccessPath(PATHS.managerDashboard, ANALYST)).toBe(false)
  })
})

describe('canAccessPath — SECURITY_ADMIN', () => {
  it('reaches the admin area, the policies and the self-service screens', () => {
    expect(canAccessPath(PATHS.adminUsers, ADMIN)).toBe(true)
    expect(canAccessPath(PATHS.auditLogs, ADMIN)).toBe(true)
    expect(canAccessPath(PATHS.policies, ADMIN)).toBe(true)
    expect(canAccessPath('/policies/policy-1', ADMIN)).toBe(true)
    expect(canAccessPath(PATHS.sessions, ADMIN)).toBe(true)
    expect(canAccessPath(PATHS.devices, ADMIN)).toBe(true)
    expect(canAccessPath(PATHS.profile, ADMIN)).toBe(true)
  })

  it('cannot reach the alert queue or the manager area', () => {
    expect(canAccessPath(PATHS.alerts, ADMIN)).toBe(false)
    expect(canAccessPath('/alerts/abc-123', ADMIN)).toBe(false)
    expect(canAccessPath(PATHS.managerDashboard, ADMIN)).toBe(false)
  })
})

describe('canAccessPath — SECURITY_MANAGER', () => {
  it('reaches the manager area, the policies, the alerts and self-service', () => {
    expect(canAccessPath(PATHS.managerDashboard, MANAGER)).toBe(true)
    expect(canAccessPath(PATHS.managerMlStats, MANAGER)).toBe(true)
    expect(canAccessPath(PATHS.policies, MANAGER)).toBe(true)
    expect(canAccessPath(PATHS.alerts, MANAGER)).toBe(true)
    expect(canAccessPath(PATHS.sessions, MANAGER)).toBe(true)
    expect(canAccessPath(PATHS.devices, MANAGER)).toBe(true)
    expect(canAccessPath(PATHS.profile, MANAGER)).toBe(true)
  })

  it('cannot reach the admin area', () => {
    expect(canAccessPath(PATHS.adminUsers, MANAGER)).toBe(false)
    expect(canAccessPath(PATHS.auditLogs, MANAGER)).toBe(false)
  })
})

describe('canAccessPath — edge cases', () => {
  it('does not let a prefix match leak into a sibling path', () => {
    expect(canAccessPath('/alertsomething', ADMIN)).toBe(true)
    expect(canAccessPath('/admin-tools', ANALYST)).toBe(true)
  })

  it('ignores the query string and the hash', () => {
    expect(canAccessPath('/admin/users?page=2', ANALYST)).toBe(false)
    expect(canAccessPath('/admin/users#top', ANALYST)).toBe(false)
    expect(canAccessPath('/sessions?next=1', ANALYST)).toBe(true)
  })

  it('rejects an empty path', () => {
    expect(canAccessPath('', ANALYST)).toBe(false)
    expect(canAccessPath(null, ANALYST)).toBe(false)
    expect(canAccessPath(undefined, ANALYST)).toBe(false)
  })

  it('resolves the longest matching prefix', () => {
    // `/manager/alerts` belongs to the manager section, not to the alerts
    // section, even though it ends with "/alerts".
    expect(sectionForPath('/manager/alerts')?.id).toBe('manager')
    expect(sectionForPath('/alerts')?.id).toBe('alerts')
  })
})

describe('landingPathFor', () => {
  it('routes each role to its own landing page', () => {
    expect(landingPathFor(['SECURITY_MANAGER'])).toBe('/manager/dashboard')
    expect(landingPathFor(['SECURITY_ADMIN'])).toBe('/admin/users')
    expect(landingPathFor(['SOC_ANALYST'])).toBe('/alerts')
    expect(landingPathFor(['USER'])).toBe('/sessions')
  })

  it('prefers the most privileged role when several are held', () => {
    expect(landingPathFor(['SOC_ANALYST', 'SECURITY_MANAGER'])).toBe(
      '/manager/dashboard',
    )
    expect(landingPathFor(['SOC_ANALYST', 'SECURITY_ADMIN'])).toBe(
      '/admin/users',
    )
  })

  it('falls back to the home route for a session without a known role', () => {
    expect(landingPathFor([])).toBe('/')
  })

  it('always lands on a path the roles may reach', () => {
    for (const roles of [USER, ANALYST, ADMIN, MANAGER]) {
      const landing = landingPathFor(roles)
      expect(canAccessPath(landing, roles)).toBe(true)
      expect(isKnownPath(landing)).toBe(true)
    }
  })
})

describe('navigationFor', () => {
  it('shows the analyst the alert queue and the self-service entries', () => {
    const labels = navigationFor(['SOC_ANALYST']).map((item) => item.label)
    expect(labels).toContain('Cảnh báo')
    expect(labels).toContain('Phiên đăng nhập')
    expect(labels).toContain('Thiết bị tin cậy')
    expect(labels).toContain('Hồ sơ')
    expect(labels).not.toContain('Người dùng')
    expect(labels).not.toContain('Chính sách')
    expect(labels).not.toContain('Tổng quan')
  })

  it('shows the admin the admin area and the policies', () => {
    const labels = navigationFor(['SECURITY_ADMIN']).map((item) => item.label)
    expect(labels).toContain('Người dùng')
    expect(labels).toContain('Nhật ký kiểm toán')
    expect(labels).toContain('Chính sách')
    expect(labels).not.toContain('Cảnh báo')
    expect(labels).not.toContain('Tổng quan')
  })

  it('shows the manager the manager area, the alerts and the policies', () => {
    const labels = navigationFor(['SECURITY_MANAGER']).map((item) => item.label)
    expect(labels).toContain('Tổng quan')
    expect(labels).toContain('Xu hướng')
    expect(labels).toContain('Phân tích cảnh báo')
    expect(labels).toContain('KPI SOC')
    expect(labels).toContain('Thống kê ML')
    expect(labels).toContain('Cảnh báo')
    expect(labels).toContain('Chính sách')
    expect(labels).not.toContain('Người dùng')
    expect(labels).not.toContain('Nhật ký kiểm toán')
  })

  it('shows a plain user only the self-service entries', () => {
    const labels = navigationFor(['USER']).map((item) => item.label)
    expect(labels).toEqual([
      'Phiên đăng nhập',
      'Thiết bị tin cậy',
      'Hồ sơ',
    ])
  })

  it('shows no navigation for a user with no roles', () => {
    expect(navigationFor([])).toEqual([])
  })

  it('never offers a link the user cannot follow', () => {
    for (const roles of [USER, ANALYST, ADMIN, MANAGER]) {
      for (const item of navigationFor(roles)) {
        expect(canAccessPath(item.path, roles)).toBe(true)
      }
    }
  })
})

describe('isKnownPath', () => {
  it('accepts the app routes, including the parameterised ones', () => {
    expect(isKnownPath('/')).toBe(true)
    expect(isKnownPath('/alerts')).toBe(true)
    expect(isKnownPath('/alerts/abc-123')).toBe(true)
    expect(isKnownPath('/policies/policy-1')).toBe(true)
    expect(isKnownPath('/admin/users')).toBe(true)
    expect(isKnownPath('/sessions')).toBe(true)
  })

  it('rejects a path the app does not have', () => {
    expect(isKnownPath('/does-not-exist')).toBe(false)
    expect(isKnownPath('/alerts/abc/extra')).toBe(false)
    expect(isKnownPath(null)).toBe(false)
    expect(isKnownPath('')).toBe(false)
  })
})

describe('resolvePostLoginPath', () => {
  it('restores a destination the roles allow', () => {
    expect(resolvePostLoginPath('/sessions', ANALYST)).toBe('/sessions')
    expect(resolvePostLoginPath('/admin/users', ADMIN)).toBe('/admin/users')
    expect(resolvePostLoginPath('/alerts/abc-123', ANALYST)).toBe(
      '/alerts/abc-123',
    )
  })

  it('falls back to the landing page when the destination is out of reach', () => {
    expect(resolvePostLoginPath('/admin/users', ANALYST)).toBe('/alerts')
    expect(resolvePostLoginPath('/alerts', ADMIN)).toBe('/admin/users')
    expect(resolvePostLoginPath('/manager/dashboard', ADMIN)).toBe(
      '/admin/users',
    )
  })

  it('falls back to the landing page when there is no destination', () => {
    expect(resolvePostLoginPath(undefined, ANALYST)).toBe('/alerts')
    expect(resolvePostLoginPath(null, ANALYST)).toBe('/alerts')
    expect(resolvePostLoginPath('', ANALYST)).toBe('/alerts')
  })

  it('never restores a public route — it would bounce the user out', () => {
    expect(resolvePostLoginPath('/login', ANALYST)).toBe('/alerts')
    expect(resolvePostLoginPath('/mfa', ANALYST)).toBe('/alerts')
    expect(resolvePostLoginPath('/trusted-device', ANALYST)).toBe('/alerts')
  })

  it('never restores a path the app does not have', () => {
    expect(resolvePostLoginPath('/does-not-exist', ANALYST)).toBe('/alerts')
  })

  it('always resolves to a path the roles may reach', () => {
    const destinations = [
      '/sessions',
      '/devices',
      '/profile',
      '/alerts',
      '/alerts/abc-123',
      '/policies',
      '/admin/users',
      '/admin/audit-logs',
      '/manager/dashboard',
      '/manager/ml-stats',
      '/login',
      '/does-not-exist',
      '/',
      undefined,
    ]

    for (const roles of [USER, ANALYST, ADMIN, MANAGER]) {
      for (const destination of destinations) {
        const resolved = resolvePostLoginPath(destination, roles)
        expect(resolved).not.toBe(PATHS.forbidden)
        expect(canAccessPath(resolved, roles)).toBe(true)
        expect(isKnownPath(resolved)).toBe(true)
      }
    }
  })
})
