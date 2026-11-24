/**
 * The shared endpoints of the real-HTTP integration suite.
 *
 * The suite talks to a LIVE backend over real HTTP, so it must never guess
 * where the backend lives. Two environment variables describe it:
 *
 *  - `M12_API_ORIGIN` — the origin of the backend (e.g. `http://127.0.0.1:8000`).
 *  - `M12_API_ROOT`   — the root of the API, i.e. the origin plus `/api/v1`.
 *
 * They MUST agree. When only the origin is given, the root is derived from
 * it; when only the root is given, the origin is derived from it. When both
 * are given and they disagree, the suite fails loudly instead of sending
 * half the requests to one backend and the other half to another — which is
 * exactly the silent failure mode this module removes.
 */

/** The API prefix the backend mounts the versioned API under. */
export const API_PREFIX = '/api/v1'

function normalizeOrigin(value: string): string {
  return value.replace(/\/+$/, '')
}

function normalizeRoot(value: string): string {
  return value.replace(/\/+$/, '')
}

/** The origin of the live backend, without a trailing slash. */
export const API_ORIGIN = normalizeOrigin(
  process.env.M12_API_ORIGIN?.trim() ||
    process.env.M12_API_ROOT?.trim() ||
    'http://127.0.0.1:8000',
)

/**
 * The root of the API, without a trailing slash.
 *
 * When `M12_API_ROOT` is set it wins; otherwise it is derived from the
 * origin. The two variables are cross-checked, so a mismatch is reported
 * instead of silently splitting the requests.
 */
export const API_ROOT = (() => {
  const explicitRoot = process.env.M12_API_ROOT?.trim()
  const explicitOrigin = process.env.M12_API_ORIGIN?.trim()

  const derivedRoot = `${API_ORIGIN}${API_PREFIX}`

  if (explicitRoot && explicitOrigin) {
    const origin = normalizeOrigin(explicitOrigin)
    if (normalizeRoot(explicitRoot) !== derivedRoot) {
      throw new Error(
        `M12_API_ORIGIN (${origin}) and M12_API_ROOT (${explicitRoot}) ` +
          `disagree: the root must be the origin plus "${API_PREFIX}". ` +
          `Set only M12_API_ORIGIN, or make both variables consistent.`,
      )
    }
    return normalizeRoot(explicitRoot)
  }

  if (explicitRoot) return normalizeRoot(explicitRoot)

  return derivedRoot
})()
