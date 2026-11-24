/**
 * S-20 — Alert Queue (`/alerts`).
 *
 * The queue is a READ-ONLY view of `GET /api/v1/alerts`. Stage 5 owns the
 * mutations (acknowledge / resolve / assign / actions); this screen never
 * writes anything.
 *
 * Three rules shape the implementation:
 *
 *  1. **The URL is the state.** The filters and the page number live in
 *     the query string, so a deep link reproduces exactly the same
 *     request, and a refresh keeps the analyst where they were.
 *  2. **The backend owns the order.** The rows are rendered exactly as
 *     they came back — the backend sorts newest first, and the client
 *     never re-sorts.
 *  3. **The backend owns the vocabulary.** The filter dropdowns offer
 *     only the statuses and risk levels the backend accepts, so the queue
 *     cannot produce a request that is known to fail with a 400.
 */

import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import { Button } from '@/shared/components/Button'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Pagination } from '@/shared/components/Pagination'
import { Spinner } from '@/shared/components/Spinner'

import {
  AlertFilters,
  type AlertFiltersValue,
} from '@/features/alerts/components/AlertFilters'
import {
  AlertTable,
  type AlertSubject,
} from '@/features/alerts/components/AlertTable'
import { fetchAlerts } from '@/lib/api/alerts.api'
import { fetchLoginAttemptSubjects } from '@/lib/api/loginAttempts.api'
import { errorMessage } from '@/lib/errors'
import { isUuid } from '@/shared/utils/uuid'

/** The page size the backend uses by default. */
const DEFAULT_LIMIT = 20
/** The largest page size the backend accepts. */
const MAX_LIMIT = 100

/** The query keys the alert queue understands. */
const PARAM_STATUS = 'status'
const PARAM_RISK = 'risk_level'
const PARAM_ASSIGNEE = 'assigned_to_id'
const PARAM_PAGE = 'page'
const PARAM_LIMIT = 'limit'

/**
 * Read a positive integer from the URL.
 *
 * A malformed value (0, -1, "abc") falls back to the default instead of
 * being forwarded to the backend, where it would produce a 422.
 */
function readPositiveInt(
  raw: string | null,
  fallback: number,
  max?: number,
): number {
  if (raw === null || raw === '') return fallback
  const parsed = Number(raw)
  if (!Number.isInteger(parsed) || parsed < 1) return fallback
  if (max !== undefined && parsed > max) return fallback
  return parsed
}

