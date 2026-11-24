/**
 * S-11 — Audit Logs (`/admin/audit-logs`).
 *
 * The `SECURITY_ADMIN` audit trail. It reads `GET /admin/audit-logs` and
 * renders each entry verbatim: the before/after states are JSON objects
 * the backend produced, and the frontend never rewrites them.
 *
 * The screen is a pure read. The IAM mutations live on the user
 * directory, where the target of the change is visible.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Input } from '@/shared/components/Input'
import { Pagination } from '@/shared/components/Pagination'
import { Spinner } from '@/shared/components/Spinner'

import { IAM_PAGE_SIZE, fetchAuditLogs } from '@/lib/api/iam.api'
import { formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import type { AuditLogItem } from '@/types/api'

/** The filters as the UI holds them. */
interface AuditFilters {
  actor: string
  action: string
  resource: string
}

const EMPTY_FILTERS: AuditFilters = { actor: '', action: '', resource: '' }

export function AuditLogsPage() {
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_FILTERS)
  const [applied, setApplied] = useState<AuditFilters>(EMPTY_FILTERS)
  const [page, setPage] = useState(1)

  const logsQuery = useQuery({
    queryKey: ['admin', 'audit-logs', applied, page],
    queryFn: () =>
      fetchAuditLogs({
        actor: applied.actor || undefined,
        action: applied.action || undefined,
        resource: applied.resource || undefined,
        page,
        limit: IAM_PAGE_SIZE,
      }),
  })

  const columns: TableColumn<AuditLogItem>[] = [
    {
      key: 'createdAt',
      header: 'Thời điểm',
      render: (log) => (
        <span className="telemetry">{formatDateTime(log.created_at)}</span>
      ),
    },
    {
      key: 'actor',
      header: 'Tác nhân',
      render: (log) => (
        <span className="telemetry">
          {log.actor === 'system' ? (
            <Badge tone="neutral">HỆ THỐNG</Badge>
          ) : (
            log.actor
          )}
        </span>
      ),
    },
    {
      key: 'action',
      header: 'Hành động',
      render: (log) => <Badge tone="info">{log.action}</Badge>,
    },
    {
      key: 'resource',
      header: 'Tài nguyên',
      render: (log) => (
        <span className="telemetry">
          {log.resource}
          {log.resource_id && (
            <span className="ml-1 text-degraded">{log.resource_id}</span>
          )}
        </span>
      ),
    },
    {
      key: 'change',
      header: 'Thay đổi',
      render: (log) => (
        <ChangeSummary log={log} />
      ),
    },
    {
      key: 'ip',
      header: 'IP',
      render: (log) =>
        log.ip_address ? (
          <span className="telemetry">{log.ip_address}</span>
        ) : (
          <span className="text-degraded">—</span>
        ),
    },
  ]

  const logs = logsQuery.data?.logs ?? []
  const total = logsQuery.data?.total ?? 0
  const hasFilters = Object.values(applied).some((value) => value !== '')

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="page-title text-text">Nhật ký kiểm toán</h1>
        <p className="text-sm text-text-muted">
          Mọi thay đổi trạng thái được hệ thống ghi lại, mới nhất trước.
        </p>
      </header>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          setApplied(filters)
          setPage(1)
        }}
        role="search"
        aria-label="Bộ lọc nhật ký kiểm toán"
        className="flex flex-wrap items-end gap-3 border border-border bg-surface-raised p-4"
      >
        <div className="min-w-48 flex-1">
          <Input
            id="audit-actor"
            label="Tác nhân"
            value={filters.actor}
            placeholder="Tên đăng nhập hoặc 'system'"
            onChange={(event) =>
              setFilters({ ...filters, actor: event.target.value.trim() })
            }
          />
        </div>
        <div className="min-w-48 flex-1">
          <Input
            id="audit-action"
            label="Hành động"
            value={filters.action}
            placeholder="assign_role"
            onChange={(event) =>
              setFilters({ ...filters, action: event.target.value.trim() })
            }
          />
        </div>
        <div className="min-w-48 flex-1">
          <Input
            id="audit-resource"
            label="Tài nguyên"
            value={filters.resource}
            placeholder="user"
            onChange={(event) =>
              setFilters({ ...filters, resource: event.target.value.trim() })
            }
          />
        </div>
        <Button type="submit">Lọc</Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            setFilters(EMPTY_FILTERS)
            setApplied(EMPTY_FILTERS)
            setPage(1)
          }}
          disabled={!hasFilters}
        >
          Đặt lại
        </Button>
      </form>

      {logsQuery.isPending && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Spinner /> Đang tải nhật ký kiểm toán…
        </div>
      )}

      {logsQuery.isError && (
        <ErrorState
          title="Không thể tải nhật ký kiểm toán"
          message={errorMessage(logsQuery.error)}
          action={
            <Button
              variant="secondary"
              onClick={() => void logsQuery.refetch()}
            >
              Thử lại
            </Button>
          }
        />
      )}

      {logsQuery.isSuccess && (
        <>
          <DataTable
            columns={columns}
            rows={logs}
            rowKey={(log) => log.id}
            caption="Nhật ký kiểm toán"
            empty={
              <EmptyState
                title="Không có dữ liệu"
                description="Không có bản ghi kiểm toán nào khớp với bộ lọc hiện tại."
              />
            }
          />
          <Pagination
            page={page}
            limit={IAM_PAGE_SIZE}
            total={total}
            disabled={logsQuery.isFetching}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  )
}

/**
 * The change an audit entry records.
 *
 * The backend stores `before_state` and `after_state` as free-form JSON.
 * A null state is NOT an empty state: it means the backend recorded no
 * state at all, which the row says explicitly.
 */
function ChangeSummary({ log }: { log: AuditLogItem }) {
  if (!log.before_state && !log.after_state) {
    return <span className="text-degraded">Không có dữ liệu</span>
  }

  const before = log.before_state ? JSON.stringify(log.before_state) : '—'
  const after = log.after_state ? JSON.stringify(log.after_state) : '—'

  return (
    <span className="telemetry break-words text-xs text-text-muted">
      {before} <span className="text-degraded">→</span> {after}
    </span>
  )
}
