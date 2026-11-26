/**
 * The direct API client.
 *
 * Some checks have to look at the BACKEND state, not at what the screen
 * shows: "the protective action really changed the Core state", "the
 * policy is really immutable", "the backend really answered 403".
 *
 * This client talks to the REAL API with the REAL credentials.  It does
 * NOT mock anything, and it does not intercept the browser's traffic —
 * it is a second, independent view of the same live system, which is
 * exactly what makes it evidence: the browser says one thing and the
 * database-backed API says another, and the test catches it.
 *
 * The base URL is the API itself, not the Vite proxy, so a call from
 * here cannot be satisfied by a frontend-side mock.
 */

import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { resetRateLimits } from './fixtureBridge'

/** The repository root. */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** Read the demo environment file. */
function readDemoEnv(): Record<string, string> {
  const envPath = resolve(REPO_ROOT, '.env.demo')
  if (!existsSync(envPath)) return {}

  const values: Record<string, string> = {}
  for (const rawLine of readFileSync(envPath, 'utf8').split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const separator = line.indexOf('=')
    if (separator === -1) continue
    values[line.slice(0, separator).trim()] = line.slice(separator + 1).trim()
  }
  return values
}

const demoEnv = readDemoEnv()

/** The API origin. */
export const API_BASE_URL =
  process.env.E2E_API_URL?.trim() ||
  `http://${demoEnv.APP_HOST ?? '127.0.0.1'}:${demoEnv.APP_PORT ?? '58000'}`

/** One API response. */
export interface ApiResponse {
  status: number
  body: unknown
  raw: string
}

/**
 * Perform one API call.
 *
 * @param path   the path below `/api/v1`
 * @param token  the bearer token, when the call is authenticated
 */
export async function apiRequest(
  path: string,
  options: {
    method?: string
    token?: string
    body?: unknown
    headers?: Record<string, string>
  } = {},
): Promise<ApiResponse> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers ?? {}),
  }
  if (options.token) headers.Authorization = `Bearer ${options.token}`

  const response = await fetch(`${API_BASE_URL}/api/v1${path}`, {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  const raw = await response.text()
  let body: unknown = raw
  try {
    body = raw ? JSON.parse(raw) : null
  } catch {
    // A non-JSON body is kept as the raw text: the caller decides
    // whether that is acceptable.
  }

  return { status: response.status, body, raw }
}

/** Log in through the API and return the access token. */
export async function apiLogin(
  username: string,
  password: string,
): Promise<{ accessToken: string; refreshToken: string; mfaRequired: boolean }> {
  await resetRateLimits()

  const response = await apiRequest('/auth/login', {
    method: 'POST',
    body: { username, password },
  })

  if (response.status !== 200) {
    throw new Error(`the API login of '${username}' failed with ${response.status}: ${response.raw.slice(0, 300)}`)
  }

  const body = (response.body ?? {}) as Record<string, unknown>
  if (body.mfa_required) {
    throw new Error(
      `the API login of '${username}' requires an MFA challenge, so it cannot be used as a bearer-token setup.`,
    )
  }

  return {
    accessToken: String(body.access_token ?? ''),
    refreshToken: String(body.refresh_token ?? ''),
    mfaRequired: Boolean(body.mfa_required),
  }
}

/**
 * Read a session's state from the Core database's own API.
 *
 * The session list is the authoritative view of what the backend holds.
 */
export async function fetchSessions(token: string): Promise<ApiResponse> {
  return apiRequest('/auth/sessions', { token })
}

/**
 * Probe the login of an account and report whether it was held for an
 * MFA challenge.
 *
 * The probe goes straight to the backend: the browser is not involved,
 * because the question is about the SERVER's answer.  It is how a
 * protective action is proved — `REQUIRE_MFA` sets a flag that no
 * endpoint exposes, so the only honest evidence is that the next login
 * of the subject is held.
 */
export async function probeLogin(
  username: string,
  password: string,
): Promise<{ status: number; mfaRequired: boolean; hasAccessToken: boolean }> {
  await resetRateLimits()

  const response = await apiRequest('/auth/login', {
    method: 'POST',
    body: { username, password },
  })

  const body = (response.body ?? {}) as Record<string, unknown>
  return {
    status: response.status,
    mfaRequired: Boolean(body.mfa_required),
    hasAccessToken: Boolean(body.access_token),
  }
}
