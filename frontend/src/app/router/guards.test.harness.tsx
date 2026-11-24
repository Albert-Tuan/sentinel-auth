/**
 * A test harness that signs the user in before rendering the guarded app.
 *
 * The guards depend on the auth state machine, which only becomes
 * `authenticated` after a real login round-trip. This component performs
 * that login on mount and renders its children once it succeeds.
 */

import { useEffect, useRef, type ReactNode } from 'react'
import { useAuthContext } from '@/app/providers/useAuthContext'

export interface AuthenticatedHarnessProps {
  children?: ReactNode
}

export function AuthenticatedHarness({ children }: AuthenticatedHarnessProps) {
  const auth = useAuthContext()
  const { login, isAuthenticated, status } = auth
  const attempted = useRef(false)

  useEffect(() => {
    if (attempted.current) return
    if (status !== 'anonymous') return
    attempted.current = true
    void login('test-user', 'test-password')
  }, [login, status])

  if (!isAuthenticated) {
    return <div>Signing in...</div>
  }

  return <>{children}</>
}
