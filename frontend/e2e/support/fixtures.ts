/**
 * The Playwright fixtures.
 *
 * The fixtures give every test the three things it needs and nothing
 * more:
 *
 *   - `manifest` — the seeded fixture ids, read from the manifest the
 *     seed script wrote;
 *   - `api`      — a direct client to the real backend, for the checks
 *     that have to read the server state rather than the screen;
 *   - `page`     — the browser, pointed at the real demo stack.
 *
 * ---------------------------------------------------------------------------
 * WHY THE FIXTURES DO NOT CLEAN UP
 * ---------------------------------------------------------------------------
 *
 * Several scenarios MUTATE shared state: they acknowledge and resolve
 * alerts, they create and activate policies, they revoke sessions, they
 * untrust devices.
 *
 * The suite therefore does NOT "reset" the demo stack between tests.  A
 * reset would:
 *
 *   1. hide a real defect — a leaked session or a wrongly applied action
 *      would be wiped before anybody could see it;
 *   2. make the suite slow enough that nobody runs it;
 *   3. make the tests order-dependent in the opposite direction, since
 *      each test would have to trust that the reset really happened.
 *
 * Instead, each scenario owns its OWN fixture rows: the policy it edits
 * is one it created, the alert it resolves is one it picked for that
 * purpose.  A test cleans up after itself where the cleanup is part of
 * the behaviour under test, and leaves the rest alone.  The suite is
 * re-runnable on the same demo stack because it never depends on the
 * state it inherited.
 */

import { test as base, expect } from '@playwright/test'

import { readManifest, type FixtureManifest } from './manifest'
import { API_BASE_URL, apiRequest, type ApiResponse } from './api'

export interface ApiClient {
  baseUrl: string
  request(
    path: string,
    options?: { method?: string; token?: string; body?: unknown },
  ): Promise<ApiResponse>
}

export interface E2EFixtures {
  /** The seeded fixture ids. */
  manifest: FixtureManifest
  /** A direct client to the real backend. */
  api: ApiClient
}

export const test = base.extend<E2EFixtures>({
  manifest: async ({}, use) => {
    await use(readManifest())
  },

  api: async ({}, use) => {
    await use({
      baseUrl: API_BASE_URL,
      request: apiRequest,
    })
  },
})

export { expect }
