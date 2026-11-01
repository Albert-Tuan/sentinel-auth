# M9 — Security Manager Analytics: Design (v3.3)

**Owner:** Khang (ML / Analytics bounded context)
**Branch:** `feature/manager-analytics-m9`
**Status:** DESIGN — pending lead approval. No M10 code in this branch.
**Milestone:** M9 (design) → M10 (implementation)
**Companion:** `docs/M9-MANAGER-ANALYTICS-REFERENCE.md` — SQL sketches for the internal aggregate
endpoints and the canonical vocabulary reference. This document is normative; the reference
document is implementation material.

---

## 1. Scope and goals

Five public, read-only endpoints for the `SECURITY_MANAGER` role:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/manager/dashboard` | Security overview snapshot (Core posture + Detection activity + ML health) |
| GET | `/api/v1/manager/trends` | Time-series trends bucketed by hour/day |
| GET | `/api/v1/manager/alerts` | Alert statistics (backlog, FPR, MTTA/MTTR) |
| GET | `/api/v1/manager/soc-kpi` | SOC effectiveness KPIs |
| GET | `/api/v1/manager/ml-stats` | ML model / inference analytics |

### 1.1 Hard constraints (from the assignment + system decisions)

| Constraint | How this design satisfies it |
|---|---|
| Manager RBAC = `SECURITY_MANAGER` | All 5 routes guarded by `require_roles("SECURITY_MANAGER")` |
| Core & Detection data only via internal HTTP contract | Manager reads them **only** through `X-Internal-Secret` calls to new internal aggregate endpoints. No direct `sentinel_core` / `sentinel_detection` queries from Manager code. |
| ML statistics from `sentinel_ml` | Manager queries `sentinel_ml` directly via `get_ml_db` — Manager lives in the ML/Analytics context, so this is an in-domain read. |
| Reuse existing APIs/models; add internal endpoints only when genuinely missing | Only **2** new internal endpoints, because no existing endpoint returns server-side aggregates (see §4) |
| No new DB tables, no Redis, no ML inference changes | Zero schema changes. No cache layer. `app/ml.py` inference path untouched. |
| Minimal design, monolith-compatible, boundaries preserved | Manager is a read-only facade over existing contracts; each domain still owns its own data and its own SQL. |

### 1.2 Explicit non-goals

* No CSV/PDF export (UC-25 export deferred — no format/queueing decision is in scope for M10).
* No manager approval queue (explicitly out of scope in `DECISIONS-SYSTEM-v3.3.md` §9.1).
* No policy mutation, no alert mutation — Manager endpoints are read-only.
* No caching layer (no Redis, no in-process TTL cache). Every request re-aggregates.
* No new ML inference behaviour, no model registry changes.

> **`manager_dashboard` stays a commented-out view.** `infra/postgres/schema-ml-service-v3.3.sql` (lines ~200–260) contains a commented-out `CREATE OR REPLACE VIEW manager_dashboard` that joins `login_attempts` and `alerts` — tables that live in `sentinel_detection`, not `sentinel_ml`. It is **documentation of a hypothetical single-database world**, not an implementation, and it **must not** be un-commented or ported. The only real view in `sentinel_ml` is `local_ml_stats`, which aggregates `inference_logs` alone. This design keeps it that way: no view, no table, no cross-database join.

### 1.3 Coverage of the assignment's Manager responsibilities

The assignment lists eight Manager responsibilities. This is how each one is served — all of them land on the **five** endpoints; no sixth endpoint is proposed.

| Assignment responsibility | Served by | Notes |
|---|---|---|
| Security overview dashboard | `GET /manager/dashboard` | Core posture + Detection activity + ML health, one snapshot |
| Risk trend visibility | `GET /manager/trends` | Risk level, outcome, alert and anomaly series over time |
| High/critical incident overview | `GET /manager/dashboard` → `detection.critical_incidents` | Top-N open high/critical alerts with the subject and the reason |
| SOC effectiveness / KPI reporting | `GET /manager/soc-kpi` | 12 KPIs (§5) |
| Alert backlog statistics | `GET /manager/alerts` → `backlog` | Open count, oldest open age, unassigned, escalated |
| False-positive statistics | `GET /manager/alerts` → `false_positive_rate`; `GET /manager/soc-kpi` | FPR with its numerator/denominator exposed |
| Audit / security activity review | `GET /manager/dashboard` → `core.audit_activity` | Activity breakdown + a short recent-activity feed |
| Policy configuration view-only | **Already satisfied** by `GET /api/v1/policies` (`SECURITY_ADMIN` + `SECURITY_MANAGER`) | Reused as-is; no new endpoint, no change. The dashboard additionally reports the **active policy version** (`detection.policy`), which is the time-scoped complement to the policy configuration list |
| ML / model analytics | `GET /manager/ml-stats` | Registry, inference stats, reason codes, feature drift |

### 1.4 Use-case traceability

| Use case | Actor | Endpoint | Status |
|---|---|---|---|
| UC-19 Xem bảng điều khiển SOC | Security Manager | `GET /manager/dashboard` | New in M10 |
| UC-25 Xuất báo cáo tổng hợp | Security Manager | The 5 endpoints, consumed as a JSON report | New in M10 (no file export — §1.2) |
| UC-23 Xem nhật ký kiểm toán | Security Manager | `GET /manager/dashboard` → `core.audit_activity` | New in M10 (read-only feed, not the admin page) |
| UC-12 Xem danh sách cảnh báo | Security Manager | `GET /api/v1/alerts` | **Existing** — reused, not duplicated |
| UC-20 Quản lý chính sách (view only) | Security Manager | `GET /api/v1/policies` | **Existing** — reused, not duplicated |

UC-24 (phê duyệt leo thang) stays a FUTURE ENHANCEMENT and is deliberately absent — `DECISIONS-SYSTEM-v3.3.md` §9.1 states there is no mandatory Manager approval workflow in v3.3.

---

## 2. Where the code lives (bounded contexts)

```
sentinel_core          sentinel_detection            sentinel_ml
(Core / IAM)           (Detection + SOC)              (ML / Analytics)
   |                        |                             |
   | GET /api/v1/internal/analytics/core                  |
   | (app/core_analytics.py — Core context)                |
   |                        | GET /api/v1/internal/analytics/detection
   |                        | (app/detection_analytics.py — Detection context)
   |                        |                             |
   +------------------------+-----------------------------+
                            |
                    app/manager.py  (Manager facade — ML/Analytics context)
                    app/manager_client.py (outbound internal HTTP client)
                            |
                    GET /api/v1/manager/*   (public, bearer + RBAC)
```

* **Manager facade** (`app/manager.py`) owns **no** table of its own. It orchestrates three sources:
  * `core` — HTTP → Core internal aggregate endpoint.
  * `detection` — HTTP → Detection internal aggregate endpoint.
  * `ml` — direct read of `sentinel_ml` (own context).
* Each upstream domain keeps full ownership of its SQL. Manager never sees a `sentinel_core` or `sentinel_detection` table.

---

## 3. Public API contract

### 3.1 Common envelope

Every response uses the same envelope so the UI can render partial state consistently.

```json
{
  "generated_at": "2026-10-31T16:00:00+00:00",
  "window": { "from": "2026-10-30T16:00:00+00:00", "to": "2026-10-31T16:00:00+00:00" },
  "degraded": false,
  "sources": {
    "core":      { "status": "ok", "detail": null },
    "detection": { "status": "ok", "detail": null },
    "ml":        { "status": "ok", "detail": null }
  }
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `generated_at` | ISO-8601 UTC | Server time the response was produced |
| `window.from` / `window.to` | ISO-8601 UTC | Effective window actually used (echoes defaults) |
| `degraded` | bool | `true` when **at least one** source failed |
| `sources.<name>.status` | `"ok" \| "unavailable"` | Per-source availability |
| `sources.<name>.detail` | string \| null | Machine-readable reason code, never an internal URL or stack trace |

Source `detail` codes: `not_configured`, `unreachable`, `timeout`, `http_<code>`, `invalid_payload`,
`database_error`, `internal_error` — the closed vocabulary is defined in §6.1.1.

`sources` lists **exactly the sources the endpoint consumes** — never a source that is not rendered:

| Endpoint | `sources` keys | Rendered sections | Section(s) `null` when the source is down |
|---|---|---|---|
| `/dashboard` | `core`, `detection`, `ml` | `core`, `detection`, `ml` | the one belonging to the failed source |
| `/trends` | `detection`, `ml` | `series.login_attempts`, `series.alerts`, `series.ml` | Detection down → `series.login_attempts` **and** `series.alerts`; ML down → `series.ml` |
| `/alerts` | `detection` | the whole body | the whole body (and the response is a **503**, since it is the only source) |
| `/soc-kpi` | `detection`, `core` | `kpis` | the KPI groups belonging to the failed source (§6.1) |
| `/ml-stats` | `ml` | the whole body | the whole body (and the response is a **503**, since it is the only source) |

### 3.2 Common query parameters

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `from` | ISO-8601 datetime | endpoint-specific (see §3.3–3.7) | Interpreted as **UTC** |
| `to` | ISO-8601 datetime | now (UTC) | Half-open window: `[from, to)` |
| `bucket` | `hour` \| `day` | auto | Only on `/trends` (see §3.4) |
| `status` | `open`\|`acknowledged`\|`resolved`\|`false_positive` | none | Only on `/alerts` |
| `risk_level` | `low`\|`medium`\|`high`\|`critical` | none | Only on `/alerts` |

Rules (all violations → **HTTP 400**):

1. `from` must be strictly earlier than `to`.
2. Maximum window = **366 days**.
3. `bucket=hour` requires a window ≤ 31 days; `bucket=day` requires ≤ 366 days.
4. Maximum number of buckets = **400** (hour) / **366** (day).
5. `bucket=auto` resolves to `day` when the window > 72 h, else `hour`.
6. Timestamps are normalised to timezone-aware UTC (`app.time_utils.as_utc`); naive input is treated as UTC.
7. `status` / `risk_level` are validated against the canonical vocabularies — an unknown value is a 400, not an empty result (same policy as `app/alerts.py` and `app/login_history.py`).

Half-open `[from, to)` is used everywhere so consecutive windows never double-count a boundary instant.

The `status` / `risk_level` filters on `/alerts` select the **alert population** (the set of alerts created inside the window). They are applied before every breakdown, so `totals`, `by_status`, `by_risk_level`, `backlog` and all time KPIs describe the same filtered population. Filtering `status=open` therefore yields `totals.open == totals.created` and `by_status` with only `open` non-zero — this is intentional and predictable.

### 3.3 `GET /api/v1/manager/dashboard`

Overview snapshot. Default window: **last 24 hours**.

```json
{
  "generated_at": "...", "window": {...}, "degraded": false,
  "sources": { "core": {...}, "detection": {...}, "ml": {...} },

  "core": {
    "total_users": 120,
    "users_by_status": { "active": 100, "locked": 5, "suspended": 15 },
    "users_with_mfa_required": 30,
    "users_under_forced_mfa": 3,
    "new_users": 4,
    "users_with_failed_logins": 6,
    "active_sessions": 42,
    "sessions_created": 88,
    "sessions_revoked": 10,
    "mfa_challenges": 20,
    "mfa_completed": 16,
    "mfa_failed": 3,
    "audit_events": 45,
    "audit_activity": {
      "by_action": { "login_success": 20, "protective_action:REQUIRE_MFA": 3, "logout": 8 },
      "by_actor_type": { "user": 30, "system": 15 },
      "recent": [
        { "id": "…", "action": "protective_action:REQUIRE_MFA", "actor": "system",
          "resource": "user", "resource_id": "…", "created_at": "2026-10-31T15:40:00+00:00" }
      ]
    }
  } | null,

  "detection": {
    "login_attempts": 300,
    "by_outcome": { "success": 240, "failure": 30, "mfa_required": 12, "mfa_success": 9,
                    "mfa_failed": 3, "blocked": 4, "locked": 1, "rate_limited": 1 },
    "by_risk_level": { "low": 180, "medium": 80, "high": 30, "critical": 10 },
    "by_decision": { "allow": 250, "challenge": 38, "block": 12 },
    "avg_combined_score": 0.3121,
    "alerts": { "total": 20, "open": 5, "acknowledged": 3, "resolved": 9,
                "false_positive": 3, "critical_open": 2 },
    "critical_incidents": [
      { "alert_id": "…", "risk_level": "critical", "status": "open",
        "created_at": "2026-10-31T15:42:00+00:00",
        "subject": { "username": "d.anhtuan", "user_id": "…" },
        "detection_reason": "REQUIRE_MFA: combined=0.8123 (rule=0.6500, ml=0.9000)",
        "combined_score": 0.8123,
        "assigned_to": null, "age_hours": 0.3 }
    ],
    "enforcement": { "attempted": 10, "succeeded": 9, "success_rate": 0.9 },
    "ml_fallback": { "assessments": 300, "fallback": 4, "fallback_rate": 0.0133 },
    "policy": { "active_version": "v1", "active_policy_id": "…" }
  } | null,

  "ml": {
    "active_model_version": "v1.0-isolation-forest",
    "model_status": "ready",
    "inferences": 300,
    "anomalies": 36,
    "anomaly_rate": 0.12,
    "avg_processing_ms": 4.2,
    "daily": [ { "day": "2026-10-31", "total": 300, "anomalies": 36,
                 "successful": 297, "errors": 3, "degraded": 0,
                 "avg_processing_ms": 4.2, "avg_anomaly_score": 0.31 } ]
  } | null
}
```

`sources` in the example is abbreviated; the real envelope always carries the full `{ "status", "detail" }` pair for each source.

Rules: `core`, `detection`, `ml` are `null` when that source is unavailable. `alerts.*` counts alerts **created** inside the window — the one exception is `alerts.critical_open`, which is a system-wide **current-backlog** count and is neither window-scoped nor affected by the `status` / `risk_level` filters (§3.3, §4.0, §4.1). `by_outcome` / `by_risk_level` / `by_decision` always carry the full canonical key set (zero-filled) so the UI never has to handle missing keys.

* `core.users_*`, `core.active_sessions`, `core.users_with_mfa_required`, `core.users_under_forced_mfa` are **point-in-time**; `core.new_users`, `core.sessions_created`, `core.sessions_revoked`, `core.mfa_challenges`, `core.audit_events` and the whole `detection` + `ml` block are **window-scoped** (§5.1 rule 13).
* Two documented exceptions to "window-scoped" in the `detection` block: `detection.critical_incidents` is the **current open backlog** and is *not* filtered by the window (§3.3), and `detection.alerts.critical_open` is a system-wide **current-backlog** count (§4.1). Everything else in the `detection` block is window-scoped.
* `core.audit_activity` is window-scoped throughout — `by_action`, `by_actor_type` and the `recent` feed all use `[from, to)`.
* `detection.alerts.total` counts alerts **created** in the window; `detection.alerts.critical_open` counts alerts that are *currently* `open` **and** `risk_level = 'critical'` — **system-wide**, not restricted to the window. It is a different population from `detection.critical_incidents`, which is a top-10 list over `high` **and** `critical` alerts in `open` **and** `acknowledged` status, so the two numbers are not equal in general.
* `detection.avg_combined_score` is the mean of `risk_assessments.combined_score` over assessments in the window; `null` when there is none (never `0`).
* `ml.active_model_version` is the **artifact's** version string, read from the loaded bundle (`IsolationForestRuntime.version`), **not** the `model_versions.version` column. The two normally agree, but the artifact is the authoritative source for "which model is actually loaded". The registry row is reported separately on `/ml-stats` (`model`).
* `ml.model_status` is the **runtime** status — `ready` when the ML artifact loads, `error` when it does not. It is obtained by calling `app/ml.py::get_ml_runtime(db)` inside a `try`/`except`: success → `"ready"`, any exception → `"error"`. `get_ml_runtime` itself returns an `IsolationForestRuntime` object and has **no** status field; the status is the *outcome* of the call. This is the same logic as the `/api/v1/internal/ml/health` endpoint, which answers `{"status": "ok"|"degraded", "model_version": ..., "model_status": "ready"|"error"}`.
* **Two different `degraded` vocabularies.** The runtime status only ever takes the values `ready` and `error`. The value `degraded` belongs to a *different* field — `inference_logs.model_status` (§3.7), which is the per-inference outcome recorded in the database and may be `ready`, `degraded` or `error`. Do not conflate the two.
* `ml.daily` uses the `local_ml_stats` view; with a 24-hour window it normally holds 1–2 rows.
* If the ML **artifact** cannot be loaded (model file missing), `ml.model_status` becomes `"error"` and `ml.active_model_version` becomes `null`, but the **rest of the `ml` section still renders** — the inference statistics come from `sentinel_ml` and are unaffected. A missing artifact is a model problem, not a data-source outage.

#### `detection.critical_incidents` — the high/critical incident overview

This is the Manager's **triage list**: the alerts that still need a human, ordered by severity then age.

| Rule | Value |
|---|---|
| Population | Alerts with `risk_level IN ('high','critical')` **and** `status IN ('open','acknowledged')` — resolved and false-positive alerts are excluded |
| Window | **Not** window-scoped. It is the *current* open backlog, because an open critical alert from 3 days ago is still an open critical alert. The window parameter does not filter it |
| Limit | Top **10**, ordered by `risk_level` (critical first) then `created_at` ascending (oldest first — the most overdue) |
| `subject` | `login_attempts.username_attempted` + `login_attempts.user_id` (may be `null` for an unknown username) |
| `detection_reason` | `alerts.detection_reason` |
| `combined_score` | `risk_assessments.combined_score` for the alert's attempt; `null` if the assessment is missing |
| `assigned_to` | `soc_analysts.display_name` (or `null` when unassigned) |
| `age_hours` | `now − alerts.created_at`, rounded to 1 decimal |

Detection owns this query entirely — it joins `alerts`, `login_attempts`, `risk_assessments` and `soc_analysts`, all of which live in `sentinel_detection`. Manager never assembles it.

#### `core.audit_activity` — the audit / security activity review

| Field | Meaning |
|---|---|
| `by_action` | Count per `audit_logs.action` in the window |
| `by_actor_type` | Count per `actor_type` (`user` / `system`) in the window |
| `recent` | The **10 most recent** audit rows in the window, newest first: `id`, `action`, `actor`, `resource`, `resource_id`, `created_at` |

`actor` is resolved to the username by Core (it owns `users`); when `actor_id` is `null` the literal `actor_type` (`system`) is returned.

**Deliberately excluded** from `recent`: `before_state`, `after_state`, `ip_address`, `user_agent`. The Manager oversight feed needs to know *what happened and when*; the state payloads and network identifiers are materially more sensitive and are available on the `SECURITY_ADMIN` audit page (`GET /api/v1/admin/audit-logs`). Keeping them out means the Manager endpoint does not become a second, less-guarded copy of the admin page.

### 3.4 `GET /api/v1/manager/trends`

Default window: **last 14 days**, `bucket=auto`.

```json
{
  "generated_at": "...", "window": {...}, "bucket": "day",
  "degraded": false,
  "sources": { "detection": { "status": "ok", "detail": null },
               "ml":        { "status": "ok", "detail": null } },

  "series": {
    "login_attempts": [
      { "bucket_start": "2026-10-30T00:00:00+00:00",
        "total": 120,
        "by_outcome": { "success": 95, "failure": 15, "mfa_required": 4, "mfa_success": 3,
                        "mfa_failed": 1, "blocked": 2, "locked": 0, "rate_limited": 0 },
        "by_risk_level": { "low": 70, "medium": 32, "high": 13, "critical": 5 },
        "avg_combined_score": 0.29 }
    ],
    "alerts": [
      { "bucket_start": "2026-10-30T00:00:00+00:00",
        "total": 7,
        "by_status": { "open": 2, "acknowledged": 1, "resolved": 3, "false_positive": 1 } }
    ],
    "ml": [
      { "bucket_start": "2026-10-30T00:00:00+00:00",
        "total": 120, "anomalies": 14, "successful": 118, "errors": 1, "degraded": 0,
        "avg_processing_ms": 4.1, "avg_anomaly_score": 0.31 }
    ]  }
}
```
* `series.login_attempts` and `series.alerts` come from **Detection**; `series.ml` comes from **`sentinel_ml`**.
* **Shape rule:** the Detection internal endpoint returns **one flat series** (§4.1 `series`), and
  the facade **splits** it into the two public arrays. The mapping is normative and is repeated in
  the facade field-mapping table (§4.3):

  | Public array | Internal field |
  |---|---|
  | `series.login_attempts[*].total` | `series[*].login_attempts` |
  | `series.login_attempts[*].by_outcome` | `series[*].by_outcome` |
  | `series.login_attempts[*].by_risk_level` | `series[*].by_risk_level` |
  | `series.login_attempts[*].avg_combined_score` | `series[*].avg_combined_score` |
  | `series.alerts[*].total` | `series[*].alerts_created` |
  | `series.alerts[*].by_status` | `series[*].alerts_by_status` |

  Both public arrays carry the **same** `bucket_start` values, so a UI can join them on that key.
* The breakdown keys are **not** reduced on the public side: `by_outcome` and `by_risk_level` keep
  the full canonical key set (zero-filled), matching §3.3. The public contract therefore does not
  expose a partial subset of `by_outcome`.
* The ML series is **window-filtered** on every endpoint. With `bucket=day` it is a
  `date_trunc('day', created_at AT TIME ZONE 'UTC')` grouping over `inference_logs` — **not** a
  straight read of the `local_ml_stats` view, which has no window predicate (§3.7). The `/trends`
  ML series and the `/ml-stats` `daily` list must agree on the totals for any given day;
  `local_ml_stats` is used by `/ml-stats` only, and the two paths are reconciled in the test plan
  (§7.1). The explicit `AT TIME ZONE 'UTC'` is **mandatory** here — see the timezone rule in §6.4.
* With `bucket=hour` the ML series groups by `date_trunc('hour', created_at AT TIME ZONE 'UTC')`.
* The ML series fields are the `/ml-stats` `daily` fields (§3.7), renamed for the series
  position: `total`, `anomalies`, `successful`, `errors`, `degraded`, `avg_processing_ms`,
  `avg_anomaly_score`. The `errors` and `degraded` fields are the counts of
  `model_status = 'error'` and `model_status = 'degraded'` rows in the bucket — the
  **per-inference** vocabulary, distinct from the runtime status of §3.3.
* Buckets are **zero-filled**: every bucket in `[from, to)` is present, even with no data.
* Bucket start is the **floor** of the bucket in UTC (`hour` → `HH:00:00`, `day` → `00:00:00`).
* A whole series is `null` if its source is unavailable; the other series still render.

### 3.5 `GET /api/v1/manager/alerts`

Alert statistics (aggregate view; the row-level SOC list stays at `GET /api/v1/alerts`).
Default window: **last 30 days**.

Extra filters: `status` (`open|acknowledged|resolved|false_positive`), `risk_level` (`low|medium|high|critical`). Both optional; both validated against the canonical vocabularies (invalid → 400, same style as `app/alerts.py`).

```json
{
  "generated_at": "...", "window": {...}, "degraded": false,
  "sources": { "detection": { "status": "ok", "detail": null } },

  "totals": { "created": 120, "open": 12, "acknowledged": 8, "resolved": 90, "false_positive": 10 },
  "by_status": { "open": 12, "acknowledged": 8, "resolved": 90, "false_positive": 10 },
  "by_risk_level": { "low": 5, "medium": 20, "high": 55, "critical": 40 },
  "by_rule": [ { "rule": "multiple_failures", "count": 41 } ],
  "by_ml_reason": [ { "code": "high_fail_count", "count": 33 } ],
  "backlog": { "open_count": 12, "oldest_open_age_hours": 33.5, "unassigned": 4, "escalated": 3 },
  "false_positive_rate": 0.1,
  "mtta_seconds": 320.4,
  "mttr_seconds": 5401.2,
  "acknowledged_count": 108,
  "resolved_count": 90
}
```

Field semantics — the two "acknowledged" numbers are deliberately different:

| Field | Meaning |
|---|---|
| `totals.acknowledged` | alerts whose **current status** is `acknowledged` (8 — still open for work) |
| `acknowledged_count` | alerts with **at least one** `acknowledged` timeline event (108 — includes the 90 resolved + 10 false-positive ones that were acknowledged first) |
| `totals.resolved` / `resolved_count` | alerts whose current status is `resolved` (90) — the MTTR population |
| `totals.false_positive` | alerts whose current status is `false_positive` (10) |
| `false_positive_rate` | `10 / (90 + 10) = 0.1` |
| `backlog.open_count` | alerts still `open` (12) — equals `totals.open` |
| `backlog.unassigned` | open alerts with `assigned_to_id IS NULL` (4) |
| `backlog.escalated` | alerts with an `escalated` timeline event (3) |
| `backlog.oldest_open_age_hours` | `now − created_at` of the oldest still-open alert created in the window |
| `by_risk_level` | counts over the **whole** population, not only open alerts |
| `by_rule` | top 20 triggered detection rules, see the note below |
| `by_ml_reason` | top 20 ML reason codes, see the note below |

`totals.open + totals.acknowledged + totals.resolved + totals.false_positive` always equals `totals.created`, because the four statuses are mutually exclusive and exhaustive.

**Why there is no `by_detection_reason`.** `alerts.detection_reason` is written by the Detection worker as a formatted string:

```
"REQUIRE_MFA: combined=0.8123 (rule=0.6500, ml=0.9000)"
```

Its cardinality is unbounded — every distinct score produces a distinct string — so it cannot be grouped. The reasons are instead read from the structured payload the Detection worker already stores in `alerts.detection_scores`:

| Breakdown | Source | Vocabulary |
|---|---|---|
| `by_rule` | `alerts.detection_scores->'rule_hits'[].rule_name` | the **triggered** rules of the active policy (`unusual_hour`, `multiple_failures`, `new_device`, `high_deviation` in policy `v1.0`) |
| `by_ml_reason` | `alerts.detection_scores->'ml_reason_codes'[]` | the canonical ML reason codes of `app/ml.py::REASON_CODES` (`unusual_hour`, `high_fail_count`, `new_ip`, `new_device`, `behavioral_deviation`, `multiple_factors`) |

**The two breakdowns are independent vocabularies and may overlap.** `by_rule` names a *detection
rule* (policy-defined, `policies.rules[].name`); `by_ml_reason` names an *ML factor*
(`app/ml.py::REASON_CODES`). The code `unusual_hour` and the rule `unusual_hour` are **different
things that happen to share a name** — one comes from the rule engine, the other from the ML
runtime. A single alert may appear in both breakdowns. The two lists are therefore never merged,
never deduplicated against each other, and their counts are not expected to add up to
`totals.created`.

Both are **multi-valued**: one alert can trigger several rules and several ML reason codes, so the counts sum to more than `totals.created`. That is expected — it is a "reasons observed" breakdown, not a partition. A rule or code that cannot be read (missing key, malformed JSON) is skipped, never raises.

Both breakdowns are **top 20 by count, descending**, with ties broken by name for deterministic output.

**Where the vocabularies live.** The full canonical vocabulary table is in the reference document
§R2. Two entries are load-bearing for this section and are restated here:

| Vocabulary | Values | Source of truth |
|---|---|---|
| ML reason code | `unusual_hour`, `high_fail_count`, `new_ip`, `new_device`, `behavioral_deviation`, `multiple_factors` | `app/ml.py::REASON_CODES` |
| Detection rule name | policy-defined (e.g. `unusual_hour`, `multiple_failures`, `new_device`, `high_deviation`) | `policies.rules[].name` |

A `by_ml_reason` code outside the ML vocabulary, or a `by_rule` name not defined by the active
policy, is **skipped**, not raised — the same tolerance that applies to a malformed payload.

### 3.6 `GET /api/v1/manager/soc-kpi`

Default window: **last 30 days**.

```json
{
  "generated_at": "...", "window": {...}, "degraded": false,
  "sources": { "detection": { "status": "ok", "detail": null },
               "core":      { "status": "ok", "detail": null } },

  "kpis": {
    "mtta_seconds": 320.4,
    "mttr_seconds": 5401.2,
    "acknowledgement_rate": 0.9,
    "resolution_rate": 0.8333,
    "false_positive_rate": 0.1,
    "escalation_rate": 0.025,
    "alerts_per_analyst": 12.0,

    "enforcement_attempted": 40,
    "enforcement_succeeded": 38,
    "enforcement_success_rate": 0.95,

    "ml_assessments": 3000,
    "ml_fallback_count": 42,
    "ml_fallback_rate": 0.014,

    "mfa_enrollment_rate": 0.25,
    "forced_mfa_users": 3,
    "audit_events": 450
  }
}
```

All KPI values are `null` when their defining source is unavailable (see the KPI table in §5).

The example is consistent with the `/alerts` population (120 alerts created in the window): `acknowledgement_rate = 108/120 = 0.9`, `resolution_rate = (90+10)/120 = 0.8333`, `false_positive_rate = 10/100 = 0.1`, `alerts_per_analyst = 120/10 = 12.0`.

The `alerts_per_analyst` denominator is the **point-in-time** count of active analysts (10), which is
why it differs from the `analysts.active` figure in the `/dashboard` example — that one describes a
24-hour window, this one a 30-day window, and the number of active analysts changes over time.
`alerts_per_analyst` uses `analysts.active` read at query time (§5.1 rule 9), never a window-scoped
value.

Unlike `/alerts`, this endpoint has **no filters** — it always reports the whole window population. A filtered KPI report is what `/alerts` is for.

### 3.7 `GET /api/v1/manager/ml-stats`

Pure ML analytics from `sentinel_ml`. Default window: **last 30 days**.

```json
{
  "generated_at": "...", "window": {...}, "degraded": false,
  "sources": { "ml": { "status": "ok", "detail": null } },

  "model": {
    "active_version": "v1.0-isolation-forest",
    "status": "active",
    "is_production": true,
    "algorithm": "IsolationForest",
    "deployed_at": "2026-10-01T00:00:00+00:00",
    "trained_by": null
  } | null,

  "versions": [
    { "version": "v1.0-isolation-forest", "status": "active", "is_production": true,
      "training_date": "2026-09-28T00:00:00+00:00", "inferences": 4200 }
  ],

  "inference": {
    "total": 3000, "anomalies": 360, "anomaly_rate": 0.12,
    "avg_normalized_score": 0.31, "avg_processing_ms": 4.2, "p95_processing_ms": 9,
    "errors": 3, "degraded": 4
  },

  "by_status": { "ready": 2993, "degraded": 4, "error": 3 },

  "reason_codes": [ { "code": "high_fail_count", "count": 120 } ],

  "daily": [ { "day": "2026-10-31", "total": 300, "anomalies": 36,
               "successful": 297, "errors": 3, "degraded": 0,
               "avg_processing_ms": 4.2, "avg_anomaly_score": 0.31 } ],

  "features": [ { "feature_name": "fail_count_24h", "count": 3000, "mean": 1.21, "std": 0.83,
                  "min": 0, "max": 9, "p25": 0, "p50": 1, "p75": 2, "p95": 4,
                  "anomaly_rate": 0.12, "timestamp": "2026-10-31T00:00:00+00:00" } ]
}
```

* `daily` is served from the **real view** `local_ml_stats`, with an explicit fallback: the identical `GROUP BY` over `inference_logs` when the view is absent (e.g. SQLite unit tests).
* **Timezone caveat — the view is not UTC-safe by itself.** The view is defined as
  `DATE_TRUNC('day', created_at)`. `created_at` is `TIMESTAMP WITH TIME ZONE`, and `DATE_TRUNC`
  truncates it in the **session's** timezone — the database server default, which this codebase does
  **not** pin (`app/db.py` creates the engine with `create_engine(url, pool_pre_ping=True)` and no
  `connect_args` timezone). If the session timezone is not UTC, the view's `day` boundaries do not
  match the UTC bucket contract of §5.3.
  **The canonical computation is therefore the explicit UTC grouping over `inference_logs`:**

  ```sql
  SELECT date_trunc('day', created_at AT TIME ZONE 'UTC') AS day, ...
  FROM inference_logs
  GROUP BY 1
  ```

  The view may be used **only** when the session timezone is UTC, and the two paths must agree on
  the daily totals. §6.4 of the design document states the rule for the implementation.
* `daily` rows are **not** filtered by the window (the view has one row per day with data); the caller filters by `day` if a strict window is needed. This is a deliberate difference from the other endpoints, and the ML series on `/trends` **is** window-filtered (§3.4).
* **Field naming.** The public `daily` names are shortened from the view's column names, so that the same quantity is named identically on `/ml-stats` and on the `/trends` ML series:

  | `local_ml_stats` column | Public field |
  |---|---|
  | `day` | `day` (on `/ml-stats`) / `bucket_start` (on `/trends`) |
  | `total_inferences` | `total` |
  | `anomalies_detected` | `anomalies` |
  | `successful_inferences` | `successful` |
  | `error_inferences` | `errors` |
  | `degraded_inferences` | `degraded` |
  | `avg_processing_ms` | `avg_processing_ms` |
  | `avg_anomaly_score` | `avg_anomaly_score` |

  The `errors` and `degraded` counts are the `model_status = 'error'` and `model_status =
  'degraded'` row counts in the bucket. They are the **per-inference** vocabulary
  (`inference_logs.model_status`), not the runtime status of §3.3.

  The shortened names are a **presentation** choice of the ML context; the view's column names are
  unchanged and remain the internal vocabulary.
* `features` holds the **latest** row per `feature_name` from `feature_statistics` (latest = max `timestamp` per `feature_name`; ties broken by max `id`).
* `reason_codes` counts occurrences across `inference_logs.reason_codes` in the window, top 20. `reason_codes` is a JSONB array, so this needs `jsonb_array_elements_text` — on SQLite the same result is produced by reading the rows and counting in Python. Both paths must return identical numbers.
* `versions` lists all registry rows; `inferences` per version is the window count.
* `model` is the registry row with `status = 'active' AND is_production = true` — the same selection `app/ml.py::resolve_model_source(db)` makes (`ModelVersion.status == "active", ModelVersion.is_production.is_(True)`). `null` when no production model is registered.
* `model` carries `active_version`, `status`, `is_production`, `algorithm`, `deployed_at`, `trained_by` — all columns of `model_versions`. `trained_by` is a logical cross-database reference to `sentinel_core.users.id` (no real FK, per the assignment §6); Manager reports it as-is and **never** joins to resolve a username.
* `model.status` is the **registry** status (`staged`/`active`/`archived`/`failed`) — deliberately different from the **runtime** status reported as `ml.model_status` on `/dashboard` (§3.3). The two answer different questions: "what is registered" vs "is the artifact loadable right now".
* `inference.by_status` is the breakdown of `inference_logs.model_status` (`ready`/`degraded`/`error`) in the window; `inference.errors` / `inference.degraded` are the `error` / `degraded` counts of that breakdown, kept flat for convenience.

---

## 4. New internal endpoints (only where genuinely missing)

Existing endpoints were reviewed against the Manager needs:

| Existing endpoint | Why it cannot serve Manager analytics |
|---|---|
| `GET /api/v1/alerts` (public, SOC/Manager) | Paginated **row** list (max 100/page). No aggregates, no MTTA/MTTR, no time bucket. Aggregating in Manager would need N round-trips and would still miss data beyond page 1. |
| `GET /api/v1/login-attempts` (public, SOC/Manager) | Same problem — paginated rows, no server-side bucketing. |
| `GET /api/v1/policies` | Policy list only. |
| `GET /api/v1/admin/audit-logs` | `SECURITY_ADMIN` only — Manager is not allowed; also paginated rows. |
| `GET /api/v1/admin/users` | `SECURITY_ADMIN` only. |
| `GET /api/v1/internal/health` (Detection) | Liveness only. |
| `GET /api/v1/internal/users/{id}` (Core) | Single user projection. |
| `POST /api/v1/internal/actions`, `POST /api/v1/internal/login-events`, `POST /api/v1/internal/pre-token-check` | Write/command endpoints, no reads. |
| `GET /api/v1/internal/ml/*` | ML context, not Core/Detection. |

**Conclusion:** server-side aggregation over a time window genuinely does not exist on either side. Two internal read endpoints are required. They are *read-only projections*, owned by the domain that owns the data.

Both endpoints are **pure reads**: no writes, no side effects, no new state, no new tables. They may be implemented as SQL aggregate queries plus a small Python layer for the bucket zero-fill; they must not introduce caching or background jobs.

### 4.0 Shared contract rules

Both internal endpoints follow the same rules, so the Manager facade has one code path:

| Rule | Value |
|---|---|
| Auth | `X-Internal-Secret` header, verified with `verify_internal_secret()` (503 when the secret is not configured, 401 when absent/wrong) |
| Method | `GET` |
| Query params | `from`, `to`, `bucket` — same semantics and same validation as the public endpoints (§3.2), so the facade can forward them verbatim |
| Extra params | Detection also accepts `status`, `risk_level` (forwarded from `/manager/alerts`) |
| Time semantics | Half-open `[from, to)`, timezone-aware UTC |
| Response envelope | `generated_at`, `window`, `bucket` + the payload |
| Bucket labels | Floored UTC bucket starts (§5.3), zero-filled |
| Error model | 400 for an invalid window/bucket/filter; 500 only for a genuine bug; never a partial body |
| Payload validation | The facade treats a malformed body as source failure (`invalid_payload`), never as a 500 for the caller |
| Filters vs backlog | The `status` / `risk_level` filters apply to the **window-scoped alert aggregates only**. They do **not** apply to `critical_incidents`, which is the current open backlog and is never filtered (§3.3, §8 item 8), nor to `alerts.critical_open`, which is a system-wide current-backlog count (§4.1) |
| `critical_incidents` scope | Always the current high/critical open backlog, top 10 — regardless of `from`, `to`, `status` or `risk_level` |
| `alerts.critical_open` scope | A system-wide count of currently-`open` `critical` alerts — regardless of `from`, `to`, `status` or `risk_level`. It is a **different population** from `critical_incidents` (which is capped at 10 and also covers `high` and `acknowledged`), so the two numbers are not equal in general (§4.1) |
| Unsourced fields | The facade never computes a field that no source supplies. If a public response needs a value the internal contract does not carry, the field is **removed from the public contract**, not invented in the facade |

The facade forwards the window and bucket to Detection and Core **unchanged**, so the two layers cannot disagree about what "the last 14 days" means.

### 4.1 `GET /api/v1/internal/analytics/detection`

Owner: **Detection context** (Tuấn Anh) — new file `app/detection_analytics.py`.
Auth: `X-Internal-Secret` via `verify_internal_secret()`.
Query: `from`, `to`, `bucket`, optional `status`, `risk_level`.

```json
{
  "generated_at": "...",
  "window": { "from": "...", "to": "..." },
  "bucket": "day",
  "login_attempts": {
    "total": 300,
    "by_outcome": { "success": 240, "failure": 30, "mfa_required": 12, "mfa_success": 9,
                    "mfa_failed": 3, "blocked": 4, "locked": 1, "rate_limited": 1 },
    "by_risk_level": { "low": 180, "medium": 80, "high": 30, "critical": 10 },
    "by_decision": { "allow": 250, "challenge": 38, "block": 12 },
    "avg_combined_score": 0.3121
  },
  "risk_assessments": {
    "total": 300, "ml_success": 296, "ml_unavailable": 3, "ml_error": 1, "fallback_rate": 0.0133
  },
  "alerts": {
    "created": 20,
    "by_status": { "open": 5, "acknowledged": 3, "resolved": 9, "false_positive": 3 },
    "by_risk_level": { "low": 1, "medium": 3, "high": 9, "critical": 7 },
    "by_rule": [ { "rule": "multiple_failures", "count": 8 },
                 { "rule": "new_device", "count": 5 } ],
    "by_ml_reason": [ { "code": "high_fail_count", "count": 7 },
                      { "code": "new_device", "count": 4 } ],
    "acknowledged_count": 15,
    "resolved_count": 9,
    "false_positive_count": 3,
    "mttr_population": 8,
    "escalated_count": 2,
    "unassigned_open": 2,
    "critical_open": 2,
    "mtta_seconds": 320.4, "mttr_seconds": 5401.2,
    "oldest_open_age_hours": 33.5
  },
  "analysts": { "active": 10 },
  "critical_incidents": [
    { "alert_id": "…", "risk_level": "critical", "status": "open",
      "created_at": "2026-10-31T15:42:00+00:00",
      "subject": { "username": "d.anhtuan", "user_id": "…" },
      "detection_reason": "REQUIRE_MFA: combined=0.8123 (rule=0.6500, ml=0.9000)",
      "combined_score": 0.8123,
      "assigned_to": null, "age_hours": 0.3 }
  ],
  "enforcement": { "attempted": 10, "succeeded": 9, "success_rate": 0.9 },
  "series": [
    { "bucket_start": "2026-10-30T00:00:00+00:00",
      "login_attempts": 120,
      "by_outcome": { "success": 95, "failure": 15, "mfa_required": 4, "mfa_success": 3,
                      "mfa_failed": 1, "blocked": 2, "locked": 0, "rate_limited": 0 },
      "by_risk_level": { "low": 70, "medium": 32, "high": 13, "critical": 5 },
      "alerts_created": 7,
      "alerts_by_status": { "open": 2, "acknowledged": 1, "resolved": 3, "false_positive": 1 },
      "avg_combined_score": 0.29 }
  ],
  "policy": { "active_version": "v1", "active_policy_id": "..." }
}
```

Field notes:

* `policy` is the **active detection policy** at query time: `policies.is_active = true` (there is
  exactly one, enforced by the partial unique index `idx_policies_single_active`). `policies` lives
  in `sentinel_detection`, so Detection owns this fact and the facade never looks it up. It tells
  the Manager which policy version produced the risk decisions in the window, which is the
  time-scoped complement to the policy *configuration* that `GET /api/v1/policies` returns.
* `policy` is **point-in-time**, not window-scoped — it describes the policy active *now*.

Field notes:

* `alerts.acknowledged_count` = alerts with ≥ 1 `acknowledged` timeline event in the window (§5.1 rule 6) — **not** the same as `alerts.by_status.acknowledged`, which is the *current-status* count. The `_count` suffix marks the event-based number, matching `/manager/alerts` (§3.5).
* `alerts.resolved_count` = alerts whose current status is `resolved` (matches the MTTR population in §5.1 rule 4).
* `alerts.false_positive_count` = alerts whose current status is `false_positive`. Together with `resolved_count` it forms the false-positive-rate denominator (§5.1 rule 5).
* `alerts.mttr_population` = alerts that are **both** currently `resolved` **and** have `resolved_at ∈ [from, to)` — the exact set the MTTR average is taken over (§5.1 rule 4). It can be smaller than `resolved_count`, because an alert resolved before the window start is still currently `resolved`.
* `alerts.escalated_count` = alerts with ≥ 1 `escalated` timeline event in the window (§5.1 rule 8).
* `alerts.critical_open` = alerts currently `open` with `risk_level = 'critical'`. Note this is a **current-backlog** count, not window-scoped, matching `critical_incidents`.
* `alerts.unassigned_open` = alerts currently `open` with `assigned_to_id IS NULL`.
* `alerts.oldest_open_age_hours` = `now − created_at` of the oldest still-open alert created in the window.
* `analysts.active` = `soc_analysts.is_active = true` count — the denominator of *alerts per analyst*.
* `risk_assessments.fallback_rate` = `(ml_unavailable + ml_error) / total`, where `ml_status IS NULL` counts as fallback (§5.1 rule 11).
* `alerts.by_rule` / `alerts.by_ml_reason` read the structured `alerts.detection_scores` payload, **not** the free-text `detection_reason` (see §3.5 for why). Both are top-20, descending, ties broken by name.
* `critical_incidents` is the Manager triage list: top 10 open/acknowledged high+critical alerts, ordered by severity then age (oldest first). It is **not** window-scoped — it is the current backlog. See §3.3 for the full rules.
* The series' `by_outcome` carries the full canonical key set, zero-filled.

### 4.2 `GET /api/v1/internal/analytics/core`

Owner: **Core context** (Sony) — new file `app/core_analytics.py`.
Auth: `X-Internal-Secret` via `verify_internal_secret()`.
Query: `from`, `to`, `bucket`.

```json
{
  "generated_at": "...",
  "window": { "from": "...", "to": "..." },
  "bucket": "day",
  "users": {
    "total": 120,
    "by_status": { "active": 100, "locked": 5, "suspended": 15 },
    "mfa_required": 30, "forced_mfa": 3,
    "new_in_window": 4, "with_failed_logins": 6
  },
  "sessions": { "active": 42, "created_in_window": 88, "revoked_in_window": 10 },
  "mfa": { "challenges": 20, "completed": 16, "failed": 3, "expired": 1 },
  "audit": { "total": 45, "by_action": { "login_success": 20, "protective_action:REQUIRE_MFA": 3 } },
  "audit_activity": {
    "by_action": { "login_success": 20, "protective_action:REQUIRE_MFA": 3, "logout": 8 },
    "by_actor_type": { "user": 30, "system": 15 },
    "recent": [
      { "id": "…", "action": "protective_action:REQUIRE_MFA", "actor": "system",
        "resource": "user", "resource_id": "…", "created_at": "2026-10-31T15:40:00+00:00" }
    ]
  },
  "protective_actions": { "total": 8, "by_action": { "REQUIRE_MFA": 5, "REVOKE_SESSIONS": 2, "LOCK_USER": 1 } },
  "series": [ { "bucket_start": "2026-10-30T00:00:00+00:00", "logins": 88, "mfa_challenges": 20, "audit_events": 45 } ]
}
```

`audit.by_action` uses the canonical Core action vocabulary (`register`, `login_success`, `logout`, `logout_all`, `revoke_session`, `refresh_session`, `assign_role`, `revoke_role`, `lock_user`, `unlock_user`, `toggle_mfa`, `trusted_device_*`, `protective_action:<ACTION>`).
Login **failures** are *not* audited by Core — they live in Detection `login_attempts`; Manager uses Detection for failure counts.

Field notes:

* `users.*` (except `new_in_window`) are **point-in-time**; `sessions.created_in_window`, `sessions.revoked_in_window`, `mfa.*`, `audit.*` are **window-scoped** (§5.1 rule 13).
* `sessions.active` = sessions with `revoked_at IS NULL AND expires_at > now()`.
* `mfa.challenges` = `mfa_transactions` created in the window, broken down by `status`.
* `audit.by_action` counts only the actions in the window; `protective_actions` is the subset of `protective_action:*` entries, split on the `:` separator.
* `audit_activity` is the Manager's read-only audit/security activity review: `by_action` and `by_actor_type` breakdowns over the window, plus the **10 most recent** audit rows (newest first) with `id`, `action`, `actor`, `resource`, `resource_id`, `created_at`.
* `audit_activity.actor` is resolved to the username by Core (it owns `users`); when `actor_id` is `null` the literal `actor_type` (`system`) is returned.
* `audit_activity.recent` **deliberately omits** `before_state`, `after_state`, `ip_address` and `user_agent`. The Manager feed needs to know *what happened and when*; the state payloads and network identifiers are materially more sensitive and remain available on the `SECURITY_ADMIN` audit page (`GET /api/v1/admin/audit-logs`). Keeping them out stops this endpoint from becoming a second, less-guarded copy of the admin page.
* `audit.by_action` and `audit_activity.by_action` are the same count — `audit` is the compact form kept for the KPI surface, `audit_activity` adds the breakdown and the feed. Core computes them once and returns both.

### 4.3 Facade field mapping (internal contract → public response)

The facade **reshapes** the two internal payloads; it never re-aggregates and never invents a number.
This table is the normative mapping between the internal contract (§4.1, §4.2) and the public
responses (§3.3–§3.7). It is the single place where a field's origin is recorded, so an
implementer never has to guess which upstream key feeds which public key.

**Rule:** every public field maps to exactly one internal field, or it does not exist. A field
that no source supplies is removed from the public contract rather than computed in the facade
(§4.0, "Unsourced fields").

| Public field | Source | Internal field |
|---|---|---|
| `dashboard.core.total_users` | Core | `users.total` |
| `dashboard.core.users_by_status` | Core | `users.by_status` |
| `dashboard.core.users_with_mfa_required` | Core | `users.mfa_required` |
| `dashboard.core.users_under_forced_mfa` | Core | `users.forced_mfa` |
| `dashboard.core.new_users` | Core | `users.new_in_window` |
| `dashboard.core.users_with_failed_logins` | Core | `users.with_failed_logins` |
| `dashboard.core.active_sessions` | Core | `sessions.active` |
| `dashboard.core.sessions_created` | Core | `sessions.created_in_window` |
| `dashboard.core.sessions_revoked` | Core | `sessions.revoked_in_window` |
| `dashboard.core.mfa_challenges` / `_completed` / `_failed` | Core | `mfa.challenges` / `mfa.completed` / `mfa.failed` |
| `dashboard.core.audit_events` | Core | `audit.total` |
| `dashboard.core.audit_activity` | Core | `audit_activity` (verbatim) |
| `dashboard.detection.login_attempts` | Detection | `login_attempts.total` |
| `dashboard.detection.by_outcome` / `by_risk_level` / `by_decision` | Detection | same names |
| `dashboard.detection.avg_combined_score` | Detection | `login_attempts.avg_combined_score` |
| `dashboard.detection.alerts.*` | Detection | `alerts.by_status` + `alerts.created` + `alerts.critical_open` |
| `dashboard.detection.critical_incidents` | Detection | `critical_incidents` (verbatim) |
| `dashboard.detection.enforcement.*` | Detection | `enforcement.*` |
| `dashboard.detection.ml_fallback.*` | Detection | `risk_assessments.*` |
| `dashboard.detection.policy` | Detection | `policy` (verbatim) |
| `dashboard.ml.*` | ML | direct read of `sentinel_ml` (§6.4) |
| `alerts.totals.created` | Detection | `alerts.created` |
| `alerts.totals.<status>` | Detection | `alerts.by_status.<status>` |
| `alerts.by_risk_level` | Detection | `alerts.by_risk_level` |
| `alerts.by_rule` / `alerts.by_ml_reason` | Detection | same names |
| `alerts.backlog.open_count` | Detection | `alerts.by_status.open` |
| `alerts.backlog.unassigned` | Detection | `alerts.unassigned_open` |
| `alerts.backlog.escalated` | Detection | `alerts.escalated_count` |
| `alerts.backlog.oldest_open_age_hours` | Detection | `alerts.oldest_open_age_hours` |
| `alerts.acknowledged_count` | Detection | `alerts.acknowledged_count` |
| `alerts.resolved_count` | Detection | `alerts.resolved_count` |
| `alerts.false_positive_rate` | Detection | `false_positive_count / (resolved_count + false_positive_count)` |
| `alerts.mtta_seconds` / `alerts.mttr_seconds` | Detection | same names |
| `soc-kpi.mtta_seconds` / `mttr_seconds` | Detection | `alerts.mtta_seconds` / `alerts.mttr_seconds` |
| `soc-kpi.acknowledgement_rate` | Detection | `alerts.acknowledged_count / alerts.created` |
| `soc-kpi.resolution_rate` | Detection | `(resolved_count + false_positive_count) / alerts.created` |
| `soc-kpi.false_positive_rate` | Detection | as above |
| `soc-kpi.escalation_rate` | Detection | `alerts.escalated_count / alerts.created` |
| `soc-kpi.alerts_per_analyst` | Detection | `alerts.created / analysts.active` |
| `soc-kpi.enforcement_*` | Detection | `enforcement.*` |
| `soc-kpi.ml_assessments` | Detection | `risk_assessments.total` |
| `soc-kpi.ml_fallback_count` | Detection | `risk_assessments.total − risk_assessments.ml_success` |
| `soc-kpi.ml_fallback_rate` | Detection | `risk_assessments.fallback_rate` |
| `soc-kpi.mfa_enrollment_rate` | Core | `users.mfa_required / users.total` |
| `soc-kpi.forced_mfa_users` | Core | `users.forced_mfa` |
| `soc-kpi.audit_events` | Core | `audit.total` |
| `trends.series.login_attempts` | Detection | `series[*]` → `login_attempts`, `by_outcome`, `by_risk_level`, `avg_combined_score` |
| `trends.series.alerts` | Detection | `series[*]` → `alerts_created`, `alerts_by_status` |
| `trends.series.ml` | ML | direct read, §6.4 |
| `ml-stats.*` | ML | direct read, §6.4 |

**Note on the rates.** The four `/soc-kpi` rates are **ratios of two fields the Detection endpoint
already returns**. The facade performs the division, not the source. This is deliberate: the
numerator and denominator are both visible in the internal payload, so the facade never needs a
second round-trip and never disagrees with the source about the population.

**Note on `alerts.totals.acknowledged` vs `alerts.acknowledged_count`.** `totals.acknowledged` is
the *current-status* count and maps to `alerts.by_status.acknowledged`; `acknowledged_count` is the
*event-based* count and maps to `alerts.acknowledged_count`. They are different numbers and the
mapping keeps them apart.

**Note on `soc-kpi.ml_fallback_count`.** The internal payload reports `ml_success`,
`ml_unavailable` and `ml_error` separately; the public KPI surface exposes a single fallback count
(`total − ml_success`), because `ml_status IS NULL` also counts as a fallback and would otherwise
be invisible in the breakdown.

---

## 5. KPI definitions (exact formulas)

All KPI populations are **alerts created in `[from, to)`**. Timeline events considered are those with `created_at < to` (events after the window end are excluded).

| KPI | Formula | Source | Null when |
|---|---|---|---|
| **MTTA** (mean time to acknowledge) | `mean( first(alert_timeline.created_at) where event_type='acknowledged' − alerts.created_at )`, seconds, over acknowledged alerts | Detection | no acknowledged alert in window |
| **MTTR** (mean time to resolve) | `mean( alerts.resolved_at − alerts.created_at )`, seconds, over alerts with `status='resolved'` (false positives excluded) | Detection | no resolved alert in window |
| **False positive rate** | `false_positive_count / (resolved_count + false_positive_count)` | Detection | denominator = 0 |
| **Acknowledgement rate** | `alerts_with_acknowledged_event / alerts_created` | Detection | alerts_created = 0 |
| **Resolution rate** | `alerts_with_status_in(resolved,false_positive) / alerts_created` | Detection | alerts_created = 0 |
| **Escalation rate** | `alerts_with_escalated_event / alerts_created` | Detection | alerts_created = 0 |
| **Alerts per analyst** | `alerts_created / active_soc_analysts` (`soc_analysts.is_active = true`) | Detection | no active analyst |
| **Enforcement success rate** | `detection_logs(stage='action_sent' AND details->>'enforced'='true') / detection_logs(stage='action_sent')` | Detection | no `action_sent` log |
| **ML fallback rate** | `risk_assessments(ml_status <> 'success') / risk_assessments` (window anchor `risk_assessments.created_at`) | Detection | no assessment in window |
| **MFA enrollment rate** | `users(admin_mfa_required) / users` | Core | total users = 0 |
| **ML anomaly rate** | `inference_logs(is_anomaly) / inference_logs` in window | ML | no inference in window |

Rounding: rates are rounded to 4 decimals; seconds to 1 decimal; counts are integers.

### 5.1 Population rules (normative)

These resolve the ambiguities that would otherwise make two implementations disagree.

1. **Alert population** — `alerts.created_at ∈ [from, to)`. Every alert KPI uses this population, *except* where stated otherwise.
2. **Timeline events** — restricted to `alert_timeline.created_at < to`. An event that happened after the window end does not count, even though its alert was created inside the window.
3. **MTTA** — for each alert with ≥ 1 `acknowledged` event, take the **earliest** such event; the duration is `event.created_at − alert.created_at`. Mean over that set. If an alert is acknowledged **after** `to`, it contributes **nothing** (it is neither acknowledged nor unacknowledged for MTTA) — it stays in the denominator of *acknowledgement rate* only if the event is inside the window, per rule 2.
4. **MTTR** — over alerts with `status = 'resolved'` **and** `resolved_at ∈ [from, to)`. An alert resolved after `to` is excluded. False positives are excluded entirely.
5. **False positive rate** — denominator is `resolved_count + false_positive_count` where both are *current-status* counts over the population. `false_positive_count` includes alerts whose `status = 'false_positive'` regardless of when they were resolved.
6. **Acknowledgement rate** — `alerts_with_an_acknowledged_event_in_window / alerts_created`. Uses the **event**, not the current status: an alert that was acknowledged and later resolved still counts as acknowledged.
7. **Resolution rate** — `alerts_with_status_in('resolved','false_positive') / alerts_created`. Uses the **current status**.
8. **Escalation rate** — `alerts_with_an_escalated_event_in_window / alerts_created`.
9. **Alerts per analyst** — `alerts_created / active_soc_analysts`. `active_soc_analysts` is a **point-in-time** count (`soc_analysts.is_active = true` at query time), not window-scoped — `soc_analysts` has no timestamp for deactivation.
10. **Enforcement success rate** — over `detection_logs` rows with `stage = 'action_sent'` and `created_at ∈ [from, to)`. Numerator = rows whose `details->>'enforced'` is the JSON string `"true"`.
11. **ML fallback rate** — over `risk_assessments` with `created_at ∈ [from, to)`. Fallback = `ml_status <> 'success'` (i.e. `'unavailable'` or `'error'`); rows with `ml_status IS NULL` count as fallback.
12. **MFA enrollment rate** — `users(admin_mfa_required = true) / users(all)`. Point-in-time, not window-scoped. `detection_mfa_once` (forced MFA) is reported separately as `forced_mfa_users` and is **not** included in the enrollment rate — one-time forced MFA is a temporary state, not an enrollment.
13. **Window-scoped vs point-in-time** — `users`, `sessions.active`, `mfa_required`, `forced_mfa` are **point-in-time** (current state). Everything with a "in_window" suffix (`new_in_window`, `sessions_created`, `sessions_revoked`, `mfa_challenges`, `audit_events`) is **window-scoped**. The `_in_window` suffix is mandatory on window-scoped fields so the UI cannot confuse the two.

### 5.2 SQL sketch (for the internal aggregate endpoints)

**Moved to the reference document.** The concrete SQL for every aggregate — MTTA, MTTR, enforcement
success rate, ML fallback rate, the bucketed series, triggered rules, ML reason codes, critical
incidents, protective actions and audit activity — now lives in
`docs/M9-MANAGER-ANALYTICS-REFERENCE.md` §R1.

The **normative** rules stay in this document, because the SQL is an implementation detail that each
domain may re-express:

* The internal endpoints own their SQL. The sketches show the intended shape — index-friendly,
  single-pass, **no cross-context joins**.
* Every window predicate is half-open `[from, to)`.
* A rate whose population is empty is `null`, never `0`. This is a data rule, not a formatting rule,
  and it survives any SQL rewrite.
* A malformed or missing JSON payload is **skipped**, never raised.
* PostgreSQL and SQLite must produce identical numbers.

### 5.3 Bucket algorithm (normative)

```
floor(ts, bucket):
  hour -> ts.replace(minute=0, second=0, microsecond=0)
  day  -> ts.replace(hour=0, minute=0, second=0, microsecond=0)

bucket_starts(from, to, bucket):
  start = floor(from, bucket)
  step  = 1 hour | 1 day
  emit start, start+step, ... while start < to
```

* `from` is floored, so the **first** bucket may start before `from` — data before `from` inside that first bucket is still excluded by the SQL predicate, but the bucket label is the floor. This keeps bucket labels aligned to the wall clock.
* The number of emitted buckets is `ceil((to − floor(from)) / step)` and is bounded by the limits in §3.2 (400 for hour, 366 for day).
* Zero-fill: build the full list of bucket starts, then merge the SQL result into it by `bucket_start`; missing buckets become all-zero rows.
* All arithmetic is on **timezone-aware UTC** datetimes (`app.time_utils.as_utc`). Bucket boundaries never depend on the server's local timezone.

### 5.4 Index support — read-only, no schema change

The window-scoped aggregates filter on `created_at` / `timestamp`. The canonical schemas already carry the needed indexes for the Detection side:

| Table | Index | Used by |
|---|---|---|
| `login_attempts` | `idx_login_attempts_timestamp` | attempt counts, outcome/risk breakdowns |
| `alerts` | `idx_alerts_created` | alert population, status/risk breakdowns |
| `alerts` | `idx_alerts_status` + `idx_alerts_risk_level` | `critical_incidents` filter (open/acknowledged + high/critical) |
| `alerts` | `idx_alerts_assigned_to` | `critical_incidents.assigned_to` join |
| `alert_timeline` | `idx_alert_timeline_created` | MTTA, ack/escalation events |
| `risk_assessments` | `idx_risk_assessments_login` (on `login_attempt_id`) | ML fallback rate — joined via `login_attempts`, not scanned directly |
| `detection_logs` | `idx_detection_logs_stage` | enforcement success rate (stage filter) |
| `inference_logs` | `idx_inference_logs_created` | ML inference counts |

One Core-side table is queried on `created_at` and **does not** have a matching index today:

| Table | Missing index | Consequence |
|---|---|---|
| `mfa_transactions` | `created_at` | `mfa.challenges` scans the table |

The `users` table is joined by primary key for the `audit_activity.recent` actor resolution — no
extra index is needed for that. `audit_logs` already carries `idx_audit_logs_created`,
`idx_audit_logs_action` and `idx_audit_logs_actor_type`.
| `audit_logs` | — has `idx_audit_logs_action` ✅ | `audit_activity.by_action` grouping |
| `audit_logs` | — has `idx_audit_logs_actor_type` ✅ | `audit_activity.by_actor_type` grouping |

**Decision: M10 adds no indexes and no schema change.** The `mfa_transactions` scan is bounded by the table size (one row per MFA challenge) and is a single sequential read on a table that is not the hot path. Adding an index would mean a schema change, which §1.1 forbids and which the assignment lists under "adding new persistent entities".

If the lead wants the index anyway, it is a **separate, explicitly-approved schema change** to `infra/postgres/schema-core-v3.3.sql` (not part of M10 Manager Analytics):

```sql
CREATE INDEX IF NOT EXISTS idx_mfa_transactions_created ON mfa_transactions(created_at);
```

Detection's `alerts.detection_scores` is read as a whole JSONB document per row — there is no index for it and none is proposed. The top-20 breakdown reads at most the alert population of the window.

---

## 6. Graceful degradation

### 6.1 Rules

| Situation | Behaviour |
|---|---|
| One source fails | **HTTP 200**, `degraded: true`, that source's section is `null`, `sources.<name>.status = "unavailable"`, `detail` set to a reason code. Other sections render normally. |
| **Every** source consumed by the endpoint fails | **HTTP 503**, body `{"detail": "analytics sources unavailable", "sources": {...}}`. |
| Malformed upstream payload | Treated as source failure (`invalid_payload`), never a 500. |
| Manager request itself invalid (bad window, bad filter) | **HTTP 400** before any upstream call. |
| Caller not authenticated / wrong role | **HTTP 401** / **403** (from the existing authz layer). |

The rule is uniform and does not need per-endpoint tuning:

> A Manager endpoint consumes a fixed set of sources (§3.1). If **all** of them fail, the endpoint has nothing to return → **503**. If **some** fail → **200** with the failed sections `null` and `degraded: true`.

### 6.1.1 Reason-code vocabulary

`sources.<name>.detail` carries exactly one of these codes. The set is **closed** — an
implementation must not invent a new code, and the facade must not surface a raw exception message,
a URL, or an upstream response body in this field.

| Reason code | Meaning | Raised when |
|---|---|---|
| `not_configured` | `INTERNAL_SECRET` is absent, empty, a known-insecure placeholder, or shorter than 32 characters | `get_internal_secret()` raises `InternalAuthConfigurationError` |
| `timeout` | the upstream did not answer within `MANAGER_FETCH_TIMEOUT_SECONDS` (3.0 s) | `httpx.TimeoutException` |
| `unreachable` | the upstream could not be contacted | `httpx.ConnectError` / `httpx.TransportError` |
| `http_<code>` | the upstream answered with an HTTP error | any status ≥ 400 (e.g. `http_401`, `http_503`) |
| `invalid_payload` | the upstream answered 2xx but the body is not a usable JSON object, or is missing a required section | JSON decode failure, non-object body, or a required key absent |
| `database_error` | the ML read failed (connection error, missing schema, SQL error) | SQLAlchemy error on `get_ml_db` |
| `internal_error` | an unexpected exception inside the aggregation step | any other exception, caught and logged |

`http_<code>` is the only code that carries a variable suffix. `http_401` in particular means the
Manager sent a secret the internal endpoint rejected — an operator error that must be visible in
the response, not silently swallowed.

**Internal-endpoint-side codes.** The two internal endpoints use the existing
`verify_internal_secret()` semantics, which are unchanged: **503** when the secret is not
configured, **401** when the header is absent or wrong. The Manager sees these as `http_503` and
`http_401` respectively.

Consequences:

* `/alerts` and `/ml-stats` each consume a single source → any failure of that source is a **503** (there is no partial state to render).
* `/trends` consumes `detection` + `ml` → when Detection is down, **both** `series.login_attempts` and `series.alerts` are `null`, while `series.ml` still renders.
* `/dashboard` consumes `core` + `detection` + `ml` → any subset can fail; only a total failure is a 503.
* `/soc-kpi` consumes `detection` + `core` → each KPI group is `null` independently; only a total failure is a 503.

For `/dashboard` the degraded section is the one belonging to the failed source — `core`, `detection`
or `ml` — and the other two render normally.

For `/soc-kpi` the KPI groups map to sources as follows:

| KPI group | Source | Behaviour when that source is down |
|---|---|---|
| `mtta_seconds`, `mttr_seconds`, `acknowledgement_rate`, `resolution_rate`, `false_positive_rate`, `escalation_rate`, `alerts_per_analyst` | Detection | `null` |
| `enforcement_attempted`, `enforcement_succeeded`, `enforcement_success_rate` | Detection | `null` |
| `ml_assessments`, `ml_fallback_count`, `ml_fallback_rate` | Detection | `null` |
| `mfa_enrollment_rate`, `forced_mfa_users`, `audit_events` | Core | `null` |

### 6.1.2 Error contract

Every Manager endpoint answers with one of exactly five shapes:

| Status | Body | When |
|---|---|---|
| **200** | the endpoint's response model | success, possibly degraded |
| **400** | `{"detail": "<reason>"}` | invalid window / bucket / filter, detected **before** any upstream call |
| **401** | `{"detail": "Missing Authorization header"}` etc. | no / invalid bearer token — from `get_current_auth_context` |
| **403** | `{"detail": "Insufficient permissions"}` | authenticated but not a `SECURITY_MANAGER` — from `require_roles` |
| **503** | `{"detail": "analytics sources unavailable", "sources": {...}}` | every consumed source failed |

The 503 body is the only Manager response that is **not** the endpoint's response model. It is raised as `HTTPException(status_code=503, detail=...)`, so FastAPI renders `{"detail": ...}` exactly like the rest of the codebase; the `sources` map is added as a header-free extra field by the exception detail. To keep it simple and avoid a custom exception handler, the recommended shape is:

```json
{ "detail": "analytics sources unavailable",
  "sources": { "detection": { "status": "unavailable", "detail": "timeout" } } }
```

achieved by raising `HTTPException(status_code=503, detail={...})` — FastAPI renders a dict detail as-is. The 503 path must not use the response model, so the route must declare `responses={503: {...}}` for OpenAPI accuracy.

**No 500.** Any unexpected exception inside a Manager route is caught, logged, and converted into a source-level failure (`database_error` for the ML read, `internal_error` for the aggregation step). A 500 is reserved for a genuine framework-level bug.

### 6.2 Outbound call mechanics

* `app/manager_client.py` is the single place where outbound internal calls happen (mirrors `app/internal_client.py`).
* Header: `X-Internal-Secret: <secret>` obtained from `get_internal_secret()`; if the secret is not configured the source is marked `not_configured` and treated as unavailable — the request never leaks a placeholder secret.
* Timeout: **3.0 s** per upstream call, a **module constant** `MANAGER_FETCH_TIMEOUT_SECONDS` in `app/manager_client.py` (not an environment variable), matching `ACTION_ENFORCE_TIMEOUT_SECONDS` in `app/internal_client.py`.
* Base URLs, resolved once per request:
  * Detection → `DETECTION_URL` (default `http://localhost:8001`), matching `app/auth.py`.
  * Core → `CORE_APP_URL` (default `http://localhost:8000`), matching `app/internal_client.py`.
  * **No new environment variables are introduced.**
* Return type: each fetch returns a `(payload | None, reason_code | None)` pair. A `None` payload plus a reason code is the *only* failure representation — the client never raises for an upstream problem, so the facade has exactly one degradation path to handle.
* Failure mapping: `httpx.TimeoutException` → `timeout`; `httpx.ConnectError`/`TransportError` → `unreachable`; HTTP ≥ 400 → `http_<code>`; non-JSON body → `invalid_payload`; SQLAlchemy error on the ML read → `database_error`. The full closed vocabulary is in §6.1.1.
* Upstream calls for one request are issued **concurrently** (`asyncio.gather` with `return_exceptions=True`), so a slow source does not serialise the others. The slowest source bounds the request latency at ~3 s.
* Manager never retries. A retry would multiply load on an already-struggling upstream.

### 6.3 Monolith deployment note

**Resolved by the lead** (§8 item 4): in a monolith deployment `DETECTION_URL` and `CORE_APP_URL`
may both point at the same FastAPI server, provided this is **configurable**. Both are **existing**
environment variables, read from the same places as today:

| Variable | Read by | Current default | Meaning |
|---|---|---|---|
| `DETECTION_URL` | `app/auth.py` (and now `app/manager_client.py`) | `http://localhost:8001` | Base URL of the Detection context |
| `CORE_APP_URL` | `app/internal_client.py` (and now `app/manager_client.py`) | `http://localhost:8000` | Base URL of the Core context |

**No new environment variable is introduced and no default is changed.** The split-service
deployment keeps working exactly as it does today.

In the single-process deployment the monolith serves all routers on port 8000, so both variables
must point at the monolith's own address for the internal analytics calls to resolve. The E2E
harness already demonstrates this pattern (it mounts the same app under `http://core.test`,
`http://detection.test`, `http://ml.test`). Recommended `.env` for monolith mode:

```
DETECTION_URL=http://localhost:8000
CORE_APP_URL=http://localhost:8000
```

This is a **deployment configuration**, not a code change. The `.env.example` update is optional
documentation (§7).

**Failure mode.** If `DETECTION_URL` still points at `8001` in monolith mode, the Detection source
fails with reason `unreachable` and the Detection section degrades to `unavailable` — **visible,
not silent**. The same applies to `CORE_APP_URL` for the Core section. This is exactly the
behaviour the degradation matrix (§6.1) is designed to surface.

### 6.4 The ML source (direct read, not HTTP)

ML is the one source that is **not** fetched over HTTP: Manager lives in the ML/Analytics context and owns `sentinel_ml`, so it reads it directly through `get_ml_db` — the same dependency `app/ml.py` uses.

* A failure of the ML read (connection error, missing schema, SQL error) → source `ml` is `unavailable` with detail `database_error`; the endpoint still returns 200 with the `ml` section `null` when the other sources are healthy.
* The session is obtained via `Depends(get_ml_db)`, so it is closed by the framework like every other DB dependency.
* The ML read is a **read-only** aggregate over `inference_logs`, `model_versions`, `feature_statistics` and the `local_ml_stats` view. It never writes, never calls the model, and never touches `app/ml.py`'s inference path.
* The ML source is read **directly** and concurrently with the two HTTP fetches, so it costs no extra round-trip.

**Timezone rule for the ML read.** Every bucket boundary produced by the ML source must be a **UTC
floor** (§5.3). `local_ml_stats` truncates with `DATE_TRUNC('day', created_at)`, which uses the
**database session's** timezone — and this codebase does not pin it (`app/db.py` builds the engine
with `create_engine(url, pool_pre_ping=True)`, no `connect_args` timezone). The Manager ML read
therefore has exactly two acceptable implementations:

1. **Preferred — explicit UTC grouping** over `inference_logs`:
   `date_trunc('day', created_at AT TIME ZONE 'UTC')`.
2. **The view**, only if the session timezone is guaranteed UTC — either because the deployment
   sets it, or because the ML session issues `SET TIME ZONE 'UTC'` before the query.

The view alone is **not** safe to assume. The implementation must not silently mix a
session-timezone `day` with the UTC floors the rest of the design produces. This affects
`/ml-stats.daily` and the `/trends` ML series identically, and both must use the same rule so the
two endpoints agree.

---

## 7. Implementation plan for M10 (file-level)

| File | Action | Owner / note |
|------|--------|--------------|
| `app/manager.py` | **new** — 5 public routes, RBAC guard, orchestration, degradation logic, local Pydantic response models (kept local, like `app/ml.py` and `app/internal_actions.py`, to avoid touching the shared `app/schemas.py`) | Khang |
| `app/manager_client.py` | **new** — outbound internal HTTP client (secret header, timeout, failure → reason code) | Khang |
| `app/detection_analytics.py` | **new** — `GET /api/v1/internal/analytics/detection` | Detection context (**Tuấn Anh**) |
| `app/core_analytics.py` | **new** — `GET /api/v1/internal/analytics/core` | Core context (**Sony**) |
| `app/main.py` | **edit** — `include_router` for the three new routers | **Lead approval required** (shared entrypoint) |
| `tests/test_manager_analytics.py` | **new** — RBAC, window/filter validation, KPI math, bucketing, degradation matrix, isolation guard | Khang |
| `tests/test_manager_internal_contracts.py` | **new** — the two internal endpoints' own auth + aggregate contract | Tuấn Anh / Sony |
| `.env.example` | **optional edit** — document monolith values for `DETECTION_URL` / `CORE_APP_URL` | Ops — optional, not a code change |
| `docs/M9-MANAGER-ANALYTICS-DESIGN.md` | this document (normative) | Khang |
| `docs/M9-MANAGER-ANALYTICS-REFERENCE.md` | companion (SQL sketches + vocabulary) | Khang |

No changes to: `app/models.py`, `app/schemas.py`, `app/db.py`, `app/ml.py` inference path, `infra/postgres/*`.

**Ownership is fixed** (§8 item 2): Khang writes `app/manager.py`, `app/manager_client.py` and
`tests/test_manager_analytics.py`. Sony writes `app/core_analytics.py`; Tuấn Anh writes
`app/detection_analytics.py`. The two internal endpoints are a **sequencing dependency** for Khang's
M10 work — his facade cannot be integration-tested until they land.

### 7.0 Pydantic model inventory

`app/manager.py` defines its response models **locally**, following the pattern of `app/ml.py` and `app/internal_actions.py` (both define local models next to their routes) rather than growing the shared `app/schemas.py`. The shared file stays untouched — that also keeps the Manager model set out of every other module's import graph.

| Model | Used by | Notes |
|---|---|---|
| `SourceStatus` | all | `{ "status": "ok" \| "unavailable", "detail": str \| None }` |
| `AnalyticsWindow` | all | `{ "from": datetime, "to": datetime }` |
| `ManagerEnvelope` | all (base) | `generated_at`, `window`, `degraded`, `sources` |
| `ManagerDashboardResponse` | `/dashboard` | + `core`, `detection`, `ml` (each `Optional[...]`) |
| `ManagerTrendsResponse` | `/trends` | + `bucket`, `series` |
| `ManagerAlertsResponse` | `/alerts` | + `totals`, `by_status`, `by_risk_level`, `by_rule`, `by_ml_reason`, `backlog`, the KPI scalars (`acknowledged_count`, `resolved_count`, `false_positive_rate`, `mtta_seconds`, `mttr_seconds`) |
| `ManagerSocKpiResponse` | `/soc-kpi` | + `kpis` |
| `ManagerMlStatsResponse` | `/ml-stats` | + `model`, `versions`, `inference`, `by_status`, `reason_codes`, `daily`, `features` |
| `CriticalIncident` | `/dashboard` (in `detection`) | one triage row: `alert_id`, `risk_level`, `status`, `created_at`, `subject`, `detection_reason`, `combined_score`, `assigned_to`, `age_hours` |
| `CriticalIncidentSubject` | `/dashboard` (in `detection`) | `username`, `user_id` — both nullable (unknown username) |
| `ActivePolicy` | `/dashboard` (in `detection`) | `active_version`, `active_policy_id` |
| `AuditActivity` | `/dashboard` (in `core`) | `by_action`, `by_actor_type`, `recent` |
| `AuditActivityRow` | `/dashboard` (in `core`) | one row: `id`, `action`, `actor`, `resource`, `resource_id`, `created_at` — no state payloads, no network identifiers |
| `ManagerTrendSeries` | `/trends` | `login_attempts`, `alerts`, `ml` — each `Optional[list[...]]` |
| `ManagerTrendPoint` | `/trends` (login attempts) | `bucket_start`, `total`, `by_outcome`, `by_risk_level`, `avg_combined_score` |
| `ManagerTrendAlertsPoint` | `/trends` (alerts) | `bucket_start`, `total`, `by_status` |
| `ManagerTrendMlPoint` | `/trends` (ML) | `bucket_start`, `total`, `anomalies`, `successful`, `errors`, `degraded`, `avg_processing_ms`, `avg_anomaly_score` |
| `ManagerMlDailyPoint` | `/ml-stats` | `day`, `total`, `anomalies`, `successful`, `errors`, `degraded`, `avg_processing_ms`, `avg_anomaly_score` |

Rules for these models:

* Every optional section is `Optional[X] = None` — `null` is the degraded representation, never `{}` and never a zeroed object.
* Every rate is `Optional[float]`; a rate over an empty population is `null`, **not** `0.0` (§5).
* Every count is `int`.
* Enum-like fields (`status`, `risk_level`, `model_status`) are plain `str` with the canonical vocabulary documented, matching the style of `app/alerts.py` (`AlertStatusEnum` is a `str` subclass there, and `app/internal_actions.py` uses plain `str`).
* `datetime` fields are timezone-aware UTC. The API serialises them with the `+00:00` offset.
* The models are declared `model_config = ConfigDict(from_attributes=False)` — they are built from dicts, not ORM objects, because Manager never touches a Core or Detection ORM object.

### 7.0.1 Serialization rules

* **UUIDs** are serialised as strings (`str(...)`), matching `app/alerts.py::_alert_to_dict` and `app/internal_actions.py`. The Manager models never expose a raw UUID object.
* **Numerics** — `Numeric` columns come back as `Decimal` from PostgreSQL and `float` from SQLite. Every numeric field is converted with `float(...)` before it reaches the response, so the JSON is a plain number in both backends.
* **Booleans** are real JSON booleans, never `"true"` strings.
* **`details->>'enforced'`** is compared as the **string** `"true"` on the PostgreSQL side (§5.2) and as a real boolean on the SQLite side. The internal endpoint normalises both to the same integer count, so the facade never sees the difference.
* **JSONB arrays** (`rule_hits`, `ml_reason_codes`, `reason_codes`) may be `null` in the database. Every reader treats `null` as an empty list.
* **Timestamps** are normalised with `app.time_utils.as_utc` before comparison or serialisation; a naive timestamp from SQLite is treated as UTC (that is the documented `as_utc` contract).

### 7.1 Test plan (M10)

* RBAC: `SECURITY_MANAGER` → 200; `SOC_ANALYST`, `SECURITY_ADMIN`, `USER` → 403; no token → 401.
* Window validation: `from >= to` → 400; window > 366 days → 400; `bucket=hour` with a 60-day window → 400; `bucket=auto` resolves to `hour` for a 48-hour window and `day` for a 30-day window.
* Filter validation: `status=banana` → 400; `risk_level=extreme` → 400.
* KPI math: fixed fixtures for MTTA, MTTR, FPR, ack/resolution/escalation rates, enforcement success rate, ML fallback rate, alerts-per-analyst — including the empty-population cases (all KPIs `null`, never `0`).
* Population rules: an alert acknowledged **after** `to` must not contribute to MTTA or the acknowledgement rate (§5.1 rules 2, 3).
* Bucketing: zero-filled buckets, correct floor, correct bucket count, no gap and no duplicate.
* Degradation matrix: each source failing individually → 200 + `degraded: true` + `null` section; **all** sources of an endpoint failing → 503 (`/alerts` and `/ml-stats` fail → 503, since each has one source).
* Error contract: 400 body is `{"detail": ...}`; 503 body is `{"detail": "analytics sources unavailable", "sources": {...}}`; **no 500** under any upstream failure.
* Internal endpoint auth: missing/incorrect `X-Internal-Secret` → 401/503 (existing `verify_internal_secret` semantics).
* Bounded-context isolation: guard test asserting `app/manager.py` does **not** import `get_core_db` / `get_detection_db` and that the only DB dependency it uses is `get_ml_db`.
* Serialization: `Decimal` from PostgreSQL and `float` from SQLite must produce the same JSON; UUIDs must be strings; `details->>'enforced'` must count the same on both backends.
* Reason breakdowns: `by_rule` / `by_ml_reason` must be multi-valued (counts may sum above `totals.created`), must be top-20 descending, and must skip a malformed `detection_scores` without raising.
* `critical_incidents`: only `high`/`critical` alerts in `open`/`acknowledged` status appear; resolved and false-positive alerts never appear; the list is capped at 10; ordering is severity-first then oldest-first; `assigned_to` is `null` when unassigned; `age_hours` is non-negative. The window parameter does **not** filter this list.
* `audit_activity`: `by_action` counts match the audit total; `recent` is capped at 10 and sorted newest-first; `actor` is the username, or the literal actor type when `actor_id` is `null`; the serialised rows contain **no** `before_state`, `after_state`, `ip_address` or `user_agent` key.
* **Facade mapping (§4.3)**: for every public field, the test asserts the value equals the mapped internal field — not a recomputation. This catches a mapping table that drifts from the implementation.
* **Field-name separation (§4.1)**: `acknowledged_count` (event-based) and `by_status.acknowledged` (current-status) must be distinct numbers on the same fixture; a test that swaps them fails.
* **`/trends` series split (§3.4)**: the two public arrays carry the same `bucket_start` values as the internal flat series; `series.alerts[*].total` equals `series[*].alerts_created`; `series.login_attempts[*].total` equals `series[*].login_attempts`.
* **`/trends` ML series vs `/ml-stats` `daily`**: for any given day, the totals agree between the window-filtered `/trends` ML series and the `local_ml_stats`-backed `/ml-stats` `daily` row.
* **Reason-code vocabulary (§6.1.1)**: every failure mode maps to exactly one code from the closed set; the `detail` field never contains a URL, a stack trace, or an upstream response body.
* **Filters vs backlog (§4.0)**: `status` / `risk_level` filters change the window-scoped aggregates but leave `critical_incidents` untouched.
* **ML timezone rule (§6.4)**: the ML daily boundaries must be UTC floors. A test must assert that the daily series computed with `AT TIME ZONE 'UTC'` matches the `local_ml_stats` view's output **when the session timezone is UTC**, and that `/trends` and `/ml-stats` agree on the daily totals. A non-UTC session timezone must not shift a day boundary.
* **ML status vocabulary (§3.3, §3.7)**: `ml.model_status` is only ever `ready` or `error`; `degraded` belongs exclusively to `inference_logs.model_status`. A test asserts the runtime status never takes the value `degraded`.

### 7.2 Ownership boundary for M10

The three new modules have different owners, and the split is deliberate:

| Module | Owner | May touch |
|---|---|---|
| `app/manager.py` | Khang | `sentinel_ml` (via `get_ml_db`) + HTTP calls only |
| `app/manager_client.py` | Khang | HTTP only |
| `app/detection_analytics.py` | Tuấn Anh | `sentinel_detection` (via `get_detection_db`) |
| `app/core_analytics.py` | Sony | `sentinel_core` (via `get_core_db`) |

Khang's M10 work therefore **blocks** on the two internal endpoints existing. If the lead wants Manager Analytics shipped in one milestone, the fallback is that Tuấn Anh and Sony implement their own aggregate endpoint first; Khang then only writes the facade. A third option — Khang implementing those endpoints inside the other contexts' modules — would break the ownership boundary and needs explicit lead approval.

### 7.3 Out of scope for M10

* CSV/PDF export (UC-25).
* Manager approval queue.
* Any change to `app/ml.py` inference, model registry, or `inference_logs` writing.
* Caching, Redis, background jobs, materialised views, new DB tables.
* Un-commenting or porting the `manager_dashboard` conceptual view from `infra/postgres/schema-ml-service-v3.3.sql` (§1.2).
* Changes to `app/schemas.py`, `app/models.py`, `app/db.py`, `infra/postgres/*`.

---

## 8. Open items for lead approval

Status legend:

* **RESOLVED** — the lead has already decided this. The decision is recorded and the design
  reflects it. Nothing further is needed.
* **NEEDS_LEAD_DECISION** — still open. The design documents a concrete proposal; the lead must
  confirm it before M10 starts. **These are not closed by this document.**

---

### Item 1 — Router mounting in `app/main.py` (lead-only file) — needed for the 3 new routers

**Status: NEEDS_LEAD_DECISION**

**Proposal:** approve. `app/main.py` is a shared entrypoint and the assignment
(`docs/assignments/KHANG_ML_MANAGER_ANALYTICS.md` §15) lists modifying it as a STOP-and-ask
condition. The change is mechanical — three `include_router` calls, no other edit:

```python
app.include_router(manager_router)              # app/manager.py
app.include_router(detection_analytics_router)  # app/detection_analytics.py
app.include_router(core_analytics_router)       # app/core_analytics.py
```

**What it blocks:** nothing in the design. It blocks only the M10 integration test, because the
routes are unreachable until they are mounted.

---

### Item 2 — `app/detection_analytics.py` + `app/core_analytics.py` — Tuấn Anh / Sony own them

**Status: RESOLVED** — the lead confirmed the ownership split:

* Core analytics provider → **Sony** (`app/core_analytics.py`).
* Detection analytics provider → **Tuấn Anh** (`app/detection_analytics.py`).
* Manager facade, ML-local analytics and aggregation → **Khang** (`app/manager.py`,
  `app/manager_client.py`).

**Consequence, now fixed in this design:** Khang's M10 scope is `app/manager.py`,
`app/manager_client.py` and `tests/test_manager_analytics.py` only. He does **not** write either
internal endpoint. His work is blocked until Sony and Tuấn Anh land theirs — this is a sequencing
dependency, not a design question. The reference document §R1 hands them the SQL sketches for their
own endpoints.

---

### Item 3 — RBAC strictness — design allows **only** `SECURITY_MANAGER` (`SECURITY_ADMIN`, `SOC_ANALYST` → 403)

**Status: RESOLVED** — the lead confirmed `SECURITY_MANAGER` as the Manager role.

**Consequence, now fixed in this design:** all five routes use `require_roles("SECURITY_MANAGER")`
and nothing else. `SECURITY_ADMIN` and `SOC_ANALYST` receive **403**, and the same strictness is
mirrored in the test plan. The design deliberately does **not** widen the role set: `SECURITY_ADMIN`
already has broader power through `GET /api/v1/admin/*`, and `SOC_ANALYST` already has the
row-level views (`GET /api/v1/alerts`, `GET /api/v1/login-attempts`).

---

### Item 4 — Monolith `DETECTION_URL` must be `http://localhost:8000` (the default `8001` is the split-service address)

**Status: RESOLVED** — the lead confirmed that in a monolith deployment `DETECTION_URL` and
`CORE_APP_URL` may both point at the same FastAPI server, provided this is **configurable**.

**Consequence, now fixed in this design:**

* Both URLs are read from the **existing** environment variables — `DETECTION_URL` and
  `CORE_APP_URL` — which already exist in `app/auth.py` and `app/internal_client.py`. **No new
  environment variable is introduced.**
* `DETECTION_URL` keeps its current default `http://localhost:8001` and `CORE_APP_URL` keeps
  `http://localhost:8000`; the design does **not** change any default, so the split-service
  deployment is unaffected.
* In monolith mode the operator sets both to the monolith's own address. §6.3 documents the exact
  values and states the failure mode: if `DETECTION_URL` still points at `8001`, the Detection
  section degrades to `unavailable` — **visible, not silent**.
* The `.env.example` update is **optional** documentation, not a code change, and is not a
  prerequisite for M10.

---

### Item 5 — No new env vars, no cache — aggregation runs per request

**Status: RESOLVED** — covered by item 4 (no new env vars) and by the lead's constraint that no
Redis is added.

**Consequence, now fixed in this design:** every request re-aggregates. There is no in-process TTL
cache, no Redis, no background job and no materialised view. The design deliberately leaves the
cache decision open for a later milestone rather than inventing one here.

---

### Item 6 — Sequencing — M10 needs all three internal endpoints to exist

**Status: RESOLVED** — the lead fixed the ownership split in item 2, which settles the sequence:
Detection and Core aggregate endpoints first, then Khang's facade.

**Consequence, now fixed in this design:** the M10 file list in §7 is ordered by dependency, and
§7.2 states the blocking relationship explicitly. The facade cannot be tested end-to-end before the
two internal endpoints land; the facade's own unit tests (degradation matrix, RBAC, window
validation) can be written against a mocked client in parallel.

---

### Item 7 — `by_rule` / `by_ml_reason` replace `by_detection_reason` — the free-text `detection_reason` cannot be grouped (unbounded cardinality)

**Status: RESOLVED** — the lead confirmed the KPI semantics stay as designed, and this item is part
of that same decision surface.

**Consequence, now fixed in this design:** the two breakdowns read the structured
`alerts.detection_scores` payload (`rule_hits[].rule_name` and `ml_reason_codes[]`). The free-text
`alerts.detection_reason` is shown **verbatim** on `critical_incidents` — a per-alert display field
— and is never used as a grouping key. Both breakdowns are multi-valued (counts may sum above the
alert total) and are top-20 descending with ties broken by name.

---

### Item 8 — `critical_incidents` is **not** window-scoped — it is the current open backlog, so `from`/`to` do not filter it

**Status: RESOLVED** — the lead confirmed that an incident backlog still open is not dropped merely
because it falls outside the reporting window.

**Consequence, now fixed in this design:** `detection.critical_incidents` returns the **current**
open high/critical backlog (top 10, severity first then oldest first). The `from`/`to` window does
not filter it, and neither does the `status` / `risk_level` query filters of the internal endpoint
(§4.0). This is now stated in four places so the three implementers cannot disagree: §3.3, §4.0,
§4.1 and the reference document §R1.8.

---

### Item 9 — `audit_activity.recent` omits `before_state`, `after_state`, `ip_address`, `user_agent`

**Status: NEEDS_LEAD_DECISION**

**Proposal:** approve as written. The Manager oversight feed needs to know *what happened and
when*; the state payloads and network identifiers are materially more sensitive and remain
available on `GET /api/v1/admin/audit-logs`, which stays `SECURITY_ADMIN`-only. Keeping them out
stops the Manager endpoint from becoming a second, less-guarded copy of the admin page.

**If the lead prefers the full rows**, the alternative is to include `before_state` / `after_state`
and accept that the Manager endpoint then exposes protection-action payloads that the admin page
exposes. `ip_address` / `user_agent` would still be excluded — they are personal data with no
oversight value. **This item is not closed by this document.**

---

### Summary

| # | Item | Status |
|---|---|---|
| 1 | Router mounting in `app/main.py` | NEEDS_LEAD_DECISION |
| 2 | Ownership of the two internal endpoints | **RESOLVED** (Sony / Tuấn Anh / Khang) |
| 3 | RBAC strictness — only `SECURITY_MANAGER` | **RESOLVED** |
| 4 | Monolith `DETECTION_URL` / `CORE_APP_URL` | **RESOLVED** (configurable, no new env var) |
| 5 | No new env vars, no cache | **RESOLVED** |
| 6 | Sequencing | **RESOLVED** |
| 7 | `by_rule` / `by_ml_reason` replace `by_detection_reason` | **RESOLVED** |
| 8 | `critical_incidents` is not window-scoped | **RESOLVED** |
| 9 | `audit_activity.recent` omits state payloads and network identifiers | NEEDS_LEAD_DECISION |

**Two items remain open** (1 and 9). Neither blocks the other seven, and neither blocks Khang from
starting the facade.

### Verification record — code cross-check (M9 final pass)

Every claim the design makes about **existing** code was checked against the repository. This is
not an audit of the repository; it is a check that the design does not send an implementer to a
symbol or constraint that does not exist. Results:

| Claim in the design | Verified against | Result |
|---|---|---|
| `get_ml_db` / `get_core_db` / `get_detection_db` | `app/db.py:233,242,251` | confirmed |
| `require_roles` / `get_current_auth_context` | `app/authz.py:141,58` | confirmed |
| `utc_now` / `as_utc` | `app/time_utils.py:16,21` | confirmed |
| `verify_internal_secret` + header name `X-Internal-Secret` | `app/internal_auth.py:123` | confirmed |
| `ALERT_STATUSES`, `RISK_LEVELS`, `TIMELINE_EVENT_TYPES`, `_alert_to_dict` | `app/alerts.py:54,63,80,246` | confirmed |
| `UserStatus`, `SecurityAction` | `app/schemas.py:131,589` | confirmed |
| `REASON_CODES`, `resolve_model_source`, `get_ml_runtime` | `app/ml.py:100,163,179` | confirmed |
| `GET /api/v1/policies` allows `SECURITY_MANAGER` | `app/detection.py:1259` | confirmed |
| `GET /api/v1/admin/audit-logs` is `SECURITY_ADMIN` only | `app/iam.py:296` | confirmed — Manager may **not** reuse it |
| `model_versions` columns (`version`, `status`, `is_production`, `algorithm`, `deployed_at`, `trained_by`) | `app/models.py:792-824` | confirmed |
| `inference_logs` columns | `app/models.py:828-860` | confirmed |
| `feature_statistics` columns | `app/models.py:864` | confirmed |
| `local_ml_stats` view definition | `infra/postgres/schema-ml-service-v3.3.sql:245` | confirmed — reproduced verbatim in reference §R1.11 |
| 8 named check constraints | `app/models.py` | confirmed |
| `chk_login_attempts_detection_decision`, `chk_users_status` | — | **do not exist** — these two are *unnamed* inline CHECKs; the vocabulary table was corrected |

Three **real defects in the design** were found by this pass and fixed:

1. **`ml.model_status` was described as `ready` / `degraded` / `error`.** Wrong.
   `get_ml_runtime(db)` returns an `IsolationForestRuntime` object and has **no** status field —
   the runtime status is the *outcome* of the call (`ready` on success, `error` on exception).
   `degraded` belongs to `inference_logs.model_status`, a different field with a different
   vocabulary. Fixed in §3.3, §3.4, §3.7, reference §R2.5, and Appendix A.
2. **`local_ml_stats` is not timezone-safe.** The view truncates with `DATE_TRUNC('day',
   created_at)`, which uses the **database session timezone** — and `app/db.py` does not pin it.
   A non-UTC session silently shifts every day boundary. Fixed in §3.4, §3.7, §6.4, reference
   §R1.11, with a mandatory test in §7.1.
3. **`/ml-stats.daily` and the `/trends` ML series had different field sets** — the daily list was
   missing `errors` and `degraded`, so the two endpoints could not agree on a day. Both now carry
   `total`, `anomalies`, `successful`, `errors`, `degraded`, `avg_processing_ms`,
   `avg_anomaly_score`. Fixed in §3.3, §3.4, §3.7, the §7 response-model inventory, and
   Appendix A.

Two further **factual corrections** were made: the `ml.daily` example used the *view's* column
names instead of the *public* field names, and the design cited two check-constraint names that do
not exist.

**Status:** M9 (this document) is complete and ready for final lead review. No M10 code has been
written on this branch, and nothing has been committed or pushed.

---

## Appendix A — Field → source map (quick reference)

| Field | Domain | Table / column |
|---|---|---|
| `core.total_users`, `core.users_by_status` | Core | `users` |
| `core.users_with_mfa_required` | Core | `users.admin_mfa_required` |
| `core.users_under_forced_mfa` | Core | `users.detection_mfa_once` |
| `core.users_with_failed_logins` | Core | `users.failed_login_count > 0` |
| `core.new_users` | Core | `users.created_at` |
| `core.active_sessions` | Core | `sessions` where `revoked_at IS NULL AND expires_at > now()` |
| `core.sessions_created` / `core.sessions_revoked` | Core | `sessions.created_at` / `sessions.revoked_at` |
| `core.mfa_challenges` / `_completed` / `_failed` | Core | `mfa_transactions.created_at` / `.status` |
| `core.audit_events` | Core | `audit_logs.created_at` |
| `core.audit_activity.by_action` | Core | `audit_logs.action` |
| `core.audit_activity.by_actor_type` | Core | `audit_logs.actor_type` |
| `core.audit_activity.recent` | Core | `audit_logs` newest 10 (action, actor→`users.username`, resource, resource_id, created_at) |
| `detection.login_attempts`, `by_outcome`, `by_risk_level`, `by_decision` | Detection | `login_attempts` |
| `detection.avg_combined_score` | Detection | `risk_assessments.combined_score` |
| `detection.alerts.*` | Detection | `alerts` |
| `detection.by_rule` | Detection | `alerts.detection_scores->'rule_hits'` |
| `detection.by_ml_reason` | Detection | `alerts.detection_scores->'ml_reason_codes'` |
| `detection.enforcement.*` | Detection | `detection_logs` where `stage='action_sent'` |
| `detection.ml_fallback.*` | Detection | `risk_assessments.ml_status` |
| `detection.critical_incidents` | Detection | `alerts` (open/acknowledged, high+critical) + `login_attempts` + `risk_assessments` + `soc_analysts` |
| `alerts.by_rule`, `alerts.by_ml_reason` | Detection | same as above |
| `alerts.mtta_seconds` | Detection | `alert_timeline` (`acknowledged`) + `alerts.created_at` |
| `alerts.mttr_seconds` | Detection | `alerts.resolved_at` + `alerts.created_at` |
| `alerts.backlog.oldest_open_age_hours` | Detection | `alerts.created_at` where `status='open'` |
| `alerts.backlog.unassigned` | Detection | `alerts.assigned_to_id IS NULL` |
| `alerts.backlog.escalated` | Detection | `alert_timeline` (`escalated`) |
| `soc-kpi.alerts_per_analyst` | Detection | `soc_analysts.is_active` |
| `soc-kpi.mfa_enrollment_rate` | Core | `users.admin_mfa_required` / `users` |
| `soc-kpi.forced_mfa_users` | Core | `users.detection_mfa_once` |
| `soc-kpi.audit_events` | Core | `audit_logs` |
| `ml.model` | ML | `model_versions` where `status='active' AND is_production` |
| `ml.versions` | ML | `model_versions` |
| `ml.inference.*`, `ml.by_status` | ML | `inference_logs` |
| `ml.daily` | ML | view `local_ml_stats` **or** explicit `date_trunc('day', created_at AT TIME ZONE 'UTC')` over `inference_logs` — see the timezone rule in §6.4 |
| `ml.features` | ML | `feature_statistics` (latest per `feature_name`) |
| `ml.reason_codes` | ML | `inference_logs.reason_codes` |
| `ml.model_status` | ML | outcome of `get_ml_runtime(db)` — `ready` / `error` only |

## Appendix B — Vocabulary reference

**Moved to the reference document.** The canonical vocabulary tables (alert status, risk level,
login outcome, detection decision, timeline event, ML inference status, ML runtime status, registry
status, user status, MFA status, protective action, ML reason code, detection rule name, Core
audit action, bucket) and the explanatory notes (`detection_decision` vs `decision`,
`alerts.detection_reason`, `rule_hits` vs `ml_reason_codes`, what Core audits and does not, the ML
status vocabularies) now live in `docs/M9-MANAGER-ANALYTICS-REFERENCE.md` §R2.

The two vocabularies that appear in *every* Manager response — alert status and risk level — are
also restated in the design document where they are used, so this document stays readable on its
own.
