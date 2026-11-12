/**
 * S-05 — Sessions (`/sessions`).
 *
 * Lists the current user's active sessions and lets them revoke one or all
 * of them. Revoking the CURRENT session also kills the access token the
 * client is holding, so the app logs out afterwards.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Spinner } from '@/shared/components/Spinner'

import { fetchSessions, logoutAll, revokeSession } from '@/lib/api/auth.api'
import { describeUserAgent, formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { PATHS } from '@/app/router/paths'
import type { SessionItem } from '@/types/api'

export function SessionsPage() {
  const auth = useAuthContext()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [revokeTarget, setRevokeTarget] = useState<SessionItem | null>(null)
  const [logoutAllOpen, setLogoutAllOpen] = useState(false)

  const sessionsQuery = useQuery({
    queryKey: ['auth', 'sessions'],
    queryFn: fetchSessions,
  })

  const revokeMutation = useMutation({
    mutationFn: (sessionId: string) => revokeSession(sessionId),
    onSuccess: async (_data, sessionId) => {
      await queryClient.invalidateQueries({ queryKey: ['auth', 'sessions'] })
      setRevokeTarget(null)
      // Revoking the current session invalidates the access token we hold.
      if (sessionId === auth.sessionId) {
        await auth.logout()
        navigate(PATHS.login, { replace: true })
      }
    },
  })

  const logoutAllMutation = useMutation({
    mutationFn: () => logoutAll(),
    onSuccess: async () => {
      setLogoutAllOpen(false)
      await auth.logout()
      navigate(PATHS.login, { replace: true })
    },
  })

  const columns: TableColumn<SessionItem>[] = [
    {
      key: 'device',
      header: 'Thiết bị',
      render: (session) => (
        <span title={session.user_agent ?? undefined}>
          {describeUserAgent(session.user_agent)}
        </span>
      ),
    },
    {
      key: 'ip',
      header: 'Địa chỉ IP',
      render: (session) => session.ip_address ?? '—',
    },
    {
      key: 'created',
      header: 'Bắt đầu',
      render: (session) => formatDateTime(session.created_at),
    },
    {
      key: 'lastActivity',
      header: 'Hoạt động gần nhất',
      render: (session) => formatDateTime(session.last_activity_at),
    },
    {
      key: 'expires',
      header: 'Hết hạn',
      render: (session) => formatDateTime(session.expires_at),
    },
    {
      key: 'current',
      header: 'Trạng thái',
      render: (session) =>
        session.is_current ? (
          <Badge tone="info">Phiên hiện tại</Badge>
        ) : (
          <Badge tone="neutral">Phiên khác</Badge>
        ),
    },
    {
      key: 'actions',
      header: '',
      render: (session) => (
        <Button
          variant="ghost"
          className="text-red-600 hover:bg-red-50"
          onClick={() => setRevokeTarget(session)}
          aria-label={`Thu hồi phiên ${session.id}`}
        >
          Thu hồi
        </Button>
      ),
    },
  ]

  const sessions = sessionsQuery.data?.sessions ?? []

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Phiên đăng nhập</h1>
          <p className="text-sm text-slate-500">
            Các phiên đang hoạt động của tài khoản này.
          </p>
        </div>
        <Button
          variant="danger"
          onClick={() => setLogoutAllOpen(true)}
          disabled={sessions.length === 0}
        >
          Đăng xuất khỏi mọi thiết bị
        </Button>
      </header>

      {sessionsQuery.isPending && (
        <div className="flex items-center gap-2 text-sm text-slate-600">
          <Spinner /> Đang tải danh sách phiên…
        </div>
      )}

      {sessionsQuery.isError && (
        <ErrorState
          message={errorMessage(sessionsQuery.error)}
          action={
            <Button
              variant="secondary"
              onClick={() => void sessionsQuery.refetch()}
            >
              Thử lại
            </Button>
          }
        />
      )}

      {sessionsQuery.isSuccess && (
        <DataTable
          columns={columns}
          rows={sessions}
          rowKey={(session) => session.id}
          caption="Danh sách phiên đăng nhập đang hoạt động"
          empty={
            <EmptyState
              title="Không có phiên đăng nhập nào"
              description="Bạn không có phiên nào đang hoạt động."
            />
          }
        />
      )}

      {revokeMutation.isError && (
        <ErrorState
          title="Không thể thu hồi phiên"
          message={errorMessage(revokeMutation.error)}
        />
      )}

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Thu hồi phiên đăng nhập?"
        message={
          revokeTarget?.is_current
            ? 'Đây là phiên hiện tại của bạn. Thu hồi sẽ đăng xuất bạn khỏi ứng dụng ngay lập tức.'
            : 'Phiên này sẽ bị thu hồi và thiết bị tương ứng phải đăng nhập lại.'
        }
        confirmLabel="Thu hồi"
        destructive
        busy={revokeMutation.isPending}
        onCancel={() => setRevokeTarget(null)}
        onConfirm={() => {
          if (revokeTarget) revokeMutation.mutate(revokeTarget.id)
        }}
      />

      <ConfirmDialog
        open={logoutAllOpen}
        title="Đăng xuất khỏi mọi thiết bị?"
        message="Tất cả phiên đăng nhập đang hoạt động, kể cả phiên hiện tại, sẽ bị thu hồi. Bạn sẽ phải đăng nhập lại trên mọi thiết bị."
        confirmLabel="Đăng xuất tất cả"
        destructive
        busy={logoutAllMutation.isPending}
        onCancel={() => setLogoutAllOpen(false)}
        onConfirm={() => logoutAllMutation.mutate()}
      />
    </div>
  )
}
