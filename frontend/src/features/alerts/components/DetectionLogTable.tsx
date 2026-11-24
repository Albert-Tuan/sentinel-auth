import { Badge } from '@/shared/components/Badge'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { formatDateTime } from '@/lib/datetime'
import type { DetectionLogSummary } from '@/types/api'

export interface DetectionLogTableProps {
  logs: DetectionLogSummary[]
}

/**
 * The detection pipeline log of an alert.
 *
 * Every optional cell is shown as "no data" rather than as an empty
 * value: a stage that produced no score contributes `null`, which is not
 * the same as a contribution of zero.
 */
export function DetectionLogTable({ logs }: DetectionLogTableProps) {
  const columns: TableColumn<DetectionLogSummary>[] = [
    {
      key: 'stage',
      header: 'Giai đoạn',
      render: (log) => (
        <span className="flex flex-col">
          <span className="font-medium">{log.stage}</span>
          {log.stage_detail && (
            <span className="text-xs text-slate-500">{log.stage_detail}</span>
          )}
        </span>
      ),
    },
    {
      key: 'rule',
      header: 'Quy tắc',
      render: (log) =>
        log.rule_name ? (
          <span className="font-mono text-xs">{log.rule_name}</span>
        ) : (
          <span className="text-slate-400">—</span>
        ),
    },
    {
      key: 'triggered',
      header: 'Kích hoạt',
      render: (log) => {
        // `triggered` is null when the stage recorded no verdict at all.
        if (log.triggered === null || log.triggered === undefined) {
          return <span className="text-slate-400">—</span>
        }
        return log.triggered ? (
          <Badge tone="danger">Có</Badge>
        ) : (
          <Badge tone="neutral">Không</Badge>
        )
      },
    },
    {
      key: 'contribution',
      header: 'Đóng góp điểm',
      render: (log) =>
        log.score_contribution === null ||
        log.score_contribution === undefined ? (
          <span className="text-slate-400">—</span>
        ) : (
          log.score_contribution.toFixed(4)
        ),
    },
    {
      key: 'decision',
      header: 'Quyết định',
      render: (log) =>
        log.decision ? (
          <span className="font-mono text-xs">{log.decision}</span>
        ) : (
          <span className="text-slate-400">—</span>
        ),
    },
    {
      key: 'reason',
      header: 'Lý do',
      render: (log) =>
        log.reason ? (
          <span title={log.reason}>{log.reason}</span>
        ) : (
          <span className="text-slate-400">—</span>
        ),
    },
    {
      key: 'created',
      header: 'Thời điểm',
      render: (log) => formatDateTime(log.created_at),
    },
  ]

  if (logs.length === 0) {
    return (
      <EmptyState
        title="Không có log phát hiện"
        description="Detection Engine không ghi lại log cho cảnh báo này."
      />
    )
  }

  return (
    <DataTable
      columns={columns}
      rows={logs}
      rowKey={(log) => log.id}
      caption="Log của quy trình phát hiện"
    />
  )
}
