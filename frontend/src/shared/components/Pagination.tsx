import { Button } from '@/shared/components/Button'

export interface PaginationProps {
  page: number
  limit: number
  total: number
  onPageChange: (page: number) => void
  /** How many items are shown per page. */
  pageSize?: number
  disabled?: boolean
}

/**
 * Page navigation for a server-paginated list.
 *
 * The backend owns the page size (`limit`), so this control only moves
 * between pages — it never changes the page size.
 */
export function Pagination({
  page,
  limit,
  total,
  onPageChange,
  pageSize,
  disabled = false,
}: PaginationProps) {
  const effectiveSize = pageSize ?? limit
  const lastPage = Math.max(1, Math.ceil(total / effectiveSize))
  const from = total === 0 ? 0 : (page - 1) * effectiveSize + 1
  const to = Math.min(total, page * effectiveSize)

  return (
    <nav
      aria-label="Phân trang"
      className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600"
    >
      <p>
        {total === 0
          ? 'Không có bản ghi'
          : `Hiển thị ${from}–${to} trên ${total} bản ghi`}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          Trước
        </Button>
        <span className="text-xs">
          Trang {page} / {lastPage}
        </span>
        <Button
          variant="secondary"
          disabled={disabled || page >= lastPage}
          onClick={() => onPageChange(page + 1)}
        >
          Sau
        </Button>
      </div>
    </nav>
  )
}
