import { Navigate, useNavigate } from 'react-router-dom'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { PATHS } from '@/app/router/paths'
import { MfaCodeInput } from '@/features/auth/components/MfaCodeInput'
import { Spinner } from '@/shared/components/Spinner'

/**
 * The MFA challenge screen.
 *
 * Reached only when the login response carried `mfa_required: true`. No
 * session exists yet: the `session_id` held by the state machine is an
 * `MfaTransaction` id, not an authenticated session.
 */
export function MfaVerifyPage() {
  const auth = useAuthContext()
  const navigate = useNavigate()

  if (auth.isAuthenticated) {
    return <Navigate to={auth.landingPath} replace />
  }

  // The user navigated here directly without a pending challenge.
  if (!auth.isMfaPending) {
    return <Navigate to={PATHS.login} replace />
  }

  async function handleSubmit(code: string) {
    const ok = await auth.verifyMfa(code)
    if (ok) {
      navigate(auth.landingPath, { replace: true })
    }
    return ok
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <header className="mb-6">
          <h1 className="text-xl font-semibold text-slate-900">
            Xác thực hai yếu tố
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Tài khoản của bạn yêu cầu mã xác thực bổ sung trước khi đăng nhập.
          </p>
        </header>

        {auth.status === 'verifying_mfa' ? (
          <Spinner label="Đang kiểm tra mã..." />
        ) : (
          <MfaCodeInput
            onSubmit={handleSubmit}
            loading={auth.isLoading}
            error={auth.error}
            onCancel={() => {
              auth.cancelMfa()
              navigate(PATHS.login, { replace: true })
            }}
          />
        )}
      </div>
    </main>
  )
}
