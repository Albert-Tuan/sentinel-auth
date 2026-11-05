# Sentinel Auth v3.3 — Manager Analytics: Implementation Reference

**Companion to:** `docs/M9-MANAGER-ANALYTICS-DESIGN.md` (the normative design document).
**Status:** M9 reference material. Not a separate source of truth — where this document and the
design document disagree, **the design document wins**.
**Scope:** SQL sketches for the two internal aggregate endpoints (§R1) and the canonical vocabulary
reference (§R2). Everything normative (response contracts, KPI formulas, population rules, bucket
algorithm, degradation rules) stays in the main design document.

---

## R1. SQL sketches for the internal aggregate endpoints

The internal endpoints own their SQL. The sketches below show the intended shape — index-friendly,
single-pass, no cross-context joins.

**Owner reminder:** the Detection sketches belong to `app/detection_analytics.py` (Tuấn Anh), the
Core sketches to `app/core_analytics.py` (Sony). Khang's `app/manager.py` never runs any of them —
it only forwards `from` / `to` / `bucket` / filters over HTTP.

### R1.1 Detection — MTTA

Earliest acknowledged event per alert, then average:

```sql
WITH acked AS (
    SELECT t.alert_id, MIN(t.created_at) AS ack_at
    FROM alert_timeline t
    WHERE t.event_type = 'acknowledged' AND t.created_at < :to
    GROUP BY t.alert_id
)
SELECT AVG(EXTRACT(EPOCH FROM (a.ack_at - al.created_at))) AS mtta_seconds
FROM acked a
JOIN alerts al ON al.id = a.alert_id
WHERE al.created_at >= :from AND al.created_at < :to;
```

`MIN(t.created_at)` implements the "earliest acknowledged event" rule of the design document's
population rules. The `t.created_at < :to` predicate is what excludes an acknowledgement that
happened after the window end.

### R1.2 Detection — MTTR

```sql
SELECT AVG(EXTRACT(EPOCH FROM (al.resolved_at - al.created_at))) AS mttr_seconds
FROM alerts al
WHERE al.created_at >= :from AND al.created_at < :to
  AND al.status = 'resolved'
  AND al.resolved_at >= :from AND al.resolved_at < :to;
```

Both window predicates are required: the first bounds the **alert population**, the second bounds
the **resolution events**. An alert resolved after `to` is excluded entirely.

### R1.3 Detection — Enforcement success rate

`details` is `JSONB`:

```sql
SELECT
  COUNT(*) FILTER (WHERE details->>'enforced' = 'true') AS succeeded,
  COUNT(*) AS attempted
FROM detection_logs
WHERE stage = 'action_sent' AND created_at >= :from AND created_at < :to;
```

`details->>'enforced'` yields the **string** `"true"` on PostgreSQL. On SQLite the equivalent is a
real boolean; the internal endpoint normalises both to the same integer count before returning it,
so the facade never sees the difference.

### R1.4 Detection — ML fallback rate

```sql
SELECT
  COUNT(*) FILTER (WHERE ml_status IS DISTINCT FROM 'success') AS fallback,
  COUNT(*) AS total
FROM risk_assessments
WHERE created_at >= :from AND created_at < :to;
```

`IS DISTINCT FROM` is deliberate: it treats `ml_status IS NULL` as a fallback, matching the
normative population rule.

### R1.5 Detection — Bucketed series

`date_trunc` in UTC, zero-filled afterwards in Python:

```sql
SELECT
  date_trunc(:bucket, la.timestamp AT TIME ZONE 'UTC') AS bucket_start,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE la.outcome = 'success') AS success,
  COUNT(*) FILTER (WHERE la.outcome = 'failure') AS failure,
  COUNT(*) FILTER (WHERE la.outcome = 'blocked') AS blocked,
  COUNT(*) FILTER (WHERE la.risk_level = 'low') AS low,
  COUNT(*) FILTER (WHERE la.risk_level = 'medium') AS medium,
  COUNT(*) FILTER (WHERE la.risk_level = 'high') AS high,
  COUNT(*) FILTER (WHERE la.risk_level = 'critical') AS critical
FROM login_attempts la
WHERE la.timestamp >= :from AND la.timestamp < :to
GROUP BY 1 ORDER BY 1;
```

`risk_level` / `detection_decision` are denormalised onto `login_attempts` (written by the Detection
worker), so the bucketed series needs **no join** to `risk_assessments`. `avg_combined_score`
**does** need it — join `risk_assessments` on `login_attempt_id` for that column only.

