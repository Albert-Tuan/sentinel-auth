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
}

/**
 * A responsive data table.
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
}: DataTableProps<T>) {
  if (rows.length === 0 && empty) {
    return <>{empty}</>
  }

  return (
    <div
      className={cn(
        'overflow-x-auto rounded-md border border-slate-200 bg-white',
        className,
      )}
    >
      <table className="w-full min-w-full border-collapse text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className="whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)} className="hover:bg-slate-50">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn('px-3 py-2 text-slate-700', column.className)}
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
