/**
 * The live session state of the application.
 *
 * ---------------------------------------------------------------------------
 * WHY THE APPLICATION'S OWN MODULE IS READ
 * ---------------------------------------------------------------------------
 *
 * The session store of the application is IN-MEMORY: the tokens live in
 * a module-scoped object, never in `localStorage`, never in a cookie.
 * A test therefore cannot read them from the page — and that is
 * exactly the point of the design.
 *
 * The module IS reachable, though.  The dev server serves the very
 * same module instance the application uses, and a dynamic import
 * returns THAT instance — not a copy.  Reading it is therefore reading
 * the application's real state, not a reconstruction of it.
 *
 * The probe answers the questions the screen cannot:
 *
 *   - the session EPOCH, which is what the race guards compare — it is
 *     a counter, not a visual state;
 *   - the identity of the token the client holds, which is what the
 *     rotation guards compare.
 *
 * The import is performed through a constructed `import()` on purpose:
 * the path is a RUNTIME path of the dev server, not a module of this
 * bundle, so the TypeScript compiler must not try to resolve it.
 */

import type { Page } from '@playwright/test'

/** The state of the application's own session store. */
export interface LiveSessionState {
  /** The session epoch.  It advances on every session boundary change. */
  epoch: number
  /** True when a session with a non-empty access token exists. */
  hasSession: boolean
  /** The access token the client holds. */
  accessToken: string
  /** The refresh token the client holds. */
  refreshToken: string
}

/**
 * Read the live session state of the application.
 *
 * The read is a READ: the helper never installs a session and never
 * touches the store.  A test that wanted to write would have to do it
 * explicitly — and it does not, because the races under test are
 * produced by the backend, not by the client.
 */
export async function readSessionState(page: Page): Promise<LiveSessionState> {
  return page.evaluate(async () => {
    const runtimeImport = new Function(
      'path',
      'return import(path)',
    ) as (path: string) => Promise<{
      getEpoch: () => number
      hasSession: () => boolean
      getAccessToken: () => string | null
      getRefreshToken: () => string | null
    }>

    const store = await runtimeImport('/src/lib/api/tokenStore.ts')

    return {
      epoch: store.getEpoch(),
      hasSession: store.hasSession(),
      accessToken: store.getAccessToken() ?? '',
      refreshToken: store.getRefreshToken() ?? '',
    }
  })
}

/**
 * A one-way gate: the caller waits until the holder arrives, and then
 * releases it.
 *
 * The gate is used to hold a request back BEFORE it reaches the
 * backend, so that a race can be arranged: the client has already
 * committed to the session it belongs to — the axios request
 * interceptor has stamped the request with that session's epoch — but
 * the server has not seen the request yet.
 */
export interface Gate {
  /** Resolves once the holder has arrived. */
  wait(): Promise<void>
  /** Releases the holder. */
  release(): void
  /** True while a holder is waiting. */
  readonly held: boolean
}

/**
 * Create a gate.
 */
export function createGate(): Gate {
  let release: (() => void) | null = null
  let arrived = false

  const opened = new Promise<void>((resolve) => {
    release = resolve
  })

  return {
    async wait(): Promise<void> {
      arrived = true
      await opened
    },
    release(): void {
      release?.()
    },
    get held(): boolean {
      return arrived
    },
  }
}