Note `login_attempts` uses the column **`timestamp`**, not `created_at` — every predicate against
that table must use `la.timestamp`.

### R1.6 Detection — Triggered rules

`detection_scores` is `JSONB`, `rule_hits` an array of objects:

```sql
SELECT hit->>'rule_name' AS rule, COUNT(*) AS total
FROM alerts a
CROSS JOIN LATERAL jsonb_array_elements(a.detection_scores->'rule_hits') AS hit
WHERE a.created_at >= :from AND a.created_at < :to
  AND hit->>'triggered' = 'true'
GROUP BY 1 ORDER BY 2 DESC, 1 ASC
LIMIT 20;
```

### R1.7 Detection — ML reason codes

Same shape, `ml_reason_codes` is an array of strings:

```sql
SELECT code, COUNT(*) AS total
FROM alerts a
CROSS JOIN LATERAL jsonb_array_elements_text(a.detection_scores->'ml_reason_codes') AS code
WHERE a.created_at >= :from AND a.created_at < :to
GROUP BY 1 ORDER BY 2 DESC, 1 ASC
LIMIT 20;
```

Both queries must tolerate a **missing or malformed** `detection_scores` (it is nullable JSONB).
On PostgreSQL use `COALESCE(a.detection_scores->'rule_hits', '[]'::jsonb)`; on SQLite read the rows
and count in Python. Both paths must produce identical numbers, and a malformed entry must be
**skipped**, never raise.

> The SQL reads `alerts.detection_scores`. The `risk_assessments` table carries a denormalised
> `rule_hits` / `ml_reason_codes` pair with the same content. The design document specifies
> `detection_scores` as the source; either is acceptable as long as the two never disagree — the
> Detection worker writes both from the same values in the same transaction.

### R1.8 Detection — Critical incidents

The Manager triage list. Note the **absence of a window filter**: this query deliberately returns
the current backlog, so a critical alert opened three days ago is still listed.

```sql
SELECT
  al.id                 AS alert_id,
  al.risk_level         AS risk_level,
  al.status             AS status,
  al.created_at         AS created_at,
  al.detection_reason   AS detection_reason,
  la.username_attempted AS username,
  la.user_id            AS user_id,
  ra.combined_score     AS combined_score,
  sa.display_name       AS assigned_to,
  EXTRACT(EPOCH FROM (now() - al.created_at)) / 3600.0 AS age_hours
FROM alerts al
JOIN login_attempts la ON la.id = al.login_attempt_id
LEFT JOIN risk_assessments ra ON ra.login_attempt_id = al.login_attempt_id
LEFT JOIN soc_analysts sa ON sa.id = al.assigned_to_id
WHERE al.risk_level IN ('high', 'critical')
  AND al.status IN ('open', 'acknowledged')
ORDER BY CASE al.risk_level WHEN 'critical' THEN 0 ELSE 1 END, al.created_at ASC
LIMIT 10;
```

* `alerts.login_attempt_id` is `NOT NULL`, so the inner join to `login_attempts` never drops a row.
* The two `LEFT JOIN`s carry optional data (`combined_score`, `assigned_to`).
* `now()` is the database clock, so `age_hours` is computed at query time and is never negative.
* On SQLite the same rows are selected and `age_hours` is computed in Python from the returned
  `created_at`.
* The `status` / `risk_level` query filters of the internal endpoint **do not** apply to this
  query — see the design document's internal-contract rules.

### R1.9 Core — Protective actions

Audit-log derived:

```sql
SELECT
  split_part(action, ':', 2) AS action_name,
  COUNT(*) AS total
FROM audit_logs
WHERE action LIKE 'protective_action:%'
  AND created_at >= :from AND created_at < :to
GROUP BY 1;
```

### R1.10 Core — Audit activity

Breakdown + recent feed. The breakdown and the feed share one `WHERE` clause, so they always
describe the same window.

```sql
-- breakdown by action
SELECT action, COUNT(*) AS total
FROM audit_logs
WHERE created_at >= :from AND created_at < :to
GROUP BY 1 ORDER BY 2 DESC;

-- breakdown by actor type
SELECT actor_type, COUNT(*) AS total
FROM audit_logs
WHERE created_at >= :from AND created_at < :to
GROUP BY 1;

-- recent feed, with the actor resolved to a username
SELECT
  al.id, al.action, al.actor_type, al.resource, al.resource_id, al.created_at,
  u.username AS actor_username
FROM audit_logs al
LEFT JOIN users u ON u.id = al.actor_id
WHERE al.created_at >= :from AND al.created_at < :to
ORDER BY al.created_at DESC
LIMIT 10;
```

