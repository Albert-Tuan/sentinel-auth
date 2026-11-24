# M12 Frontend — Stage 0–2 Delivery Report

**Branch:** `feature/m12-frontend-foundation`
**Baseline:** `origin/dev` @ `c89bff513c5ae38f52ec90a1ad2b04e4eeab924f`
**Planning baseline:** `cd5b2a8` — `docs(frontend): define M12 API contracts and integration plan` (PR #18 — **đã merge vào `dev`**, merge commit `113159a`)
**Date:** 2026-11-11

> **Status: superseded by the Stage 0–3 final review.**
> Báo cáo này mô tả trạng thái tại thời điểm Stage 0–2. Đợt final review
> (Stage 0–3) đã sửa thêm: nguồn quyền duy nhất `src/app/router/policy.ts`,
> epoch guard trong `useAuth`, ranh giới no-refresh của trusted-device, và
> hai job CI cho frontend. Xem `frontend/M12-STAGE-3-REPORT.md` §11 và
> `docs/frontend/M12-STAGE-0-3-SECURITY-NOTES.md`.
>
> Phần còn lại của báo cáo vẫn đúng: frontend đã được commit trong
> `feat(frontend): implement authentication and user self-service flows`.

---

## 1. Files changed

> *(Cập nhật ở final review: commit `feat(frontend): implement authentication and
> user self-service flows` còn chứa thêm `.github/workflows/ci.yml`,
> `scripts/ci_seed_frontend_users.py`, `scripts/ci_smtp_sink.py` và
> `docs/frontend/M12-STAGE-0-3-SECURITY-NOTES.md`.)*

Tại Stage 0–2, không có gì ngoài `frontend/` bị đụng tới. `git status` trên
branch cho thấy một thư mục untracked duy nhất:

```
?? frontend/
```

### 1.1 Frontend files (59 tracked-candidate files, including this report)

| Path | Purpose |
| --- | --- |
| `frontend/package.json` | Scripts, deps: React 19, Vite 7, React Router 7, TanStack Query 5, Axios, Tailwind 4, Vitest 3, RTL 16 |
| `frontend/package-lock.json` | Lockfile |
| `frontend/vite.config.ts` | Vite config + dev proxy (mode A) |
| `frontend/vitest.config.ts` | Unit-test config (jsdom, hermetic) |
| `frontend/vitest.integration.config.ts` | Live-backend integration config (node) |
| `frontend/eslint.config.js` | Flat ESLint config (typescript-eslint + react-hooks) |
| `frontend/tsconfig.json` / `tsconfig.app.json` / `tsconfig.node.json` | Strict TS project refs |
| `frontend/index.html`, `frontend/.gitignore`, `frontend/.env.example` | Shell, ignore rules, public env template |
| `frontend/src/main.tsx`, `src/App.tsx` | Entry point, root router |
| `frontend/src/types/api.ts` | Typed API contracts (all 46 browser-callable operations' shapes) |
| `frontend/src/lib/errors.ts` | `ApiError`, `toApiError`, `apiErrorFromResponse`, `kindForStatus` |
| `frontend/src/lib/config.ts` | `VITE_API_BASE_URL` / `VITE_DEV_API_TARGET` / `VITE_DEV_PORT` |
| `frontend/src/lib/queryRetry.ts` | Query retry policy (401/403/404 never retried) |
| `frontend/src/lib/api/endpoints.ts` | Single source of truth for every URL path |
| `frontend/src/lib/api/tokenStore.ts` | In-memory session store + `sessionEpoch` |
| `frontend/src/lib/api/client.ts` | Axios client, refresh mutex, retry-once, epoch guard |
| `frontend/src/lib/api/auth.api.ts` | Auth endpoint wrappers |
| `frontend/src/features/auth/useAuth.ts` | Auth state machine (reducer + hook) |
| `frontend/src/features/auth/components/LoginForm.tsx` | Login form |
| `frontend/src/features/auth/components/MfaCodeInput.tsx` | 6-digit OTP input |
| `frontend/src/features/auth/pages/LoginPage.tsx` | Login screen |
| `frontend/src/features/auth/pages/MfaVerifyPage.tsx` | MFA challenge/verify screen |
| `frontend/src/features/auth/pages/ForbiddenPage.tsx` | 403 screen |
| `frontend/src/features/auth/pages/NotFoundPage.tsx` | 404 screen |
| `frontend/src/app/providers/AuthProvider.tsx` | Centralised auth context + query-cache clearing |
| `frontend/src/app/providers/QueryProvider.tsx` | TanStack Query client |
| `frontend/src/app/providers/useAuthContext.ts` | Auth context + hook |
| `frontend/src/app/router/routes.tsx` | Route table |
| `frontend/src/app/router/guards.tsx` | `RequireAuth`, `RequireRole` |
| `frontend/src/app/router/paths.ts` | Path constants |
| `frontend/src/app/layout/AppShell.tsx` | Responsive shell (sidebar + topbar + content) |
| `frontend/src/app/layout/Sidebar.tsx` | Role-filtered sidebar |
| `frontend/src/app/layout/MobileNav.tsx` | Compact nav for small screens |
| `frontend/src/app/layout/Topbar.tsx` | User, roles, logout |
| `frontend/src/app/layout/navigation.ts` | Role-aware navigation model |
| `frontend/src/app/layout/PlaceholderPage.tsx` | Stage-3+ screen placeholder |
| `frontend/src/shared/components/{Button,Input,Spinner,ErrorState,EmptyState}.tsx` | Shared UI primitives |
| `frontend/src/shared/utils/cn.ts` | Class-name joiner |
| `frontend/src/styles/index.css` | Tailwind 4 entry |
| `frontend/src/test/setup.ts`, `fixtures.ts`, `renderApp.tsx` | Test harness |
| `frontend/src/test/integration/realBackend.test.ts` | Live-backend integration suite |
| `frontend/src/features/auth/useAuth.test.tsx` | 12 unit tests |
| `frontend/src/lib/api/client.test.ts` | 16 unit tests |
| `frontend/src/app/router/guards.test.tsx` | 8 unit tests |
| `frontend/src/features/auth/pages/authPages.test.tsx` | 10 unit tests |
| `frontend/M12-STAGE-0-2-REPORT.md` | This delivery report |

### 1.2 Backend / Core / Detection / ML / Manager

**No change.** `git diff HEAD -- app/ tests/ scripts/ docs/` is empty. No
business logic, contract or schema was modified.

---

## 2. Frontend architecture

Feature-based, layered, with a strict dependency direction
`shared → lib → features → app`:

```
frontend/src/
├── app/                     # app shell: providers, router, layout
│   ├── providers/           # AuthProvider (auth state), QueryProvider (TanStack Query)
│   ├── router/              # routes.tsx, guards.tsx (RequireAuth/RequireRole), paths.ts
│   └── layout/              # AppShell, Sidebar, MobileNav, Topbar, navigation.ts
├── features/
│   └── auth/                # useAuth.ts (state machine), components/, pages/
├── lib/
│   ├── api/                 # client.ts (axios), tokenStore.ts, auth.api.ts, endpoints.ts
│   ├── errors.ts            # ApiError
│   ├── config.ts            # env configuration
│   └── queryRetry.ts
├── shared/                  # Button, Input, Spinner, ErrorState, EmptyState, cn()
├── types/api.ts             # typed contracts
└── test/                    # setup, fixtures, renderApp, integration/
```

**Typed API contracts.** `src/types/api.ts` transcribes the live FastAPI
schemas. Tokens are typed as opaque strings — never decoded as JWT.
Timestamps stay strings (microsecond precision is lost in a `Date`
round-trip, which causes spurious 409s on policy updates).

**Centralized API error handling.** Every failure becomes an `ApiError` with a
programmatic `kind` (`validation | unauthorized | forbidden | not_found |
conflict | gone | locked | rate_limited | dependency_unavailable | server |
network | cancelled | unknown`) plus a `userMessage` that is safe to render.
`kindForStatus` maps `400/422 → validation`, `401 → unauthorized`,
`403 → forbidden`, `429 → rate_limited`, `502/503/504 → dependency_unavailable`,
other `5xx → server`. The raw backend `detail` is only surfaced for `400`,
`403`, `423` and `429` and only when it is a plain string ≤ 200 chars;
`5xx` details (e.g. a psycopg2 traceback string) are never rendered. This is
covered by the test *"does not leak internal backend detail into the UI"*.

**Centralized authentication state.** `AuthProvider` owns the state machine
and publishes it through context. No component keeps its own copy.

**Protected routes and role-aware navigation.** `RequireAuth` redirects
anonymous visitors to `/login`; `RequireRole` renders `/forbidden` when the
user lacks the role. The sidebar shows only the items `navigationFor(roles)`
permits, so a user never sees a link that would return 403.

**Loading / error / empty / unauthorized states.** `Spinner`, `ErrorState`,
`EmptyState` and the `ForbiddenPage` / `NotFoundPage` screens cover the four
cases. The login page shows the normalised `userMessage` only.

**Responsive layout foundation.** Tailwind 4 (`@tailwindcss/vite`, no
config file needed). The sidebar is a fixed rail from `md` up; below that
`MobileNav` renders the same role-filtered items as a horizontally
scrollable bar, so a phone user is never left without navigation.

**Environment configuration.** `frontend/.env.example` documents the two
development connection modes and explicitly forbids `INTERNAL_SECRET`,
database, ML and signing secrets. Only three `VITE_` variables exist and
all three are public by construction.

**Dev connection mode — one mode only (mode A, the Vite proxy).**
`VITE_API_BASE_URL` is empty, so the browser issues same-origin `/api/...`
requests and the Vite dev server forwards them to `VITE_DEV_API_TARGET`. The
proxy is only registered when mode A is active, so the proxy and direct-CORS
configurations can never both be live. Mode B (direct CORS) is documented as
the alternative, with the required backend
`CORS_ALLOWED_ORIGINS=http://localhost:5173` entry.

**Secrets.** A scan of `frontend/src`, `frontend/*.ts|js|json` and
`frontend/.env.example` finds no `INTERNAL_SECRET`, no PostgreSQL/ML
credentials and no signing secrets. There is no `console.*` call anywhere in
`frontend/src`.

---

## 3. Authentication state machine

`src/features/auth/useAuth.ts` — a `useReducer` state machine with six
states:

```
anonymous ──login()──▶ authenticating ──┬── mfa_required=true ──▶ mfa_required
                                         │        (MfaTransaction id held,
                                         │         NO tokens installed)
                                         └── tokens ──────────────▶ authenticated
                                                                       │
mfa_required ──verify()──▶ verifying_mfa ──┬── tokens ─────────────▶ authenticated
                                             └── failure ─────────▶ mfa_required
                                                                       │
anonymous ◀──logout() / session expired────────────────────────────────┘
```

Transitions are explicit actions (`LOGIN_START`, `LOGIN_MFA_REQUIRED`,
`LOGIN_SUCCESS`, `LOGIN_FAILURE`, `MFA_START`, `MFA_SUCCESS`, `MFA_FAILURE`,
`LOGOUT`, `SESSION_EXPIRED`, `CLEAR_ERROR`).

### The MFA invariant

`mfa_required: true` means **not authenticated**. The response carries
`access_token: ""` and `refresh_token: ""`, and the `session_id` is an
`MfaTransaction` id — *not* an authenticated session. The reducer moves to
`mfa_required`, `tokenStore.setSession()` is **not** called, and the
`session_id` is only ever echoed back to `POST /auth/mfa/verify`.

The app only enters `authenticated` after a response carries real, non-empty
tokens **and** `GET /auth/me` has returned the user. A non-MFA login response
that somehow carried empty tokens is rejected defensively (`LOGIN_FAILURE`).

### Role handling

Roles are read from `GET /auth/me` — never inferred on the client. The
landing route is derived from the backend roles:
`SECURITY_MANAGER → /manager/dashboard`, `SECURITY_ADMIN → /admin/users`,
`SOC_ANALYST → /alerts`, otherwise `/`.

### Logout

`logout()` revokes server-side first (`POST /auth/logout`), then clears the
local session and dispatches `LOGOUT`. A failing revoke never blocks the
local teardown, so the user always ends up logged out. `AuthProvider.logout()`
additionally calls `queryClient.clear()` so no user-scoped cached data
survives the session.

---

## 4. Refresh concurrency design

`src/lib/api/client.ts`.

**1. Single-flight mutex.** A module-scoped `refreshPromise` holds the
in-flight refresh. Every concurrent 401 awaits the *same* promise, so
exactly one `POST /auth/refresh` is sent. This matters because the backend
**rotates** the refresh token: a second refresh with the old token would
fail with 401 and log the user out spuriously.

**2. Both tokens updated.** On success `updateTokens(access, refresh)` writes
the new pair. The old refresh token is dead server-side.

**3. Retry exactly once.** The replayed request carries a `_retry` flag, so
the replay itself can never trigger another refresh — no infinite loop.

**4. Failure clears the session.** A failed refresh calls `clearSession()`,
notifies the app through `onSessionExpired` (which clears the TanStack Query
cache and routes to `/login`), and surfaces the normalised error.

**5. No refresh on the auth handshake.** `NO_REFRESH_PATHS` contains
`/auth/login`, `/auth/mfa/verify`, `/auth/refresh` and `/auth/register`. A
401 from those means "wrong credentials", not "expired token". The refresh
call additionally passes `_skipRefresh: true` as a belt-and-braces measure.

**6. Stale-response guard (logout/login race).** The store carries a
monotonic `sessionEpoch`, bumped on every session boundary change. The
refresh captures the epoch before it starts; if the epoch changed when the
response arrives, the response is **discarded** via a dedicated
`StaleSessionError` — the session that superseded it is *not* cleared.
An earlier revision of this code funnelled the epoch mismatch into
`.catch()`, which unconditionally called `clearSession()` and wiped out a
newly established session. That defect is fixed and covered by two tests.

**7. Logout clears everything.** Logout clears the token store (bumping the
epoch, which invalidates any in-flight refresh), clears the pending retry
state and clears the TanStack Query cache.

---

## 5. Tests and results

### 5.1 Unit / component tests — 46 tests, all passing

`npm run test` (hermetic, jsdom, `axios-mock-adapter`):

| File | Tests |
| --- | --- |
| `src/features/auth/useAuth.test.tsx` | 12 |
| `src/lib/api/client.test.ts` | 16 |
| `src/app/router/guards.test.tsx` | 8 |
| `src/features/auth/pages/authPages.test.tsx` | 10 |

Mapping to the 13 required scenarios:

| # | Required scenario | Test |
| --- | --- | --- |
| 1 | Login success | `useAuth — login > authenticates on valid credentials and stores the tokens in memory`; `LoginPage > submits the credentials and authenticates` |
| 2 | Login failure | `useAuth — login > surfaces a failure and stays anonymous on invalid credentials`; `LoginPage > shows an error message when the credentials are rejected` |
| 3 | MFA required | `useAuth — MFA > does NOT authenticate when MFA is required`; `LoginPage > sends the user to the MFA screen when MFA is required` |
| 4 | MFA verification success | `useAuth — MFA > authenticates after a successful MFA verification`; `MfaVerifyPage > verifies the code and authenticates on success` |
| 5 | MFA verification failure | `useAuth — MFA > stays on the MFA challenge when verification fails`; `MfaVerifyPage > shows an error when the code is wrong and stays on the MFA screen`; `MfaVerifyPage > rejects a code that is not six digits without calling the API` |
| 6 | Protected route | `RequireAuth > redirects an anonymous visitor to the login screen`; `RequireAuth > admits an authenticated user` |
| 7 | RBAC-based navigation | `RequireRole > blocks a SOC analyst from the SECURITY_ADMIN area` (+2 more); `role-filtered navigation > filters the navigation down to the roles the user holds` (+2 more) |
| 8 | Expired / invalid access token | `client.test.ts > single-flight refresh` (401 → refresh → replay) |
| 9 | Concurrent 401 → exactly one refresh | `client.test.ts > issues exactly ONE refresh for many concurrent 401s` |
| 10 | Refresh token rotation | `client.test.ts > rotates BOTH tokens on a successful refresh` |
| 11 | Refresh failure | `client.test.ts > clears the session and notifies the app when the refresh fails`; `… > does not retry the original request after a failed refresh` |
| 12 | Retry-once behaviour | `client.test.ts > replays the original request exactly once`; `… > does not refresh again when the replay also returns 401` |
| 13 | Logout | `useAuth — roles and logout > clears the session and the query cache on logout` |
| 13b | Logout vs. in-flight refresh race | `client.test.ts > does not let an in-flight refresh write tokens into a new session`; `… > discards a refresh result that belongs to a superseded session` |
| 13c | Reload requires login again | `client.test.ts > does not survive a reload — the store starts empty`; `client.test.ts > never writes tokens to localStorage or sessionStorage`; `authPages.test.tsx > reload behaviour > requires a new login after a page reload, because the session is memory-only` |

Extra coverage: 429 rate-limit mapping, no-refresh on login/MFA/refresh,
status→kind mapping, 422 field-issue extraction, internal-detail leakage.

### 5.2 Real HTTP integration — 10 tests, all passing

`npm run test:integration` — runs the **real** frontend HTTP stack
(`apiClient` + interceptors + `tokenStore` + `auth.api`) against the **live**
FastAPI backend on `127.0.0.1:8000`. No mocks, no MSW. A separate Vitest
config with `environment: 'node'` is used so the same axios client the browser
uses is exercised, only the origin differs.

| # | Test | Evidence |
| --- | --- | --- |
| 1 | `logs in, stores opaque tokens in memory and returns the current user` | Real login → non-empty tokens → `session_id` present → token has no `.` (not a JWT) → `GET /auth/me` returns the user and their roles |
| 2 | `rejects a wrong password with 401 and no tokens` | Raw POST → 401; the axios client normalises it to `kind: 'unauthorized'` and does **not** attempt a refresh on the login endpoint; the store stays empty |
| 3 | `issues no tokens on the challenge and only authenticates after verification` | `mfa_required: true`, `access_token === ""`, `refresh_token === ""`, `session_id` present; the store still holds no token; a wrong OTP is rejected with 401; the real SMTP-delivered OTP verifies and returns a **different** session id; `GET /auth/me` then returns `SECURITY_ADMIN` |
| 4 | `rotates BOTH tokens and invalidates the old refresh token` | Refresh → new access **and** new refresh token, both different from the old; replaying the old refresh token → 401; the new access token → 200 on `/auth/me` |
| 5 | `triggers EXACTLY ONE refresh for concurrent 401 responses` | 5 parallel `GET /auth/me` with a poisoned access token → all 5 succeed; the server-side `audit_logs` row count for `refresh_session` grows by exactly **1**; the store holds the rotated pair |
| 6 | `clears the session when the refresh itself fails` | Invalid access + invalid refresh → `kind: 'unauthorized'`; the access and refresh tokens are both `null` afterwards |
| 7 | `revokes the session so the token is rejected afterwards` | `/auth/me` → 200 before logout; `POST /auth/logout` → `{status: "ok"}`; the same access token → **401** afterwards |
| 8 | `maps backend roles to the canonical landing route` | `landingPathFor()` on the roles returned by `/auth/me` yields `/alerts` for `SOC_ANALYST` |
| 9 | `enforces RBAC server-side: an analyst gets 403 on admin routes` | Analyst + `GET /admin/users` → **403**; analyst + `GET /alerts` → **200** |
| 10 | `allows the Vite dev origin and rejects an unknown origin` | Preflight from `http://localhost:5173` → `access-control-allow-origin: http://localhost:5173`; preflight from `http://evil.example.com` → **no** allow-origin header |

The MFA OTP is captured by a local SMTP sink on `127.0.0.1:1025` (the
backend's default `MFA_SMTP_HOST`/`MFA_SMTP_PORT`), which mirrors what
Mailpit does in the documented deployment. The sink lives in `/tmp` and is
**not** part of the repository.

### 5.3 Browser verification against the real backend

Driven through the Cursor IDE browser against the Vite dev server
(`http://localhost:5173`) proxying to the live FastAPI backend:

| Step | Observed |
| --- | --- |
| Open `/login` | Login form renders |
| Submit `m12analyst` / valid password | Redirected to `/alerts`; sidebar shows `m12analyst` with roles `SOC_ANALYST · USER` (read from `/auth/me`, not guessed) |
| `localStorage` / `sessionStorage` / `document.cookie` after login | `[]` / `[]` / `""` — **no token anywhere outside memory** |
| Reload the page | Redirected back to `/login` — the in-memory session is gone, a new login is required |
| Submit `m12admin` (MFA user) | Redirected to `/mfa`, code input shown — **not** authenticated |
| Submit the SMTP-delivered OTP | Redirected to `/admin/users`; sidebar shows `SECURITY_ADMIN · USER`; the admin-only items (Người dùng, Nhật ký kiểm toán) appear |
| Storage after MFA | still empty |
| Click "Đăng xuất" | Redirected to `/login`; the `sessions` row in PostgreSQL shows `revoked_at IS NOT NULL` for that session |

### 5.4 Acceptance gates

> *(Cập nhật ở final review: số liệu dưới đây là của Stage 0–2. Kết quả cuối
> cùng sau final review nằm ở `frontend/M12-STAGE-3-REPORT.md` §11.4.)*

| Gate | Command | Result |
| --- | --- | --- |
| TypeScript strict | `npx tsc -b` | **PASS** (no errors) |
| ESLint | `npx eslint .` | **PASS** (0 problems) |
| Unit / component tests | `npm run test` | **PASS** — 46/46 |
| Production build | `npm run build` | **PASS** — 176 modules, `dist/` emitted |
| Real API integration | `npm run test:integration` | **PASS** — 10/10 |
| Backend regression | `python3 -m pytest -q` | **PASS** — 729 passed, 60 skipped, 0 failed (23.75 s) |
| Backend untouched | `git diff HEAD -- app/ tests/ scripts/ docs/` | **empty** |
| M12 doc drift | `python3 scripts/check_m12_docs_drift.py` | **OK — docs match the live backend** |

---

## 6. Remaining risks

1. **In-memory sessions are lost on reload.** By design (the security
   requirement), but it is a UX cost: every browser refresh asks the user to
   log in again, and the MFA OTP must be re-entered. A silent-refresh
   bootstrap via a short-lived, non-HttpOnly-protected mechanism would
   change the security posture and needs an explicit decision.
2. **The MFA challenge is bound to the transaction id, not to a cookie.** If
   the user opens two tabs, the second tab's login overwrites the first
   tab's pending transaction in the shared in-memory store. Acceptable for
   Stage 0–2, worth revisiting when the app grows multi-tab usage.
3. **Stage 3+ screens are placeholders.** `alerts`, `admin/users`,
   `sessions`, `devices`, `policies`, `manager/*` render a placeholder that
   states the infrastructure is ready. The route table, guards and
   navigation model already match the 24-screen page map.
4. **`/auth/me` is fetched once per session.** Role changes made by an admin
   while a user is signed in are only picked up on the next login or a
   manual refetch. The backend resolves roles from the database in
   real-time, so this is a client-refresh policy question, not a contract
   gap.
5. **The integration suite needs a live backend and a PostgreSQL CLI.** It
   resets the `rate_limits` login row between tests and reads the
   `audit_logs` table to prove single-flight refresh. That makes it
   unsuitable for a hermetic CI job as written; it should run against a
   disposable deployment (the documented `scripts/deploy_local.sh` path) in
   CI, or be refactored to observe the refresh count via the network
   interceptor instead of the database.
   *(Đã xử lý ở final review: job `frontend-integration` trong
   `.github/workflows/ci.yml` dựng PostgreSQL disposable, seed fixture,
   chạy SMTP sink + uvicorn thật, rồi chạy `npm run test:integration`.
   Xem `frontend/M12-STAGE-3-REPORT.md` §11.3.)*
6. **The login rate limit (5 per minute per IP) bites during local
   development.** The integration harness works around it; a human
   developing against the proxy will see `429` after 5 rapid attempts.
   The frontend maps it to `kind: 'rate_limited'` and shows a dedicated
   message, which is the correct behaviour.
7. **`LogoutResponse.status` is `"ok"`, not `"success"`.** The frontend type
   documents the literal value; the integration test asserts it, so a
   backend change to that string would fail the integration test rather
   than silently drift.
8. **Only the Core auth surface is implemented.** Device trust, alert
   actions, policy CRUD and manager analytics are Stage 3+ work.

---

## 7. Status

**READY FOR M12 STAGE 0–2 REVIEW.** *(Trạng thái tại Stage 0–2; xem §11 của
`frontend/M12-STAGE-3-REPORT.md` cho trạng thái sau final review.)*

- Phase A is complete and independent: the five planning documents are
  committed on `feature/m12-frontend-planning` (`cd5b2a8`), pushed, and
  open as **PR #18 into `dev`**. It has **not** been merged.
   410|- The Stage 0–2 frontend implementation is complete, builds, lints, type-checks,
  passes 46 unit/component tests, passes 10 real-HTTP integration tests against
  the live FastAPI backend, and leaves the backend regression suite green
  (729 passed, 60 skipped).
- The implementation is **not committed and not pushed**, per the instruction
  to wait for lead review. It sits as untracked files in `frontend/` on
  `feature/m12-frontend-foundation`.
- `feature/m12-frontend-foundation` is based on `cd5b2a8` (the planning
  commit on top of the baseline `c89bff5`), so the implementation inherits
  the reviewed contract documents.

> **Cập nhật sau final review (Stage 0–3):**
> - **PR #18 đã được merge vào `dev`** (merge commit `113159a`), CI xanh.
> - Frontend đã được commit trong
>   `feat(frontend): implement authentication and user self-service flows`
>   và push lên `feature/m12-frontend-foundation`.
> - PR Stage 0–3 → `dev` đã được mở, **không** tự merge.
> - Số liệu kiểm thử cuối: 128 unit/component test, 23 real-HTTP integration
>   test, backend 1189 passed / 0 failed / 0 skipped, HTTP smoke 79/79.
