/**
 * S-07 — Profile (`/profile`).
 *
 * Read-only view of the current user. Every value comes from
 * `GET /auth/me`; nothing is inferred on the client.
 */

import { Badge } from '@/shared/components/Badge'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { ErrorState } from '@/shared/components/ErrorState'
import { Spinner } from '@/shared/components/Spinner'

import { formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { UserStatus } from '@/types/api'

const STATUS_TONE: Record<string, 'success' | 'warning' | 'danger'> = {
  active: 'success',
  suspended: 'warning',
  locked: 'danger',
}

interface ProfileRow {
  label: string
  value: string
}

export function ProfilePage() {
  const { user, status, error, roles } = useAuthContext()

  if (status === 'authenticating' || status === 'verifying_mfa') {
    return <Spinner label="Đang tải hồ sơ…" />
  }

  if (!user) {
    return (
      <ErrorState
        title="Không tải được hồ sơ"
        message={error ? errorMessage(error) : 'Không có dữ liệu người dùng.'}
      />
    )
  }

  const rows: ProfileRow[] = [
    { label: 'Tên đăng nhập', value: user.username },
    { label: 'Email', value: user.email },
    { label: 'Họ tên', value: user.full_name ?? '—' },
    { label: 'Trạng thái', value: user.status },
    { label: 'Đăng nhập gần nhất', value: formatDateTime(user.last_login_at) },
    {
      label: 'Số lần đăng nhập thất bại',
      value: String(user.failed_login_count),
    },
    { label: 'Tạo tài khoản', value: formatDateTime(user.created_at) },
    { label: 'Bị khoá lúc', value: formatDateTime(user.locked_at) },
    {
      label: 'Yêu cầu MFA bắt buộc',
      value: user.admin_mfa_required ? 'Có' : 'Không',
    },
  ]

  const columns: TableColumn<ProfileRow>[] = [
    {
      key: 'label',
      header: 'Trường',
      render: (row: ProfileRow) => (
        <span className="font-medium text-slate-600">{row.label}</span>
      ),
      className: 'w-56',
    },
    {
      key: 'value',
      header: 'Giá trị',
      render: (row: ProfileRow) => row.value,
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Hồ sơ</h1>
        <p className="text-sm text-slate-500">
          Thông tin tài khoản đang đăng nhập.
        </p>
      </header>

      <section className="rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Vai trò
        </h2>
        <div className="mt-2 flex flex-wrap gap-2">
          {roles.length === 0 ? (
            <span className="text-sm text-slate-500">Chưa có vai trò nào.</span>
          ) : (
            roles.map((role) => (
              <Badge key={role} tone="info">
                {role}
              </Badge>
            ))
          )}
        </div>
        <div className="mt-3">
          <Badge tone={STATUS_TONE[user.status] ?? 'neutral'}>
            {user.status === UserStatus.active
              ? 'Đang hoạt động'
              : user.status === UserStatus.suspended
                ? 'Tạm khóa'
                : 'Bị khoá'}
          </Badge>
        </div>
      </section>

      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(row) => row.label}
        caption="Thông tin tài khoản"
      />
    </div>
  )
}
