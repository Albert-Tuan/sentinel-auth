# Sentinel Auth — Domain context

This glossary is the shared language for implementation, documentation and tests. Terms below are intentionally ownership-specific.

| Term | Meaning | Owner |
|---|---|---|
| Login attempt | Immutable record of a credential attempt, successful or failed. It is emitted after the synchronous authentication decision. | core-app produces; detection-engine stores its copy |
| Pre-auth transaction | Short-lived server-side state created after password verification when MFA is required. It is not a session and cannot call protected endpoints. | core-app |
| Session | Server-side record identified by `session_id` and token `jti`; only token hashes are stored. | core-app |
| Synchronous policy | Deterministic, low-latency checks performed by core-app: credential status, lockout, rate limit, password policy and required MFA. | core-app |
| Detection | Asynchronous rule and ML evaluation of an immutable login-attempt event. It creates monitoring evidence; it does not directly decide the login response. | detection-engine |
| Risk assessment | Versioned rule/ML result for one login attempt, with a `DEGRADED` state when a signal is unavailable. | detection-engine |
| Alert | A discrete finding for a risk assessment. One login attempt can create at most one active alert. | detection-engine |
| Incident | An investigation aggregate that can contain one or more alerts. It is created by policy or an analyst, not automatically for every alert. | detection-engine |
| Action request | Signed, idempotent request to enforce a security response. Core-app remains the policy enforcement point. | detection-engine requests; core-app enforces |
| Feature vector | Versioned, deterministic input produced by detection-engine and sent to ML. It contains no raw password, OTP or token. | detection-engine |
| Feature schema | Immutable, ordered definition of names/types/ranges for a feature vector. Its digest binds train and inference contracts. | ml-service owns; detection-engine implements |
| Training dataset manifest | Evidence of data source, digest, generator/version, sample count and sensitivity declaration. It is metadata, not the training data itself. | ml-service |
| Model artifact | Immutable serialized estimator addressed by SHA-256; it is verified before loading and is never selected by a mutable `latest` tag. | ml-service |
| Calibration profile | Persisted mapping from raw anomaly score to the stable `0..1` contract plus threshold. | ml-service |
| Model promotion | Reviewed approval/rejection that controls candidate-to-active transition. | ml-service |
| Inference record | Minimal ML evidence: input digest, model identity, score/outcome, reason codes, latency and correlation ID. It contains no raw feature vector. | ml-service |
| Model version | Immutable model metadata plus metrics, feature schema, dataset manifest, artifact digest and lifecycle status. | ml-service |
| Audit event | Append-only record of a security-relevant state transition. Request bodies and secrets are redacted. | originating module; central export later |

## Invariants

1. A user cannot receive an authenticated session until core-app's synchronous policy returns `ALLOW` or MFA succeeds.
2. Detection and ML outages cannot silently turn a login into a lower-risk decision; they only affect post-auth assessment and produce a degraded signal.
3. A module owns its database. Cross-module data moves through a versioned HTTP or event interface, never direct database access.
4. Every asynchronous message has an event ID, schema version, occurred-at time, correlation ID and idempotent consumer handling.
5. Rule, policy, feature-schema and model versions are retained with each security decision.
6. Only an approved model with verified artifact digest may become active. A missing ML model creates a `DEGRADED` detection assessment, never a score of zero.
7. ML inference evidence stores only a canonical feature-vector digest; it must not duplicate raw IP/device identifiers or secrets.
