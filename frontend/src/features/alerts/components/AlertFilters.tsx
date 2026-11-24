import { Button } from '@/shared/components/Button'
import { Input } from '@/shared/components/Input'
import { ALERT_STATUSES } from '@/shared/components/alertStatuses'
import { RISK_LEVELS } from '@/shared/components/riskLevels'
import {
  UUID_FORMAT_MESSAGE,
  isUuid,
} from '@/shared/utils/uuid'

/**
 * The filter state of the alert queue.
 *
 * Every value is a string because it comes straight from the URL query
 * parameters — the URL is the single source of truth, so a deep link and
 * a typed filter produce exactly the same request.
 */
export interface AlertFiltersValue {
  status: string
  risk_level: string
  assigned_to_id: string
}

export interface AlertFiltersProps {
  value: AlertFiltersValue
  onChange: (next: AlertFiltersValue) => void
  /** Called when the user asks to clear every filter. */
  onReset: () => void
}

const STATUS_LABEL: Record<string, string> = {
  open: 'Mở',
  acknowledged: 'Đã xác nhận',
  resolved: 'Đã xử lý',
  false_positive: 'Báo động giả',
}

const RISK_LABEL: Record<string, string> = {
  low: 'Thấp',
  medium: 'Trung bình',
  high: 'Cao',
  critical: 'Nghiêm trọng',
}

/**
 * The filter bar of the alert queue.
 *
 * The dropdowns offer ONLY the values the backend accepts. An unknown
 * value is not offered, because the backend answers it with a 400 — the
 * queue must never be able to produce a request it knows will fail.
 *
 * The `assigned_to_id` field is a free-text UUID because the backend has
 * no endpoint listing the SOC analysts (documented gap G-1). It is the
 * one filter that CAN be typed wrong, so the format is checked here: a
 * non-UUID would reach the PostgreSQL UUID column as an invalid cast and
 * the backend would answer 500 instead of an empty page. The invalid
 * value is therefore never sent, and the field says why.
 */
export function AlertFilters({
  value,
  onChange,
  onReset,
}: AlertFiltersProps) {
  const hasFilters =
    value.status !== '' ||
    value.risk_level !== '' ||
    value.assigned_to_id !== ''

  const assigneeInvalid =
    value.assigned_to_id !== '' && !isUuid(value.assigned_to_id)

  return (
    <div
      className="flex flex-wrap items-end gap-3 rounded-md border border-slate-200 bg-white p-4"
      role="search"
      aria-label="Bộ lọc danh sách cảnh báo"
    >
      <div className="w-48">
        <label
          htmlFor="alert-filter-status"
          className="text-sm font-medium text-slate-700"
        >
          Trạng thái
        </label>
        <select
          id="alert-filter-status"
          className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-100"
          value={value.status}
          onChange={(event) =>
            onChange({ ...value, status: event.target.value })
          }
        >
          <option value="">Tất cả</option>
          {ALERT_STATUSES.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABEL[status] ?? status}
            </option>
          ))}
        </select>
      </div>

      <div className="w-48">
        <label
          htmlFor="alert-filter-risk"
          className="text-sm font-medium text-slate-700"
        >
          Mức rủi ro
        </label>
        <select
          id="alert-filter-risk"
          className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-100"
          value={value.risk_level}
          onChange={(event) =>
            onChange({ ...value, risk_level: event.target.value })
          }
        >
          <option value="">Tất cả</option>
          {RISK_LEVELS.map((level) => (
            <option key={level} value={level}>
              {RISK_LABEL[level] ?? level}
            </option>
          ))}
        </select>
      </div>

      <div className="min-w-64 flex-1">
        <Input
          id="alert-filter-assignee"
          label="Người được giao (UUID)"
          placeholder="soc_analysts.id — ví dụ: 8f3c…"
          value={value.assigned_to_id}
          error={assigneeInvalid ? UUID_FORMAT_MESSAGE : undefined}
          onChange={(event) =>
            onChange({ ...value, assigned_to_id: event.target.value.trim() })
          }
        />
      </div>

      <Button variant="secondary" onClick={onReset} disabled={!hasFilters}>
        Xóa bộ lọc
      </Button>
    </div>
  )
}