The `actor` field in the response is `COALESCE(u.username, al.actor_type)` — a system action has no
`actor_id`, so it falls back to the literal actor type. The `users` join is a `LEFT JOIN` because
`actor_id` is nullable and `ON DELETE SET NULL`.

The feed deliberately selects **no** `before_state`, `after_state`, `ip_address` or `user_agent`
column — the Manager oversight feed does not expose them.

---

## R1.11 Core — ML daily series (ML context)

The ML daily series groups `inference_logs` explicitly in UTC. The `local_ml_stats` view uses a
bare `DATE_TRUNC('day', created_at)`, which truncates in the **session's** timezone — and this
codebase does not pin the session timezone (`app/db.py` uses
`create_engine(url, pool_pre_ping=True)` with no `connect_args` timezone). The explicit form is
therefore the canonical one:

```sql
-- canonical: explicit UTC
SELECT
  date_trunc('day', created_at AT TIME ZONE 'UTC') AS day,
  COUNT(*)                                          AS total,
  COUNT(*) FILTER (WHERE is_anomaly)                AS anomalies,
  COUNT(*) FILTER (WHERE model_status = 'ready')    AS successful,
  COUNT(*) FILTER (WHERE model_status = 'error')    AS errors,
  COUNT(*) FILTER (WHERE model_status = 'degraded') AS degraded,
  AVG(processing_time_ms)                           AS avg_processing_ms,
  AVG(normalized_score)                             AS avg_anomaly_score
FROM inference_logs
WHERE created_at >= :from AND created_at < :to
GROUP BY 1 ORDER BY 1;
```

The SQL aliases already match the **public** field names (`total`, `anomalies`, `successful`,
`errors`, `degraded`), so the facade needs no renaming for the explicit path. The view path needs
the mapping table in design document §3.7 (`total_inferences` → `total`, etc.).

The equivalent view definition, for reference — **not** timezone-safe on its own:

```sql
CREATE OR REPLACE VIEW local_ml_stats AS
SELECT
    DATE_TRUNC('day', created_at) AS day,
    COUNT(*) AS total_inferences,
    COUNT(*) FILTER (WHERE is_anomaly = TRUE) AS anomalies_detected,
    COUNT(*) FILTER (WHERE model_status = 'ready') AS successful_inferences,
    COUNT(*) FILTER (WHERE model_status = 'degraded') AS degraded_inferences,
    COUNT(*) FILTER (WHERE model_status = 'error') AS error_inferences,
    AVG(processing_time_ms)::NUMERIC(10,2) AS avg_processing_ms,
    AVG(normalized_score)::NUMERIC(5,4) AS avg_anomaly_score
FROM inference_logs
GROUP BY DATE_TRUNC('day', created_at);
```

The view **is** used when the session timezone is UTC (either guaranteed by the deployment, or set
explicitly with `SET TIME ZONE 'UTC'` on the ML session). The two paths must produce identical
daily totals. The view is **not** modified — that would be a schema change (§1.2).

---

## R2. Vocabulary reference

The canonical values used by every Manager response. A value outside these sets is a 400, never a
silently empty result.

