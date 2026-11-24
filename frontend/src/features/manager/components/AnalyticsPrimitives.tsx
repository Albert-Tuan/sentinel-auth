/**
 * The shared building blocks of the Manager analytics screens.
 *
 * Every Manager response carries the same envelope, so every screen
 * shows the same three things:
 *
 *   - the EFFECTIVE window (the backend applies a default when the
 *     caller sends none, so the window must always be visible);
 *   - the `degraded` flag with the per-source status, because a
 *     degraded payload is NOT an error — it is a valid payload with
 *     some sections missing;
 *   - the "no data" marker for a `null` metric, because a KPI over an
 *     empty population is `null` and rendering it as `0` would be a
 *     lie.
 */

import type { ReactNode } from 'react'

import { Badge } from '@/shared/components/Badge'
import type { ManagerEnvelope } from '@/types/api'

/**
 * The window banner.
 *
 * The backend echoes the window it actually used, so the screen never
 * has to guess whether the default applied.
 */
export function AnalyticsWindowBar({
  window,
  generatedAt,
}: {
  window: ManagerEnvelope['window']
  generatedAt: string
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border border-border bg-surface-raised px-3 py-2">
      <span className="label-ops text-degraded">CỬA SỔ PHÂN TÍCH</span>
      <span className="telemetry text-xs text-text">
        {window.from} → {window.to}
      </span>
      <span className="text-degraded">|</span>
      <span className="label-ops text-degraded">SINH LÚC</span>
      <span className="telemetry text-xs text-text">{generatedAt}</span>
    </div>
  )
}

/**
 * The degraded banner.
 *
 * A degraded payload is a VALID payload: the sections that do not
 * depend on the missing source are present and correct. The banner says
 * WHICH source is down and why (the backend's closed reason code), so
 * the manager does not mistake a partial view for a complete one.
 */
export function DegradedBanner({
  degraded,
  sources,
}: {
  degraded: boolean
  sources: ManagerEnvelope['sources']
}) {
  const unavailable = Object.entries(sources).filter(
    ([, status]) => status.status !== 'ok',
  )

  if (!degraded && unavailable.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-3 border border-l-4 border-border border-l-success bg-surface-raised px-3 py-2">
        <span className="h-2 w-2 bg-success" aria-hidden="true" />
        <span className="label-ops text-success">ALL_SYSTEMS_OPERATIONAL</span>
        <span className="telemetry text-xs text-text-muted">
          Tất cả nguồn phân tích đang hoạt động.
        </span>
      </div>
    )
  }

  return (
    <div
      role="status"
      className="flex flex-col gap-2 border border-l-4 border-border border-l-warning bg-surface-raised px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="h-2 w-2 bg-warning" aria-hidden="true" />
        <span className="label-ops text-warning">DEGRADED_MODE</span>
        <span className="telemetry text-xs text-text-muted">
          Một hoặc nhiều nguồn phân tích không khả dụng — số liệu hiển thị
          bên dưới chỉ là phần còn đọc được.
        </span>
      </div>
      {unavailable.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {unavailable.map(([name, status]) => (
            <li key={name}>
              <Badge tone="warning">
                {name.toUpperCase()}: {status.detail ?? 'unavailable'}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * One metric tile.
 *
 * A `null` metric is rendered as "không có dữ liệu", never as `0`:
 * the backend uses `null` for BOTH an empty population and a missing
 * source, and a zero would claim a measurement that was never taken.
 */
export function MetricTile({
  label,
  value,
  unit,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: number | string | null | undefined
  unit?: string
  hint?: string
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}) {
  const missing = value === null || value === undefined

  return (
    <div className="flex flex-col gap-1 border border-border bg-surface-raised p-3">
      <span className="label-ops text-degraded">{label}</span>
      {missing ? (
        <span className="telemetry text-sm text-degraded">— không có dữ liệu</span>
      ) : (
        <span className="flex items-baseline gap-1">
          <span className={`telemetry text-xl font-bold ${VALUE_TONE_CLASS[tone]}`}>
            {value}
          </span>
          {unit && <span className="label-ops text-text-muted">{unit}</span>}
        </span>
      )}
      {hint && <span className="text-[10px] text-degraded">{hint}</span>}
    </div>
  )
}

/**
 * The concrete class of each metric tone.
 *
 * The classes are written out because Tailwind scans the SOURCE for
 * literal class names: a `text-${tone}` template would never be
 * generated and the value would be unstyled.
 */
const VALUE_TONE_CLASS: Record<
  'neutral' | 'success' | 'warning' | 'danger' | 'info',
  string
> = {
  neutral: 'text-text',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-secondary',
}

/**
 * A labelled group of metrics.
 */
export function MetricGrid({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="heading-ops text-text">{title}</h2>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">{children}</div>
    </section>
  )
}

/**
 * A horizontal distribution bar.
 *
 * The bar is the design system's answer to a "share of total" question:
 * a filled segment per category, with the raw count next to it. A
 * category with a zero count is rendered as a zero-width segment, never
 * as a missing row.
 */
export function DistributionBar({
  label,
  count,
  total,
  tone = 'primary',
}: {
  label: string
  count: number
  total: number
  tone?: 'primary' | 'secondary' | 'warning' | 'danger'
}) {
  const share = total > 0 ? Math.round((count / total) * 100) : 0

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-3">
        <span className="label-ops text-text-muted">{label}</span>
        <span className="telemetry text-xs text-text">
          {count}
          <span className="text-degraded"> ({share}%)</span>
        </span>
      </div>
      <div className="h-1.5 w-full bg-surface-sunken">
        <div
          className={`h-full ${BAR_TONE_CLASS[tone]}`}
          style={{ width: `${share}%` }}
          role="presentation"
        />
      </div>
    </div>
  )
}

/**
 * The concrete class of each distribution tone.
 *
 * The classes are written out because Tailwind scans the SOURCE for
 * literal class names: a `bg-${tone}` template would never be generated
 * and the bar would be invisible.
 */
const BAR_TONE_CLASS: Record<
  'primary' | 'secondary' | 'warning' | 'danger',
  string
> = {
  primary: 'bg-primary',
  secondary: 'bg-secondary',
  warning: 'bg-warning',
  danger: 'bg-danger',
}
