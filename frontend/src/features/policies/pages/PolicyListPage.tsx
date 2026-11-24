/**
 * S-30 — Detection Policies (`/policies`).
 *
 * The policy registry. It reads `GET /policies`, which returns a SUMMARY
 * per policy: `id`, `version`, `name`, `description`, `rule_count`,
 * `is_active`, `created_at` and `activated_at`.
 *
 * Two things the screen deliberately does NOT do:
 *
 *   - It does not filter on the server. The listing endpoint takes no
 *     query parameters, so the search and the status filter are applied
 *     on the data the client already holds. The count in the header is
 *     the number of rows the API returned, not the number of matches.
 *
 *   - It does not read the rules. The summary carries `rule_count` only;
 *     the rules themselves live behind the detail endpoint, which is
 *     where the editor loads them from.
 *
 * The lifecycle rules the screen encodes:
 *
 *   - A policy that is CURRENTLY ACTIVE cannot be edited. The backend
 *     answers 409 "Policy is immutable" — the rules are referenced by the
 *     risk assessments they produced, so changing them would rewrite
 *     history. The editor is therefore not offered.
 *
 *   - A policy that was activated IN THE PAST is frozen too, for the
 *     same reason. The summary carries `activated_at`, so the screen can
 *     tell "never active" from "active once".
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Input } from '@/shared/components/Input'
import { Spinner } from '@/shared/components/Spinner'

import { fetchPolicies } from '@/lib/api/policies.api'
import { policyDetailPath } from '@/app/router/paths'
import { formatDateTime } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import type { PolicySummary } from '@/types/api'

/** The lifecycle state a policy is in, derived from the summary. */
type PolicyLifecycle = 'active' | 'frozen' | 'draft'

/**
 * Classify a policy.
 *
 * `is_active` → currently in service.
 * `activated_at` set but `is_active` false → it was in service and has
 *   been replaced; its rules still back historical assessments, so it
 *   is frozen.
 * neither → a draft that was never in service; the only editable state.
 */
function lifecycleOf(policy: PolicySummary): PolicyLifecycle {
  if (policy.is_active) return 'active'
  if (policy.activated_at) return 'frozen'
  return 'draft'
}

const LIFECYCLE_BADGE: Record<
  PolicyLifecycle,
  { tone: 'success' | 'warning' | 'neutral'; label: string }
> = {
  active: { tone: 'success', label: 'ĐANG ÁP DỤNG' },
  frozen: { tone: 'warning', label: 'ĐÃ ĐÓNG BĂNG' },
  draft: { tone: 'neutral', label: 'BẢN NHÁP' },
}

