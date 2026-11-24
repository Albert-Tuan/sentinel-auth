# M12 Stage 4 — SOC Alerts (Alert Queue + Alert Detail)

**Baseline:** `origin/dev` @ `6839be70ccb60ffa1abd52cb4e6504d0a68c80a4`
**Branch:** `feature/m12-soc-alerts`
**Scope:** Stage 4 — READ ONLY. No Stage 5 mutation (acknowledge / resolve / assign / actions) is exposed by the UI.
**Status:** **READY** (pending lead review — not committed, not pushed, not merged)

---

## 1. Screens and components

### Screens

| Screen | Path | Route page key | Component |
|---|---|---|---|
| S-20 — SOC Alert Queue | `/alerts` | `alerts` | `frontend/src/features/alerts/pages/AlertQueuePage.tsx` |
| S-21 — SOC Alert Detail | `/alerts/:id` | `alert-detail` | `frontend/src/features/alerts/pages/AlertDetailPage.tsx` |

Both routes are wired into `IMPLEMENTED_PAGES` in `frontend/src/app/router/routes.tsx`. The centralized route policy in `frontend/src/app/router/policy.ts` was **not** changed — the pre-existing `alerts` section already declared `roles: [SOC_ANALYST, SECURITY_MANAGER]`, so the frontend keeps denying `SECURITY_ADMIN` and `USER` while the backend keeps enforcing the truth.

### New components

| Component | File | Purpose |
|---|---|---|
| `AlertTable` | `features/alerts/components/AlertTable.tsx` | `DataTable` wrapper: risk badge, status badge, detection reason, username, IP, assignee, created time. Row click → `/alerts/:id`. |
| `AlertFilters` | `features/alerts/components/AlertFilters.tsx` | Filter bar: status, risk level, assignee UUID, reset. Only canonical vocabularies are offered. |
| `AlertEvidencePanel` | `features/alerts/components/AlertEvidencePanel.tsx` | Login attempt details, risk assessment (rule/ML), rule hits, ML reason codes. |
| `DetectionLogTable` | `features/alerts/components/DetectionLogTable.tsx` | Stage, stage detail, rule name, triggered, score contribution, decision, reason, timestamp. |
| `TimelineFeed` | `features/alerts/components/TimelineFeed.tsx` | Audit trail: event type badge, actor, old → new transition, comment, IP, timestamp. |

### Shared components reused (no duplication)

`DataTable`, `Pagination`, `EmptyState`, `ErrorState`, `Spinner`, `Badge` — all reused as-is from `frontend/src/shared/components/`.

### New shared components

| Component | File | Purpose |
|---|---|---|
| `RiskBadge` | `shared/components/RiskBadge.tsx` | Maps `low / medium / high / critical` to semantic tones + Vietnamese labels. |
| `StatusBadge` | `shared/components/StatusBadge.tsx` | Maps `open / acknowledged / resolved / false_positive` to semantic tones + Vietnamese labels. |
| `riskLevels.ts` / `alertStatuses.ts` | `shared/components/` | Canonical constant lists + types, split out so the badge files stay Fast-Refresh clean. |

### Small change to an existing shared component

`frontend/src/shared/components/DataTable.tsx` gained an optional `onRowClick?: (row: T) => void`. When present, the row gets `role="button"`, `tabIndex={0}` and `Enter`/`Space` keyboard handlers. The prop is optional, so every existing consumer is unaffected.

---

## 2. API contract mapping

All four endpoints exist in the backend already (`app/alerts.py`) and were **not** modified.

| UI surface | Endpoint | Backend handler | Request parameters |
|---|---|---|---|
| Queue | `GET /alerts` | `list_alerts` | `status`, `risk_level`, `assigned_to_id`, `page` (≥1), `limit` (1–100) |
| Detail overview | `GET /alerts/{id}` | `get_alert` | — |
| Evidence | `GET /alerts/{id}/evidence` | `get_alert_evidence` | — |
| Timeline | `GET /alerts/{id}/timeline` | `get_alert_timeline` | — |

