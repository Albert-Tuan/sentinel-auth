import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { resolvePostLoginPath } from '@/app/router/policy'
import { PATHS } from '@/app/router/paths'
import { LoginForm } from '@/features/auth/components/LoginForm'
import { Spinner } from '@/shared/components/Spinner'

/**
 * The login screen.
 *
 * When MFA is required the auth state machine moves to `mfa_required` and
 * this page redirects to the MFA screen. The user is NOT considered
 * authenticated at that point.
 *
 * The post-login redirect happens in exactly ONE place: the `<Navigate>`
 * below, which renders once the auth context reports an authenticated
 * session. Doing it in the submit handler as well would race two
 * navigations — one built from the pre-login roles, one from the real
 * ones — and the loser could send the user to the wrong page.
 */
export function LoginPage() {
  const auth = useAuthContext()
  const location = useLocation()

  const from = (location.state as { from?: string } | null)?.from

  if (auth.status === 'mfa_required' || auth.status === 'verifying_mfa') {
    return <Navigate to={PATHS.mfa} replace />
  }

  if (auth.isAuthenticated) {
    // The remembered destination is only used when the signed-in roles
    // allow it — otherwise the user would land on a 403 page for a route
    // they were never entitled to.
    return (
      <Navigate to={resolvePostLoginPath(from, auth.roles)} replace />
    )
  }

  async function handleSubmit(username: string, password: string) {
    // The redirect itself is handled by the `<Navigate>` above, which runs
    // with the freshly fetched roles.
    return auth.login(username, password)
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <header className="mb-6">
          <h1 className="text-xl font-semibold text-slate-900">Sentinel Auth</h1>
          <p className="mt-1 text-sm text-slate-500">
            Đăng nhập để truy cập bảng điều khiển an ninh.
          </p>
        </header>

        {auth.status === 'authenticating' ? (
          <Spinner label="Đang xác thực..." />
        ) : (
          <LoginForm
            onSubmit={handleSubmit}
            loading={auth.isLoading}
            error={auth.error}
          />
        )}

        <div className="mt-6 border-t border-slate-100 pt-4 text-center">
          <Link
            to={PATHS.trustedDeviceLogin}
            className="text-sm text-indigo-600 hover:text-indigo-700 hover:underline"
          >
            Đăng nhập bằng thiết bị tin cậy
          </Link>
        </div>
      </div>
    </main>
  )
}
