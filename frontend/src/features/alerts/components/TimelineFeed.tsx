import { Badge, type BadgeTone } from '@/shared/components/Badge'
import { EmptyState } from '@/shared/components/EmptyState'
import { formatDateTime } from '@/lib/datetime'
import type { TimelineEvent } from '@/types/api'

export interface TimelineFeedProps {
  events: TimelineEvent[]
}

/**
 * The event types the backend records, with their labels and tones.
 *
 * Mirrors `app/alerts.py::TIMELINE_EVENT_TYPES`. An event type outside
 * this list is rendered verbatim instead of being forced into a known
 * category.
 */
const EVENT_LABEL: Record<string, string> = {
  created: 'Được tạo',
  assigned: 'Được giao',
  unassigned: 'Bị gỡ giao',
  acknowledged: 'Đã xác nhận',
  escalated: 'Đã leo thang',
  note_added: 'Đã thêm ghi chú',
  status_changed: 'Đổi trạng thái',
  resolved: 'Đã xử lý',
  false_positive: 'Báo động giả',
}

const EVENT_TONE: Record<string, BadgeTone> = {
  created: 'info',
  assigned: 'info',
  unassigned: 'neutral',
  acknowledged: 'warning',
  escalated: 'danger',
  note_added: 'neutral',
  status_changed: 'warning',
  resolved: 'success',
  false_positive: 'neutral',
}

/**
 * The audit trail of one alert.
 *
 * The feed is read-only in Stage 4: adding a note is a Stage 5 mutation.
 */
export function TimelineFeed({ events }: TimelineFeedProps) {
  if (events.length === 0) {
    return (
      <EmptyState
        title="Chưa có sự kiện nào"
        description="Dòng thời gian của cảnh báo này còn trống."
      />
    )
  }

  return (
    <ol
      className="flex flex-col gap-3"
      aria-label="Dòng thời gian cảnh báo"
    >
      {events.map((event) => {
        const tone = EVENT_TONE[event.event_type] ?? 'neutral'
        const label = EVENT_LABEL[event.event_type] ?? event.event_type

        return (
          <li
            key={event.id}
            className="rounded-md border border-border bg-surface-raised p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={tone}>{label}</Badge>
              <span className="text-xs text-text-muted">
                {formatDateTime(event.created_at)}
              </span>
              <span className="text-xs text-degraded">
                {event.actor_type || 'user'}
                {event.actor_id ? ` · ${event.actor_id}` : ''}
              </span>
            </div>

            {(event.old_value !== null || event.new_value !== null) && (
              <p className="mt-2 text-sm text-text">
                {event.old_value !== null && (
                  <span className="text-text-muted line-through">
                    {event.old_value}
                  </span>
                )}
                {event.old_value !== null && event.new_value !== null && (
                  <span className="mx-1 text-degraded">→</span>
                )}
                {event.new_value !== null && (
                  <span className="font-medium">{event.new_value}</span>
                )}
              </p>
            )}

            {event.comment && (
              <p className="mt-2 whitespace-pre-wrap text-sm text-text-muted">
                {event.comment}
              </p>
            )}

            {event.ip_address && (
              <p className="mt-1 text-xs text-degraded">
                IP: {event.ip_address}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