Responses are typed in `frontend/src/types/api.ts` against the real Pydantic schemas (`AlertItem`, `AlertListResponse`, `AlertEvidence`, `TimelineEvent`). The M12 OpenAPI spec was the source of truth; no field was inferred.

### Vocabularies (taken from the backend, not guessed)

- **Alert status:** `open`, `acknowledged`, `resolved`, `false_positive`.
  `escalated` is a *timeline event type*, not an alert status — the frontend types keep them apart.
- **Risk level:** `low`, `medium`, `high`, `critical`.
- **Timeline event type:** `created`, `assigned`, `unassigned`, `acknowledged`, `escalated`, `note_added`, `status_changed`, `resolved`, `false_positive`.
- **ML status** (`risk_assessments.ml_status`): `success`, `unavailable`, `error`.

### Type drift corrected in `frontend/src/types/api.ts`

`AlertStatus` and `TimelineEventType` previously carried values the backend never emits. They were realigned with the canonical vocabularies. `AlertItem.login_attempt_id` was widened to a real `string` (not `number`), `risk_level` and `detection_scores` were made nullable exactly as the backend declares them, and `LoginAttemptItem` was realigned with the `login_attempts` schema (`timestamp`, `status`, …).

### Alert subject enrichment

`GET /alerts` returns the `login_attempt_id` but not the username/IP — those columns live on `login_attempts` in the Detection DB. The queue enriches them with one extra request to `GET /api/v1/login-attempts` (same role gate: `SOC_ANALYST`, `SECURITY_MANAGER`), matched on `login_attempt_id`. The enrichment is best-effort: if it fails, the queue still renders the alerts without a subject rather than blocking the whole table. No fake subject is ever displayed.

### URL as state

`useSearchParams` mirrors `status`, `risk_level`, `assigned_to_id`, `page`, `limit` into the query string, so a queue URL is shareable and survives a refresh. Changing any filter resets `page` to `1`. The client never re-sorts the rows: the newest-first order is the backend's (`Alert.created_at.desc()`).

---

## 3. Test results

### Frontend unit / component tests

```
 Test Files  13 passed (13)
      Tests  193 passed (193)
```

Baseline was 139 tests; Stage 4 adds 54:

| Suite | Tests | Covers |
|---|---|---|
| `features/alerts/alertQueue.test.tsx` | 20 | Rendering, status/risk/assignee filters, pagination, empty state, invalid filter → 400, 401/403/404, URL deep-link + refresh, ordering, no `/api/v1/internal/*` call. |
| `features/alerts/alertDetail.test.tsx` | 19 | Overview, evidence, timeline, nullable ML score, rule-only fallback, missing/unknown alert → 404. |
| `features/alerts/alertAuthorization.test.tsx` | 15 | `SOC_ANALYST` / `SECURITY_MANAGER` allowed, `SECURITY_ADMIN` / `USER` denied, anonymous → `/login`. |

### Real HTTP integration tests (no MSW, no mocks)

```
 Test Files  3 passed (3)
      Tests  49 passed (49)
```

| File | Tests | Scope |
|---|---|---|
| `src/test/integration/realBackendAlerts.test.ts` | 26 | **New** — list / detail / evidence / timeline, filters, pagination, empty page beyond the last one, nullable ML score, RBAC with the four real roles, no internal endpoint. |
| `src/test/integration/realBackendDevices.test.ts` | 13 | Pre-existing — no regression. |
| `src/test/integration/realBackend.test.ts` | 10 | Pre-existing MFA handshake (real SMTP hop) — no regression. |

The suite runs against a live `uvicorn` on `127.0.0.1:8000` backed by a disposable PostgreSQL, using the real axios client, the real in-memory `tokenStore` and the real RBAC layer.

### Backend pytest (PostgreSQL)

```
1189 passed in 85.45s (0:01:25)
```

0 failed, 0 skipped.

### M10 HTTP smoke

```
HTTP SMOKE: 79 passed, 0 failed
```

### TypeScript, ESLint, production build

