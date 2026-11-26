/**
 * The fixture helper bridge.
 *
 * The browser tests need alert rows the backend does not create on
 * demand — there is no endpoint that creates an alert for a given
 * subject, and the alert lifecycle is terminal: a resolved alert is
 * immutable and the backend answers 409 for every later mutation.
 *
 * `scripts/e2e_fixtures.py` writes those rows directly into the demo
 * detection database with DETERMINISTIC ids, so the suite is re-runnable
 * on the same demo stack for ever.  The script only ever touches rows
 * that carry its own marker, so it can never damage a seeded fixture.
 *
 * The bridge runs it through the demo environment, which is why the
 * helper is a separate process rather than inline SQL: the test must
 * not have to know how the demo stack is configured.
 */

import { execFile } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const run = promisify(execFile)

/** The repository root. */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** The fixture helper. */
const HELPER = resolve(REPO_ROOT, 'scripts', 'e2e_fixtures.py')

/**
 * The demo environment file.
 *
 * The path can be overridden with `DEMO_ENV_FILE`, because the CI job
 * writes its OWN environment file from the disposable container's
 * coordinates: the canonical `.env.demo` of the repository describes a
 * developer's local stack, and the CI run must never point at it.
 */
const DEMO_ENV = resolve(
  REPO_ROOT,
  process.env.DEMO_ENV_FILE ?? resolve(REPO_ROOT, '.env.demo'),
)

/** Read the demo environment file into an environment map. */
function demoEnvironment(): Record<string, string> {
  if (!existsSync(DEMO_ENV)) return {}

  const values: Record<string, string> = {}
  for (const rawLine of readFileSync(DEMO_ENV, 'utf8').split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const separator = line.indexOf('=')
    if (separator === -1) continue
    values[line.slice(0, separator).trim()] = line.slice(separator + 1).trim()
  }
  return values
}

/** The fixture the helper created. */
export interface E2EAlertFixture {
  alert_id: string
  login_attempt_id: string
  subject_user_id: string
  subject_username: string
  status: string
  risk_level: string
}

/**
 * Run the fixture helper.
 *
 * The helper is the ONLY thing that writes to the demo database from
 * the browser suite, and it is a real process with the real demo
 * environment — so the write is exactly the one the M13 scenario
 * scripts perform.
 */
async function runHelper(args: string[]): Promise<Record<string, unknown>> {
  const { stdout } = await run('python3', [HELPER, ...args], {
    cwd: REPO_ROOT,
    env: { ...process.env, ...demoEnvironment() },
  })

  return JSON.parse(stdout.trim()) as Record<string, unknown>
}

/**
 * Create (or re-arm) an alert the suite owns.
 *
 * Re-arming is what makes the suite re-runnable: the alert is put back
 * into the state the test expects BEFORE the test runs, not after it
 * failed.
 */
export async function createAlert(
  key: string,
  riskLevel = 'critical',
  status = 'open',
): Promise<E2EAlertFixture> {
  const result = await runHelper([
    'create-alert',
    '--key',
    key,
    '--risk',
    riskLevel,
    '--status',
    status,
  ])
  return result as unknown as E2EAlertFixture
}

/**
 * Create an alert whose subject the core context does NOT know.
 *
 * A protective action against such an alert cannot be enforced, so the
 * backend answers 502 — the failure the UI has to report honestly.
 */
export async function createOrphanAlert(key = 'orphan'): Promise<E2EAlertFixture> {
  const result = await runHelper(['create-orphan-alert', '--key', key])
  return result as unknown as E2EAlertFixture
}

/** Remove an alert the suite owns. */
export async function deleteAlert(key: string): Promise<void> {
  await runHelper(['delete-alert', '--key', key])
}

/**
 * Arm (or clear) the ONE-TIME MFA gate of an account.
 *
 * `REQUIRE_MFA` sets `users.detection_mfa_once`, and the flag is cleared
 * as soon as the account completes an MFA handshake.  A test that runs
 * twice would therefore find the gate already consumed and could not
 * prove it a second time — so the gate is re-armed BEFORE the test
 * runs.
 */
export async function setMfaGate(
  username: string,
  armed: boolean,
): Promise<void> {
  await runHelper([
    'set-mfa-gate',
    '--username',
    username,
    '--armed',
    armed ? 'true' : 'false',
  ])
}

/**
 * Clear the login rate-limit counter of the test client.
 *
 * ---------------------------------------------------------------------------
 * WHY THIS IS NOT A "CHEAT"
 * ---------------------------------------------------------------------------
 *
 * The backend rate-limits the login endpoint at 5 requests per minute
 * per client IP.  That limit is a REAL product control, and it works.
 *
 * The problem is that every browser scenario logs in, and every
 * scenario runs from the SAME loopback address — so a suite of eight
 * scenarios would trip a control that is designed for real traffic
 * rather than for a test harness.
 *
 * Clearing the counter removes the interference of the test client
 * with that control.  It does NOT disable the limiter, does not change
 * a threshold, and touches no business state: the seeded fixtures, the
 * sessions and the alerts are untouched.  The limiter itself keeps
 * working for anybody else.
 */
export async function resetRateLimits(ip = '127.0.0.1'): Promise<void> {
  await runHelper(['reset-rate-limits', '--ip', ip])
}

