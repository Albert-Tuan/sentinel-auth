/**
 * Test rendering helpers.
 */

import { render, type RenderOptions } from '@testing-library/react'
import {
  MemoryRouter,
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement, ReactNode } from 'react'
import { AuthProvider } from '@/app/providers/AuthProvider'
import { buildRoutes, type PageFactory } from '@/app/router/routes'
import type { AuthApi } from '@/features/auth/useAuth'

export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
}

export interface RenderAppOptions extends Omit<RenderOptions, 'wrapper'> {
  api?: AuthApi
  initialEntries?: string[]
  queryClient?: QueryClient
  /** Override the page factory (the real feature screens come later). */
  createPage?: PageFactory
}

/**
 * Render a component inside the same providers the real app uses.
 */
export function renderWithProviders(
  ui: ReactElement,
  options: RenderAppOptions = {},
) {
  const {
    api,
    initialEntries = ['/'],
    queryClient = makeTestQueryClient(),
    ...renderOptions
  } = options

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider api={api}>
          <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    )
  }

  return {
    queryClient,
    ...render(ui, { wrapper: Wrapper, ...renderOptions }),
  }
}

/**
 * Render the real route table.
 *
 * The pages redirect between routes (login -> MFA -> landing), so the tests
 * need the actual route table rather than an isolated page.
 */
export function renderRouter(options: RenderAppOptions = {}) {
  const {
    api,
    initialEntries = ['/login'],
    queryClient = makeTestQueryClient(),
    createPage,
    ...renderOptions
  } = options

  const router = createMemoryRouter(buildRoutes(createPage), {
    initialEntries,
  })

  function Wrapper() {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider api={api}>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>
    )
  }

  return {
    router,
    queryClient,
    ...render(<div />, { wrapper: Wrapper, ...renderOptions }),
  }
}
