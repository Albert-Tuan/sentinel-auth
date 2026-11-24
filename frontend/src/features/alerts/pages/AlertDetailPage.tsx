/**
 * S-21 — Alert Detail (`/alerts/:alertId`).
 *
 * A READ-ONLY investigation screen. It merges three real endpoints:
 *
 *   GET /alerts/{id}            → the alert overview
 *   GET /alerts/{id}/evidence   → attempt + risk assessment + logs
 *   GET /alerts/{id}/timeline   → the audit trail
 *
 * The three requests are independent, so each section renders as soon as
 * its own data arrives: a failing timeline does not hide the evidence.
 *
 * Stage 5 owns every mutation (acknowledge / resolve / assign / actions
 * / add note); this screen never writes.
 */

import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { ErrorState } from '@/shared/components/ErrorState'
import { RiskBadge } from '@/shared/components/RiskBadge'
import { Spinner } from '@/shared/components/Spinner'
import { StatusBadge } from '@/shared/components/StatusBadge'

import { AlertEvidencePanel } from '@/features/alerts/components/AlertEvidencePanel'
import { TimelineFeed } from '@/features/alerts/components/TimelineFeed'
import { PATHS } from '@/app/router/paths'
import {
  fetchAlert,
  fetchAlertEvidence,
  fetchAlertTimeline,
} from '@/lib/api/alerts.api'
import { formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import type { AlertItem } from '@/types/api'

export function AlertDetailPage() {
  const { alertId } = useParams<{ alertId: string }>()

  const alertQuery = useQuery({
    queryKey: ['alerts', 'detail', alertId],
    queryFn: () => fetchAlert(alertId ?? ''),
    enabled: Boolean(alertId),
  })

  const evidenceQuery = useQuery({
    queryKey: ['alerts', 'evidence', alertId],
    queryFn: () => fetchAlertEvidence(alertId ?? ''),
    enabled: Boolean(alertId),
  })

  const timelineQuery = useQuery({
    queryKey: ['alerts', 'timeline', alertId],
    queryFn: () => fetchAlertTimeline(alertId ?? ''),
    enabled: Boolean(alertId),
  })

  const alert: AlertItem | undefined = alertQuery.data

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to={PATHS.alerts}
            className="text-sm text-indigo-600 hover:underline"
          >
            ← Về hàng đợi cảnh báo
          </Link>
          <h1 className="mt-1 text-xl font-semibold text-slate-900">
            Chi tiết cảnh báo
          </h1>
          {alert && (
            <p className="font-mono text-xs text-slate-500">{alert.id}</p>
          )}
        </div>
        {alert && (
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge riskLevel={alert.risk_level} />
            <StatusBadge status={alert.status} />
          </div>
        )}
      </header>

      {alertQuery.isPending && (
        <div className="flex items-center gap-2 text-sm text-slate-600">
          <Spinner /> Đang tải cảnh báo…
        </div>
      )}

      {alertQuery.isError && (
        <ErrorState
          title="Không thể tải cảnh báo"
          message={errorMessage(alertQuery.error)}
          action={
            <Button
              variant="secondary"
              onClick={() => void alertQuery.refetch()}
            >
              Thử lại
            </Button>
          }
        />
      )}

      {alert && <AlertOverview alert={alert} />}

      <section aria-labelledby="alert-evidence-heading" className="flex flex-col gap-3">
        <h2 id="alert-evidence-heading" className="text-sm font-semibold text-slate-900">
          Bằng chứng
        </h2>
        {evidenceQuery.isPending && (
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <Spinner /> Đang tải bằng chứng…
          </div>
        )}
        {evidenceQuery.isError && (
          <ErrorState
            title="Không thể tải bằng chứng"
            message={errorMessage(evidenceQuery.error)}
            action={
              <Button
                variant="secondary"
                onClick={() => void evidenceQuery.refetch()}
              >
                Thử lại
              </Button>
            }
          />
        )}
        {evidenceQuery.isSuccess && (
          <AlertEvidencePanel evidence={evidenceQuery.data} />
        )}
      </section>

      <section aria-labelledby="alert-timeline-heading" className="flex flex-col gap-3">
        <h2 id="alert-timeline-heading" className="text-sm font-semibold text-slate-900">
          Dòng thời gian
        </h2>
        {timelineQuery.isPending && (
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <Spinner /> Đang tải dòng thời gian…
          </div>
        )}
        {timelineQuery.isError && (
          <ErrorState
            title="Không thể tải dòng thời gian"
            message={errorMessage(timelineQuery.error)}
            action={
              <Button
                variant="secondary"
                onClick={() => void timelineQuery.refetch()}
              >
                Thử lại
              </Button>
            }
          />
        )}
        {timelineQuery.isSuccess && (
          <TimelineFeed events={timelineQuery.data} />
        )}
      </section>
    </div>
  )
}

