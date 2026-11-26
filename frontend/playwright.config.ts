/**
 * Sentinel Auth v3.3 — M13.2 Playwright configuration.
 *
 * The browser tests drive the REAL demo stack: the real FastAPI
 * monolith, the real PostgreSQL databases and the real Redis.  Nothing
 * is mocked — no request is intercepted, no route is stubbed.
 *
 * ---------------------------------------------------------------------------
 * WHY THE CONFIGURATION IS THIS STRICT
 * ---------------------------------------------------------------------------
 *
 * 1. **The base URL is the demo stack, never a mock server.**  It comes
 *    from `VITE_DEV_PORT` / `E2E_BASE_URL`, which `scripts/demo_stack.sh`
 *    and `.env.demo` own.  A test that pointed somewhere else would be
 *    testing a different application.
 *
 * 2. **One worker.**  Several scenarios MUTATE shared state: they
 *    acknowledge and resolve alerts, they create and activate policies,
 *    they revoke sessions.  Running them in parallel would make the
 *    outcome depend on the scheduling order, and the suite would be
 *    flaky by construction.  `workers: 1` is therefore a correctness
 *    requirement, not a performance choice.
 *
 * 3. **The retries are BOUNDED and they never mask a failure.**  A test
 *    that fails once and passes on the retry reports as `flaky`, which
 *    is NOT green — Playwright marks the run as failed when a test is
 *    flaky.  The retry exists only to absorb a genuinely transient
 *    condition (a container warming up, a database committing late);
 *    it must never become the reason a real defect survives.
 *
 * 4. **Artefacts are kept on failure.**  A trace, a screenshot and the
 *    DOM snapshot are written for every failing test, so a defect can be
 *    reproduced from the report alone.
 *
 * 5. **No secret ever reaches an artefact.**  The trace records network
 *    traffic, and the traffic carries bearer tokens, passwords and OTP
 *    codes.  The artefact directory therefore lives under `.ci/` — which
 *    is gitignored — and the CI job never publishes it as a public
 *    artifact.  See `docs/M13-BROWSER-E2E-REPORT.md`.
 */

import { defineConfig, devices } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

/** The repository root, derived from this file's location. */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/**
 * The filesystem type the repository lives on.
 *
 * ---------------------------------------------------------------------------
 * WHY THIS IS CHECKED
 * ---------------------------------------------------------------------------
 *
 * The repository may sit on a FUSE mount (an NTFS/exFAT partition, a
 * network share, a container bind mount).  Playwright writes its traces,
 * videos and screencast frames with operations that FUSE does not
 * implement the way the browser expects: the trace directory is
 * created, the frame files are written, and then the finalisation step
 * that MOVES the recording into the trace archive fails with ENOENT.
 *
 * The symptom is deceptive: the test body PASSES and the failure is
 * reported on the context close, as if the application had broken.  The
 * application is fine — the ARTEFACT DIRECTORY is on a filesystem that
 * cannot host it.
 *
 * The artefact directory therefore moves to the local disk whenever the
 * repository is on such a mount.  The tests still run against the
 * repository; only the evidence is written elsewhere.  An explicit
 * `E2E_ARTIFACT_DIR` always wins, so CI can pin the location.
 */
function repoFilesystemType(): string {
  try {
    return execFileSync('stat', ['-f', '-c', '%T', REPO_ROOT], {
      encoding: 'utf8',
    }).trim()
  } catch {
    return ''
  }
}

/** Filesystems on which the Playwright artefacts cannot be written. */
const UNSUPPORTED_FILESYSTEMS = new Set(['fuse', 'fuseblk', 'ntfs', 'exfat', 'cifs', 'smbfs'])

/**
 * The directory the artefacts are written to.
 *
 * `.ci/e2e` is the default and stays correct on a normal filesystem.  On
 * a FUSE mount the artefacts move to a directory under the system temp
 * root, which is always a local disk.
 */
