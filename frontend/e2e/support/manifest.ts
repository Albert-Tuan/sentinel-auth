/**
 * The fixture manifest of the M13 demo stack.
 *
 * `scripts/demo_seed_demo.py` writes `.ci/demo/fixture-manifest.json`
 * after it seeds the demo fixtures, and the file holds the REAL ids of
 * the seeded rows: the user ids, the session ids, the alert ids, the
 * policy ids, the analyst id and the device ids.
 *
 * The browser tests read those ids from here instead of inventing them.
 * That matters for two reasons:
 *
 *   1. The ids are DERIVED, not random — the seed script computes them
 *      from a fixed namespace.  A test that guessed an id would fail.
 *   2. The manifest is written by the SEED, so reading it proves the
 *      browser is looking at the state the seed actually created.
 */

import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

/** The repository root. */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** The manifest path. */
export const MANIFEST_PATH = resolve(REPO_ROOT, '.ci', 'demo', 'fixture-manifest.json')

/** One seeded alert. */
export interface SeededAlert {
  id: string
  login_attempt_id: string
  risk_level: string
  status: string
  subject_user_id: string
}

/** One seeded user. */
export interface SeededUser {
  email: string
  id: string
  mfa_required: boolean
  roles: string[]
  username: string
}

/** One seeded policy. */
export interface SeededPolicy {
  id: string
  is_active: boolean
  version: string
}

/** The whole manifest. */
export interface FixtureManifest {
  core: {
    devices: Array<{
      device_name: string
      fingerprint: string
      id: string
      pending: boolean
      username: string
    }>
    ip_ids: Record<string, string>
    mfa: Array<{ id: string; status: string; username: string }>
    sessions: Array<{ id: string; username: string }>
    user_ids: Record<string, string>
    users: Record<string, SeededUser>
  }
  detection: {
    alerts: Record<string, SeededAlert>
    analysts: Array<{ id: string; username: string }>
    policies: {
      active: SeededPolicy
      draft: SeededPolicy
    }
  }
  marker: string
  ml: {
    feature_stats: number
    inference_logs: number
    models: Record<string, { id: string; is_production: boolean; status: string; version: string }>
  }
}

/**
 * Read the manifest.
 *
 * The manifest is REQUIRED: a browser test that ran against a demo stack
 * without fixtures would prove nothing, and a test that silently used an
 * empty manifest would report a meaningless failure.  A missing manifest
 * therefore fails loudly, with the command that produces it.
 */
export function readManifest(): FixtureManifest {
  if (!existsSync(MANIFEST_PATH)) {
    throw new Error(
      `the demo fixture manifest is missing: ${MANIFEST_PATH}\n` +
        'Seed the fixtures first:\n' +
        '  scripts/demo_stack.sh start\n' +
        '  python3 scripts/demo_seed_demo.py --seed --manifest-out .ci/demo/fixture-manifest.json',
    )
  }

  return JSON.parse(readFileSync(MANIFEST_PATH, 'utf8')) as FixtureManifest
}

/** The demo accounts, keyed the way the manifest keys them. */
export type AccountKey = 'user' | 'analyst' | 'admin' | 'manager'

/** The four accounts of the demo stack. */
export const ACCOUNTS: AccountKey[] = ['user', 'analyst', 'admin', 'manager']

/** The username of a demo account. */
export function usernameOf(manifest: FixtureManifest, key: AccountKey): string {
  const user = manifest.core.users[key]
  if (!user) throw new Error(`the manifest holds no user for the key '${key}'`)
  return user.username
}

/** The email of a demo account — the SMTP sink addresses the OTP to it. */
export function emailOf(manifest: FixtureManifest, key: AccountKey): string {
  const user = manifest.core.users[key]
  if (!user) throw new Error(`the manifest holds no user for the key '${key}'`)
  return user.email
}

/** The user id of a demo account. */
export function userIdOf(manifest: FixtureManifest, key: AccountKey): string {
  const user = manifest.core.users[key]
  if (!user) throw new Error(`the manifest holds no user for the key '${key}'`)
  return user.id
}
