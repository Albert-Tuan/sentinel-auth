/**
 * S-10 / S-11 — IAM API calls.
 *
 * The Core-owned identity surface, gated by `SECURITY_ADMIN` on every
 * route. The backend contracts that shape these signatures:
 *
 *   - `DELETE /users/{id}/roles/USER` answers 422: the USER base role
 *     cannot be removed. The UI therefore never offers it.
 *   - Revoking a role, locking a user and toggling MFA all REVOKE the
 *     target's sessions as a side effect, and all of them are audited.
 *   - The last active `SECURITY_ADMIN` is protected by the backend
 *     (`_guard_last_active_admin`); the UI surfaces the 409/422 message
 *     instead of pre-empting it.
 */

import { apiDelete, apiGet, apiPost, apiPut } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type {
  AdminUserItem,
  AdminUserList,
  AuditLogItem,
  AuditLogList,
  MfaToggleRequest,
  RoleAssignRequest,
  UserRoleEnum,
  UserStatus,
} from '@/types/api'

/** The page size the backend is asked for. */
export const IAM_PAGE_SIZE = 20

export interface UserListQuery {
  role?: UserRoleEnum
  status?: UserStatus
  page?: number
  limit?: number
}

/**
 * `GET /admin/users` — the user directory.
 *
 * The filters are sent only when they carry a value: `role` and `status`
 * are enums the backend validates, and an unset one must not reach it as
 * an empty string.
 */
export async function fetchUsers(
  query: UserListQuery = {},
): Promise<AdminUserList> {
  return apiGet<AdminUserList>(ENDPOINTS.admin.users, {
    params: {
      role: query.role || undefined,
      status: query.status || undefined,
      page: query.page,
      limit: query.limit,
    },
  })
}

/**
 * `POST /admin/users/{user_id}/roles` — grant a role.
 *
 * Granting a role revokes the target's sessions, so the user has to sign
 * in again.
 */
export async function assignUserRole(
  userId: string,
  payload: RoleAssignRequest,
): Promise<AdminUserItem> {
  return apiPost<AdminUserItem>(ENDPOINTS.admin.userRoles(userId), payload)
}

/**
 * `DELETE /admin/users/{user_id}/roles/{role_id}` — revoke a role.
 *
 * The base role `USER` cannot be revoked — the backend answers 422 and
 * the UI does not offer it.
 */
export async function revokeUserRole(
  userId: string,
  roleId: string,
): Promise<AdminUserItem> {
  return apiDelete<AdminUserItem>(ENDPOINTS.admin.userRole(userId, roleId))
}

/** `POST /admin/users/{user_id}/lock` — lock the account. */
export async function lockUser(userId: string): Promise<AdminUserItem> {
  return apiPost<AdminUserItem>(ENDPOINTS.admin.userLock(userId))
}

/** `DELETE /admin/users/{user_id}/lock` — unlock the account. */
export async function unlockUser(userId: string): Promise<AdminUserItem> {
  return apiDelete<AdminUserItem>(ENDPOINTS.admin.userLock(userId))
}

/**
 * `PUT /admin/users/{user_id}/mfa` — require (or stop requiring) MFA.
 *
 * The change revokes the target's sessions.
 */
export async function setUserMfaRequired(
  userId: string,
  payload: MfaToggleRequest,
): Promise<AdminUserItem> {
  return apiPut<AdminUserItem>(ENDPOINTS.admin.userMfa(userId), payload)
}

export interface AuditLogQuery {
  actor?: string
  action?: string
  resource?: string
  from?: string
  to?: string
  page?: number
  limit?: number
}

/**
 * `GET /admin/audit-logs` — the audit trail.
 *
 * `from` and `to` are inclusive on both ends. The parameters are sent
 * only when they carry a value.
 */
export async function fetchAuditLogs(
  query: AuditLogQuery = {},
): Promise<AuditLogList> {
  return apiGet<AuditLogList>(ENDPOINTS.admin.auditLogs, {
    params: {
      actor: query.actor || undefined,
      action: query.action || undefined,
      resource: query.resource || undefined,
      from: query.from || undefined,
      to: query.to || undefined,
      page: query.page,
      limit: query.limit,
    },
  })
}

export type { AuditLogItem, AdminUserItem }
