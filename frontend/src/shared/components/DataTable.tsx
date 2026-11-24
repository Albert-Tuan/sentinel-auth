import type { ReactNode } from 'react'
import { cn } from '@/shared/utils/cn'

export interface TableColumn<T> {
  key: string
  header: ReactNode
  /** Cell renderer. Receives the row and the row index. */
  render: (row: T, index: number) => ReactNode
  /** Extra classes for the cell. */
  className?: string
}

export interface DataTableProps<T> {
  columns: TableColumn<T>[]
  rows: T[]
  /** Stable key for a row. */
  rowKey: (row: T, index: number) => string
  caption?: string
  /** Rendered when `rows` is empty. */
  empty?: ReactNode
  className?: string
  /**
   * Called when a row is clicked.
   *
   * When present the row becomes an interactive control: it is
   * focusable, exposes `role="button"` and reacts to Enter/Space, so the
   * table stays keyboard-navigable.
   */
  onRowClick?: (row: T) => void
}

/**
 * A dense data table.
 *
 * The design system calls for a 32px row height, alternating row shading
 * between the panel and the raised surface, and a 1px hairline baseline
 * between rows. Column headers are uppercase with wide tracking, and
 * technical values are tabular-aligned.
 *
 * On small screens the table scrolls horizontally rather than collapsing
 * into stacked cards — the columns are a fixed contract that the backend
 * defines, and a stacked layout would hide the column headers.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  empty,
  className,
  onRowClick,
}: DataTableProps<T>) {
  if (rows.length === 0 && empty) {
    return <>{empty}</>
  }

  return (
    <div
      className={cn(
        'overflow-x-auto border border-border bg-surface-raised',
        className,
      )}
    >
      <table className="w-full min-w-full border-collapse text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="bg-panel">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className="label-ops whitespace-nowrap border-b border-border px-3 py-2 text-text-muted"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={rowKey(row, index)}
              className={cn(
                'h-8 border-b border-border last:border-b-0',
                index % 2 === 1 ? 'bg-panel' : 'bg-surface-raised',
                onRowClick && 'cursor-pointer hover:bg-surface hover:border-l-2 hover:border-l-primary',
              )}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={
                onRowClick
                  ? (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onRowClick(row)
                      }
                    }
                  : undefined
              }
              tabIndex={onRowClick ? 0 : undefined}
              role={onRowClick ? 'button' : undefined}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    'px-3 py-1.5 align-middle text-text',
                    column.className,
                  )}
                >
                  {column.render(row, index)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
