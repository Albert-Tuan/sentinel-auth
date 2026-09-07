# Sentinel Auth

Sentinel Auth is a learning-grade security monitoring system for abnormal login activity. It has a safe synchronous authentication path and a separate asynchronous detection path, so a delayed ML score cannot accidentally grant or deny access.

## Architecture at a glance

```text
Browser -> core-app -> allow | require MFA | deny
                    |
                    +-> transactional outbox -> Redis Stream
                                                   |
                                      detection-engine -> alert / incident
                                                   |
                                      signed action request -> core-app
```

- `core-app`: identities, credentials, MFA, sessions and enforcement of protection actions.
- `detection-engine`: consumes login events, evaluates rules/ML scores and owns alerts, incidents and SOC views.
- `ml-service`: verifies/promotes and serves anomaly models; it receives a versioned feature vector and never queries another module's database. It verifies artifact digest, schema order and stored calibration before scoring.
- PostgreSQL is split into databases by data owner. Redis Streams carries asynchronous events for the demo; the transactional outbox remains the delivery guarantee.

The authoritative decisions are recorded in [docs/adr](docs/adr/). The public/internal HTTP contract is [docs/api-contract.yml](docs/api-contract.yml), and asynchronous envelopes are in [docs/events](docs/events/).
The detailed ML boundary is in [ml-service/README.md](ml-service/README.md).

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

Each FastAPI process exposes `/health` and `/docs`. ml-service also implements
private `/ready` and `/internal/v1/ml/score`; the other business workflows remain
ticket-driven. This repository is intentionally not presented as a complete
authentication product.

### Run a local-only ML demonstration

No trained model is committed. This is intentional: a checked-in model would
not be reviewed evidence. Create a deterministic synthetic Isolation Forest
artifact, then restart only ML so it loads the verified manifest:

```bash
docker compose run --rm ml-service python -m app.bootstrap_demo --output-dir /app/models
docker compose up -d --force-recreate ml-service
```

Score it using the development workload token from `.env`:

```bash
set -a; . ./.env; set +a
curl -X POST http://localhost:8003/internal/v1/ml/score \
  -H "Authorization: Bearer $INTERNAL_DEV_TOKEN" \
  -H "X-Correlation-ID: 96cb09f9-14fe-4ec9-8a90-b381d5734933" \
  -H "Content-Type: application/json" \
  -d '{"login_attempt_id":"6a9f8de8-9e0b-48d2-9e1d-b735a2287011","feature_schema_version":1,"features":{"hour_of_day":2,"fail_count_24h":7,"ip_change_rate_7d":0.7,"new_device":true,"average_login_interval_seconds":300,"deviation_score":0.9}}'
```

The result has a model/artifact identity and `inference_id`. The artifact is
synthetic demonstration data, not a production fraud model.

For a fresh local PostgreSQL volume, Compose also bootstraps the ML-owned schema
in [02-ml-service-schema.sql](infra/postgres/02-ml-service-schema.sql). The
service currently consumes a verified local manifest/artifact for the demo;
production promotion and durable inference recording must use the reviewed
migration path described in [ADR-005](docs/adr/ADR-005-model-lifecycle-and-inference-evidence.md).

## Verify

```bash
docker compose ps
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
```

Run local checks with:

```bash
make check
```

## Security constraints

- No raw access token, refresh token, password or OTP is stored or written to logs.
- Browser access decisions use only core-app's synchronous policy; detection results are post-auth monitoring signals.
- Internal calls require authenticated workload identity, an audience/scope, correlation ID and idempotency key.
- A detection result is a request for action. Core-app validates policy before it revokes sessions, locks a user or requires MFA.

## Project status

This repository now contains an executable infrastructure/service skeleton and aligned design artefacts. It is not production-ready until migrations, contract tests, security controls and the tickets marked P0/P1 are implemented.
