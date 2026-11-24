/**
 * S-40 — Manager Dashboard (`/manager/dashboard`).
 *
 * The overview screen of the `SECURITY_MANAGER` role. It reads
 * `GET /manager/dashboard`, whose default window is the last 24 hours.
 *
 * The screen renders the envelope first — the effective window, the
 * generated-at stamp and the source health — because the three core
 * sections below it are only meaningful in that context:
 *
 *   - the backend applies a DEFAULT window when the caller sends none,
 *     so "last 24 hours" vs "last 14 days" must be visible;
 *   - a `degraded` payload is a VALID payload with some sections
 *     missing, not an error, and the manager has to be able to tell the
 *     difference;
 *   - a section that is `null` (its source was down) renders as an
 *     explicit "không có dữ liệu" panel, never as zeros.
 */

import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Spinner } from '@/shared/components/Spinner'

import { fetchManagerDashboard } from '@/lib/api/manager.api'
import { formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import type { ManagerCriticalIncident } from '@/types/api'

import {
  AnalyticsWindowBar,
  DegradedBanner,
  DistributionBar,
  MetricGrid,
  MetricTile,
} from '@/features/manager/components/AnalyticsPrimitives'
import { toneForRisk } from '@/features/manager/analyticsTones'

export function ManagerDashboardPage() {
  const dashboardQuery = useQuery({
    queryKey: ['manager', 'dashboard'],
    queryFn: () => fetchManagerDashboard(),
  })

  if (dashboardQuery.isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-muted">
        <Spinner /> Đang tải bảng điều khiển…
      </div>
    )
  }

  if (dashboardQuery.isError) {
    return (
      <ErrorState
        title="Không thể tải bảng điều khiển quản lý"
        message={errorMessage(dashboardQuery.error)}
        action={
          <Button variant="secondary" onClick={() => void dashboardQuery.refetch()}>
            Thử lại
          </Button>
        }
      />
    )
  }

  const data = dashboardQuery.data
  const core = data.core
  const detection = data.detection
  const ml = data.ml

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h1 className="page-title text-text">Bảng điều khiển quản lý</h1>
        <p className="text-sm text-text-muted">
          Tổng quan vận hành an ninh: xác thực, phát hiện mối đe dọa và mô
          hình máy học.
        </p>
      </header>

      <AnalyticsWindowBar window={data.window} generatedAt={data.generated_at} />
      <DegradedBanner degraded={data.degraded} sources={data.sources} />

      {/* --- Section 1: Core --------------------------------------------- */}
      {core ? (
        <MetricGrid title="01. Xác thực & định danh">
          <MetricTile label="Tổng người dùng" value={core.total_users} />
          <MetricTile
            label="Phiên đang hoạt động"
            value={core.active_sessions}
            tone="info"
          />
          <MetricTile
            label="Yêu cầu MFA"
            value={core.mfa_challenges}
            hint={`Hoàn tất: ${core.mfa_completed} · Thất bại: ${core.mfa_failed}`}
          />
          <MetricTile
            label="Sự kiện kiểm toán"
            value={core.audit_events}
            tone="neutral"
          />
        </MetricGrid>
      ) : (
        <UnavailablePanel title="01. Xác thực & định danh" />
      )}

      {core && (
        <section className="flex flex-col gap-3">
          <h2 className="heading-ops text-text">Phân bố người dùng</h2>
          <div className="grid gap-2 md:grid-cols-3">
            {Object.entries(core.users_by_status).map(([status, count]) => (
              <DistributionBar
                key={status}
                label={status}
                count={count}
                total={core.total_users}
              />
            ))}
          </div>
        </section>
      )}

      {/* --- Section 2: Detection ---------------------------------------- */}
      {detection ? (
        <>
          <MetricGrid title="02. Phát hiện mối đe dọa & cảnh báo SOC">
            <MetricTile label="Lần đăng nhập" value={detection.login_attempts} />
            <MetricTile
              label="Cảnh báo đang mở"
              value={detection.alerts.open}
              tone="warning"
            />
            <MetricTile
              label="Cảnh báo nghiêm trọng"
              value={detection.alerts.critical_open}
              tone="danger"
            />
            <MetricTile
              label="Điểm tổ hợp TB"
              value={detection.avg_combined_score ?? null}
              tone="info"
            />
          </MetricGrid>

          <section className="flex flex-col gap-3">
            <h2 className="heading-ops text-text">Phân bố mức rủi ro</h2>
            <div className="grid gap-2 md:grid-cols-4">
              {Object.entries(detection.by_risk_level).map(([level, count]) => (
                <DistributionBar
                  key={level}
                  label={level}
                  count={count}
                  total={detection.login_attempts}
                  tone={toneForRisk(level)}
                />
              ))}
            </div>
          </section>

          {detection.critical_incidents.length > 0 && (
            <CriticalIncidents incidents={detection.critical_incidents} />
          )}
        </>
      ) : (
        <UnavailablePanel title="02. Phát hiện mối đe dọa & cảnh báo SOC" />
      )}

      {/* --- Section 3: ML ------------------------------------------------ */}
      {ml ? (
        <MetricGrid title="03. Phân tích mô hình máy học">
          <MetricTile label="Suy luận" value={ml.inferences} />
          <MetricTile
            label="Bất thường"
            value={ml.anomalies}
            tone="warning"
            hint={`Tỉ lệ: ${ml.anomaly_rate ?? '—'}`}
          />
          <MetricTile
            label="Thời gian xử lý TB"
            value={ml.avg_processing_ms ?? null}
            unit="ms"
            tone="info"
          />
          <MetricTile
            label="Phiên bản mô hình"
            value={ml.active_model_version ?? '—'}
          />
        </MetricGrid>
      ) : (
        <UnavailablePanel title="03. Phân tích mô hình máy học" />
      )}
    </div>
  )
}

