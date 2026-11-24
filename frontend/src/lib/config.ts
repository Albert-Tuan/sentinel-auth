/**
 * Environment configuration.
 *
 * The frontend NEVER receives a server-side secret. Only two values are
 * read, both public by construction:
 *
 *  - `VITE_API_BASE_URL` — the API origin. Leave EMPTY to use the Vite dev
 *    proxy (same-origin, no CORS involved). Set it to
 *    `http://localhost:8000` for the direct-CORS mode.
 *  - `VITE_DEV_API_TARGET` — the backend the Vite dev proxy forwards to.
 *    Development only; never shipped to the browser bundle.
 *
 * Anything starting with `VITE_` is inlined into the JS bundle, so it must
 * never hold `INTERNAL_SECRET`, database credentials, ML service credentials
 * or signing secrets.
 */

const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').trim()

/** The API prefix every browser-callable endpoint lives under. */
export const API_PREFIX = '/api/v1'

/**
 * The API base URL used by the Axios client.
 *
 * - `''`  -> same-origin requests; the Vite dev proxy forwards them.
 * - full origin -> cross-origin requests; CORS must allow this origin.
 *
 * The `/api/v1` prefix is appended in both modes so the endpoint constants
 * stay relative (`/auth/login`).
 */
export const API_BASE_URL = `${rawBaseUrl}${API_PREFIX}`

/**
 * True when the app talks to the API through the dev proxy (mode A).
 */
export const USING_DEV_PROXY = rawBaseUrl === ''

/** The backend the Vite dev proxy forwards to (development only). */
export const DEV_API_TARGET = (
  import.meta.env.VITE_DEV_API_TARGET ?? 'http://localhost:8000'
).trim()
