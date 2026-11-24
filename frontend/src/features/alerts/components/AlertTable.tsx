import { useNavigate } from 'react-router-dom'

import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { RiskBadge } from '@/shared/components/RiskBadge'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { alertDetailPath } from '@/app/router/paths'
import { formatDateTime } from '@/lib/datetime'
import type { AlertItem } from '@/types/api'

export interface AlertTableProps {
  alerts: AlertItem[]
  /**
   * The subject of each alert, keyed by `login_attempt_id`.
   *
   * The queue endpoint does NOT return the username or the IP: they live
   * on the login attempt, which the queue does not join. The map is
   * therefore supplied by the caller when the data is available, and the
   * columns render "—" when it is not. Nothing is guessed.
   */
  subjects?: Record<string, AlertSubject>
}

/**
 * What the queue knows about the subject of an alert.
 *
 * `username` is the `login_attempts.username_attempted` the detection
 * engine captured at login time — NOT the Core `users` table.
 */
export interface AlertSubject {
  username: string | null
  ip_address: string | null
}

/**
 * The alert queue table.
 *
 * Clicking a row opens the alert detail. The ordering is the BACKEND's:
 * the rows are rendered exactly as the server returned them, so the
 * newest-first rule of the backend is never overridden by the client.
 */
export function AlertTable({ alerts, subjects = {} }: AlertTableProps) {
  const navigate = useNavigate()

  const columns: TableColumn<AlertItem>[] = [
    {
      key: 'risk',
      header: 'Mức rủi ro',
      render: (alert) => <RiskBadge riskLevel={alert.risk_level} />,
    },
    {
      key: 'status',
      header: 'Trạng thái',
      render: (alert) => <StatusBadge status={alert.status} />,
    },
    {
      key: 'reason',
      header: 'Lý do phát hiện',
      render: (alert) =>
        alert.detection_reason ? (
          <span title={alert.detection_reason}>{alert.detection_reason}</span>
        ) : (
          <span className="text-slate-400">—</span>
        ),
    },
    {
      key: 'username',
      header: 'Tài khoản',
      render: (alert) => {
        const subject = subjects[alert.login_attempt_id]
        return subject?.username ? (
          subject.username
        ) : (
          <span className="text-slate-400">—</span>
        )
      },
    },
    {
      key: 'ip',
      header: 'Địa chỉ IP',
      render: (alert) => {
        const subject = subjects[alert.login_attempt_id]
        return subject?.ip_address ? (
          subject.ip_address
        ) : (
          <span className="text-slate-400">—</span>
        )
      },
    },
    {
      key: 'assignee',
      header: 'Người được giao',
      render: (alert) =>
        alert.assigned_to_id ? (
          <span className="font-mono text-xs">{alert.assigned_to_id}</span>
        ) : (
          <span className="text-slate-400">Chưa giao</span>
        ),
    },
    {
      key: 'created',
      header: 'Thời điểm phát hiện',
      render: (alert) => formatDateTime(alert.created_at),
    },
  ]

  return (
    <DataTable
      columns={columns}
      rows={alerts}
      rowKey={(alert) => alert.id}
      caption="Danh sách cảnh báo an ninh"
      onRowClick={(alert) => navigate(alertDetailPath(alert.id))}
    />
  )
}
