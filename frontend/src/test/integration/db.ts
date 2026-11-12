/**
 * SQL access for the real-HTTP integration suite.
 *
 * The integration tests need to do two things the HTTP API cannot do:
 * reset a rate-limiter row, and read an audit-log counter. Both are test
 * harness housekeeping — they change no application behaviour.
 *
 * Two invocation modes are supported, so the SAME suite runs unchanged
 * locally and in CI:
 *
 *  - **`M12_DATABASE_URL` set** (CI): the `psql` client is invoked directly
 *    with the connection URL. This is what the GitHub Actions job does —
 *    the disposable PostgreSQL is a service container, so there is no
 *    container to `exec` into.
 *  - **`M12_DATABASE_URL` unset** (local development): the `psql` client
 *    runs inside the `sentinel-pg` container via `podman exec`, which is
 *    how the local stack exposes its database.
 *
 * The SQL itself is identical in both modes.
 */

import { execFileSync } from 'node:child_process'

/** The connection URL of the Core database, when the direct mode is used. */
const DATABASE_URL = process.env.M12_DATABASE_URL?.trim() || ''

/** The local container that holds the Core database. */
const LOCAL_CONTAINER = process.env.M12_PG_CONTAINER?.trim() || 'sentinel-pg'

/** The local container's Core database name. */
const LOCAL_DATABASE = process.env.M12_PG_DATABASE?.trim() || 'sentinel_core'

/**
 * Run one SQL statement against the Core database and return its output.
 */
export function psql(sql: string): string {
  const output = DATABASE_URL
    ? execFileSync('psql', [DATABASE_URL, '-tAc', sql], {
        encoding: 'utf8',
      })
    : execFileSync(
        'podman',
        [
          'exec',
          LOCAL_CONTAINER,
          'psql',
          '-U',
          process.env.M12_PG_USER?.trim() || 'sentinel',
          '-d',
          LOCAL_DATABASE,
          '-tAc',
          sql,
        ],
        { encoding: 'utf8' },
      )

  return output.trim()
}

/**
 * The backend rate-limits logins to 5 per minute per IP, and the
 * trusted-device approval endpoint has its own counter (5 per minute).
 * The limiter rows are reset between tests. Test-harness housekeeping only
 * — it changes no application behaviour.
 */
export function resetLoginRateLimit(): void {
  psql(
    `DELETE FROM rate_limits WHERE action IN ('login', 'trusted_device_approval')`,
  )
}

/** Count the server-side audit rows of a given action. */
export function countAudit(action: string): number {
  return Number(psql(`SELECT count(*) FROM audit_logs WHERE action='${action}'`))
}
