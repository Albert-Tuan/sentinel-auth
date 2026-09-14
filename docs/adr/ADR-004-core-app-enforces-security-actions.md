# ADR-004: Core-app validates and enforces security actions

- Status: Accepted
- Date: 2026-09-07

## Context

Detection must be able to respond to serious findings, but a compromise of the detection workload must not grant unrestricted account-control power.

## Decision

Detection submits a signed, scoped and expiring action request with an idempotency key and evidence reference. Core-app verifies workload identity, permitted action, policy, expiry and duplicate status before enforcement. High-impact actions may require security-admin approval.

## Consequences

- Core-app is the sole writer for users, sessions and pre-auth requirements.
- Every request/enforcement pair is separately audited and traceable by correlation ID.
