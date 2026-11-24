/**
 * S-10 — User Management (`/admin/users`).
 *
 * The `SECURITY_ADMIN` directory. It reads `GET /admin/users` and drives
 * the four IAM mutations the backend exposes:
 *
 *   POST   /admin/users/{id}/roles            → grant a role
 *   DELETE /admin/users/{id}/roles/{role_id}  → revoke a role
 *   POST   /admin/users/{id}/lock             → lock the account
 *   DELETE /admin/users/{id}/lock             → unlock the account
 *   PUT    /admin/users/{id}/mfa              → require (or drop) MFA
 *
 * Two backend rules shape the UI:
 *
 *   1. The base role `USER` cannot be revoked — the backend answers 422.
 *      The UI therefore never offers it as revocable.
 *   2. Every one of these mutations REVOKES the target's sessions and is
 *      audited. The confirm dialog says so, because the admin is about to
 *      sign the user out.
 *
 * The last active `SECURITY_ADMIN` is protected by the backend; the UI
 * surfaces that refusal instead of guessing which admin it is.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Pagination } from '@/shared/components/Pagination'
import { Spinner } from '@/shared/components/Spinner'

import {
  IAM_PAGE_SIZE,
  assignUserRole,
  fetchUsers,
  lockUser,
  revokeUserRole,
  setUserMfaRequired,
  unlockUser,
} from '@/lib/api/iam.api'
import { formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import { UserRole, UserStatus, type AdminUserItem } from '@/types/api'

/** The roles the backend accepts in `POST /users/{id}/roles`. */
const GRANTABLE_ROLES = [
  UserRole.SECURITY_ADMIN,
  UserRole.SOC_ANALYST,
  UserRole.SECURITY_MANAGER,
] as const

/** The base role. The backend refuses to revoke it (422). */
const BASE_ROLE = UserRole.USER

const STATUS_LABEL: Record<string, string> = {
  active: 'Hoạt động',
  suspended: 'Tạm khoá',
  locked: 'Bị khoá',
}

const STATUS_TONE: Record<string, 'success' | 'warning' | 'danger'> = {
  active: 'success',
  suspended: 'warning',
  locked: 'danger',
}

