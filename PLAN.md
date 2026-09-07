# Sentinel Auth — Implementation architecture

This document is the implementation source of truth. Diagrams, OpenAPI, event schemas, tickets and the roadmap must conform to it. A change to an invariant requires an ADR in `docs/adr/` and a compatible contract version.

## 1. Goals and non-goals

### Goals

- Authenticate users safely and deterministically.
- Detect abnormal logins asynchronously without making ML availability part of the authentication availability budget.
- Give SOC analysts explainable, versioned evidence and controlled response actions.
- Run locally with Docker Compose and support contract, unit and end-to-end tests.

### Non-goals for this release

- Production multi-region deployment, real Telegram credentials, enterprise SIEM integration and automated irreversible remediation.
- Treating synthetic-data ML metrics as production fraud-detection performance.

## 2. Architecture decisions

| Decision | Rationale | ADR |
|---|---|---|
| Split synchronous authentication from asynchronous detection | A token must not be issued before a risk decision that claims to gate it. ML is monitoring evidence, not an inline availability dependency. | ADR-001 |
| Use a transactional outbox and Redis Streams for the local demo | HTTP background tasks lose events on process failure. An outbox provides at-least-once delivery; consumers are idempotent. | ADR-002 |
| One database owner per module | Direct cross-database reads make deployment, retention and tests coupled. | ADR-003 |
| Core-app is the policy enforcement point | Detection may request action but cannot directly mutate users or sessions. | ADR-004 |

## 3. Runtime topology

```text
                         ┌──────────────┐
Browser ─ HTTPS ───────► │   core-app   │ ──► core_app PostgreSQL
                         │ auth + MFA   │
                         └──────┬───────┘
                                │ transaction: login_attempt + outbox row
                                ▼
                         Redis Stream: auth.login-attempt.v1
                                │
                         ┌──────▼────────┐        ┌─────────────┐
                         │ detection     │ ─────► │ ml-service  │
                         │ rules + SOC   │  HTTP  │ inference + │
                         └──┬─────────┬──┘        │ registry    │
                            │         │           └──────┬──────┘
                            │         │                  │
                            ▼         ▼                  ▼
                    detection PostgreSQL  action-request.v1  ml PostgreSQL
                            │         │
                            └─────► SOC dashboard / notification worker
```

`core-app` is the only browser-facing authentication process. Detection and ML are private workloads. In production, workload identity uses mTLS plus a short-lived service JWT; local Compose uses a development token only and must never be deployed as a production secret.

## 4. The two login flows

### 4.1 Synchronous path: access decision

1. Core-app rate-limits by normalized account identifier plus IP, then performs generic credential verification.
2. It checks account state, lockout, password policy and static authentication policy.
3. It returns one of `ALLOW`, `MFA_REQUIRED` or `DENY`. `MFA_REQUIRED` creates a 5-minute `pre_auth_transaction`; no session exists yet.
4. After MFA succeeds, core-app creates a session, records only token hashes/JTI and rotates refresh tokens.
5. In the same database transaction, core-app records the immutable login attempt and an outbox event. Passwords, OTPs and raw tokens are never in that event.

The current release deliberately does not use detection or ML to alter this synchronous decision. A later inline risk feature requires a separate ADR, strict latency SLO and a fail-safe policy.

### 4.2 Asynchronous path: monitoring and response

1. The outbox publisher delivers `auth.login-attempt.v1` to Redis Streams.
2. Detection stores a deduplicated event, evaluates deterministic rules, builds feature vector `feature_schema_version=1`, then calls ML with a 500 ms timeout.
3. If ML is unavailable, the assessment is `DEGRADED`; its anomaly score is `null`, never `0`. Rule evidence still creates alerts according to policy.
4. Detection saves a versioned risk assessment, creates at most one active alert per attempt and optionally associates it with an incident.
5. A response action is emitted or sent as an authenticated request. Core-app validates the action policy, idempotency key, expiry and requester scope before enforcing it.

## 5. Interface contract rules

- HTTP endpoints and responses are defined in `docs/api-contract.yml`; additions are backward compatible within a major version.
- Events use `docs/events/envelope.schema.json` and a named payload schema. Required metadata: `event_id`, `event_type`, `schema_version`, `occurred_at`, `correlation_id`, `producer` and `payload`.
- Every producer retries through the outbox. Every consumer deduplicates by `event_id` and treats delivery as at-least-once.
- Internal HTTP requires `Authorization: Bearer` workload token with a correct audience and scope, `X-Correlation-ID`, `Idempotency-Key` for mutations and a bounded `expires_at` for actions.
- Failures return RFC 9457-style problem responses. Client-visible authentication failures remain generic.

## 6. Data ownership and retention

| Database | Owner | Primary records | Notes |
|---|---|---|---|
| `core_app` | core-app | user, credential, pre-auth transaction, session, auth policy, outbox, enforcement audit | Password hashes and refresh-token hashes only. |
| `detection_engine` | detection-engine | login attempt projection, rule version/hit, risk assessment, alert, incident, action request, SOC audit | `login_attempts` is a Timescale hypertable with indexes by time, user hash and source IP prefix. |
| `ml_service` | ml-service | feature schema/definition, training-data manifest, immutable artifact, model version/promotion, calibration and inference evidence | ML never reads another database directly. Inference evidence keeps an input digest, never raw feature vectors. |