export function PolicyListPage() {
  const [search, setSearch] = useState('')
  const [lifecycle, setLifecycle] = useState<'all' | PolicyLifecycle>('all')

  const policiesQuery = useQuery({
    queryKey: ['policies'],
    queryFn: fetchPolicies,
  })

  const policies = useMemo(() => policiesQuery.data ?? [], [policiesQuery.data])

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return policies.filter((policy) => {
      if (lifecycle !== 'all' && lifecycleOf(policy) !== lifecycle) {
        return false
      }
      if (!needle) return true
      return (
        (policy.name ?? '').toLowerCase().includes(needle) ||
        policy.version.toLowerCase().includes(needle) ||
        policy.id.toLowerCase().includes(needle)
      )
    })
  }, [policies, search, lifecycle])

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="page-title text-text">Chính sách phát hiện</h1>
          <Badge tone="info">{policies.length} PHIÊN BẢN</Badge>
        </div>
        <p className="text-sm text-text-muted">
          Cấu hình quy tắc heuristic và vector máy học áp dụng trực tiếp
          trong luồng xác thực zero-trust.
        </p>
      </header>

      <form
        onSubmit={(event) => event.preventDefault()}
        role="search"
        aria-label="Bộ lọc chính sách"
        className="flex flex-wrap items-end gap-3 border border-border bg-surface-raised p-4"
      >
        <div className="min-w-56 flex-1">
          <Input
            id="policy-search"
            label="Tên / phiên bản / ID"
            value={search}
            placeholder="Ví dụ: v1.2 hoặc POL-SEC"
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label
            htmlFor="policy-lifecycle"
            className="label-ops text-text-muted"
          >
            Trạng thái
          </label>
          <select
            id="policy-lifecycle"
            value={lifecycle}
            onChange={(event) =>
              setLifecycle(event.target.value as 'all' | PolicyLifecycle)
            }
            className="telemetry border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="active">Đang áp dụng (ACTIVE)</option>
            <option value="frozen">Đã đóng băng (FROZEN)</option>
            <option value="draft">Bản nháp (DRAFT)</option>
          </select>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={!search && lifecycle === 'all'}
          onClick={() => {
            setSearch('')
            setLifecycle('all')
          }}
        >
          Đặt lại
        </Button>
      </form>

      {policiesQuery.isPending && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Spinner /> Đang tải chính sách…
        </div>
      )}

      {policiesQuery.isError && (
        <ErrorState
          title="Không thể tải danh sách chính sách"
          message={errorMessage(policiesQuery.error)}
          action={
            <Button variant="secondary" onClick={() => void policiesQuery.refetch()}>
              Thử lại
            </Button>
          }
        />
      )}

      {policiesQuery.isSuccess && visible.length === 0 && (
        <EmptyState
          title="Không có chính sách phù hợp"
          description={
            policies.length === 0
              ? 'Chưa có chính sách phát hiện nào trong hệ thống.'
              : 'Không có chính sách nào khớp với bộ lọc hiện tại.'
          }
        />
      )}

      {policiesQuery.isSuccess && visible.length > 0 && (
        <div className="flex flex-col gap-3">
          {visible.map((policy) => (
            <PolicyCard key={policy.id} policy={policy} />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * One policy, as a high-density telemetry card.
 *
 * The card is the unit of the screen: the version, the lifecycle badge,
 * the rule count and the activation timestamp, plus the two actions the
 * lifecycle allows.
 */
function PolicyCard({ policy }: { policy: PolicySummary }) {
  const lifecycle = lifecycleOf(policy)
  const badge = LIFECYCLE_BADGE[lifecycle]
  const editable = lifecycle === 'draft'
  const detailPath = policyDetailPath(policy.id)

  return (
    <article
      className={`border bg-surface-raised p-4 ${
        lifecycle === 'active' ? 'border-primary/60' : 'border-border'
      }`}
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 flex-col items-center justify-center border border-border bg-surface-sunken">
            <span className="telemetry text-sm font-bold text-text">
              {policy.version}
            </span>
            <span className="label-ops text-[9px] text-degraded">REV</span>
          </div>

          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="heading-ops text-text">
                {policy.name ?? 'Chính sách chưa đặt tên'}
              </h2>
              <span className="telemetry border border-border bg-surface-sunken px-2 py-0.5 text-xs text-secondary">
                ID: {policy.id.slice(0, 8).toUpperCase()}
              </span>
              <Badge tone={badge.tone}>{badge.label}</Badge>
            </div>

            {policy.description && (
              <p className="text-sm text-text-muted">{policy.description}</p>
            )}

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="telemetry border border-border bg-surface-sunken px-2 py-0.5 text-xs text-text">
                {policy.rule_count} QUY TẮC
              </span>
              <span className="telemetry border border-border bg-surface-sunken px-2 py-0.5 text-xs text-text-muted">
                TẠO: {formatDateTime(policy.created_at)}
              </span>
              {policy.activated_at && (
                <span className="telemetry border border-border bg-surface-sunken px-2 py-0.5 text-xs text-text-muted">
                  KÍCH HOẠT: {formatDateTime(policy.activated_at)}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border pt-3 lg:border-t-0 lg:pt-0">
          <Link to={detailPath}>
            <Button variant="secondary">Chi tiết</Button>
          </Link>
          {editable ? (
            <Link to={`${detailPath}?edit=1`}>
              <Button>Chỉnh sửa</Button>
            </Link>
          ) : (
            <Button
              variant="secondary"
              disabled
              title="Chính sách đã từng được kích hoạt nên bị đóng băng — hãy tạo phiên bản mới."
            >
              Đã đóng băng
            </Button>
          )}
        </div>
      </div>
    </article>
  )
}
