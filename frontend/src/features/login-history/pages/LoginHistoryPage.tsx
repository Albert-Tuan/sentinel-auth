/**
 * S-22 — Login History (`/login-history`).
 *
 * The analyst's search over every login attempt the Detection Engine
 * recorded. It reads `GET /api/v1/login-attempts` and renders the rows
 * exactly as the server returned them: the backend owns the ordering
 * (newest first) and the pagination, and the client never re-sorts or
 * re-pages the result.
 *
 * The screen is a pure read. Every mutation lives on the alert detail
 * screen, where the alert context is available.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Input } from '@/shared/components/Input'
import { Pagination } from '@/shared/components/Pagination'
import { RiskBadge } from '@/shared/components/RiskBadge'
import { Spinner } from '@/shared/components/Spinner'

import { alertDetailPath } from '@/app/router/paths'
import {
  SEARCH_OUTCOMES,
  SEARCH_RISK_LEVELS,
  fetchLoginHistory,
  type SearchOutcome,
  type SearchRiskLevel,
} from '@/lib/api/loginHistory.api'
import { describeUserAgent, formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import type { LoginAttemptItem } from '@/types/api'

/** The page size the backend is asked for. */
const PAGE_SIZE = 20

/** The filters as the UI holds them. */
interface HistoryFilters {
  username: string
  ip_address: string
  outcome: '' | SearchOutcome
  risk_level: '' | SearchRiskLevel
}

const EMPTY_FILTERS: HistoryFilters = {
  username: '',
  ip_address: '',
  outcome: '',
  risk_level: '',
}

const OUTCOME_LABEL: Record<string, string> = {
  success: 'Thành công',
  failure: 'Thất bại',
  mfa_required: 'Yêu cầu MFA',
  mfa_success: 'MFA thành công',
  mfa_failed: 'MFA thất bại',
  blocked: 'Bị chặn',
  locked: 'Bị khoá',
  rate_limited: 'Bị giới hạn',
}

/**
 * The outcome of an attempt, as a chip.
 *
 * The stored vocabulary is finer-grained than the search vocabulary, so an
 * outcome the UI does not know is shown verbatim rather than folded into a
 * known one — the analyst must see what the engine actually recorded.
 */
function OutcomeBadge({ outcome }: { outcome: string }) {
  const tone =
    outcome === 'success' || outcome === 'mfa_success'
      ? 'success'
      : outcome === 'blocked' || outcome === 'locked'
        ? 'danger'
        : outcome === 'failure' || outcome === 'mfa_failed'
          ? 'warning'
          : 'neutral'

  return <Badge tone={tone}>{OUTCOME_LABEL[outcome] ?? outcome}</Badge>
}

