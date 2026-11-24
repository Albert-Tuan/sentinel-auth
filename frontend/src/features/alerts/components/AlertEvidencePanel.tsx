import { Badge, type BadgeTone } from '@/shared/components/Badge'
import { EmptyState } from '@/shared/components/EmptyState'
import { describeUserAgent, formatDateTime } from '@/lib/datetime'
import type {
  AlertEvidence,
  DetectionLogSummary,
  LoginAttemptSummary,
  RiskAssessmentSummary,
} from '@/types/api'

import { DetectionLogTable } from '@/features/alerts/components/DetectionLogTable'

export interface AlertEvidencePanelProps {
  evidence: AlertEvidence
}

/**
 * One score of the risk assessment.
 *
 * The distinction this component exists for: **null is not zero**.
 *
 *   - `null`  → the backend produced NO score. The row says so; it never
 *                shows a number.
 *   - `0`     → a real score of zero. It is shown as `0.0000`.
 *
 * A score of zero and a missing score mean very different things to an
 * analyst, so they must never collapse into each other.
 */
function ScoreRow({
  label,
  value,
  hint,
}: {
  label: string
  value: number | null | undefined
  hint?: string
}) {
  const missing = value === null || value === undefined

  return (
    <div className="flex flex-col">
      <dt className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="text-sm text-slate-800">
        {missing ? (
          <span className="text-slate-400">Không có dữ liệu</span>
        ) : (
          <span className="font-mono">{value.toFixed(4)}</span>
        )}
      </dd>
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

/**
 * A labelled value of the login attempt.
 */
function DetailRow({
  label,
  value,
}: {
  label: string
  value: string | null | undefined
}) {
  return (
    <div className="flex flex-col">
      <dt className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="break-words text-sm text-slate-800">
        {value ? value : <span className="text-slate-400">Không có dữ liệu</span>}
      </dd>
    </div>
  )
}

/**
 * The ML status vocabulary of the backend.
 *
 * `app/models.py` constrains `risk_assessments.ml_status` to
 * `success | unavailable | error`. The schema comment states the
 * contract: `ml_score` is NULL when the status is `unavailable` or
 * `error` — that is the rule-only fallback.
 */
const ML_FALLBACK_STATUSES = new Set(['unavailable', 'error'])

/** True when the engine scored the attempt with the rules alone. */
function isRuleOnly(assessment: RiskAssessmentSummary): boolean {
  return (
    assessment.ml_score === null &&
    assessment.ml_status !== null &&
    ML_FALLBACK_STATUSES.has(assessment.ml_status)
  )
}

/** The tone of the ML status badge. */
function mlStatusTone(status: string): BadgeTone {
  if (status === 'success') return 'success'
  if (ML_FALLBACK_STATUSES.has(status)) return 'warning'
  return 'neutral'
}

/**
 * The evidence bundle of one alert.
 *
 * Three sources are rendered, in the order an investigator reads them:
 * the login attempt (what happened), the risk assessment (how risky it
 * was), and the detection logs (why the pipeline decided so).
 */
export function AlertEvidencePanel({ evidence }: AlertEvidencePanelProps) {
  const attempt: LoginAttemptSummary | null = evidence.login_attempt
  const assessment: RiskAssessmentSummary | null = evidence.risk_assessment
  const logs: DetectionLogSummary[] = evidence.detection_logs ?? []

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="evidence-attempt-heading" className="flex flex-col gap-3">
        <h3 id="evidence-attempt-heading" className="text-sm font-semibold text-slate-900">
          Lần đăng nhập
        </h3>
        {attempt === null ? (
          <EmptyState
            title="Không có dữ liệu lần đăng nhập"
            description="Bản ghi lần đăng nhập của cảnh báo này không tồn tại."
          />
        ) : (
          <dl className="grid grid-cols-1 gap-4 rounded-md border border-slate-200 bg-white p-4 sm:grid-cols-2">
            <DetailRow label="Tài khoản" value={attempt.username_attempted} />
            <DetailRow label="Kết quả" value={attempt.outcome} />
            <DetailRow label="Địa chỉ IP" value={attempt.ip_address} />
            <DetailRow label="Mức rủi ro" value={attempt.risk_level} />
            <DetailRow
              label="Quyết định phát hiện"
              value={attempt.detection_decision}
            />
            <DetailRow
              label="Đã dùng MFA"
              value={attempt.mfa_used ? 'Có' : 'Không'}
            />
            <DetailRow label="Thời điểm" value={formatDateTime(attempt.timestamp)} />
            <DetailRow label="User agent" value={describeUserAgent(attempt.user_agent)} />
            <DetailRow label="Mã lần đăng nhập" value={attempt.id} />
            <DetailRow label="Mã sự kiện" value={attempt.event_id} />
          </dl>
        )}
      </section>

      <section aria-labelledby="evidence-risk-heading" className="flex flex-col gap-3">
        <h3 id="evidence-risk-heading" className="text-sm font-semibold text-slate-900">
          Đánh giá rủi ro
        </h3>
        {assessment === null ? (
          <EmptyState
            title="Không có đánh giá rủi ro"
            description="Chưa có bản ghi đánh giá rủi ro cho cảnh báo này."
          />
        ) : (
          <div className="flex flex-col gap-4 rounded-md border border-slate-200 bg-white p-4">
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <ScoreRow label="Điểm quy tắc" value={assessment.rule_score} />
              <ScoreRow label="Điểm ML" value={assessment.ml_score} />
              <ScoreRow label="Điểm tổng hợp" value={assessment.combined_score} />
            </dl>

            {/*
              The ML status explains WHY a score may be missing. A null
              `ml_score` with an "unavailable"/"error" status means the
              engine fell back to the rules only — that is a materially
              different finding than "no assessment at all", and the
              analyst must see it.
            */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs uppercase tracking-wide text-slate-500">
                Trạng thái ML
              </span>
              {assessment.ml_status ? (
                <Badge tone={mlStatusTone(assessment.ml_status)}>
                  {assessment.ml_status}
                </Badge>
              ) : (
                <Badge tone="neutral">Không có dữ liệu</Badge>
              )}
              {assessment.ml_model_version && (
                <span className="font-mono text-xs text-slate-500">
                  {assessment.ml_model_version}
                </span>
              )}
              {isRuleOnly(assessment) && (
                <span className="text-xs text-amber-700">
                  Không có điểm ML — chỉ dùng điểm quy tắc (rule-only).
                </span>
              )}
              {assessment.ml_score === null && !isRuleOnly(assessment) && (
                <span className="text-xs text-slate-500">
                  Không có điểm ML từ engine.
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <DetailRow label="Mức rủi ro" value={assessment.risk_level} />
              <DetailRow label="Quyết định" value={assessment.decision} />
            </div>

            {assessment.rule_hits && assessment.rule_hits.length > 0 && (
              <div className="flex flex-col gap-1">
                <span className="text-xs uppercase tracking-wide text-slate-500">
                  Quy tắc đã kích hoạt
                </span>
                <ul className="list-inside list-disc text-sm text-slate-700">
                  {assessment.rule_hits.map((hit, index) => (
                    <li key={index}>
                      {typeof hit === 'string'
                        ? hit
                        : JSON.stringify(hit)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {assessment.ml_reason_codes &&
              assessment.ml_reason_codes.length > 0 && (
                <div className="flex flex-col gap-1">
                  <span className="text-xs uppercase tracking-wide text-slate-500">
                    Mã lý do ML
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {assessment.ml_reason_codes.map((code, index) => (
                      <Badge key={index} tone="neutral">
                        {typeof code === 'string' ? code : JSON.stringify(code)}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
          </div>
        )}
      </section>

      <section aria-labelledby="evidence-logs-heading" className="flex flex-col gap-3">
        <h3 id="evidence-logs-heading" className="text-sm font-semibold text-slate-900">
          Log phát hiện
        </h3>
        <DetectionLogTable logs={logs} />
      </section>
    </div>
  )
}
