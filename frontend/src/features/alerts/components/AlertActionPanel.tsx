/**
 * S-21 — Alert Action Bar (mutations).
 *
 * The panel that turns the read-only investigation screen into an
 * investigation WORKSPACE. It owns five backend contracts, each with a
 * distinct failure mode that the UI must not blur together:
 *
 *   1. **Acknowledge** — `POST /alerts/{id}/acknowledge`. Only valid while
 *      the alert is `open`. A second acknowledge answers 409.
 *   2. **Resolve** — `POST /alerts/{id}/resolve`. Requires one of the four
 *      canonical resolutions. Makes the alert IMMUTABLE: a later mutation
 *      answers 409.
 *   3. **Assign** — `POST /alerts/{id}/assign`. `assigned_to_id` is a
 *      `soc_analysts.id` UUID. The backend has no endpoint listing the
 *      analysts (gap G-1), so the field is validated client-side: an
 *      invalid UUID is never sent, because PostgreSQL would answer 500
 *      instead of a 400.
 *   4. **Protective action** — `POST /alerts/{id}/actions`. The action
 *      runs inside Core via the Detection Engine and can fail on its own:
 *      the backend answers **502** and the action was NOT applied. A 502
 *      is therefore rendered as an explicit failure, never as a success.
 *   5. **Note** — `POST /alerts/{id}/timeline` with `event_type:
 *      "note_added"` (gap G-9: there is no dedicated note route). The
 *      backend imposes no length limit, so the UI caps the comment at
 *      2000 characters.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { Button } from '@/shared/components/Button'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorState } from '@/shared/components/ErrorState'
import { Input } from '@/shared/components/Input'
import { UUID_FORMAT_MESSAGE, isUuid } from '@/shared/utils/uuid'

import {
  acknowledgeAlert,
  addTimelineEvent,
  assignAlert,
  resolveAlert,
  runAlertAction,
} from '@/lib/api/alertMutations.api'
import { toApiError } from '@/lib/errors'
import {
  AlertResolution,
  SecurityAction,
  type AlertItem,
  type AlertResolution as AlertResolutionValue,
  type SecurityAction as SecurityActionValue,
} from '@/types/api'

/** The maximum length of an analyst note. */
const MAX_NOTE_LENGTH = 2000

const RESOLUTION_LABEL: Record<AlertResolutionValue, string> = {
  true_attack: 'Đúng là tấn công',
  false_positive: 'Báo động giả',
  benign_true_positive: 'Cảnh báo hợp lệ nhưng không nguy hiểm',
  insufficient_evidence: 'Chưa đủ bằng chứng',
}

const ACTION_LABEL: Record<SecurityActionValue, string> = {
  REQUIRE_MFA: 'Yêu cầu MFA bắt buộc',
  REVOKE_SESSIONS: 'Thu hồi toàn bộ phiên',
  LOCK_USER: 'Khoá tài khoản',
  FORCE_LOGOUT: 'Buộc đăng xuất',
}

/**
 * A destructive action: it touches the USER, not just the alert.
 */
const DESTRUCTIVE_ACTIONS: SecurityActionValue[] = [
  SecurityAction.REVOKE_SESSIONS,
  SecurityAction.LOCK_USER,
  SecurityAction.FORCE_LOGOUT,
]

export interface AlertActionPanelProps {
  alert: AlertItem
}

