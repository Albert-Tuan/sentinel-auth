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
      className="md:hidden border-b border-slate-200 bg-slate-50"
    >
      <ul className="flex gap-1 overflow-x-auto p-2">
        {items.map((item) => (
          <li key={item.path} className="shrink-0">
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
