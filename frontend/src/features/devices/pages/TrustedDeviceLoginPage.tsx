/**
 * S-04 — Trusted-device Login (`/trusted-device`).
 *
 * This is an ALTERNATIVE login flow, not the main one:
 *
 *   1. `POST /devices/pending` — the new device proves the password and
 *      gets back a `request_id` (202 Accepted).
 *   2. The user approves the request on an already signed-in device
 *      (`POST /devices/pending/{id}/approve`).
 *   3. The new device polls `POST /devices/pending/{id}/complete` until it
 *      returns real tokens.
 *
 * The poll distinguishes three outcomes:
 *   - 200 → tokens issued, the user is signed in.
 *   - 409 `still pending` → keep polling.
 *   - 409 `Detection requires MFA` / `MFA is required` → the risk gate or
 *     an admin MFA requirement wins; the user must use the normal flow.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/shared/components/Button'
import { ErrorState } from '@/shared/components/ErrorState'
import { Input } from '@/shared/components/Input'
import { Spinner } from '@/shared/components/Spinner'

import {
  completeTrustedDeviceLogin,
  requestTrustedDeviceApproval,
} from '@/lib/api/devices.api'
import { ApiError, errorMessage, toApiError } from '@/lib/errors'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { PATHS } from '@/app/router/paths'

/** How often the pending approval is polled, in milliseconds. */
const POLL_INTERVAL_MS = 3000

type Phase =
  | { kind: 'form' }
  | { kind: 'pending'; requestId: string; expiresAt: string }
  | { kind: 'done' }
  | { kind: 'failed'; message: string }

