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
      className="hidden w-60 shrink-0 border-r border-border bg-panel p-3 md:block"
    >
      <p className="heading-ops px-3 pb-3 pt-1 text-text">Sentinel Auth</p>
      <ul className="flex flex-col">
        {items.map((item) => (
          <li key={item.path}>
            <NavLink
              to={item.path}
              className={({ isActive }) =>
                cn(
                  'label-ops block border-l-2 px-3 py-2',
                  isActive
                    ? 'border-l-primary bg-surface-raised text-text'
                    : 'border-l-transparent text-text-muted hover:bg-surface-raised hover:text-text',
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
