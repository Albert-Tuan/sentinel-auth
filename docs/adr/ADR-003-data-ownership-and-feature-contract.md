# ADR-003: Each module owns its data and ML receives feature contracts

- Status: Accepted
- Date: 2026-09-07

## Context

The prior plan prohibited shared databases yet allowed the ML workload to write and query detection data directly.

## Decision

Core-app, detection-engine and ml-service own separate PostgreSQL databases. Detection-engine derives a versioned feature vector from its login-attempt projection and sends it to ml-service over an authenticated interface. ML returns a score and model metadata only.

## Consequences

- Feature schema changes are versioned contract changes.
- ML training receives curated dataset manifests/events, not database credentials to another module.
