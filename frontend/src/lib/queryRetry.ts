/**
 * Retry policy helper.
 *
 * Only transient failures are worth retrying: a network drop, a 5xx from a
 * dependency, or a rate limit. A 401/403/404/409 will not resolve itself, and
 * retrying a 409 could mask a real concurrency conflict.
 */

import { toApiError } from '@/lib/errors'

export function isRetryableError(error: unknown): boolean {
  return toApiError(error).isRetryable
}