export function LoginHistoryPage() {
  const [filters, setFilters] = useState<HistoryFilters>(EMPTY_FILTERS)
  const [applied, setApplied] = useState<HistoryFilters>(EMPTY_FILTERS)
  const [page, setPage] = useState(1)

  const historyQuery = useQuery({
    queryKey: ['login-history', applied, page],
    queryFn: () =>
      fetchLoginHistory({
        username: applied.username || undefined,
        ip_address: applied.ip_address || undefined,
        outcome: applied.outcome || undefined,
        risk_level: applied.risk_level || undefined,
        page,
        limit: PAGE_SIZE,
      }),
  })

  const columns: TableColumn<LoginAttemptItem>[] = [
    {
      key: 'timestamp',
      header: 'Thời điểm',
      render: (attempt) => (
        <span className="telemetry">{formatDateTime(attempt.timestamp)}</span>
      ),
    },
    {
      key: 'username',
      header: 'Tài khoản',
      render: (attempt) =>
        attempt.username_attempted ? (
          <span className="telemetry">{attempt.username_attempted}</span>
        ) : (
          <span className="text-degraded">Không có dữ liệu</span>
        ),
    },
    {
      key: 'outcome',
      header: 'Kết quả',
      render: (attempt) => <OutcomeBadge outcome={attempt.outcome} />,
    },
    {
      key: 'risk',
      header: 'Rủi ro',
      render: (attempt) => <RiskBadge riskLevel={attempt.risk_level} />,
    },
    {
      key: 'ip',
      header: 'Địa chỉ IP',
      render: (attempt) =>
        attempt.ip_address ? (
          <span className="telemetry">{attempt.ip_address}</span>
        ) : (
          <span className="text-degraded">Không có dữ liệu</span>
        ),
    },
    {
      key: 'device',
      header: 'Thiết bị',
      render: (attempt) => (
        <span title={attempt.user_agent ?? undefined}>
          {describeUserAgent(attempt.user_agent)}
        </span>
      ),
    },
    {
      key: 'decision',
      header: 'Quyết định',
      render: (attempt) =>
        attempt.detection_decision ? (
          <span className="telemetry">{attempt.detection_decision}</span>
        ) : (
          <span className="text-degraded">Không có dữ liệu</span>
        ),
    },
    {
      key: 'alert',
      header: 'Cảnh báo',
      render: (attempt) =>
        attempt.primary_alert_id ? (
          <Link
            to={alertDetailPath(attempt.primary_alert_id)}
            className="telemetry text-xs text-secondary hover:underline"
          >
            {attempt.primary_alert_id}
          </Link>
        ) : (
          <span className="text-degraded">—</span>
        ),
    },
  ]

  const attempts = historyQuery.data?.attempts ?? []
  const total = historyQuery.data?.total ?? 0
  const hasFilters = Object.values(applied).some((value) => value !== '')

  function handleReset() {
    setFilters(EMPTY_FILTERS)
    setApplied(EMPTY_FILTERS)
    setPage(1)
  }

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="page-title text-text">Lịch sử đăng nhập</h1>
        <p className="text-sm text-text-muted">
          Mọi lần đăng nhập mà Detection Engine đã ghi nhận, mới nhất trước.
        </p>
      </header>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          setApplied(filters)
          setPage(1)
        }}
        role="search"
        aria-label="Bộ lọc lịch sử đăng nhập"
        className="flex flex-wrap items-end gap-3 border border-border bg-surface-raised p-4"
      >
        <div className="min-w-48 flex-1">
          <Input
            id="history-username"
            label="Tài khoản"
            value={filters.username}
            maxLength={50}
            placeholder="Tên đăng nhập được thử"
            onChange={(event) =>
              setFilters({ ...filters, username: event.target.value.trim() })
            }
          />
        </div>
        <div className="min-w-48 flex-1">
          <Input
            id="history-ip"
            label="Địa chỉ IP"
            value={filters.ip_address}
            maxLength={45}
            placeholder="203.0.113.7"
            onChange={(event) =>
              setFilters({ ...filters, ip_address: event.target.value.trim() })
            }
          />
        </div>
        <div className="w-44">
          <label
            htmlFor="history-outcome"
            className="label-ops text-text-muted"
          >
            Kết quả
          </label>
          <select
            id="history-outcome"
            value={filters.outcome}
            onChange={(event) =>
              setFilters({
                ...filters,
                outcome: event.target.value as HistoryFilters['outcome'],
              })
            }
            className="mt-1 w-full border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
          >
            <option value="">Tất cả</option>
            {SEARCH_OUTCOMES.map((outcome) => (
              <option key={outcome} value={outcome}>
                {OUTCOME_LABEL[outcome]}
              </option>
            ))}
          </select>
        </div>
        <div className="w-44">
          <label
            htmlFor="history-risk"
            className="label-ops text-text-muted"
          >
            Mức rủi ro
          </label>
          <select
            id="history-risk"
            value={filters.risk_level}
            onChange={(event) =>
              setFilters({
                ...filters,
                risk_level: event.target.value as HistoryFilters['risk_level'],
              })
            }
            className="mt-1 w-full border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
          >
            <option value="">Tất cả</option>
            {SEARCH_RISK_LEVELS.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit">Tìm kiếm</Button>
        <Button
          type="button"
          variant="secondary"
          onClick={handleReset}
          disabled={!hasFilters}
        >
          Đặt lại
        </Button>
      </form>

      {historyQuery.isPending && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Spinner /> Đang tải lịch sử đăng nhập…
        </div>
      )}

      {historyQuery.isError && (
        <ErrorState
          title="Không thể tải lịch sử đăng nhập"
          message={errorMessage(historyQuery.error)}
          action={
            <Button
              variant="secondary"
              onClick={() => void historyQuery.refetch()}
            >
              Thử lại
            </Button>
          }
        />
      )}

      {historyQuery.isSuccess && (
        <>
          <DataTable
            columns={columns}
            rows={attempts}
            rowKey={(attempt) => attempt.id}
            caption="Lịch sử đăng nhập"
            empty={
              <EmptyState
                title="Không có dữ liệu"
                description="Không có lần đăng nhập nào khớp với bộ lọc hiện tại."
              />
            }
          />

          <Pagination
            page={page}
            limit={PAGE_SIZE}
            total={total}
            disabled={historyQuery.isFetching}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  )
}