/**
 * The panel shown when a section is missing.
 *
 * The section is `null` because its SOURCE was unavailable. That is a
 * different situation from "the section is empty", and the wording says
 * so — an empty section would show zeros.
 */
function UnavailablePanel({ title }: { title: string }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="heading-ops text-text">{title}</h2>
      <EmptyState
        title="Không có dữ liệu"
        description="Nguồn dữ liệu của phần này không khả dụng — các số liệu không được tính."
      />
    </section>
  )
}

/**
 * The open critical incidents.
 *
 * The rows are rendered verbatim: the detection reason and the score
 * come from the Detection Engine, and the frontend never rewrites them.
 */
function CriticalIncidents({
  incidents,
}: {
  incidents: ManagerCriticalIncident[]
}) {
  const columns: TableColumn<ManagerCriticalIncident>[] = [
    {
      key: 'alertId',
      header: 'Cảnh báo',
      render: (incident) => (
        <span className="telemetry text-xs text-secondary">{incident.alert_id}</span>
      ),
    },
    {
      key: 'subject',
      header: 'Đối tượng',
      render: (incident) => (
        <span className="telemetry text-xs text-text">
          {incident.subject?.username ?? incident.subject?.user_id ?? '—'}
        </span>
      ),
    },
    {
      key: 'risk',
      header: 'Mức rủi ro',
      render: (incident) => (
        <Badge tone={incident.risk_level === 'critical' ? 'danger' : 'warning'}>
          {incident.risk_level.toUpperCase()}
        </Badge>
      ),
    },
    {
      key: 'score',
      header: 'Điểm',
      render: (incident) => (
        <span className="telemetry text-xs text-text">
          {incident.combined_score ?? '—'}
        </span>
      ),
    },
    {
      key: 'reason',
      header: 'Lý do phát hiện',
      render: (incident) => (
        <span className="telemetry text-xs text-text-muted">
          {incident.detection_reason ?? '—'}
        </span>
      ),
    },
    {
      key: 'age',
      header: 'Tuổi',
      render: (incident) => (
        <span className="telemetry text-xs text-text-muted">
          {incident.age_hours !== null && incident.age_hours !== undefined
            ? `${incident.age_hours}h`
            : '—'}
        </span>
      ),
    },
    {
      key: 'createdAt',
      header: 'Thời điểm',
      render: (incident) => (
        <span className="telemetry text-xs text-text-muted">
          {formatDateTime(incident.created_at)}
        </span>
      ),
    },
  ]

  return (
    <section className="flex flex-col gap-3">
      <h2 className="heading-ops text-text">Sự cố nghiêm trọng đang mở</h2>
      <DataTable
        columns={columns}
        rows={incidents}
        rowKey={(incident) => incident.alert_id}
        caption="Sự cố nghiêm trọng đang mở"
        empty={
          <EmptyState
            title="Không có sự cố nghiêm trọng"
            description="Không có cảnh báo mức rủi ro nghiêm trọng nào đang mở."
          />
        }
      />
    </section>
  )
}
