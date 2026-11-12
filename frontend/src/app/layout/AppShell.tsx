import { Outlet } from 'react-router-dom'
import { Sidebar } from '@/app/layout/Sidebar'
import { MobileNav } from '@/app/layout/MobileNav'
import { Topbar } from '@/app/layout/Topbar'

/**
 * The authenticated application shell: sidebar + top bar + content area.
 *
 * The sidebar is a fixed rail that only fits from the `md` breakpoint up.
 * Below it the same navigation is rendered as a scrollable bar by
 * `<MobileNav/>`, so a phone user is never left without navigation.
 */
export function AppShell() {
  return (
    <div className="flex min-h-screen bg-slate-100">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <MobileNav />
        <main className="flex-1 p-4">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
