# Contract: Core ↔ Detection Engine

**Owners:** Sony (Core) + Tuấn Anh (Detection)
**Reviewer:** Lead

---

## Overview

This contract governs the integration between the Core/Auth service (Sony) and the Detection Engine service (Tuấn Anh).

- **Core owns enforcement.** Detection owns risk/action decision.
- **Neither service writes directly into the other's PostgreSQL database.**
- **Changes to this contract require lead approval** and must update this document.

---

## A. Pre-Token Risk Check

**Purpose:** Core calls Detection before granting access to determine if MFA challenge is required.

### Direction
```
Core  ──────►  Detection Engine
Sony               Tuấn Anh
```

### Endpoint
```
POST /api/v1/internal/pre-token-check
```

### Authentication
- Detection validates `X-Internal-Secret` header
- Core sends shared secret from `system_settings.detection.internal_secret`

### Request Schema

```json
{
  "username": "string",           // username being authenticated
  "user_id": "uuid | null",     // null if user does not exist yet
  "ip_address": "string",       // client IP (not proxy)
  "user_agent": "string | null",
  "timestamp": "iso8601"
}
```

### Response Schema

```json
{
  "risk_level": "low | medium | high | critical",
  "require_mfa": true,           // true if high or critical
  "degraded": false,             // true if detection partially unavailable
  "reason": "string | null"
}
```

### Timeout

| Direction | Timeout | Behavior |
|-----------|---------|----------|
| Core → Detection | **3 seconds** | **Fail open** |

- Core MUST implement a 3-second timeout
- If Detection does not respond within 3 seconds, Core **MUST allow login** (fail open)
- This allows the Detection to act via protective action after the fact

### Decision Semantics

| `risk_level` | `require_mfa` | Core Action |
|--------------|---------------|-------------|
| `low` | `false` | Grant access |
| `medium` | `false` | Grant access |
| `high` | `true` | Block access, trigger MFA challenge |
| `critical` | `true` | Block access, trigger MFA challenge |
| `degraded` | `false` | Grant access (fail open from Detection perspective) |

---

## B. Login Event Delivery

**Purpose:** Core delivers login events to Detection for the detection pipeline.

### Direction
```
Core  ──────►  Detection Engine
Sony               Tuấn Anh
```

### Endpoint
```
POST /api/v1/internal/login-events
```

### Authentication
- Detection validates `X-Internal-Secret` header

### Request Schema

```json
{
  "event_id": "uuid",           // Idempotency key from Core
  "user_id": "uuid | null",     // null if login failed (no account)
  "username_attempted": "string",
  "outcome": "string",           // success | failure | mfa_required | mfa_success | mfa_failed | blocked | locked | rate_limited
  "mfa_used": false,
  "ip_address": "string",
  "user_agent": "string | null",
  "timestamp": "iso8601"
}
```

### Response

```
202 Accepted
{
  "login_attempt_id": "uuid",
  "status": "received"
}
```

### Idempotency
- Core MUST generate a stable `event_id` (UUID) per login attempt
- Detection MUST deduplicate on `event_id` (idempotency key)
- Duplicate events return `202` with the existing `login_attempt_id`

### CURRENT vs TARGET Implementation

| Aspect | Current | Target |
|--------|---------|--------|
| Transport | **Direct HTTP** (Detection receiver only) | Core transaction + outbox → future publisher → Redis Stream → Detection consumer |
| Detection receiver | **Implemented** (`POST /api/v1/internal/login-events`) | — |
| Core producer | **NOT YET IMPLEMENTED** | — |
| Retry behavior | **NOT YET IMPLEMENTED** | — |
| Outbox publisher | IMPLEMENTATION PENDING | |
| Redis Streams | IMPLEMENTATION PENDING | |
| Status | Active | Not yet implemented |

**Important:** The async Redis flow is **NOT currently implemented**. Do not claim it is.

---

## C. Protective Actions

**Purpose:** Detection Engine instructs Core to enforce protective actions.

### Direction
```
Core  ◄──────  Detection Engine
Sony               Tuấn Anh
```

### Endpoint
```
POST /api/v1/internal/actions
```

### Authentication
- Core validates `X-Internal-Secret` header

### Request Schema

```json
{
  "idempotency_key": "uuid",    // Prevents duplicate action execution
  "action": "REQUIRE_MFA | REVOKE_SESSIONS | LOCK_USER | FORCE_LOGOUT",
  "target_user_id": "uuid",
  "reason": "string",
  "alert_id": "uuid | null",    // Optional: links action to an alert
  "detected_at": "iso8601"
}
```

### Response Schema

```json
{
  "action_applied": true,
  "action_type": "REQUIRE_MFA | REVOKE_SESSIONS | LOCK_USER | FORCE_LOGOUT",
  "details": {
    "sessions_revoked": 3,
    "action": "REQUIRE_MFA",
    "user_locked": false
  },
  "already_applied": false
}
```

### Supported Actions

| Action | Core Enforcement |
|--------|----------------|
| `REQUIRE_MFA` | Set `users.detection_mfa_once = true`; revoke existing sessions; user must MFA on next login |
| `REVOKE_SESSIONS` | Set `sessions.revoked_at = NOW()` for all active sessions of target user |
| `LOCK_USER` | Set `users.status = 'locked'`, `users.locked_at = NOW()` |
| `FORCE_LOGOUT` | Alias for `REVOKE_SESSIONS` + optional `LOCK_USER` based on Detection's decision |

