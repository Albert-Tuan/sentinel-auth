# ADR-002: Use transactional outbox and at-least-once event delivery

- Status: Accepted
- Date: 2026-09-07

## Context

HTTP background tasks can lose a login event after an authentication transaction commits and before an HTTP call completes.

## Decision

Core-app writes the login attempt and an outbox row in one database transaction. A publisher sends the row to Redis Streams with retry and marks it published only after acknowledgement. Consumers deduplicate by `event_id`.

## Consequences

- Delivery is at-least-once, not exactly-once; all consumers must be idempotent.
- Redis Streams is sufficient for the local demo. A managed durable broker can replace it without changing the envelope schema.
