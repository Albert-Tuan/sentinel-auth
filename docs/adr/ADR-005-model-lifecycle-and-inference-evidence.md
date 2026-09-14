# ADR-005: ML models are immutable, promoted artifacts with privacy-safe inference evidence

- Status: Accepted
- Date: 2026-09-07

## Context

`ModelVersion` and `FeatureSchema` alone do not prove that a loaded artifact was
reviewed, compatible with inference input, calibrated consistently or safe to
correlate during an investigation. Storing full feature vectors would also copy
security-sensitive context into another owner database unnecessarily.

## Decision

ml-service owns an immutable feature schema, a training-dataset manifest, model
artifact metadata, calibration profile, model-promotion record and inference
evidence. A model can be `ACTIVE` only when an `APPROVED` promotion references:

1. one immutable artifact whose SHA-256 is verified before deserialization;
2. one ordered feature schema and matching schema digest;
3. one training dataset manifest with source and sensitivity declaration; and
4. one persisted calibration profile and anomaly threshold.

The inference API accepts only an exact supported schema version. It emits an
`inference_id`, model version and artifact digest. ml-service records/logs an
input digest, outcome, latency and heuristic reason codes; it does not retain a
raw feature vector, IP address, device identifier, password, OTP or token.

No active artifact, checksum failure or load failure is an explicit `503` from
ml-service. detection-engine converts this to its own `DEGRADED` risk
assessment with a null anomaly score.

## Consequences

- Model promotion is reviewable and reversible without mutating historical evidence.
- Train/inference feature order cannot silently drift.
- Synthetic training results remain clearly labeled and cannot be represented as
  production fraud-detection quality.
- The local implementation uses a checked manifest/artifact directory; a
  production registry/object store must preserve the same immutable contract and
  must not expose a mutable `latest` tag to inference.