### Idempotency
- Detection generates a stable `idempotency_key` per action
- Core deduplicates on `idempotency_key`
- If action already applied, return `"already_applied": true` without error

### Timeout

| Direction | Timeout | Behavior |
|-----------|---------|----------|
| Detection → Core | **3 seconds** | Detection should handle timeout gracefully |

---

## D. Authentication / Service Trust

### Internal API Authentication

All internal endpoints use `X-Internal-Secret` header:

```
X-Internal-Secret: <value from system_settings.detection.internal_secret>
```

| Caller | Callee | Secret Source |
|--------|--------|--------------|
| Core | Detection | `system_settings.detection.internal_secret` |
| Detection | Core | `system_settings.detection.internal_secret` |

**Both services share the same secret** configured in `system_settings`.

### Service Trust Model

- Detection **trusts** requests from Core (authenticated by secret)
- Core **trusts** requests from Detection (authenticated by secret)
- Both services trust each other's identity via shared secret
- No JWT, no OAuth, no mTLS required for internal calls

---

## E. Error Handling

### Core → Detection Errors

| Scenario | Detection Response | Core Behavior |
|----------|------------------|---------------|
| Invalid secret | `401 Unauthorized` | Log error; fail open (allow login) |
| Malformed request | `422 Unprocessable Entity` | Log error; fail open |
| Detection error | `500 Internal Server Error` | Log error; fail open |
| Timeout (3s) | No response | Fail open — allow login |

### Detection → Core Errors

| Scenario | Core Response | Detection Behavior |
|----------|--------------|-------------------|
| Invalid secret | `401 Unauthorized` | Log error; skip action |
| Invalid action type | `400 Bad Request` | Log error; do not retry |
| Target user not found | `404 Not Found` | Log error; skip action |
| Malformed request | `422 Unprocessable Entity` | Log error; skip action |
| Timeout (3s) | No response | Log timeout; skip action; do not block pipeline |

---

## F. Timeout Semantics Summary

| Call | Timeout | Failure Behavior |
|------|---------|-----------------|
| Core → Detection (pre-token) | 3 seconds | **Fail open** — allow login |
| Core → Detection (login events) | **Implementation decision** | Retry once; log failure if retry implemented |
| Detection → Core (actions) | 3 seconds | **Skip action** — do not block pipeline |

---

## G. Idempotency

Both directions support idempotency:

| Call | Idempotency Key | Deduplication |
|------|----------------|---------------|
| Core → Detection (login events) | `event_id` | Detection deduplicates on `event_id` |
| Detection → Core (actions) | `idempotency_key` | Core deduplicates on `idempotency_key` |

Both sides MUST return success on duplicate requests (not error).

---

## H. Contract Tests

Both Sony and Tuấn Anh are responsible for writing contract tests.

### Minimum Contract Tests

| Test | Owner | Description |
|------|-------|-------------|
| Pre-token returns risk_level | Tuấn Anh | Detection responds with correct risk_level |
| Pre-token 3s timeout → fail open | Sony | Core allows login on timeout |
| Pre-token invalid secret → fail open | Both | 401 from Detection → Core allows login |
| Login event idempotency | Sony + Tuấn Anh | Duplicate event_id → 202, same login_attempt_id |
| Login event invalid → 422 | Sony | Core sends invalid → Detection rejects |
| Action REQUIRE_MFA | Tuấn Anh | Detection sends → Core enforces |
| Action REVOKE_SESSIONS | Tuấn Anh | Detection sends → Core revokes sessions |
| Action LOCK_USER | Tuấn Anh | Detection sends → Core locks user |
| Action FORCE_LOGOUT | Tuấn Anh | Detection sends → Core logs out user |
| Action idempotency | Tuấn Anh | Duplicate idempotency_key → `already_applied: true` |
| Action 3s timeout | Tuấn Anh | Core timeout → Detection logs, does not block |

---

## I. Versioning / Change Procedure

### Change Classification

| Change Type | Requires |
|-------------|---------|
| Adding optional fields to request/response | Lead approval + both owners |
| Adding required fields to request/response | Lead approval + both owners |
| Changing field types | Lead approval + both owners |
| Changing timeout values | Lead approval + both owners |
| Adding new action types | Lead approval + both owners |
| Deprecating endpoints | Lead approval + both owners |

### Procedure

1. Owner proposes change in writing
2. Other owner reviews
3. Lead approves
4. Both services update
5. Contract document updated
6. Contract tests updated
7. Integration tested
8. Merged to dev

### Versioning

This contract uses document versioning. The current version is `1.0`.

Add version header to all contract documents:
```
Contract Version: 1.0
Last Updated: 2026-10-10
```

---

## J. Shared Non-Functional Requirements

| Requirement | Value | Note |
|-------------|-------|------|
| Internal API latency | < 500ms p95 | Excluding ML call (5s timeout) |
| Pre-token timeout | 3 seconds | Core → Detection |
| Action timeout | 3 seconds | Detection → Core |
| Login event timeout | **Implementation decision** (no canonical value) | Core → Detection |
| Concurrent requests | Handle 100 rps | Per service |
| Idempotency window | 24 hours | Reject duplicate event_id after 24h |
