/**
 * S-42 — Manager Alert Analytics (`/manager/alerts`).
 *
 * The alert analytics of the `SECURITY_MANAGER` role. It reads
 * `GET /manager/alerts`, whose default window is the last 30 days.
 *
 * Two filters are sent to the backend — `status` and `risk_level` —
 * and they filter the POPULATION the numbers are computed over, not
 * the rows on the screen. The screen therefore says so explicitly: a
 * filter narrows the whole analysis, and a manager comparing two
 * filtered views is comparing two populations.
 *
 * A filter value that is not in the backend vocabulary is a 400, so the
 * selects only offer the canonical values and an unset filter is NOT
 * sent (an empty string would be an invalid filter).
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/shared/components/Button'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Spinner } from '@/shared/components/Spinner'

import {
  MANAGER_ALERT_STATUSES,
  MANAGER_RISK_LEVELS,
  fetchManagerAlerts,
  type ManagerAlertStatus,
} from '@/lib/api/manager.api'
import { errorMessage } from '@/lib/errors'

import {
  AnalyticsWindowBar,
  DegradedBanner,
  DistributionBar,
  MetricGrid,
  MetricTile,
} from '@/features/manager/components/AnalyticsPrimitives'
import { toneForRisk } from '@/features/manager/analyticsTones'

/**
 * A breakdown row of the backend (`by_rule` / `by_ml_reason`).
 *
 * The rows are free-form JSON objects, so the shape is read defensively:
 * the frontend never assumes which key carries the label.
 */
interface BreakdownRow {
  label: string
  count: number
}