export function AlertQueuePage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const status = searchParams.get(PARAM_STATUS) ?? ''
  const riskLevel = searchParams.get(PARAM_RISK) ?? ''
  const assignee = searchParams.get(PARAM_ASSIGNEE) ?? ''
  const page = readPositiveInt(searchParams.get(PARAM_PAGE), 1)
  const limit = readPositiveInt(
    searchParams.get(PARAM_LIMIT),
    DEFAULT_LIMIT,
    MAX_LIMIT,
  )

  const filters = useMemo<AlertFiltersValue>(
    () => ({
      status,
      risk_level: riskLevel,
      assigned_to_id: assignee,
    }),
    [status, riskLevel, assignee],
  )

  /**
   * The assignee id that is actually sent to the backend.
   *
   * A value that is not a UUID cannot be matched: the column is a real
   * UUID column, so an invalid cast would make the endpoint answer 500.
   * The queue therefore sends the filter ONLY when it is well-formed —
   * exactly like it only offers the statuses and risk levels the backend
   * accepts. An incomplete UUID (the analyst is still typing) is simply
   * not a filter yet.
   */
  const assigneeParam = useMemo(
    () => (isUuid(assignee) ? assignee : ''),
    [assignee],
  )

  /**
   * Write the filter state into the URL.
   *
   * Changing a filter always returns to page 1 — the analyst is looking
   * at a different result set, so the old page number no longer applies.
   */
  const updateFilters = useCallback(
    (next: AlertFiltersValue) => {
      const params = new URLSearchParams()
      if (next.status) params.set(PARAM_STATUS, next.status)
      if (next.risk_level) params.set(PARAM_RISK, next.risk_level)
      if (next.assigned_to_id)
        params.set(PARAM_ASSIGNEE, next.assigned_to_id)
      params.set(PARAM_LIMIT, String(limit))
      params.set(PARAM_PAGE, '1')
      setSearchParams(params, { replace: true })
    },
    [limit, setSearchParams],
  )

  const resetFilters = useCallback(() => {
    const params = new URLSearchParams()
    params.set(PARAM_LIMIT, String(limit))
    params.set(PARAM_PAGE, '1')
    setSearchParams(params, { replace: true })
  }, [limit, setSearchParams])

  const goToPage = useCallback(
    (nextPage: number) => {
      const params = new URLSearchParams(searchParams)
      params.set(PARAM_PAGE, String(nextPage))
      params.set(PARAM_LIMIT, String(limit))
      setSearchParams(params, { replace: true })
    },
    [searchParams, limit, setSearchParams],
  )

  const alertsQuery = useQuery({
    queryKey: ['alerts', 'list', filters, page, limit],
    queryFn: () =>
      fetchAlerts({
        status: filters.status || undefined,
        risk_level: filters.risk_level || undefined,
        assigned_to_id: assigneeParam || undefined,
        page,
        limit,
      }),
  })

  const alerts = useMemo(
    () => alertsQuery.data?.alerts ?? [],
    [alertsQuery.data],
  )
  const total = alertsQuery.data?.total ?? 0

  /**
   * The subject (username, IP) of each alert.
   *
   * `GET /alerts` does not return them — they live on the login attempt.
   * The lookup is a SECONDARY read: when it fails, the queue still
   * renders every row, only the subject columns stay empty. A failed
   * enrichment must never hide the alerts themselves.
   */
  const loginAttemptIds = useMemo(
    () => alerts.map((alert) => alert.login_attempt_id),
    [alerts],
  )

  const subjectsQuery = useQuery({
    queryKey: ['alerts', 'subjects', loginAttemptIds],
    queryFn: () => fetchLoginAttemptSubjects(loginAttemptIds),
    enabled: loginAttemptIds.length > 0,
    // The subject data is a nice-to-have: it must never keep the queue
    // from being displayed.
    retry: false,
  })

  const subjects = subjectsQuery.data ?? {}

  const hasFilters =
    filters.status !== '' ||
    filters.risk_level !== '' ||
    filters.assigned_to_id !== ''

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold text-text">Hàng đợi cảnh báo</h1>
        <p className="text-sm text-text-muted">
          Cảnh báo an ninh do Detection Engine tạo ra, mới nhất trước. Chọn
          một cảnh báo để mở chi tiết điều tra.
        </p>
      </header>

      <AlertFilters
        value={filters}
        onChange={updateFilters}
        onReset={resetFilters}
      />

      {alertsQuery.isPending && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Spinner /> Đang tải danh sách cảnh báo…
        </div>
      )}

      {alertsQuery.isError && (
        <ErrorState
          title="Không thể tải danh sách cảnh báo"
          message={errorMessage(alertsQuery.error)}
          action={
            <Button
              variant="secondary"
              onClick={() => void alertsQuery.refetch()}
            >
              Thử lại
            </Button>
          }
        />
      )}

      {alertsQuery.isSuccess && (
        <>
          {alerts.length === 0 ? (
            <EmptyState
              title="Không có cảnh báo nào"
              description={
                hasFilters
                  ? 'Không có cảnh báo nào khớp với bộ lọc hiện tại.'
                  : 'Chưa có cảnh báo nào trong hệ thống.'
              }
              action={
                hasFilters ? (
                  <Button variant="secondary" onClick={resetFilters}>
                    Xóa bộ lọc
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <AlertTable alerts={alerts} subjects={subjects} />
          )}

          <Pagination
            page={page}
            limit={limit}
            total={total}
            onPageChange={goToPage}
            disabled={alertsQuery.isFetching}
          />
        </>
      )}
    </div>
  )
}

export type { AlertSubject }
