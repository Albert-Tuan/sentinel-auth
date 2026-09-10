# Sentinel Auth — Delivery tickets

Statuses are `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`. A ticket is `DONE` only after its listed tests pass in CI. The current repository contains a scaffold and contracts; no functional ticket is marked done yet.

## Dependency graph

```text
ADR + contract + Compose
          |
          +--> core schema/security --> synchronous login/MFA/session --> outbox publisher
          |                                                               |
          +--> detection schema/consumer --> rules --> ML client --> risk/alert --> SOC workflow
          |                                                               |
          +--> ML data/schema --> model --> inference -------------------+
                                                                          |
                                                 action enforcement <-----+
                                                                          |
                                            contract/E2E/security/load tests
```

## P0 — foundation and security

### INFRA-01 — Verify local runtime scaffold

- Owner: shared; Status: READY; Blockers: none.
- Deliver: validate `docker-compose.yml`, health checks, `.env.example` and service docs.
- Acceptance: `docker compose up --build` reaches healthy status for Postgres, Redis and three workloads; no default development secret is accepted outside local profile.

### INFRA-02 — Contract validation gate

- Owner: shared; Status: READY; Blockers: none.
- Deliver: validate `docs/api-contract.yml`, all event schemas and backward-compatible versioning policy.
- Acceptance: contract tests reject missing event ID/schema version/correlation ID; every mutating internal call requires idempotency key; review sign-off by all module owners.

### CORE-01 — Core schema, migrations and security primitives

- Owner: Sony; Status: READY; Blockers: INFRA-01, INFRA-02.
- Deliver: Alembic schema for user, policy version, login attempt, pre-auth transaction, MFA challenge, session, outbox and enforcement audit.
- Acceptance: no raw password/OTP/access/refresh token column; migration up/down works on clean database; authorization/audit migrations are tested.

### CORE-02 — Synchronous login decision

- Owner: Sony; Status: READY; Blockers: CORE-01.
- Deliver: `/api/v1/auth/login` returning only `ALLOW`, `MFA_REQUIRED` or generic `DENY`.
- Acceptance: Argon2id, generic error, progressive account+IP throttling, lockout policy, correlation log redaction and contract tests.

### CORE-03 — Pre-auth MFA and session lifecycle

- Owner: Sony; Status: READY; Blockers: CORE-02.
- Deliver: pre-auth transaction, WebAuthn/TOTP flow, session JTI, refresh-token rotation and revocation.
- Acceptance: replay/expired challenge/cross-user tests pass; no session before MFA pass; revocation takes effect for the defined token validation model.

### CORE-04 — Transactional outbox publisher

- Owner: Sony; Status: READY; Blockers: CORE-01, CORE-02.
- Deliver: atomic login-attempt/outbox write and Redis Streams publisher with retry, jitter and replay command.
- Acceptance: process crash between DB commit and publish does not lose event; duplicate delivery retains one event ID; lag/retry metrics exist.

### CORE-05 — Controlled action enforcement

- Owner: Sony; Status: READY; Blockers: CORE-01, INFRA-02.
- Deliver: authenticated `/internal/v1/actions` policy evaluation and enforcement.
- Acceptance: forged audience/scope, expired action, duplicate idempotency key and unapproved high-impact action fail safely; every result has enforcement audit.

## P1 — detection and ML

### DET-01 — Detection schema and idempotent event consumer

- Owner: Tuấn Anh; Status: READY; Blockers: INFRA-01, INFRA-02.
- Deliver: Timescale hypertable projection, dedup table, risk/alert/incident/action/audit tables and Redis consumer.
- Acceptance: event ID unique, replays safe, time/user/IP search indexes exist and no cross-database credentials are used.

### DET-02 — Versioned deterministic rules

- Owner: Tuấn Anh; Status: READY; Blockers: DET-01.
- Deliver: six rule implementations, immutable RuleSet versions, test vectors and version activation/rollback.
- Acceptance: each rule has pass/fail/boundary tests; assessment preserves version/evidence; threshold changes cannot rewrite history.

