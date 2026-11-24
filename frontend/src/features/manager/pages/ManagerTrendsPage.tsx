/**
 * S-41 — Manager Trends (`/manager/trends`).
 *
 * The time series of the `SECURITY_MANAGER` role. It reads
 * `GET /manager/trends`, whose default window is the last 14 days.
 *
 * The bucket is a QUERY PARAMETER, not a client-side grouping: the
 * backend buckets the series itself, and it resolves `auto` from the
 * window length (`hour` up to 72 hours, `day` beyond). The screen
 * therefore sends the bucket it wants and renders the `bucket` the
 * backend echoed back — the two are not always the same, and the
 * echoed one is the truth.
 *
 * The three series (login attempts, alerts, ML) are INDEPENDENT
 * sources: one of them can be `null` while the others are present. A
 * missing series renders as an explicit "không có dữ liệu" panel.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/shared/components/Button'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Spinner } from '@/shared/components/Spinner'

import {
  MANAGER_BUCKETS,
  fetchManagerTrends,
  type ManagerBucket,
} from '@/lib/api/manager.api'
import { formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import type { ManagerTrendPoint } from '@/types/api'

import {
  AnalyticsWindowBar,
  DegradedBanner,
  DistributionBar,
} from '@/features/manager/components/AnalyticsPrimitives'
import { toneForRisk } from '@/features/manager/analyticsTones'

const BUCKET_LABEL: Record<ManagerBucket, string> = {
  auto: 'Tự động',
  hour: 'Theo giờ',
  day: 'Theo ngày',
}

export function ManagerTrendsPage() {
  const [bucket, setBucket] = useState<ManagerBucket>('auto')

  const trendsQuery = useQuery({
    queryKey: ['manager', 'trends', bucket],
    queryFn: () => fetchManagerTrends({ bucket }),
  })

  if (trendsQuery.isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-muted">
        <Spinner /> Đang tải xu hướng…
      </div>
    )
  }

  if (trendsQuery.isError) {
    return (
      <ErrorState
        title="Không thể tải xu hướng an ninh"
        message={errorMessage(trendsQuery.error)}
        action={
          <Button variant="secondary" onClick={() => void trendsQuery.refetch()}>
            Thử lại
          </Button>
        }
      />
    )
  }

  const data = trendsQuery.data
  const attempts = data.series.login_attempts
  const alerts = data.series.alerts
  const ml = data.series.ml

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h1 className="page-title text-text">Xu hướng an ninh</h1>
        <p className="text-sm text-text-muted">
          Chuỗi thời gian của lần đăng nhập, cảnh báo và suy luận máy học.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3 border border-border bg-surface-raised p-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="trends-bucket" className="label-ops text-text-muted">
            Độ phân giải
          </label>
          <select
            id="trends-bucket"
            value={bucket}
            onChange={(event) => setBucket(event.target.value as ManagerBucket)}
            className="telemetry border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
          >
            {MANAGER_BUCKETS.map((option) => (
              <option key={option} value={option}>
                {BUCKET_LABEL[option]}
              </option>
            ))}
          </select>
        </div>
        <p className="telemetry text-xs text-text-muted">
          Bucket backend áp dụng:{' '}
          <strong className="text-primary">{data.bucket}</strong>
        </p>
      </div>

      <AnalyticsWindowBar window={data.window} generatedAt={data.generated_at} />
      <DegradedBanner degraded={data.degraded} sources={data.sources} />

      {/* --- Login attempts ---------------------------------------------- */}
      <section className="flex flex-col gap-3">
        <h2 className="heading-ops text-text">Lần đăng nhập</h2>
        {attempts ? (
          <TrendTable points={attempts} />
        ) : (
          <EmptyState
            title="Không có dữ liệu"
            description="Nguồn Detection không khả dụng nên chuỗi lần đăng nhập không được tính."
          />
        )}
      </section>

      {/* --- Alerts ------------------------------------------------------ */}
      <section className="flex flex-col gap-3">
        <h2 className="heading-ops text-text">Cảnh báo</h2>
        {alerts && alerts.length > 0 ? (
          <div className="flex flex-col gap-2 border border-border bg-surface-raised p-3">
            {alerts.map((point) => (
              <div
                key={point.bucket_start}
                className="flex flex-wrap items-center gap-3 border-b border-border py-1.5 last:border-b-0"
              >
                <span className="telemetry text-xs text-text-muted">
                  {formatDateTime(point.bucket_start)}
                </span>
                <span className="telemetry text-xs text-text">
                  {point.total} cảnh báo
                </span>
                <span className="telemetry text-xs text-degraded">
                  {Object.entries(point.by_status)
                    .map(([status, count]) => `${status}: ${count}`)
                    .join(' · ')}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Không có dữ liệu"
            description="Không có cảnh báo nào trong cửa sổ phân tích, hoặc nguồn Detection không khả dụng."
          />
        )}
      </section>

      {/* --- ML ---------------------------------------------------------- */}
      <section className="flex flex-col gap-3">
        <h2 className="heading-ops text-text">Suy luận máy học</h2>
        {ml && ml.length > 0 ? (
          <div className="flex flex-col gap-2 border border-border bg-surface-raised p-3">
            {ml.map((point) => (
              <div
                key={point.bucket_start}
                className="flex flex-wrap items-center gap-3 border-b border-border py-1.5 last:border-b-0"
              >
                <span className="telemetry text-xs text-text-muted">
                  {formatDateTime(point.bucket_start)}
                </span>
                <span className="telemetry text-xs text-text">
                  {point.total} suy luận
                </span>
                <span className="telemetry text-xs text-warning">
                  {point.anomalies} bất thường
                </span>
                <span className="telemetry text-xs text-degraded">
                  {point.errors} lỗi · {point.degraded} degraded
                </span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Không có dữ liệu"
            description="Không có bản ghi suy luận nào trong cửa sổ phân tích, hoặc nguồn ML không khả dụng."
          />
        )}
      </section>
    </div>
  )
}

/**
 * The login-attempt series, as a table.
 *
 * The backend already bucketed the series, so the screen renders the
 * buckets as they arrive — it never re-groups them, because that would
 * silently disagree with the numbers the backend reports.
 */
function TrendTable({ points }: { points: ManagerTrendPoint[] }) {
  const totals = points.map((point) => point.total)
  const max = Math.max(...totals, 0)

  return (
    <div className="flex flex-col gap-2 border border-border bg-surface-raised p-3">
      {points.map((point) => {
        const share = max > 0 ? Math.round((point.total / max) * 100) : 0
        return (
          <div
            key={point.bucket_start}
            className="flex flex-col gap-1 border-b border-border py-1.5 last:border-b-0"
          >
            <div className="flex flex-wrap items-center gap-3">
              <span className="telemetry text-xs text-text-muted">
                {formatDateTime(point.bucket_start)}
              </span>
              <span className="telemetry text-xs text-text">
                {point.total} lần đăng nhập
              </span>
              <span className="telemetry text-xs text-degraded">
                {Object.entries(point.by_outcome)
                  .map(([outcome, count]) => `${outcome}: ${count}`)
                  .join(' · ')}
              </span>
            </div>
            <div className="h-1.5 w-full bg-surface-sunken">
              <div
                className="h-full bg-primary"
                style={{ width: `${share}%` }}
                role="presentation"
              />
            </div>
            <div className="flex flex-wrap gap-3">
              {Object.entries(point.by_risk_level).map(([level, count]) => (
                <span key={level} className="telemetry text-[10px] text-degraded">
                  {level}: {count}
                </span>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/**
 * The risk-level distribution of the last bucket.
 *
 * The distribution is derived from the LAST bucket of the series: it is
 * the current state, and a manager reads it as "where are we now" rather
 * than "how did we get here".
 */
export function LastBucketRiskDistribution({
  points,
}: {
  points: ManagerTrendPoint[]
}) {
  const last = points[points.length - 1]
  if (!last) return null

  const total = Object.values(last.by_risk_level).reduce(
    (sum, value) => sum + value,
    0,
  )

  return (
    <div className="grid gap-2 md:grid-cols-4">
      {Object.entries(last.by_risk_level).map(([level, count]) => (
        <DistributionBar
          key={level}
          label={level}
          count={count}
          total={total}
          tone={toneForRisk(level)}
        />
      ))}
    </div>
  )
}