export function TrustedDeviceLoginPage() {
  const auth = useAuthContext()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [deviceName, setDeviceName] = useState('')
  const [phase, setPhase] = useState<Phase>({ kind: 'form' })
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelledRef = useRef(false)

  useEffect(() => {
    return () => {
      cancelledRef.current = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  /**
   * Try to exchange the approved request for real tokens.
   *
   * A 409 that says the approval is still pending is the normal case and
   * schedules the next poll. Every other failure stops the flow.
   */
  const pollComplete = useCallback(
    async (requestId: string) => {
      try {
        const response = await completeTrustedDeviceLogin(requestId)
        if (cancelledRef.current) return

        if (!response.access_token || !response.refresh_token) {
          setPhase({
            kind: 'failed',
            message: 'Máy chủ đã phản hồi nhưng không cấp token hợp lệ.',
          })
          return
        }

        setPhase({ kind: 'done' })
        const established = await auth.loginWithTokens(
          response.access_token,
          response.refresh_token,
          response.session_id,
        )
        if (cancelledRef.current) return
        if (!established) {
          // The tokens were rejected by `GET /auth/me`, or the session was
          // superseded while the request was in flight. Navigating now would
          // land the user on an authenticated-looking page with no usable
          // session.
          setPhase({
            kind: 'failed',
            message:
              'Không thể xác nhận phiên đăng nhập từ máy chủ. Vui lòng thử lại.',
          })
          return
        }
        navigate(auth.landingPath, { replace: true })
      } catch (caught) {
        if (cancelledRef.current) return

        const apiError = toApiError(caught)
        const detail =
          apiError instanceof ApiError ? (apiError.detail ?? '') : ''

        const stillPending =
          apiError.status === 409 && /still pending/i.test(detail)

        if (stillPending) {
          timerRef.current = setTimeout(() => {
            void pollComplete(requestId)
          }, POLL_INTERVAL_MS)
          return
        }

        if (apiError.status === 409) {
          setPhase({
            kind: 'failed',
            message:
              'Hệ thống phát hiện rủi ro hoặc yêu cầu xác thực hai yếu tố. Vui lòng dùng luồng đăng nhập thường.',
          })
          return
        }

        if (apiError.status === 403) {
          setPhase({
            kind: 'failed',
            message: 'Yêu cầu bị từ chối: thiết bị hoặc địa chỉ IP không khớp.',
          })
          return
        }

        if (apiError.status === 410) {
          setPhase({
            kind: 'failed',
            message: 'Yêu cầu phê duyệt đã hết hạn. Vui lòng thử lại.',
          })
          return
        }

        setPhase({ kind: 'failed', message: errorMessage(apiError) })
      }
    },
    [auth, navigate],
  )

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const response = await requestTrustedDeviceApproval({
        username,
        password,
        device_name: deviceName.trim() || null,
      })

      if (response.status === 'already_trusted') {
        setPhase({
          kind: 'failed',
          message: 'Thiết bị này đã được tin cậy. Vui lòng dùng luồng đăng nhập thường.',
        })
        return
      }

      setPhase({
        kind: 'pending',
        requestId: response.request_id,
        expiresAt: response.expires_at,
      })
      timerRef.current = setTimeout(() => {
        void pollComplete(response.request_id)
      }, POLL_INTERVAL_MS)
    } catch (caught) {
      const apiError = toApiError(caught)
      if (apiError.status === 401) {
        setError('Tên đăng nhập hoặc mật khẩu không đúng.')
      } else if (apiError.status === 409) {
        setError(
          'Tài khoản này yêu cầu xác thực hai yếu tố. Vui lòng dùng luồng đăng nhập thường.',
        )
      } else if (apiError.status === 423) {
        setError('Tài khoản đang bị khoá.')
      } else if (apiError.status === 429) {
        setError('Quá nhiều yêu cầu phê duyệt. Vui lòng thử lại sau.')
      } else {
        setError(errorMessage(apiError))
      }
    } finally {
      setSubmitting(false)
    }
  }

  function handleCancel() {
    cancelledRef.current = true
    if (timerRef.current) clearTimeout(timerRef.current)
    navigate(PATHS.login, { replace: true })
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <header className="mb-6">
          <h1 className="text-xl font-semibold text-slate-900">
            Đăng nhập bằng thiết bị tin cậy
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Xác nhận thiết bị này từ một thiết bị đã đăng nhập.
          </p>
        </header>

        {phase.kind === 'form' && (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <Input
              label="Tên đăng nhập"
              value={username}
              autoComplete="username"
              required
              onChange={(event) => setUsername(event.target.value)}
            />
            <Input
              label="Mật khẩu"
              type="password"
              value={password}
              autoComplete="current-password"
              required
              onChange={(event) => setPassword(event.target.value)}
            />
            <Input
              label="Tên thiết bị (tùy chọn)"
              value={deviceName}
              maxLength={100}
              onChange={(event) => setDeviceName(event.target.value)}
            />

            {error && <ErrorState title="Không thể gửi yêu cầu" message={error} />}

            <Button type="submit" fullWidth loading={submitting}>
              Gửi yêu cầu phê duyệt
            </Button>
            <Button variant="ghost" onClick={handleCancel}>
              Quay lại đăng nhập thường
            </Button>
          </form>
        )}

        {phase.kind === 'pending' && (
          <div className="flex flex-col gap-4">
            <Spinner label="Đang chờ thiết bị đã đăng nhập xác nhận..." />
            <p className="text-sm text-slate-500">
              Mở ứng dụng trên một thiết bị đã đăng nhập và phê duyệt yêu
              cầu này. Yêu cầu hết hạn lúc{' '}
              {new Date(phase.expiresAt).toLocaleTimeString('vi-VN')}.
            </p>
            <Button variant="secondary" onClick={handleCancel}>
              Hủy
            </Button>
          </div>
        )}

        {phase.kind === 'failed' && (
          <div className="flex flex-col gap-4">
            <ErrorState title="Yêu cầu không thành công" message={phase.message} />
            <Button variant="secondary" onClick={handleCancel}>
              Quay lại đăng nhập thường
            </Button>
          </div>
        )}

        {phase.kind === 'done' && <Spinner label="Đang đăng nhập..." />}
      </div>
    </main>
  )
}