export function AlertActionPanel({ alert }: AlertActionPanelProps) {
  const queryClient = useQueryClient()

  const [notes, setNotes] = useState('')
  const [resolution, setResolution] = useState<AlertResolutionValue>(
    AlertResolution.true_attack,
  )
  const [assignee, setAssignee] = useState('')
  const [action, setAction] = useState<SecurityActionValue>(
    SecurityAction.REQUIRE_MFA,
  )
  const [actionReason, setActionReason] = useState('')

  const [resolveOpen, setResolveOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)
  const [actionOpen, setActionOpen] = useState(false)

  const assigneeInvalid = assignee !== '' && !isUuid(assignee)

  /**
   * A resolved or false-positive alert is immutable. The backend answers
   * 409 for any further mutation, so the buttons are disabled instead of
   * letting the analyst fire a request that can only fail.
   */
  const isImmutable =
    alert.status === 'resolved' || alert.status === 'false_positive'
  const isOpen = alert.status === 'open'

  /** Refresh every alert query after a successful mutation. */
  function invalidateAlerts() {
    return queryClient.invalidateQueries({ queryKey: ['alerts'] })
  }

  const acknowledgeMutation = useMutation({
    mutationFn: () =>
      acknowledgeAlert(alert.id, notes.trim() ? { notes: notes.trim() } : {}),
    onSuccess: async () => {
      setNotes('')
      await invalidateAlerts()
    },
  })

  const resolveMutation = useMutation({
    mutationFn: () =>
      resolveAlert(alert.id, {
        resolution,
        notes: notes.trim() ? notes.trim() : null,
      }),
    onSuccess: async () => {
      setResolveOpen(false)
      setNotes('')
      await invalidateAlerts()
    },
  })

  const assignMutation = useMutation({
    mutationFn: () =>
      assignAlert(alert.id, {
        assigned_to_id: assignee.trim(),
        notes: notes.trim() ? notes.trim() : null,
      }),
    onSuccess: async () => {
      setAssignOpen(false)
      setAssignee('')
      await invalidateAlerts()
    },
  })

  const actionMutation = useMutation({
    mutationFn: () =>
      runAlertAction(alert.id, {
        action,
        reason: actionReason.trim() ? actionReason.trim() : null,
      }),
    onSuccess: async () => {
      setActionOpen(false)
      setActionReason('')
      await invalidateAlerts()
    },
  })

  const noteMutation = useMutation({
    mutationFn: () =>
      addTimelineEvent(alert.id, {
        event_type: 'note_added',
        comment: notes.trim(),
      }),
    onSuccess: async () => {
      setNotes('')
      await invalidateAlerts()
    },
  })

  const anyPending =
    acknowledgeMutation.isPending ||
    resolveMutation.isPending ||
    assignMutation.isPending ||
    actionMutation.isPending ||
    noteMutation.isPending

  function handleNoteSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!notes.trim()) return
    noteMutation.mutate()
  }

  return (
    <section
      aria-labelledby="alert-actions-heading"
      className="flex flex-col gap-4"
    >
      <h2 id="alert-actions-heading" className="heading-ops text-text">
        Hành động điều tra
      </h2>

      {isImmutable && (
        <div
          role="status"
          className="border border-l-4 border-border border-l-warning bg-surface-raised p-3 text-sm text-text-muted"
        >
          Cảnh báo này đã được xử lý và bị đóng băng. Mọi thao tác thay đổi
          tiếp theo sẽ bị từ chối.
        </div>
      )}

      <div className="border border-border bg-surface-raised p-4">
        <div className="flex flex-wrap items-end gap-3">
          <Button
            onClick={() => acknowledgeMutation.mutate()}
            loading={acknowledgeMutation.isPending}
            disabled={!isOpen || isImmutable || anyPending}
          >
            Xác nhận cảnh báo
          </Button>
          <Button
            variant="secondary"
            onClick={() => setResolveOpen(true)}
            disabled={isImmutable || anyPending}
          >
            Xử lý cảnh báo
          </Button>
          <Button
            variant="secondary"
            onClick={() => setAssignOpen(true)}
            disabled={isImmutable || anyPending}
          >
            Giao cho analyst
          </Button>
          <Button
            variant="danger"
            onClick={() => setActionOpen(true)}
            disabled={isImmutable || anyPending}
          >
            Hành động bảo vệ
          </Button>
        </div>

        {acknowledgeMutation.isError && (
          <div className="mt-3">
            <ErrorState
              title="Không thể xác nhận cảnh báo"
              message={toApiError(acknowledgeMutation.error).userMessage}
            />
          </div>
        )}
      </div>

      {/* --- Note ------------------------------------------------------- */}
      <form
        onSubmit={handleNoteSubmit}
        noValidate
        className="flex flex-col gap-3 border border-border bg-surface-raised p-4"
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="alert-note" className="label-ops text-text-muted">
            Ghi chú điều tra
          </label>
          <textarea
            id="alert-note"
            value={notes}
            maxLength={MAX_NOTE_LENGTH}
            rows={3}
            disabled={anyPending}
            onChange={(event) => setNotes(event.target.value)}
            className="border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none placeholder:text-degraded focus:border-primary disabled:text-degraded"
            placeholder="Ghi lại nhận xét của bạn về cảnh báo này…"
          />
          <p className="text-xs text-degraded">
            Ghi chú được ghi vào dòng thời gian của cảnh báo.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="submit"
            variant="secondary"
            loading={noteMutation.isPending}
            disabled={!notes.trim() || anyPending}
          >
            Thêm ghi chú
          </Button>
          <span className="telemetry text-xs text-degraded">
            {notes.length}/{MAX_NOTE_LENGTH}
          </span>
        </div>
        {noteMutation.isError && (
          <ErrorState
            title="Không thể thêm ghi chú"
            message={toApiError(noteMutation.error).userMessage}
          />
        )}
      </form>

      {/* --- Resolve ---------------------------------------------------- */}
      <ConfirmDialog
        open={resolveOpen}
        title="Xử lý cảnh báo?"
        message={
          <div className="flex flex-col gap-3">
            <p>
              Kết quả xử lý sẽ đóng băng cảnh báo: mọi thay đổi sau này sẽ bị
              từ chối.
            </p>
            <label
              htmlFor="alert-resolution"
              className="label-ops text-text-muted"
            >
              Kết quả xử lý
            </label>
            <select
              id="alert-resolution"
              value={resolution}
              onChange={(event) =>
                setResolution(event.target.value as AlertResolutionValue)
              }
              className="border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
            >
              {Object.values(AlertResolution).map((value) => (
                <option key={value} value={value}>
                  {RESOLUTION_LABEL[value]}
                </option>
              ))}
            </select>
            {notes.trim() && (
              <p className="text-xs text-text-muted">
                Ghi chú sẽ được lưu kèm: “{notes.trim()}”
              </p>
            )}
          </div>
        }
        confirmLabel="Xử lý"
        busy={resolveMutation.isPending}
        onCancel={() => setResolveOpen(false)}
        onConfirm={() => resolveMutation.mutate()}
      />

      {resolveMutation.isError && (
        <ErrorState
          title="Không thể xử lý cảnh báo"
          message={toApiError(resolveMutation.error).userMessage}
        />
      )}

      {/* --- Assign ----------------------------------------------------- */}
      <ConfirmDialog
        open={assignOpen}
        title="Giao cảnh báo cho analyst?"
        message={
          <div className="flex flex-col gap-3">
            <p>
              Nhập <code className="telemetry">soc_analysts.id</code> của analyst
              (không phải <code className="telemetry">users.id</code>).
            </p>
            <Input
              id="alert-assignee"
              label="UUID analyst"
              value={assignee}
              onChange={(event) => setAssignee(event.target.value.trim())}
              error={assigneeInvalid ? UUID_FORMAT_MESSAGE : undefined}
              placeholder="8f3c…"
            />
            <p className="text-xs text-degraded">
              Backend chưa có endpoint liệt kê analyst — sao chép UUID từ cơ
              sở dữ liệu hoặc từ lịch sử phân công.
            </p>
          </div>
        }
        confirmLabel="Giao"
        busy={assignMutation.isPending}
        confirmDisabled={assigneeInvalid || !assignee.trim()}
        onCancel={() => setAssignOpen(false)}
        onConfirm={() => {
          if (!assigneeInvalid && assignee.trim()) assignMutation.mutate()
        }}
      />

      {assignMutation.isError && (
        <ErrorState
          title="Không thể giao cảnh báo"
          message={toApiError(assignMutation.error).userMessage}
        />
      )}

      {/* --- Protective action ------------------------------------------ */}
      <ConfirmDialog
        open={actionOpen}
        title="Chạy hành động bảo vệ?"
        message={
          <div className="flex flex-col gap-3">
            <p>
              Hành động được thực thi bởi Detection Engine bên trong Core và
              có thể thất bại độc lập với cảnh báo. Khi thất bại, hành động
              sẽ <strong>không</strong> được áp dụng.
            </p>
            <label htmlFor="alert-action" className="label-ops text-text-muted">
              Hành động
            </label>
            <select
              id="alert-action"
              value={action}
              onChange={(event) =>
                setAction(event.target.value as SecurityActionValue)
              }
              className="border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary"
            >
              {Object.values(SecurityAction).map((value) => (
                <option key={value} value={value}>
                  {ACTION_LABEL[value]}
                </option>
              ))}
            </select>
            <Input
              id="alert-action-reason"
              label="Lý do (không bắt buộc)"
              value={actionReason}
              onChange={(event) => setActionReason(event.target.value)}
            />
          </div>
        }
        confirmLabel="Chạy hành động"
        destructive={DESTRUCTIVE_ACTIONS.includes(action)}
        busy={actionMutation.isPending}
        onCancel={() => setActionOpen(false)}
        onConfirm={() => actionMutation.mutate()}
      />

      {actionMutation.isError && (
        <ActionFailureNotice error={actionMutation.error} />
      )}
    </section>
  )
}

/**
 * The failure notice of a protective action.
 *
 * A 502 from this endpoint means the Detection Engine could not complete
 * the action INSIDE Core — so the action was NOT applied, even though the
 * alert itself may well have been updated. The notice says exactly that,
 * because telling the analyst "done" when the user was never locked out
 * would be worse than showing nothing at all.
 */
function ActionFailureNotice({ error }: { error: unknown }) {
  const apiError = toApiError(error)
  const notApplied = apiError.status === 502

  return (
    <div
      role="alert"
      className="border border-l-4 border-border border-l-danger bg-surface-raised p-4 text-sm text-text"
    >
      <p className="heading-ops text-danger">
        {notApplied ? 'HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG' : 'Không thể chạy hành động'}
      </p>
      <p className="mt-1 text-text-muted">{apiError.userMessage}</p>
      {notApplied && (
        <p className="mt-2 text-text-muted">
          Detection Engine không hoàn tất được hành động bên trong Core.
          Hành động <strong>chưa</strong> được áp dụng — hãy kiểm tra lại
          trạng thái phiên và tài khoản của người dùng trước khi thử lại.
        </p>
      )}
    </div>
  )
}
