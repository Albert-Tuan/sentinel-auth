/**
 * S-44 — Manager ML Stats (`/manager/ml-stats`).
 *
 * The machine-learning statistics of the `SECURITY_MANAGER` role. It
 * reads `GET /manager/ml-stats`, whose default window is the last 30
 * days.
 *
 * The endpoint consumes a SINGLE source, so a failure of that source is
 * a 503 and there is nothing to render. The screen shows the failure
 * state with the reason code the backend reported.
 *
 * The feature statistics are rendered as a table rather than as charts:
 * the backend already computes the percentiles, and a table shows the
 * exact value of every column without the reader having to hover a
 * tooltip.
 */

import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Spinner } from '@/shared/components/Spinner'

import { fetchManagerMlStats } from '@/lib/api/manager.api'
import { formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import type { ManagerMlFeaturePoint } from '@/types/api'

import {
  AnalyticsWindowBar,
  DegradedBanner,
  DistributionBar,
  MetricGrid,
  MetricTile,
} from '@/features/manager/components/AnalyticsPrimitives'

export function ManagerMlStatsPage() {
  const mlQuery = useQuery({
    queryKey: ['manager', 'ml-stats'],
    queryFn: () => fetchManagerMlStats(),
  })

  if (mlQuery.isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-muted">
        <Spinner /> Đang tải thống kê máy học…
      </div>
    )
  }

  if (mlQuery.isError) {
    return (
      <ErrorState
        title="Không thể tải thống kê máy học"
        message={errorMessage(mlQuery.error)}
        action={
          <Button variant="secondary" onClick={() => void mlQuery.refetch()}>
            Thử lại
          </Button>
        }
      />
    )
  }

  const data = mlQuery.data
  const model = data.model
  const inference = data.inference
  const statusTotal = Object.values(data.by_status).reduce(
    (sum, value) => sum + value,
    0,
  )

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h1 className="page-title text-text">Thống kê máy học</h1>
        <p className="text-sm text-text-muted">
          Trạng thái mô hình, thống kê suy luận và phân bố đặc trưng.
        </p>
      </header>

      <AnalyticsWindowBar window={data.window} generatedAt={data.generated_at} />
      <DegradedBanner degraded={data.degraded} sources={data.sources} />

      {/* --- Model ------------------------------------------------------- */}
      <section className="flex flex-col gap-3">
        <h2 className="heading-ops text-text">Mô hình đang hoạt động</h2>
        {model ? (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <MetricTile label="Phiên bản" value={model.active_version ?? '—'} />
            <MetricTile
              label="Trạng thái"
              value={model.status ?? '—'}
              tone={model.is_production ? 'success' : 'neutral'}
            />
            <MetricTile label="Thuật toán" value={model.algorithm ?? '—'} />
            <MetricTile
              label="Triển khai lúc"
              value={model.deployed_at ? formatDateTime(model.deployed_at) : '—'}
            />
          </div>
        ) : (
          <EmptyState
            title="Không có dữ liệu"
            description="Không có mô hình nào đang hoạt động, hoặc nguồn ML không khả dụng."
          />
        )}
      </section>

      {/* --- Inference --------------------------------------------------- */}
      <MetricGrid title="Thống kê suy luận">
        <MetricTile label="Tổng suy luận" value={inference.total} />
        <MetricTile
          label="Bất thường"
          value={inference.anomalies}
          tone="warning"
          hint={`Tỉ lệ: ${inference.anomaly_rate ?? '—'}`}
        />
        <MetricTile
          label="Thời gian TB"
          value={inference.avg_processing_ms ?? null}
          unit="ms"
          tone="info"
          hint={`p95: ${inference.p95_processing_ms ?? '—'} ms`}
        />
        <MetricTile
          label="Lỗi / degraded"
          value={inference.errors}
          tone="danger"
          hint={`degraded: ${inference.degraded}`}
        />
      </MetricGrid>

      {/* --- Versions ---------------------------------------------------- */}
      {data.versions.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="heading-ops text-text">Phiên bản mô hình</h2>
          <div className="flex flex-col gap-2 border border-border bg-surface-raised p-3">
            {data.versions.map((version) => (
              <div
                key={version.version}
                className="flex flex-wrap items-center gap-3 border-b border-border py-1.5 last:border-b-0"
              >
                <span className="telemetry text-xs text-text">{version.version}</span>
                <Badge tone={version.is_production ? 'success' : 'neutral'}>
                  {version.status.toUpperCase()}
                </Badge>
                <span className="telemetry text-xs text-degraded">
                  {version.inferences} suy luận
                </span>
                {version.training_date && (
                  <span className="telemetry text-xs text-degraded">
                    huấn luyện: {formatDateTime(version.training_date)}
                  </span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* --- Status distribution ------------------------------------------ */}
      {statusTotal > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="heading-ops text-text">Phân bố trạng thái suy luận</h2>
          <div className="grid gap-2 md:grid-cols-4">
            {Object.entries(data.by_status).map(([status, count]) => (
              <DistributionBar
                key={status}
                label={status}
                count={count}
                total={statusTotal}
                tone={status === 'degraded' ? 'warning' : 'primary'}
              />
            ))}
          </div>
        </section>
      )}

      {/* --- Features ----------------------------------------------------- */}
      <section className="flex flex-col gap-3">
        <h2 className="heading-ops text-text">Phân bố đặc trưng</h2>
        <FeatureTable features={data.features} />
      </section>
    </div>
  )
}

/**
 * The feature statistics, as a table.
 *
 * Every numeric column is nullable in the backend, and a `null` is
 * rendered as an em dash rather than a zero.
 */
function FeatureTable({ features }: { features: ManagerMlFeaturePoint[] }) {
  const columns: TableColumn<ManagerMlFeaturePoint>[] = [
    {
      key: 'name',
      header: 'Đặc trưng',
      render: (feature) => (
        <span className="telemetry text-xs text-text">{feature.feature_name}</span>
      ),
    },
    {
      key: 'count',
      header: 'Số lần',
      render: (feature) => (
        <span className="telemetry text-xs text-text">{feature.count}</span>
      ),
    },
    {
      key: 'mean',
      header: 'TB',
      render: (feature) => (
        <span className="telemetry text-xs text-text-muted">
          {feature.mean ?? '—'}
        </span>
      ),
    },
    {
      key: 'std',
      header: 'Độ lệch',
      render: (feature) => (
        <span className="telemetry text-xs text-text-muted">
          {feature.std ?? '—'}
        </span>
      ),
    },
    {
      key: 'min',
      header: 'Min',
      render: (feature) => (
        <span className="telemetry text-xs text-text-muted">
          {feature.min ?? '—'}
        </span>
      ),
    },
    {
      key: 'p95',
      header: 'p95',
      render: (feature) => (
        <span className="telemetry text-xs text-text-muted">
          {feature.p95 ?? '—'}
        </span>
      ),
    },
    {
      key: 'max',
      header: 'Max',
      render: (feature) => (
        <span className="telemetry text-xs text-text-muted">
          {feature.max ?? '—'}
        </span>
      ),
    },
    {
      key: 'anomalyRate',
      header: 'Tỉ lệ bất thường',
      render: (feature) => (
        <span className="telemetry text-xs text-warning">
          {feature.anomaly_rate ?? '—'}
        </span>
      ),
    },
  ]

  return (
    <DataTable
      columns={columns}
      rows={features}
      rowKey={(feature) => feature.feature_name}
      caption="Phân bố đặc trưng"
      empty={
        <EmptyState
          title="Không có dữ liệu"
          description="Không có bản ghi đặc trưng nào trong cửa sổ phân tích."
        />
      }
    />
  )
}
