/**
 * The centralised authentication state.
 *
 * A single provider owns the auth state machine and exposes it to the whole
 * app through context. Every component that needs to know "is the user
 * logged in", "what roles do they hold" or "how do I log out" reads it from
 * here — no component keeps its own copy of the auth state.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { onSessionExpired } from '@/lib/api/client'
import {
  useAuth,
  type AuthApi,
  type UseAuthReturn,
} from '@/features/auth/useAuth'
import { AuthContext } from '@/app/providers/useAuthContext'

export interface AuthProviderProps {
  children: ReactNode
  /** Injected for tests. */
  api?: AuthApi
}

export function AuthProvider({ children, api }: AuthProviderProps) {
  const auth = useAuth(api ? { api } : {})
  const queryClient = useQueryClient()

  // The interceptor tells us when the session died (refresh failed). Clear
  // the query cache so no stale, user-scoped data survives the logout, and
  // let the router send the user back to the login screen.
  useEffect(() => {
    return onSessionExpired(() => {
      queryClient.clear()
    })
  }, [queryClient])

  const logout = useCallback(async () => {
    await auth.logout()
    // Drop every cached response: it belongs to the session that just ended.
    queryClient.clear()
  }, [auth, queryClient])

  const value = useMemo<UseAuthReturn>(
    () => ({ ...auth, logout }),
    [auth, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