/**
 * Remove the E2E-owned policy of a given version.
 *
 * ---------------------------------------------------------------------------
 * WHY THE POLICY IS REMOVED AND NOT RESET
 * ---------------------------------------------------------------------------
 *
 * A policy that has been ACTIVATED is frozen for ever: its
 * `activated_at` is set, and the backend answers 409 for every later
 * edit.  A scenario that activates its own policy would therefore be
 * able to run exactly once.
 *
 * Removing the row before the scenario restores the "never activated"
 * state — which is the state the scenario is supposed to start from.
 * The seeded policies of the demo stack are never touched: the helper
 * refuses to remove a version that does not carry the E2E prefix.
 */
export async function deletePolicy(version: string): Promise<void> {
  await runHelper(['delete-policy', '--version', version])
}

/**
 * Restore the demo stack to "exactly one active policy": the seeded one.
 *
 * ---------------------------------------------------------------------------
 * WHY THIS CLEANUP IS PART OF THE BEHAVIOUR UNDER TEST
 * ---------------------------------------------------------------------------
 *
 * Activating a policy deactivates the current one — that is what
 * "only one policy may be in service" means, and the scenario has to
 * prove it.  The side effect is that the seeded ACTIVE policy of the
 * demo stack is no longer active, so the demo would drift away from its
 * own fixtures.
 *
 * Putting the demo back the way the scenario found it is therefore a
 * REQUIRED cleanup, not a way of hiding a defect: the E2E-owned
 * policies keep the evidence of the scenario, and the seeded fixtures
 * are never modified by the scenario itself.
 */
export async function restoreActivePolicy(): Promise<void> {
  await runHelper(['restore-active-policy'])
}

/**
 * Make the ML analytics source fail.
 *
 * ---------------------------------------------------------------------------
 * WHY A REAL FAULT AND NOT A MOCK
 * ---------------------------------------------------------------------------
 *
 * The Manager facade has to prove two DIFFERENT failure contracts, and
 * one fault cannot prove both:
 *
 *   - a DEGRADED payload — HTTP 200 with the sections that do not
 *     depend on the broken source present, and the broken section
 *     `null`;
 *   - a 503 — HTTP 503 with the per-source reasons, for an endpoint
 *     that consumes ONE source only.
 *
 * The helper therefore breaks the ML source for REAL: the table the ML
 * statistics are computed from is renamed, so the read fails with a
 * genuine database error.  Nothing is mocked, no application code is
 * touched, and the facade sees a source that really does not answer.
 */
export async function breakMlSource(): Promise<void> {
  await runHelper(['break-ml-source'])
}

/**
 * Undo `breakMlSource`.
 *
 * The restore MUST happen even when the scenario fails, so it is
 * registered as an `afterEach` hook rather than called at the end of
 * the test body.
 */
export async function restoreMlSource(): Promise<void> {
  await runHelper(['restore-ml-source'])
}

/**
 * Expire ONE session, by its id.
 *
 * ---------------------------------------------------------------------------
 * WHY THE EXPIRY IS PRODUCED IN THE DATABASE AND NOT WAITED FOR
 * ---------------------------------------------------------------------------
 *
 * The access token of a session lives for an hour.  A browser test can
 * never wait for that, so the expiry has to be produced some other way.
 *
 * The honest way is to move the session's own deadline into the past:
 * the backend then behaves exactly as it would after a real hour — the
 * access token is refused AND the refresh token is refused, because the
 * refresh endpoint checks the SAME deadline.  Nothing is mocked and no
 * application code is touched.
 *
 * Only a DEADLINE moves.  The identity of the session, its tokens and
 * every business state stay exactly as they were.
 *
 * The session is addressed BY ITS ID, never by "the sessions of this
 * account": an account may hold several sessions, and a race scenario
 * has to expire exactly ONE of them.
 */
export async function expireSession(sessionId: string): Promise<void> {
  await runHelper(['expire-session', '--session-id', sessionId])
}

/**
 * Make the stored refresh token of ONE session dead.
 *
 * ---------------------------------------------------------------------------
 * WHY THIS IS THE REFRESH RACE AND NOT A SIMULATION OF ONE
 * ---------------------------------------------------------------------------
 *
 * The backend ROTATES the refresh token: every `POST /auth/refresh`
 * overwrites the stored hash, so the copy the client holds is dead the
 * moment the rotation happened.  That is exactly what happens when the
 * same refresh token is spent from two places at once: the first spend
 * wins, the second one finds a token the server no longer knows.
 *
 * The helper performs that rotation from the outside, so the browser's
 * copy of the refresh token becomes stale.  The next 401 the browser
 * sees makes it refresh with a dead token, the backend refuses it with
 * a genuine 401, and the browser has to end the session cleanly —
 * without taking a NEWER session down with it.
 *
 * The session is addressed BY ITS ID, so exactly ONE session is
 * affected: the race scenario needs the session of the browser under
 * test to be the one that dies, while the sessions of the other
 * browsers of the same account stay alive.
 */
export async function spendRefreshToken(sessionId: string): Promise<void> {
  await runHelper(['spend-refresh-token', '--session-id', sessionId])
}