export function ManagerAlertsPage() {
  const [status, setStatus] = useState<'' | ManagerAlertStatus>('')
  const [riskLevel, setRiskLevel] = useState<'' | string>('')

  const alertsQuery = useQuery({
    queryKey: ['manager', 'alerts', status, riskLevel],
    queryFn: () =>
      fetchManagerAlerts({
        status: status || undefined,
        riskLevel: riskLevel || undefined,
      }),
  })

  if (alertsQuery.isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-muted">
        <Spinner /> Đang tải phân tích cảnh báo…
      </div>
    )
  }

  if (alertsQuery.isError) {
    return (
      <ErrorState
        title="Không thể tải phân tích cảnh báo"
        message={errorMessage(alertsQuery.error)}
        action={
          <Button variant="secondary" onClick={() => void alertsQuery.refetch()}>
            Thử lại
          </Button>
        }
      />
    )
  }

  const data = alertsQuery.data
  const totalStatus = Object.values(data.by_status).reduce(
    (sum, value) => sum + value,
    0,
  )
  const totalRisk = Object.values(data.by_risk_level).reduce(
    (sum, value) => sum + value,
    0,
  )

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h1 className="page-title text-text">Phân tích cảnh báo</h1>
        <p className="text-sm text-text-muted">
          Bộ lọc áp dụng cho TOÀN BỘ dân số của trang, không chỉ cho các
          dòng hiển thị.
        </p>
      </header>

      <form
        onSubmit={(event) => event.preventDefault()}
        role="search"
        aria-label="Bộ lọc phân tích cảnh báo"
        className="flex flex-wrap items-end gap-3 border border-border bg-surface-raised p-4"
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="alerts-status" className="label-ops text-text-muted">
            Trạng thái
          </label>
          <select
            id="alerts-status"
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as '' | ManagerAlertStatus)
            }
            className="telemetry border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
          >
            <option value="">Tất cả trạng thái</option>
            {MANAGER_ALERT_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="alerts-risk" className="label-ops text-text-muted">
            Mức rủi ro
          </label>
          <select
            id="alerts-risk"
            value={riskLevel}
            onChange={(event) => setRiskLevel(event.target.value)}
            className="telemetry border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
          >
            <option value="">Tất cả mức rủi ro</option>
            {MANAGER_RISK_LEVELS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={!status && !riskLevel}
          onClick={() => {
            setStatus('')
            setRiskLevel('')
          }}
        >
          Đặt lại
        </Button>
      </form>

      <AnalyticsWindowBar window={data.window} generatedAt={data.generated_at} />
      <DegradedBanner degraded={data.degraded} sources={data.sources} />

      <MetricGrid title="Tổng quan cảnh báo">
        <MetricTile label="Đã tạo" value={data.totals.created} />
        <MetricTile
          label="Đang mở"
          value={data.totals.open}
          tone="warning"
        />
        <MetricTile
          label="Đã xử lý"
          value={data.totals.resolved}
          tone="success"
        />
        <MetricTile
          label="Báo động giả"
          value={data.totals.false_positive}
          tone="danger"
        />
      </MetricGrid>

      <MetricGrid title="Tồn đọng">
        <MetricTile label="Đang mở" value={data.backlog.open_count} />
        <MetricTile
          label="Tuổi cũ nhất"
          value={data.backlog.oldest_open_age_hours ?? null}
          unit="giờ"
        />
        <MetricTile label="Chưa phân công" value={data.backlog.unassigned} />
        <MetricTile label="Đã escalate" value={data.backlog.escalated} />
      </MetricGrid>

      <MetricGrid title="Hiệu suất xử lý">
        <MetricTile
          label="MTTA"
          value={data.mtta_seconds ?? null}
          unit="giây"
          hint="Thời gian trung bình tới phân công"
        />
        <MetricTile
          label="MTTR"
          value={data.mttr_seconds ?? null}
          unit="giây"
          hint="Thời gian trung bình tới xử lý"
        />
        <MetricTile
          label="Tỉ lệ báo động giả"
          value={data.false_positive_rate ?? null}
          tone="danger"
        />
        <MetricTile label="Đã xác nhận" value={data.acknowledged_count} />
      </MetricGrid>

      <section className="flex flex-col gap-3">
        <h2 className="heading-ops text-text">Phân bố trạng thái</h2>
        <div className="grid gap-2 md:grid-cols-4">
          {Object.entries(data.by_status).map(([key, count]) => (
            <DistributionBar
              key={key}
              label={key}
              count={count}
              total={totalStatus}
            />
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="heading-ops text-text">Phân bố mức rủi ro</h2>
        <div className="grid gap-2 md:grid-cols-4">
          {Object.entries(data.by_risk_level).map(([level, count]) => (
            <DistributionBar
              key={level}
              label={level}
              count={count}
              total={totalRisk}
              tone={toneForRisk(level)}
            />
          ))}
        </div>
      </section>

      <BreakdownTable title="Theo quy tắc phát hiện" rows={data.by_rule} />
      <BreakdownTable title="Theo mã lý do ML" rows={data.by_ml_reason} />
    </div>
  )
}

/**
 * One breakdown table.
 *
 * The backend returns free-form JSON objects, so the label and the
 * count are read from the first string value and the first numeric
 * value found — whichever the backend chose. Nothing is renamed.
 */
function BreakdownTable({
  title,
  rows,
}: {
  title: string
  rows: Array<Record<string, unknown>>
}) {
  const columns: TableColumn<BreakdownRow>[] = [
    {
      key: 'label',
      header: 'Nhãn',
      render: (row) => <span className="telemetry text-xs text-text">{row.label}</span>,
    },
    {
      key: 'count',
      header: 'Số lượng',
      render: (row) => (
        <span className="telemetry text-xs text-text">{row.count}</span>
      ),
    },
  ]

  const parsed = rows.map(toBreakdownRow)

  return (
    <section className="flex flex-col gap-3">
      <h2 className="heading-ops text-text">{title}</h2>
      <DataTable
        columns={columns}
        rows={parsed}
        rowKey={(row, index) => `${row.label}-${index}`}
        caption={title}
        empty={
          <EmptyState
            title="Không có dữ liệu"
            description="Không có bản ghi nào khớp bộ lọc hiện tại."
          />
        }
      />
    </section>
  )
}

/**
 * Read a free-form breakdown row.
 *
 * The first string is the label and the first number is the count. A row
 * with neither is rendered with placeholder values rather than crashing
 * the table.
 */
function toBreakdownRow(row: Record<string, unknown>, index: number): BreakdownRow {
  const entries = Object.entries(row)
  const labelEntry = entries.find(([, value]) => typeof value === 'string')
  const countEntry = entries.find(([, value]) => typeof value === 'number')

  return {
    label: labelEntry ? String(labelEntry[1]) : `#${index + 1}`,
    count: countEntry ? Number(countEntry[1]) : 0,
  }
}