### ML-00 — ML schema and migration guardrails

- Owner: Khang; Status: READY; Blockers: INFRA-02.
- Deliver: reviewed migration for feature schema/definition, training manifest, artifact, model version, calibration, promotion and inference evidence; active-model partial uniqueness and retention indexes.
- Acceptance: migration works on a clean ML database; raw feature vectors cannot be stored in the inference table; exactly one active model per feature schema is enforced.

### ML-01 — Feature schema and synthetic data manifest

- Owner: Khang; Status: READY; Blockers: ML-00.
- Deliver: ordered FeatureSchema/FeatureDefinition v1, deterministic generator and digested train/test manifest; detection produces features rather than granting ML DB access.
- Acceptance: seed is reproducible; PII/raw secrets excluded; feature order, bounds and schema digest match at train and inference; raw vectors are not retained as ML evidence.

### ML-02 — Model training and registry

- Owner: Khang; Status: READY; Blockers: ML-01.
- Deliver: Isolation Forest training, immutable artifact metadata, percentile calibration, candidate/active promotion evidence and local registry manifest.
- Acceptance: metrics reported as synthetic-data metrics; candidate is evaluated before activation; one approved model is active per feature schema; artifact checksum and feature order are verified before load.

### ML-03 — Inference contract

- Owner: Khang; Status: READY; Blockers: ML-02, INFRA-02.
- Deliver: authenticated `/internal/v1/ml/score`, readiness endpoint, schema/version validation, model/artifact identity, inference ID and privacy-safe evidence digest.
- Acceptance: p95 target measured, invalid feature schema rejected, model unavailable returns explicit `503` rather than score zero; detection records `DEGRADED`; response reason codes are documented as non-causal heuristics.

### DET-03 — ML client and degraded assessment

- Owner: Tuấn Anh; Status: READY; Blockers: DET-02, ML-03.
- Deliver: 500 ms timeout, circuit breaker, correlation propagation and `DEGRADED` risk assessment.
- Acceptance: timeout test stores `anomaly_score=null`, `ml_status=DEGRADED`; rule-only policy behavior is tested; fallback rate metric alerts.

### DET-04 — Risk, alert and incident workflow

- Owner: Tuấn Anh; Status: READY; Blockers: DET-03.
- Deliver: risk assessment aggregation, one-active-alert uniqueness, optional many-to-many incident association and alert transition state machine.
- Acceptance: duplicate/replay/concurrent-transition tests pass; no automatic incident per alert; version/policy/evidence are queryable.

### DET-05 — SOC, audit and notification interfaces

- Owner: Tuấn Anh; Status: READY; Blockers: DET-04, CORE-05.
- Deliver: RBAC-protected SOC endpoints, append-only audit, action request UI/API and notification work queue.
- Acceptance: role matrix, optimistic lock, PII redaction, notification idempotency and bounded retry tests pass.

## P2 — operational readiness and evidence

### OPS-01 — Observability and retention

- Owner: shared; Status: READY; Blockers: CORE-04, DET-04, ML-03.
- Deliver: structured logs, trace propagation, Prometheus metrics, dashboards, retention/compression and backup/restore runbook.
- Acceptance: one correlation ID crosses three workloads; stream lag/ML degraded/action failure alerts are demonstrable.

### TEST-01 — Contract, E2E and threat suite

- Owner: shared; Status: READY; Blockers: CORE-05, DET-05.
- Deliver: automated flow tests for allow, MFA, deny, outbox retry, duplicate event, ML degradation, alert action and authorization abuse.
- Acceptance: CI test suite passes; security-critical paths have branch coverage target >= 80% and no P0 finding open.

### DOCS-01 — Rendered report and service handoff

- Owner: shared; Status: READY; Blockers: TEST-01.
- Deliver: regenerated diagrams, implementation README per workload, runbook and report export.
- Acceptance: every PNG has a tracked `.puml` source; report and `PLAN.md` use the same decisions and terminology.