| Vocabulary | Values | Source of truth |
|---|---|---|
| Alert status | `open`, `acknowledged`, `resolved`, `false_positive` | `chk_alerts_status` / `app/alerts.py::ALERT_STATUSES` |
| Risk level | `low`, `medium`, `high`, `critical` | `chk_login_attempts_risk_level` / `app/alerts.py::RISK_LEVELS` (a `frozenset` of plain strings). **Note:** `app/login_history.py` defines its own `RISK_LEVELS` tuple with the same four values — two definitions, one vocabulary. Do not treat them as different sets. |
| Login outcome | `success`, `failure`, `mfa_required`, `mfa_success`, `mfa_failed`, `blocked`, `locked`, `rate_limited` | `chk_login_attempts_outcome` |
| Detection decision | `allow`, `challenge`, `block` | inline CHECK on `login_attempts.detection_decision` (unnamed in `app/models.py`; same expression in `infra/postgres/schema-detection-v3.3.sql`) |
| Timeline event | `created`, `assigned`, `unassigned`, `acknowledged`, `escalated`, `note_added`, `status_changed`, `resolved`, `false_positive` | `chk_alert_timeline_event_type` / `app/alerts.py::TIMELINE_EVENT_TYPES` |
| ML inference status | `ready`, `degraded`, `error` | `chk_inference_logs_model_status` / `inference_logs.model_status` — the **per-inference** outcome |
| ML runtime status | `ready`, `error` | outcome of calling `get_ml_runtime(db)` — see §R2.5 |
| Detection ml_status | `success`, `unavailable`, `error` | `chk_risk_assessments_ml_status` |
| Model registry status | `staged`, `active`, `archived`, `failed` | `chk_model_versions_status` |
| User status | `active`, `suspended`, `locked` | inline CHECK on `users.status` (unnamed in `app/models.py`; same expression in `infra/postgres/schema-core-v3.3.sql`) / `app/schemas.py::UserStatus` |
| MFA transaction status | `pending`, `completed`, `expired`, `failed` | `chk_mfa_transactions_status` |
| Protective action | `REQUIRE_MFA`, `REVOKE_SESSIONS`, `LOCK_USER`, `FORCE_LOGOUT` | `app/schemas.py::SecurityAction` |
| ML reason code | `unusual_hour`, `high_fail_count`, `new_ip`, `new_device`, `behavioral_deviation`, `multiple_factors` | `app/ml.py::REASON_CODES` |
| Detection rule name | policy-defined (e.g. `unusual_hour`, `multiple_failures`, `new_device`, `high_deviation`) | `policies.rules[].name` |
| Core audit action | `register`, `login_success`, `logout`, `logout_all`, `revoke_session`, `refresh_session`, `assign_role`, `revoke_role`, `lock_user`, `unlock_user`, `toggle_mfa`, `trusted_device_updated`, `trusted_device_created`, `trusted_device_approval`, `trusted_device_requested`, `trusted_device_approved`, `trusted_device_login`, `protective_action:<ACTION>` | `app/auth.py::_audit`, `app/iam.py`, `app/devices.py`, `app/internal_actions.py` |
| Bucket | `hour`, `day` | design document §3.2 (common query parameters) |

### R2.1 Note on `detection_decision` vs `decision`

`login_attempts.detection_decision` and `risk_assessments.decision` hold the same verdict. The
aggregate uses `login_attempts.detection_decision` because the bucketed series reads
`login_attempts` alone and needs no join.

### R2.2 Note on `alerts.detection_reason`

`alerts.detection_reason` is written by the Detection worker as a formatted string:

```
"REQUIRE_MFA: combined=0.8123 (rule=0.6500, ml=0.9000)"
```

Its cardinality is unbounded — every distinct score produces a distinct string — so it **cannot**
be grouped. It is shown verbatim on `critical_incidents` (a per-alert field) but is never used as a
grouping key. The breakdowns read the structured `alerts.detection_scores` payload instead.

### R2.3 Note on `rule_hits` vs `ml_reason_codes`

Both are **multi-valued**: one alert can trigger several rules and several ML reason codes, so the
counts in `by_rule` / `by_ml_reason` sum to more than the alert total. That is expected — it is a
"reasons observed" breakdown, not a partition.

`rule_hits` contains only rules that actually fired (the Detection worker appends a hit only when
the comparison matched); the `triggered` field is present on each hit and is `true` for all of them.
`ml_reason_codes` comes from the ML runtime and uses the canonical vocabulary in §R2.

### R2.4 Note on what Core audits — and what it does not

Core writes an `audit_logs` row for **successful** authentication and for administrative actions.
It does **not** audit a failed login: `app/auth.py` calls `_audit(action="login_success", ...)`
only on the success path. Failed logins live in Detection's `login_attempts` table, with their own
`outcome` vocabulary.

**Consequence for Manager analytics:** the failure counts in every Manager response come from
**Detection**, never from Core's audit log. A Manager comparing "audit log login count" against
"login attempt count" will see a gap — that gap is the failure volume, by design. Do not attempt
to reconcile them in the facade.

The `action="login"` string that appears in `app/auth.py` belongs to the **`rate_limits`** table,
not to `audit_logs` — it is not part of the audit vocabulary.

### R2.5 Note on the ML runtime status vs the ML registry status

Three different statuses are easy to confuse. They are distinct fields with distinct vocabularies:

| Status | Field | Vocabulary | Source |
|---|---|---|---|
| ML runtime status | `ml.model_status` on `/dashboard` | `ready`, `error` | outcome of calling `get_ml_runtime(db)` |
| ML registry status | `model.status` on `/ml-stats` | `staged`, `active`, `archived`, `failed` | `model_versions.status` |
| Per-inference status | `inference_logs.model_status` | `ready`, `degraded`, `error` | written per inference |

`degraded` exists **only** in the third vocabulary. The runtime status is never `degraded`; the
`/api/v1/internal/ml/health` endpoint uses `degraded` in its separate `status` field, not in
`model_status`.