/**
 * The overview of one alert.
 *
 * Every optional field is rendered as "no data" when the backend returned
 * null — a missing resolution is not the same as an empty resolution.
 */
function AlertOverview({ alert }: { alert: AlertItem }) {
  return (
    <section
      aria-labelledby="alert-overview-heading"
      className="flex flex-col gap-4"
    >
      <h2 id="alert-overview-heading" className="text-sm font-semibold text-slate-900">
        Tổng quan
      </h2>

      {alert.detection_reason && (
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">
            Lý do phát hiện
          </p>
          <p className="mt-1 text-sm text-slate-800">{alert.detection_reason}</p>
        </div>
      )}

      <dl className="grid grid-cols-1 gap-4 rounded-md border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-3">
        <OverviewField label="Trạng thái">
          <StatusBadge status={alert.status} />
        </OverviewField>
        <OverviewField label="Mức rủi ro">
          <RiskBadge riskLevel={alert.risk_level} />
        </OverviewField>
        <OverviewField label="Thời điểm tạo">
          {formatDateTime(alert.created_at)}
        </OverviewField>
        <OverviewField label="Cập nhật lần cuối">
          {formatDateTime(alert.updated_at)}
        </OverviewField>
        <OverviewField label="Mã lần đăng nhập">
          <span className="font-mono text-xs">{alert.login_attempt_id}</span>
        </OverviewField>
        <OverviewField label="Mã chính sách">
          {alert.policy_id ? (
            <span className="font-mono text-xs">{alert.policy_id}</span>
          ) : (
            <span className="text-slate-400">Không có dữ liệu</span>
          )}
        </OverviewField>
        <OverviewField label="Người được giao">
          {alert.assigned_to_id ? (
            <span className="font-mono text-xs">{alert.assigned_to_id}</span>
          ) : (
            <span className="text-slate-400">Chưa giao</span>
          )}
        </OverviewField>
        <OverviewField label="Kết quả xử lý">
          {alert.resolution ? (
            <Badge tone="neutral">{alert.resolution}</Badge>
          ) : (
            <span className="text-slate-400">Chưa xử lý</span>
          )}
        </OverviewField>
        <OverviewField label="Người xử lý">
          {alert.resolved_by_id ? (
            <span className="font-mono text-xs">{alert.resolved_by_id}</span>
          ) : (
            <span className="text-slate-400">Không có dữ liệu</span>
          )}
        </OverviewField>
        <OverviewField label="Thời điểm xử lý">
          {alert.resolved_at ? (
            formatDateTime(alert.resolved_at)
          ) : (
            <span className="text-slate-400">Không có dữ liệu</span>
          )}
        </OverviewField>
      </dl>

      {alert.notes && (
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Ghi chú</p>
          <p className="mt-1 whitespace-pre-wrap text-sm text-slate-800">
            {alert.notes}
          </p>
        </div>
      )}

      {alert.detection_scores && (
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">
            Điểm phát hiện
          </p>
          <dl className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(alert.detection_scores).map(([key, value]) => (
              <OverviewField key={key} label={key}>
                {typeof value === 'number' ? (
                  <span className="font-mono">{value.toFixed(4)}</span>
                ) : value === null || value === undefined ? (
                  // A missing score is NOT a score of zero, and it is not
                  // the text "null" either. The backend sends JSON null for
                  // "the engine produced no value here" — for example the
                  // `ml_score` of a rule-only fallback — so the row says
                  // so explicitly.
                  <span className="text-slate-400">Không có dữ liệu</span>
                ) : (
                  <span className="break-words font-mono text-xs">
                    {typeof value === 'object'
                      ? JSON.stringify(value)
                      : String(value)}
                  </span>
                )}
              </OverviewField>
            ))}
          </dl>
        </div>
      )}
    </section>
  )
}

/** One labelled field of the overview grid. */
function OverviewField({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-800">{children}</dd>
    </div>
  )
}
