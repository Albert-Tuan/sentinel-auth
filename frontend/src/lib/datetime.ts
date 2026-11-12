/**
 * Date/time formatting helpers.
 *
 * The backend sends ISO-8601 strings with microsecond precision. They are
 * kept as strings everywhere (a `Date` round-trip loses the microseconds
 * and causes spurious 409 conflicts on policy updates), so formatting is
 * always an explicit, local operation.
 */

/** Format an ISO-8601 timestamp for display, in the viewer's locale. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

/** Format an ISO-8601 timestamp as a date only. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium' }).format(date)
}

/**
 * A short, human description of a user agent.
 *
 * The raw user agent is long and noisy; the table shows a recognisable
 * label instead while the full value stays in the `title` attribute.
 */
export function describeUserAgent(userAgent: string | null | undefined): string {
  if (!userAgent) return '—'
  const ua = userAgent.toLowerCase()
  if (ua.includes('edg/')) return 'Microsoft Edge'
  if (ua.includes('chrome/') && !ua.includes('chromium')) return 'Google Chrome'
  if (ua.includes('firefox/')) return 'Mozilla Firefox'
  if (ua.includes('safari/') && !ua.includes('chrome')) return 'Safari'
  if (ua.includes('curl/')) return 'curl'
  if (ua.includes('node') || ua.includes('axios')) return 'API client'
  return 'Thiết bị khác'
}

/** True when the timestamp is in the past. */
export function isExpired(iso: string | null | undefined): boolean {
  if (!iso) return false
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return false
  return date.getTime() <= Date.now()
}
