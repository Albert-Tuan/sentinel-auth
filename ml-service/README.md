# ml-service

Private anomaly-inference workload. It is intentionally not an authentication
service and never reads `core_app` or `detection_engine` databases.

## Runtime contract

- `GET /health` reports process liveness and whether a model is loaded.
- `GET /ready` is `200` only when a verified `ACTIVE` model is ready; otherwise
  it returns RFC 9457 `503` Problem Details.
- `POST /internal/v1/ml/score` requires the `ml.score` workload identity and
  `X-Correlation-ID`. It accepts only feature schema v1 and returns an
  `inference_id`, calibrated score, model version, artifact digest and
  heuristic—not causal—reason codes.

No model is silently substituted. A missing, unapproved, tampered or
incompatible model returns `503`; detection-engine owns the resulting
`DEGRADED` assessment.

## Model lifecycle

1. A feature schema fixes ordered names, types and valid ranges.
2. A dataset manifest records provenance and explicitly declares that raw
   security data is absent.
3. A candidate model references the schema, dataset, SHA-256 artifact and a
   persisted calibration profile.
4. Only an `APPROVED` promotion may select one active model per schema.
5. Inference evidence uses a SHA-256 digest of the canonical feature vector,
   never the raw vector or credentials.

The full domain and database models are [documented here](../docs/ml-service-domain.puml)
and [here](../docs/ml-service-erd.puml). The local schema bootstrap is
[`infra/postgres/02-ml-service-schema.sql`](../infra/postgres/02-ml-service-schema.sql).

## Local model

Install `requirements-ml.txt` with Python 3.11, then create an explicit,
deterministic synthetic demo model:

```bash
python -m app.bootstrap_demo --output-dir models
```

The generated artifact is for local flow validation only, never a production
fraud-detection claim. See the root [README](../README.md) for Docker commands.
