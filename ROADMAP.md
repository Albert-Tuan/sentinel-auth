# Sentinel Auth — Delivery roadmap

The roadmap is dependency-driven, not person-driven. Do not start an integration milestone before its required enforcement, risk and test tickets exist.

## Week 1 — Contract and safe authentication foundation

- Verify `INFRA-01` and `INFRA-02` in CI.
- Complete `CORE-01`, `CORE-02` and `CORE-03`.
- Complete `DET-01` in parallel with the ordered ML foundation: `ML-00` then `ML-01`.
- Checkpoint: local stack healthy; contract schemas validate; login has only a synchronous core decision; MFA/session tests pass.

## Week 2 — Reliable event and scoring path

- Complete `CORE-04`, `DET-02`, `ML-02`, `ML-03` and `DET-03`.
- Demonstrate crash/retry/duplicate event behavior and ML-degraded behavior.
- Checkpoint: an allowed/denied/MFA attempt is durably emitted; risk assessment contains versioned rule evidence and nullable degraded ML state.

## Week 3 — SOC response without direct account control

- Complete `CORE-05`, `DET-04` and `DET-05`.
- Implement authorization matrix, action approval policy, optimistic alert transitions and notification worker.
- Checkpoint: SOC can investigate evidence and request an action; core-app alone enforces it; all attempts are auditable.

## Week 4 — Operational proof and submission

- Complete `OPS-01`, `TEST-01` and `DOCS-01`.
- Load check time-series queries, test backup/restore, replay a dead-letter event, and regenerate PNG/report assets.
- Checkpoint: Compose starts cleanly, CI passes, core security tests are >=80% branch coverage, no P0/P1 issue remains open.

## Risk register

| Risk | Guardrail |
|---|---|
| Detection/ML outage hides suspicious behavior | Outbox, retry, circuit breaker, `DEGRADED` assessment and fallback-rate alert. |
| Cross-module schema drift | OpenAPI/JSON-schema contract gate and version compatibility policy. |
| Detection compromise controls accounts | Workload identity, scoped action request, expiry/idempotency and core-app enforcement policy. |
| Synthetic ML overstates quality | Label metrics as synthetic, preserve data/model manifests and make ML advisory. |
| SOC concurrent edits lose evidence | Optimistic lock, state machine and append-only audit timeline. |
| Sensitive data leaks into logs/reports | Redaction tests, PII scopes and aggregate-only manager reports. |

## Definition of done

- All P0/P1 acceptance criteria have passing automated evidence.
- `docker compose up --build` has healthy workloads from an empty local volume.
- HTTP/event contracts, migrations and diagrams match the deployed interfaces.
- At least one E2E trace proves login → outbox → assessment → alert → validated action request.
- Security review finds no raw credential/token persistence and no unauthenticated internal mutation path.