| Check | Result |
|---|---|
| `tsc -b` (strict) | pass, 0 errors |
| `eslint .` | pass, 0 errors, 0 warnings |
| `npm run build` | pass — `vite v7.3.8`, 201 modules, built in 1.21s |

---

## 4. Real HTTP evidence

The integration run was performed locally against a real stack:

```
podman exec sentinel-pg psql -U sentinel -d sentinel_detection_test   # schema present
python scripts/ci_seed_frontend_users.py                              # 4 role fixtures
python scripts/ci_seed_frontend_alerts.py                             # 3 alert fixtures
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000          # real backend
npm run test:integration                                               # 49 passed
```

### Seeded fixtures (`scripts/ci_seed_frontend_alerts.py`, idempotent, `--cleanup` supported)

| Fixture | Status | Risk level | Purpose |
|---|---|---|---|
| `critical` | `open` | `critical` | Fully scored alert, `ml_status = success`. |
| `ruleless` | `open` | `medium` | Rule-only fallback, `ml_score IS NULL`, `ml_status = unavailable`. |
| `low` | `acknowledged` | `low` | An alert that already left the `open` state. |

Each fixture ships with its login attempt, risk assessment, detection logs and timeline events, and carries the marker `m12-stage4-fixture` in `detection_reason` so the suite can identify its own rows.

### Observed evidence

- **List** — `GET /api/v1/alerts` answers 200 with `{ alerts, total, page, limit }`; every row carries `id`, `login_attempt_id`, `status`, `created_at`, `updated_at`.
- **Ordering** — the rows arrive newest-first straight from the backend; the client does not re-sort.
- **Filters** — `?status=open` and `?risk_level=critical` are applied by the backend; `?assigned_to_id=<unknown uuid>` returns an empty page rather than an unfiltered list.
- **Invalid filters** — `?status=bogus` → **400**, `?risk_level=bogus` → **400** (backend validation, not an empty list).
- **Pagination** — `?page`/`?limit` are server-side; a page beyond the last one returns an empty `alerts` array with the real `total`.
- **Detail / evidence / timeline** — all three endpoints answer 200 for a seeded alert and **404** for an unknown UUID.
- **Nullable ML score** — the rule-only fixture returns `ml_score = null` (and **not** `0`), `rule_score` is a real number, `ml_status = unavailable`. The fully scored fixture returns a numeric `ml_score` with `ml_status = success`. The UI renders "Không có dữ liệu" for `null` and `0.0000` for a real zero — the two are never conflated.
- **Internal boundary** — the alert client only ever builds URLs from `ENDPOINTS.alerts`; the test asserts that no path contains `/internal/`.

### Bug found and fixed during the real run

The first real run returned **5 failures**: every RBAC case answered 401 instead of 200/403. Root cause was in the *test*, not in the product code: `rawGet()` built its own `fetch` call but never attached the bearer token from the in-memory `tokenStore`, so every "authenticated" request went out anonymous. The helper now reads the token from the store (an explicit token still overrides it, which is how the anonymous case is exercised). After the fix: 49/49 pass.

---

## 5. Authorization verification

### Frontend (centralized route policy — unchanged)

`frontend/src/app/router/policy.ts` declares for the `alerts` section:

```ts
access: 'roles',
roles: [UserRole.SOC_ANALYST, UserRole.SECURITY_MANAGER],
```

| Role | Frontend route | Backend `GET /alerts` (real HTTP) |
|---|---|---|
| `SOC_ANALYST` | allowed | **200** — data returned |
| `SECURITY_MANAGER` | allowed | **200** — data returned |
| `SECURITY_ADMIN` (no SOC role) | denied → forbidden screen | **403** |
| `USER` | denied → forbidden screen | **403** |
| Anonymous | redirect to `/login` | **401** |

The backend gate is `require_roles("SOC_ANALYST", "SECURITY_MANAGER")` on all four read endpoints, so the detail and evidence endpoints deny the same way — verified over real HTTP for `USER` on both `/alerts` and `/alerts/{id}`.

