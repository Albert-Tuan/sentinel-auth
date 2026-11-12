/**
 * The role-filtered sidebar.
 *
 * The item list comes from the shared policy (`@/app/router/policy`), the
 * same table the route guard and the access check use. A link that
 * appears here is therefore always a link the user may follow.
 */
import { NavLink } from 'react-router-dom'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { navigationFor } from '@/app/router/policy'
import { cn } from '@/shared/utils/cn'

export function Sidebar() {
  const { roles } = useAuthContext()
  const items = navigationFor(roles)

  return (
    <nav
      aria-label="Điều hướng chính"
      className="hidden w-56 shrink-0 border-r border-slate-200 bg-slate-50 p-3 md:block"
    >
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.path}>
            <NavLink
              to={item.path}
              className={({ isActive }) =>
                cn(
                  'block rounded-md px-3 py-2 text-sm font-medium',
                  isActive
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-600 hover:bg-slate-100',
                )
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