IP address, device identifier and user-agent are security data. Retention defaults must be configurable, documented and tested. Use a hashed device fingerprint; restrict raw security context to SOC roles and redact it from logs/exports.

## 7. Core data model constraints

### core-app

- `sessions`: `id`, `user_id`, `access_jti`, `refresh_token_hash`, `created_at`, `expires_at`, `revoked_at`, `token_version`; no raw token column.
- `pre_auth_transactions`: `id`, `user_id`, `login_attempt_id`, `expires_at`, `status`, `bound_ip_hash`, `bound_device_hash`.
- `mfa_challenges`: references `pre_auth_transaction_id`, never a future session; limit attempts and record only challenge/OTP hashes where applicable.
- `outbox_events`: one unique event ID and payload checksum per state transition, published/attempt counters.

### detection-engine

- A `risk_assessment` stores `rule_set_version`, `policy_version`, `feature_schema_version`, `model_version`, `ml_status` and immutable evidence.
- `alerts` have an optimistic-lock `version` and an active uniqueness constraint per login attempt.
- `incidents` are optional aggregates; `incident_alerts` is many-to-many.
- `trusted_list_entries` require type, normalized value, mode, reason, creator, expiry, version and revocation fields. TRUST can lower friction but cannot bypass a hard block or account policy.

### ml-service

- `FeatureSchema` is an ordered, digested contract. Each feature records type, range and sensitivity; v1 permits only non-secret derived signals. A schema cannot be rewritten after a model uses it.
- A training manifest records source (`SYNTHETIC` or curated), data digest, generator version, sample count and a false `contains_raw_security_data` invariant. Synthetic metrics must never be called production performance.
- A model version references one immutable SHA-256 artifact, one feature schema and one training-data manifest. Its promotion record must be `APPROVED`; one model only may be `ACTIVE` for a supported schema.
- A calibration profile persists percentile bounds and anomaly threshold. Score normalization never uses volatile per-request min/max scaling.
- Each inference receives the exact schema version, validates the feature order, returns an `inference_id`, model/artifact identity and score. It retains only an input digest, correlation metadata, outcome and latency; it never stores a raw feature vector.
- A missing/invalid artifact, failed checksum or unsupported schema returns `503`/`422`. Detection converts dependency failure to `DEGRADED` and `anomaly_score=null`; the ML endpoint never returns a fake zero score.
- Isolation Forest reason codes are explicit heuristic feature signals, not causal explanations.

## 8. Security model

- Argon2id password hashing; generic login errors; progressive throttling by account/IP; account lockout must not create a trivial denial-of-service vector.
- MFA preference: WebAuthn/passkey, then TOTP; email/SMS OTP is a demo fallback. Bind a challenge to a pre-auth transaction, expiry, IP/device context and attempt counter.
- RBAC is scoped: `SOC_ANALYST` can acknowledge/investigate; high-impact actions require policy approval or `SECURITY_ADMIN`. `SECURITY_MANAGER` is read-only.
- All admin policy/rule/list changes are versioned, reviewed where policy demands, scheduled with `effective_at`, reversible and auditable.
- Audit entries are append-only at the application role; redact credentials, OTP, tokens and secrets. A later central export is an additional copy, not a second source of truth.

## 9. Reliability and observability

| Area | Requirement |
|---|---|
| Authentication | Core-app never waits for detection/ML. Login attempts are durably placed in the outbox with the auth transaction. |
| Event delivery | Exponential retry with jitter, dead-letter stream after bounded attempts, replay command and consumer lag metric. |
| ML dependency | 500 ms timeout, circuit breaker, `DEGRADED` risk assessment, alert on fallback rate/latency. |
| Notifications | Separate worker/outbox, idempotent send key, bounded retry and channel degradation state. |
| Observability | Structured JSON log, `correlation_id`, OpenTelemetry trace propagation, health/readiness endpoints and metrics for auth, outbox, stream lag, ML and actions. |
| Data scale | Time partitioning, retention/compression policy, indexed search paths and cursor pagination. |

## 10. Quality gates

1. Format/lint/type check and unit tests on every pull request.
2. Contract tests validate HTTP and event payloads against schemas.
3. E2E tests cover allow, MFA, deny, outbox retry, duplicate event, ML-degraded alert and idempotent action enforcement.
4. Security tests cover authorization matrix, cross-user access, token rotation/revocation, MFA replay and forged workload tokens.
5. No branch may add a dependency, migration or public contract without review.

## 11. Delivery order

The exact dependency graph is in `TICKETS.md`. The non-negotiable order is:

1. Contracts, ADRs, Compose, migrations and security primitives.
2. Core synchronous login/MFA/session plus transactional outbox.
3. Detection consumer/rules/risk assessment and ML inference contract.
4. Alert/incident/action workflow, then SOC views and notification worker.
5. E2E, threat tests, load checks and documentation export.
