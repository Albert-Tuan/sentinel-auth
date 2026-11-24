/**
 * The compact navigation shown on small screens.
 *
 * The sidebar is a fixed vertical rail, which does not fit a phone. This
 * component renders the SAME role-filtered items as a horizontally
 * scrollable bar and is only visible below the `md` breakpoint.
 *
 * The item list comes from the shared policy (`@/app/router/policy`), the
 * same table the route guard uses, so the two can never drift apart.
 */
import { NavLink } from 'react-router-dom'
import { useAuthContext } from '@/app/providers/useAuthContext'
import { navigationFor } from '@/app/router/policy'
import { cn } from '@/shared/utils/cn'

export function MobileNav() {
  const { roles } = useAuthContext()
  const items = navigationFor(roles)

  if (items.length === 0) return null

  return (
    <nav
      aria-label="Điều hướng chính (mobile)"
      className="border-b border-border bg-panel md:hidden"
    >
      <ul className="flex gap-1 overflow-x-auto p-2">
        {items.map((item) => (
          <li key={item.path} className="shrink-0">
            <NavLink
              to={item.path}
              className={({ isActive }) =>
                cn(
                  'label-ops block border-l-2 px-3 py-2',
                  isActive
                    ? 'border-l-primary bg-surface-raised text-text'
                    : 'border-l-transparent text-text-muted hover:text-text',
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