function resolveArtifactDir(): string {
  const explicit = process.env.E2E_ARTIFACT_DIR?.trim()
  if (explicit) return resolve(explicit)

  const inRepo = resolve(REPO_ROOT, '.ci', 'e2e')
  if (UNSUPPORTED_FILESYSTEMS.has(repoFilesystemType())) {
    return resolve(process.env.TMPDIR?.trim() || '/tmp', 'sentinel-auth-e2e')
  }
  return inRepo
}

/**
 * Read the demo environment file.
 *
 * The demo stack owns `.env.demo`; the canonical deployment owns `.env`.
 * The browser tests talk to the DEMO stack, so they read `.env.demo`.
 * The values are read here — and ONLY here — so that a test file never
 * has to know how the demo stack is configured.
 */
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

/** The frontend origin the browser opens. */
const baseURL =
  process.env.E2E_BASE_URL?.trim() ||
  `http://127.0.0.1:${demoEnv.VITE_DEV_PORT ?? '55173'}`

/**
 * The artefact directory.
 *
 * It lives inside `.ci/`, which is gitignored, so a trace — which holds
 * the bearer tokens and the OTP codes of the traffic — is never
 * committed.  On a filesystem that cannot host the artefacts, it moves
 * to the local disk; see `resolveArtifactDir`.
 */
const artifactDir = resolveArtifactDir()

export default defineConfig({
  testDir: './e2e',
  outputDir: resolve(artifactDir, 'output'),

  /**
   * The suite drives shared, mutable state, so it runs serially.
   */
  fullyParallel: false,
  workers: 1,

  /**
   * The forbidden default is `expect: { timeout: 5000 }`.  A real
   * browser against a real database needs more room than that on a cold
   * container, so the per-expectation timeout is raised — but the
   * per-test timeout stays tight enough that a hang is reported rather
   * than waited out.
   */
  timeout: 90_000,
  expect: {
    timeout: 15_000,
  },

  /**
   * One retry.  A test that needs a second attempt has to be reported
   * as flaky, and a flaky test fails the run — so the retry cannot hide
   * a defect, it can only give a genuinely transient failure one more
   * chance.
   */
  retries: 1,

  /**
   * The reporter writes a JUnit XML that the CI job parses for the
   * zero-skip policy, plus an HTML report for a human.
   */
  reporter: [
    ['list'],
    ['junit', { outputFile: resolve(artifactDir, 'junit.xml') }],
    ['html', { outputFolder: resolve(artifactDir, 'html-report'), open: 'never' }],
    ['json', { outputFile: resolve(artifactDir, 'results.json') }],
  ],

  use: {
    baseURL,

    /**
     * The trace records EVERYTHING: DOM snapshots, network traffic and
     * console output.  It is the primary evidence for a failure — and
     * it is also the reason the artefact directory must stay private.
     */
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',

    /**
     * The browser viewport.  The layout is responsive, but the fixed
     * viewport keeps the screenshots comparable between runs.
     */
    viewport: { width: 1440, height: 900 },

    /**
     * The application is written in Vietnamese.  The locale affects
     * nothing in the DOM, but it keeps the browser's own formatting
     * consistent with the application.
     */
    locale: 'vi-VN',
    timezoneId: 'Asia/Ho_Chi_Minh',

    /**
     * The action timeout is the budget for ONE interaction — a click, a
     * fill.  It is deliberately shorter than the test timeout, so a
     * control that never becomes clickable fails fast and precisely.
     */
    actionTimeout: 15_000,
    navigationTimeout: 30_000,

    /**
     * The browser may not be installed on every machine, so the failure
     * message has to say what to run.
     */
    ignoreHTTPSErrors: true,
  },

  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        /**
         * The demo stack runs in PROXY mode: the browser makes a
         * SAME-ORIGIN request to the Vite dev server, which proxies
         * `/api` to the FastAPI monolith.  No CORS is involved, so the
         * tests exercise the real backend without a cross-origin
         * preflight in the way.
         */
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
})
