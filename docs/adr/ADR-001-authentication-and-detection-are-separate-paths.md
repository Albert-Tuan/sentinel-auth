# ADR-001: Authentication and detection are separate paths

- Status: Accepted
- Date: 2026-09-07

## Context

The original design issued a token in a fire-and-forget flow while also using rule and ML results to require MFA or deny the same login. Both cannot be true for one request.

## Decision

Core-app makes the synchronous access decision from credentials, lockout/rate-limit state and its own authentication policy only. It returns `ALLOW`, `MFA_REQUIRED` or `DENY`.

After the decision, core-app atomically records a login attempt and outbox event. Detection consumes it asynchronously and creates evidence, alerts and action requests. Detection is not permitted to mutate user/session state directly.

## Consequences

- Authentication remains available when detection or ML is unavailable.
- ML cannot immediately block the first login in this release; post-auth response action handles high-confidence findings.
- Any future inline risk gate needs a separate design, latency SLO and fail-safe decision policy.
