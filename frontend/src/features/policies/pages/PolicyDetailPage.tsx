/**
 * S-31 / S-32 — Policy Detail (`/policies/:policyId`) and Policy Editor.
 *
 * One screen carries both contracts, because the backend treats them as
 * one object: `GET /policies/{id}` returns the full policy, and the
 * editor writes that same object back with `PUT /policies/{id}`.
 *
 * The lifecycle rules the screen encodes:
 *
 *   - **A policy that has ever been active is FROZEN.** The backend
 *     answers 409 "Policy is immutable" for a currently-active policy
 *     AND for one that was activated in the past: their rules are
 *     referenced by the risk assessments they produced, so changing
 *     them would rewrite history. The editor is read-only in that state
 *     and says so.
 *
 *   - **`expected_updated_at` is mandatory on a save.** It is the
 *     optimistic-concurrency token: the client sends back the
 *     `updated_at` it last read, and the backend answers 409 when the
 *     policy changed in the meantime. The value is kept as the STRING
 *     the backend returned — a `Date` round-trip would lose microsecond
 *     precision and trigger spurious conflicts.
 *
 *   - **The server owns `is_active`, `created_by` and every timestamp.**
 *     The write payload never carries them; sending one is a 400 that
 *     names the offending field.
 *
 *   - **Activation is a separate, explicit step.** A policy is created
 *     INACTIVE, so a half-finished policy can never influence the
 *     scoring of a login. Activating it deactivates the current one in
 *     the same transaction — which is why activation asks for a
 *     confirmation.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorState } from '@/shared/components/ErrorState'
import { Spinner } from '@/shared/components/Spinner'

import {
  activatePolicy,
  fetchPolicy,
} from '@/lib/api/policies.api'
import { PATHS } from '@/app/router/paths'
import { formatDateTime } from '@/lib/datetime'
import { errorMessage, toApiError } from '@/lib/errors'
import type { PolicyDetail } from '@/types/api'

import { PolicyEditor } from '@/features/policies/components/PolicyEditor'

export function PolicyDetailPage() {
  const { policyId = '' } = useParams<{ policyId: string }>()
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const policyQuery = useQuery({
    queryKey: ['policies', policyId],
    queryFn: () => fetchPolicy(policyId),
    enabled: Boolean(policyId),
  })

  const [activateOpen, setActivateOpen] = useState(false)

  const activateMutation = useMutation({
    mutationFn: () => activatePolicy(policyId),
    onSuccess: async () => {
      setActivateOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['policies'] })
    },
  })

  if (policyQuery.isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-muted">
        <Spinner /> Đang tải chính sách…
      </div>
    )
  }

  if (policyQuery.isError) {
    return (
      <ErrorState
        title="Không thể tải chính sách"
        message={errorMessage(policyQuery.error)}
        action={
          <Button variant="secondary" onClick={() => void policyQuery.refetch()}>
            Thử lại
          </Button>
        }
      />
    )
  }

  const policy = policyQuery.data
  const frozen = policy.is_active || policy.activated_at !== null
  const wantsEdit = searchParams.get('edit') === '1'

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="page-title text-text">
            {policy.name ?? 'Chính sách chưa đặt tên'}
          </h1>
          <Badge tone="info">{policy.version}</Badge>
          {policy.is_active ? (
            <Badge tone="success">ĐANG ÁP DỤNG</Badge>
          ) : frozen ? (
            <Badge tone="warning">ĐÃ ĐÓNG BĂNG</Badge>
          ) : (
            <Badge tone="neutral">BẢN NHÁP</Badge>
          )}
        </div>
        <nav aria-label="Đường dẫn" className="telemetry text-xs text-text-muted">
          <Link to={PATHS.policies} className="hover:text-primary">
            CHÍNH SÁCH
          </Link>
          <span className="px-2 text-degraded">/</span>
          <span className="text-text">{policy.id.slice(0, 8).toUpperCase()}</span>
        </nav>
        {policy.description && (
          <p className="text-sm text-text-muted">{policy.description}</p>
        )}
      </header>

      <PolicyMeta policy={policy} />

      {frozen && (
        <div
          role="status"
          className="border border-l-4 border-border border-l-warning bg-surface-raised p-3 text-sm text-text-muted"
        >
          {policy.is_active
            ? 'Chính sách này đang áp dụng trong luồng xác thực nên bị đóng băng. Hãy tạo một phiên bản mới để thay đổi cấu hình.'
            : 'Chính sách này đã từng được kích hoạt nên bị đóng băng: các đánh giá rủi ro lịch sử vẫn tham chiếu tới nó. Hãy tạo một phiên bản mới để thay đổi cấu hình.'}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 border border-border bg-surface-raised p-4">
        {!policy.is_active && (
          <Button onClick={() => setActivateOpen(true)}>
            Kích hoạt chính sách
          </Button>
        )}
        <Link to={PATHS.policies}>
          <Button variant="secondary">Về danh sách</Button>
        </Link>
      </div>

      {activateMutation.isError && (
        <ErrorState
          title="Không thể kích hoạt chính sách"
          message={toApiError(activateMutation.error).userMessage}
        />
      )}

      <ConfirmDialog
        open={activateOpen}
        title="Kích hoạt chính sách?"
        message={
          <div className="flex flex-col gap-2">
            <p>
              Chỉ một chính sách có thể được kích hoạt tại một thời điểm. Chính
              sách đang áp dụng sẽ bị tự động vô hiệu hoạt.
            </p>
            <p className="text-xs text-degraded">
              Phiên bản {policy.version} sẽ bắt đầu được áp dụng cho các lần
              đăng nhập mới. Các đánh giá rủi ro đã có vẫn giữ nguyên.
            </p>
          </div>
        }
        confirmLabel="Kích hoạt"
        busy={activateMutation.isPending}
        onCancel={() => setActivateOpen(false)}
        onConfirm={() => activateMutation.mutate()}
      />

      <PolicyEditor
        key={policy.id}
        policy={policy}
        readOnly={frozen && !wantsEdit}
      />
    </div>
  )
}

/**
 * The telemetry grid of the policy.
 *
 * Every timestamp is rendered from the raw string, so the value on screen
 * is exactly the value the backend holds.
 */
function PolicyMeta({ policy }: { policy: PolicyDetail }) {
  const rows: Array<[string, string]> = [
    ['ID', policy.id],
    ['PHIÊN BẢN', policy.version],
    ['SỐ QUY TẮC', String(policy.rules.length)],
    ['TẠO BỞI', policy.created_by ?? '—'],
    ['TẠO LÚC', formatDateTime(policy.created_at)],
    ['CẬP NHẬT LÚC', formatDateTime(policy.updated_at)],
    ['KÍCH HOẠT LÚC', policy.activated_at ? formatDateTime(policy.activated_at) : '—'],
    ['VÔ HIỆU HOÁ LÚC', policy.deactivated_at ? formatDateTime(policy.deactivated_at) : '—'],
  ]

  return (
    <dl className="grid grid-cols-2 gap-px border border-border bg-border md:grid-cols-4">
      {rows.map(([label, value]) => (
        <div key={label} className="flex flex-col gap-1 bg-surface-raised p-3">
          <dt className="label-ops text-degraded">{label}</dt>
          <dd className="telemetry break-all text-xs text-text">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

