import { createContext, useContext } from 'react'
import type { UseAuthReturn } from '@/features/auth/useAuth'

/**
 * The auth context handle.
 *
 * It lives in its own module so that `AuthProvider.tsx` exports only a
 * component — that keeps Vite's fast-refresh working.
 */
export const AuthContext = createContext<UseAuthReturn | null>(null)

/**
 * Read the auth state. Throws when used outside an `AuthProvider`.
 */
export function useAuthContext(): UseAuthReturn {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuthContext must be used inside an <AuthProvider>')
  }
  return context
}