export function UserManagementPage() {
  const queryClient = useQueryClient()

  const [page, setPage] = useState(1)
  const [roleFilter, setRoleFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const [grantTarget, setGrantTarget] = useState<AdminUserItem | null>(null)
  const [grantRole, setGrantRole] = useState<string>(UserRole.SOC_ANALYST)
  const [revokeTarget, setRevokeTarget] = useState<{
    user: AdminUserItem
    role: string
  } | null>(null)
  const [lockTarget, setLockTarget] = useState<AdminUserItem | null>(null)
  const [mfaTarget, setMfaTarget] = useState<AdminUserItem | null>(null)

  const usersQuery = useQuery({
    queryKey: ['admin', 'users', roleFilter, statusFilter, page],
    queryFn: () =>
      fetchUsers({
        role: (roleFilter || undefined) as never,
        status: (statusFilter || undefined) as never,
        page,
        limit: IAM_PAGE_SIZE,
      }),
  })

  /** Every IAM mutation refreshes the directory. */
  function invalidateUsers() {
    return queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
  }

  const grantMutation = useMutation({
    mutationFn: () =>
      assignUserRole(grantTarget?.id ?? '', {
        role: grantRole as never,
      }),
    onSuccess: async () => {
      setGrantTarget(null)
      await invalidateUsers()
    },
  })

  const revokeMutation = useMutation({
    mutationFn: () =>
      revokeUserRole(revokeTarget?.user.id ?? '', revokeTarget?.role ?? ''),
    onSuccess: async () => {
      setRevokeTarget(null)
      await invalidateUsers()
    },
  })

  const lockMutation = useMutation({
    mutationFn: () => lockUser(lockTarget?.id ?? ''),
    onSuccess: async () => {
      setLockTarget(null)
      await invalidateUsers()
    },
  })

  const unlockMutation = useMutation({
    mutationFn: () => unlockUser(lockTarget?.id ?? ''),
    onSuccess: async () => {
      setLockTarget(null)
      await invalidateUsers()
    },
  })

  const mfaMutation = useMutation({
    mutationFn: () =>
      setUserMfaRequired(mfaTarget?.id ?? '', {
        mfa_required: !mfaTarget?.admin_mfa_required,
      }),
    onSuccess: async () => {
      setMfaTarget(null)
      await invalidateUsers()
    },
  })

  const anyPending =
    grantMutation.isPending ||
    revokeMutation.isPending ||
    lockMutation.isPending ||
    unlockMutation.isPending ||
    mfaMutation.isPending

  const columns: TableColumn<AdminUserItem>[] = [
    {
      key: 'username',
      header: 'Tài khoản',
      render: (user) => (
        <div className="flex flex-col">
          <span className="telemetry text-text">{user.username}</span>
          {user.full_name && (
            <span className="text-xs text-degraded">{user.full_name}</span>
          )}
        </div>
      ),
    },
    {
      key: 'email',
      header: 'Email',
      render: (user) =>
        user.email ? (
          <span className="telemetry">{user.email}</span>
        ) : (
          <span className="text-degraded">Không có dữ liệu</span>
        ),
    },
    {
      key: 'status',
      header: 'Trạng thái',
      render: (user) => (
        <Badge tone={STATUS_TONE[user.status] ?? 'neutral'}>
          {STATUS_LABEL[user.status] ?? user.status}
        </Badge>
      ),
    },
    {
      key: 'roles',
      header: 'Vai trò',
      render: (user) => (
        <div className="flex flex-wrap gap-1">
          {user.roles.length === 0 ? (
            <span className="text-degraded">—</span>
          ) : (
            user.roles.map((role) => (
              <Badge key={role} tone={role === BASE_ROLE ? 'neutral' : 'info'}>
                {role}
              </Badge>
            ))
          )}
        </div>
      ),
    },
    {
      key: 'mfa',
      header: 'MFA',
      render: (user) =>
        user.admin_mfa_required ? (
          <Badge tone="success">Bắt buộc</Badge>
        ) : (
          <Badge tone="neutral">Không</Badge>
        ),
    },
    {
      key: 'lastLogin',
      header: 'Đăng nhập gần nhất',
      render: (user) => (
        <span className="telemetry">{formatDateTime(user.last_login_at)}</span>
      ),
    },
    {
      key: 'failed',
      header: 'Đăng nhập thất bại',
      render: (user) => (
        <span className="telemetry">{user.failed_login_count}</span>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (user) => (
        <div className="flex flex-wrap items-center gap-1">
          <Button
            variant="secondary"
            onClick={() => {
              setGrantTarget(user)
              setGrantRole(UserRole.SOC_ANALYST)
            }}
            disabled={anyPending}
          >
            Cấp vai trò
          </Button>
          {user.roles
            .filter((role) => role !== BASE_ROLE)
            .map((role) => (
              <Button
                key={role}
                variant="ghost"
                onClick={() => setRevokeTarget({ user, role })}
                disabled={anyPending}
                aria-label={`Thu hồi vai trò ${role} của ${user.username}`}
              >
                Thu hồi {role}
              </Button>
            ))}
          {user.status === UserStatus.locked ? (
            <Button
              variant="secondary"
              onClick={() => setLockTarget(user)}
              disabled={anyPending}
            >
              Mở khoá
            </Button>
          ) : (
            <Button
              variant="danger"
              onClick={() => setLockTarget(user)}
              disabled={anyPending}
            >
              Khoá
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={() => setMfaTarget(user)}
            disabled={anyPending}
          >
            {user.admin_mfa_required ? 'Bỏ MFA' : 'Bắt buộc MFA'}
          </Button>
        </div>
      ),
    },
  ]

  const users = usersQuery.data?.users ?? []
  const total = usersQuery.data?.total ?? 0

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="page-title text-text">Quản lý người dùng</h1>
        <p className="text-sm text-text-muted">
          Danh sách tài khoản và các vai trò được phân công trong Sentinel Auth.
        </p>
      </header>

      <div
        role="search"
        aria-label="Bộ lọc người dùng"
        className="flex flex-wrap items-end gap-3 border border-border bg-surface-raised p-4"
      >
        <div className="w-48">
          <label htmlFor="user-role" className="label-ops text-text-muted">
            Vai trò
          </label>
          <select
            id="user-role"
            value={roleFilter}
            onChange={(event) => {
              setRoleFilter(event.target.value)
              setPage(1)
            }}
            className="mt-1 w-full border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
          >
            <option value="">Tất cả</option>
            {Object.values(UserRole).map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </div>
        <div className="w-48">
          <label htmlFor="user-status" className="label-ops text-text-muted">
            Trạng thái
          </label>
          <select
            id="user-status"
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value)
              setPage(1)
            }}
            className="mt-1 w-full border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
          >
            <option value="">Tất cả</option>
            {Object.values(UserStatus).map((status) => (
              <option key={status} value={status}>
                {STATUS_LABEL[status]}
              </option>
            ))}
          </select>
        </div>
      </div>

      {usersQuery.isPending && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Spinner /> Đang tải danh sách người dùng…
        </div>
      )}

      {usersQuery.isError && (
        <ErrorState
          title="Không thể tải danh sách người dùng"
          message={errorMessage(usersQuery.error)}
          action={
            <Button
              variant="secondary"
              onClick={() => void usersQuery.refetch()}
            >
              Thử lại
            </Button>
          }
        />
      )}

      {usersQuery.isSuccess && (
        <>
          <DataTable
            columns={columns}
            rows={users}
            rowKey={(user) => user.id}
            caption="Danh sách người dùng"
            empty={
              <EmptyState
                title="Không có dữ liệu"
                description="Không có tài khoản nào khớp với bộ lọc hiện tại."
              />
            }
          />
          <Pagination
            page={page}
            limit={IAM_PAGE_SIZE}
            total={total}
            disabled={usersQuery.isFetching}
            onPageChange={setPage}
          />
        </>
      )}

      {anyMutationError(grantMutation, revokeMutation, lockMutation, unlockMutation, mfaMutation) && (
        <ErrorState
          title="Thao tác không thành công"
          message={anyMutationError(
            grantMutation,
            revokeMutation,
            lockMutation,
            unlockMutation,
            mfaMutation,
          ) as string}
        />
      )}

      {/* --- Grant a role ------------------------------------------------- */}
      <ConfirmDialog
        open={grantTarget !== null}
        title="Cấp vai trò?"
        message={
          <div className="flex flex-col gap-3">
            <p>
              Cấp vai trò cho <strong>{grantTarget?.username}</strong> sẽ thu hồi
              toàn bộ phiên đăng nhập hiện tại của tài khoản đó. Thao tác được
              ghi vào nhật ký kiểm toán.
            </p>
            <label htmlFor="grant-role" className="label-ops text-text-muted">
              Vai trò
            </label>
            <select
              id="grant-role"
              value={grantRole}
              onChange={(event) => setGrantRole(event.target.value)}
              className="border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
            >
              {GRANTABLE_ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </div>
        }
        confirmLabel="Cấp vai trò"
        busy={grantMutation.isPending}
        onCancel={() => setGrantTarget(null)}
        onConfirm={() => grantMutation.mutate()}
      />

      {/* --- Revoke a role ------------------------------------------------ */}
      <ConfirmDialog
        open={revokeTarget !== null}
        title="Thu hồi vai trò?"
        message={
          <p>
            Thu hồi vai trò <strong>{revokeTarget?.role}</strong> của{' '}
            <strong>{revokeTarget?.user.username}</strong> sẽ thu hồi toàn bộ
            phiên đăng nhập của tài khoản đó.
          </p>
        }
        confirmLabel="Thu hồi vai trò"
        destructive
        busy={revokeMutation.isPending}
        onCancel={() => setRevokeTarget(null)}
        onConfirm={() => revokeMutation.mutate()}
      />

      {/* --- Lock / unlock ------------------------------------------------ */}
      <ConfirmDialog
        open={lockTarget !== null}
        title={
          lockTarget?.status === UserStatus.locked
            ? 'Mở khoá tài khoản?'
            : 'Khoá tài khoản?'
        }
        message={
          <p>
            {lockTarget?.status === UserStatus.locked
              ? `Mở khoá tài khoản ${lockTarget?.username}.`
              : `Khoá tài khoản ${lockTarget?.username} sẽ chặn mọi đăng nhập mới và thu hồi toàn bộ phiên hiện tại.`}
          </p>
        }
        confirmLabel={
          lockTarget?.status === UserStatus.locked ? 'Mở khoá' : 'Khoá'
        }
        destructive={lockTarget?.status !== UserStatus.locked}
        busy={lockMutation.isPending || unlockMutation.isPending}
        onCancel={() => setLockTarget(null)}
        onConfirm={() => {
          if (lockTarget?.status === UserStatus.locked) {
            unlockMutation.mutate()
          } else {
            lockMutation.mutate()
          }
        }}
      />

      {/* --- MFA toggle ---------------------------------------------------- */}
      <ConfirmDialog
        open={mfaTarget !== null}
        title={
          mfaTarget?.admin_mfa_required
            ? 'Bỏ yêu cầu MFA?'
            : 'Bắt buộc MFA?'
        }
        message={
          <p>
            {mfaTarget?.admin_mfa_required
              ? `Tài khoản ${mfaTarget?.username} sẽ không còn bắt buộc xác thực hai yếu tố.`
              : `Tài khoản ${mfaTarget?.username} sẽ phải xác thực hai yếu tố ở lần đăng nhập kế tiếp.`}{' '}
            Thay đổi này thu hồi toàn bộ phiên đăng nhập hiện tại.
          </p>
        }
        confirmLabel={
          mfaTarget?.admin_mfa_required ? 'Bỏ yêu cầu MFA' : 'Yêu cầu MFA'
        }
        busy={mfaMutation.isPending}
        onCancel={() => setMfaTarget(null)}
        onConfirm={() => mfaMutation.mutate()}
      />
    </div>
  )
}

/**
 * The message of the first mutation that failed, if any.
 *
 * The mutations are mutually exclusive in practice — the confirm dialogs
 * are separate — so the first error is the one the admin needs to see.
 */
function anyMutationError(
  ...mutations: { isError: boolean; error: unknown }[]
): string | null {
  for (const mutation of mutations) {
    if (mutation.isError) return errorMessage(mutation.error)
  }
  return null
}
