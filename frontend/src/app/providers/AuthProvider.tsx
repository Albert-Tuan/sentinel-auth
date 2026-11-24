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
import { isExpiredSessionCurrent } from '@/lib/api/tokenStore'
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
  //
  // The `useAuth` hook listens to the very same event and moves the auth
  // state machine back to `anonymous`; the guard then bounces the user to
  // `/login`. This effect only owns the cache.
  //
  // The notification is ignored when it no longer describes the current
  // situation: a newer session replaced the expired one, and its cached
  // data must survive.
  useEffect(() => {
    return onSessionExpired((expiredEpoch) => {
      if (!isExpiredSessionCurrent(expiredEpoch)) {
        // A newer session replaced the expired one — its cache stays.
        return
      }
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