The `SECURITY_ADMIN` denial is genuine, not a UI fiction: the admin fixture signs in through the **real MFA handshake** (real SMTP hop, OTP read back from the capture file) so the request carries a fully authenticated admin token, and the backend still answers 403.

### Route authorization tests

`frontend/src/features/alerts/alertAuthorization.test.tsx` — 15 tests covering the allowed roles, the denied roles, the anonymous redirect and the landing route for an analyst.

---

## 6. Known risks

1. **Alert subject enrichment is a second request.** The queue needs one extra call to `GET /api/v1/login-attempts` to show username/IP. It is best-effort: a failure degrades the subject column to "—" instead of breaking the queue. On a very large queue this is one extra round-trip per page — acceptable now, worth revisiting if the queue grows.
2. **`assigned_to_id` is a raw UUID field.** The backend exposes no "list of assignees" endpoint in Stage 4, so the filter is a UUID text input. A dropdown would need a new endpoint (out of scope) — Stage 5 candidate.
3. **The alert list is not searchable by free text.** `GET /alerts` supports only `status`, `risk_level` and `assigned_to_id`; no `q` parameter exists. The UI does not fake a search box.
4. **psycopg3 compatibility is a known issue, out of scope.** All CI integration paths keep `postgresql+psycopg2://` because psycopg3 returns `ipaddress.IPv4Address` for an `INET` column, which the `str` response model rejects with a 500. The backend was **not** modified.
5. **Real HTTP integration is CI-dependent.** The suite needs a live PostgreSQL, a live `uvicorn` and an SMTP sink for the MFA handshake. It is excluded from the default hermetic unit run (`vitest.integration.config.ts`, `environment: 'node'`).
6. **Stage 5 mutations are deliberately absent.** `acknowledge`, `resolve`, `assign`, `actions` and the timeline `POST` exist in `ENDPOINTS.alerts` but are **not** called by any Stage 4 code — the queue and the detail are strictly read-only.

---

## 7. READY / NOT READY

### READY

- All acceptance criteria are met:

| Criterion | Result |
|---|---|
| 139 existing frontend tests still pass | ✅ 193 passed (139 baseline + 54 new), 0 failed |
| New Stage 4 tests | ✅ 54 unit + 26 real HTTP integration |
| 23 existing real HTTP integration tests, no regression | ✅ 23 passed (13 + 10) |
| Backend PostgreSQL ≥1189 passed | ✅ 1189 passed, 0 failed, 0 skipped |
| M10 HTTP smoke 79/79 | ✅ 79 passed, 0 failed |
| TypeScript strict | ✅ 0 errors |
| ESLint | ✅ 0 errors, 0 warnings |
| Production build | ✅ pass |
| GitHub Actions 4/4 jobs | ⏳ pending — the CI workflow was updated (alert fixture seeding + the three extra role passwords); it must be run on the remote to confirm. |

- S-20 and S-21 are fully functional against real FastAPI/PostgreSQL data.
- The authorization contract holds on both sides, proven with the four real roles over real HTTP.
- No Stage 5 mutation is exposed.
- No fake or hard-coded alert data appears in the production UI.

### NOT READY

- **GitHub Actions has not been executed on the remote** for this branch. The workflow changes are in place and mirror the locally verified procedure, but the 4/4 green badge still has to be observed.
- **No commit, no push, no merge** — per the delivery rule, the branch is left with the work in the working tree for lead review.

---

## Changed files

```
 M .github/workflows/ci.yml
 M frontend/src/app/router/routes.tsx
 M frontend/src/shared/components/DataTable.tsx
 M frontend/src/types/api.ts
?? frontend/src/features/alerts/
?? frontend/src/lib/api/alerts.api.ts
?? frontend/src/lib/api/loginAttempts.api.ts
?? frontend/src/shared/components/RiskBadge.tsx
?? frontend/src/shared/components/StatusBadge.tsx
?? frontend/src/shared/components/alertStatuses.ts
?? frontend/src/shared/components/riskLevels.ts
?? frontend/src/test/integration/realBackendAlerts.test.ts
?? scripts/ci_seed_frontend_alerts.py
```
