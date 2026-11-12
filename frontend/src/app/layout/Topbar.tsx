import { useNavigate } from 'react-router-dom'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { PATHS } from '@/app/router/paths'
import { Button } from '@/shared/components/Button'

/**
 * The top bar: current user, roles and the logout action.
 */
export function Topbar() {
  const auth = useAuthContext()
  const navigate = useNavigate()

  async function handleLogout() {
    await auth.logout()
    navigate(PATHS.login, { replace: true })
  }

  return (
    <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-slate-900">
          {auth.user?.username ?? '—'}
        </p>
        {auth.roles.length > 0 && (
          <p className="truncate text-xs text-slate-500">
            {auth.roles.join(' · ')}
          </p>
        )}
      </div>
      <Button variant="secondary" onClick={handleLogout}>
        Đăng xuất
      </Button>
    </header>
  )
}
