/**
 * S-43 — Manager SOC KPI (`/manager/soc-kpi`).
 *
 * The KPI board of the `SECURITY_MANAGER` role. It reads
 * `GET /manager/soc-kpi`, whose default window is the last 30 days.
 *
 * EVERY KPI is nullable, and the two reasons are DIFFERENT:
 *
 *   - a KPI over an EMPTY population is `null`;
 *   - a KPI whose SOURCE is down is also `null`.
 *
 * The backend cannot tell them apart, so the screen does not guess
 * either: a `null` renders as "không có dữ liệu", NEVER as a zero. A
 * zero would claim a measurement that was never taken, and a manager
 * reading a board of zeros would draw exactly the wrong conclusion.
 *
 * The `degraded` banner tells the manager WHICH source is down, which
 * is what makes the missing KPIs explicable.
 */

import { useQuery } from '@tanstack/react-query'

import { Button } from '@/shared/components/Button'
import { ErrorState } from '@/shared/components/ErrorState'
import { Spinner } from '@/shared/components/Spinner'

import { fetchManagerSocKpi } from '@/lib/api/manager.api'
import { errorMessage } from '@/lib/errors'

import {
  AnalyticsWindowBar,
  DegradedBanner,
  MetricGrid,
  MetricTile,
} from '@/features/manager/components/AnalyticsPrimitives'

export function ManagerSocKpiPage() {
  const kpiQuery = useQuery({
    queryKey: ['manager', 'soc-kpi'],
    queryFn: () => fetchManagerSocKpi(),
  })

  if (kpiQuery.isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-muted">
        <Spinner /> Đang tải KPI SOC…
      </div>
    )
  }

  if (kpiQuery.isError) {
    return (
      <ErrorState
        title="Không thể tải KPI SOC"
        message={errorMessage(kpiQuery.error)}
        action={
          <Button variant="secondary" onClick={() => void kpiQuery.refetch()}>
            Thử lại
          </Button>
        }
      />
    )
  }

  const data = kpiQuery.data
  const kpis = data.kpis

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h1 className="page-title text-text">KPI SOC</h1>
        <p className="text-sm text-text-muted">
          Chỉ số vận hành của đội SOC. Một chỉ số không có dữ liệu được hiển
          thị rõ ràng, không phải giá trị 0.
        </p>
      </header>

      <AnalyticsWindowBar window={data.window} generatedAt={data.generated_at} />
      <DegradedBanner degraded={data.degraded} sources={data.sources} />

      <MetricGrid title="Thời gian phản hồi">
        <MetricTile
          label="MTTA"
          value={kpis.mtta_seconds ?? null}
          unit="giây"
          hint="Thời gian trung bình tới phân công"
        />
        <MetricTile
          label="MTTR"
          value={kpis.mttr_seconds ?? null}
          unit="giây"
          hint="Thời gian trung bình tới xử lý"
        />
        <MetricTile
          label="Cảnh báo / analyst"
          value={kpis.alerts_per_analyst ?? null}
        />
        <MetricTile
          label="Sự kiện kiểm toán"
          value={kpis.audit_events ?? null}
        />
      </MetricGrid>

      <MetricGrid title="Tỉ lệ xử lý">
        <MetricTile
          label="Tỉ lệ xác nhận"
          value={kpis.acknowledgement_rate ?? null}
          tone="info"
        />
        <MetricTile
          label="Tỉ lệ xử lý"
          value={kpis.resolution_rate ?? null}
          tone="success"
        />
        <MetricTile
          label="Tỉ lệ báo động giả"
          value={kpis.false_positive_rate ?? null}
          tone="danger"
        />
        <MetricTile
          label="Tỉ lệ escalate"
          value={kpis.escalation_rate ?? null}
          tone="warning"
        />
      </MetricGrid>

      <MetricGrid title="Thực thi bảo vệ">
        <MetricTile
          label="Số lần thực thi"
          value={kpis.enforcement_attempted ?? null}
        />
        <MetricTile
          label="Số lần thành công"
          value={kpis.enforcement_succeeded ?? null}
          tone="success"
        />
        <MetricTile
          label="Tỉ lệ thành công"
          value={kpis.enforcement_success_rate ?? null}
          tone="info"
        />
        <MetricTile
          label="Fallback ML"
          value={kpis.ml_fallback_count ?? null}
          tone="warning"
          hint={`Tỉ lệ: ${kpis.ml_fallback_rate ?? '—'}`}
        />
      </MetricGrid>

      <MetricGrid title="Xác thực">
        <MetricTile
          label="Tỉ lệ bật MFA"
          value={kpis.mfa_enrollment_rate ?? null}
          tone="info"
        />
        <MetricTile
          label="Người dùng bắt buộc MFA"
          value={kpis.forced_mfa_users ?? null}
        />
        <MetricTile
          label="Số lần đánh giá ML"
          value={kpis.ml_assessments ?? null}
        />
        <MetricTile
          label="Fallback ML (số lần)"
          value={kpis.ml_fallback_count ?? null}
          tone="warning"
        />
      </MetricGrid>
    </div>
  )
}
