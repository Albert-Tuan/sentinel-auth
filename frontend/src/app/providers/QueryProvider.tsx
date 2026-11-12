/**
 * TanStack Query configuration.
 *
 * The defaults are tuned for an ops console:
 *  - `retry` is 0 for 4xx failures (a 403 will not fix itself) but 1 for
 *    network/server failures.
 *  - `refetchOnWindowFocus` is off: an ops dashboard should not silently
 *    re-fire every request when the analyst switches tabs.
 */

import { QueryClient } from '@tanstack/query-core'
import { isRetryableError } from '@/lib/queryRetry'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (!isRetryableError(error)) return false
          return failureCount < 1
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 5000),
      },
      mutations: {
        retry: false,
      },
    },
  })
}
