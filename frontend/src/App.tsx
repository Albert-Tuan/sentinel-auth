/**
 * The router.
 *
 * `App` wires the providers and the route table together. It contains no
 * business logic.
 */

import { RouterProvider, createBrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { useMemo } from 'react'
import { buildRoutes } from '@/app/router/routes'
import { AuthProvider } from '@/app/providers/AuthProvider'
import { createQueryClient } from '@/app/providers/QueryProvider'

export function App() {
  const router = useMemo(() => createBrowserRouter(buildRoutes()), [])
  const queryClient = useMemo(() => createQueryClient(), [])

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  )
}
