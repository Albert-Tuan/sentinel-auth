# Sentinel Auth - Cross-Artifact Conflicts

## Executive Summary

This document identifies contradictions between different artifacts in the Sentinel Auth repository.

---

## C-01: Three Services vs. Single FastAPI App

| Artifact | Claim | Status |
|----------|-------|--------|
| SENTINEL_AUTH_TONG_HOP_v3.3.md | Three separate services on ports 8000, 8001, 8002 | CONFLICT |
| docs/DECISIONS-DETECTION-v3.3.md | Services communicate over HTTP | CONFLICT |
| app/main.py | All routers in one FastAPI app | ACTUAL |
| Dockerfile | Single service on port 8000 | ACTUAL |

**Evidence:**
```python
# app/main.py - actual deployment
app.include_router(auth_router)        # /api/v1/auth/*
app.include_router(detection_router)   # /api/v1/internal/*
# ... all in one app
```

**Classification:** DOCUMENTATION_CONFLICT
**Severity:** MEDIUM
**Resolution Required:** Document this as prototype consolidation; clarify three-service as target architecture.

---

## C-02: Outbox Pattern Status

| Artifact | Claim | Status |
|----------|-------|--------|
| SENTINEL_AUTH_TONG_HOP_v3.3.md ADR-002 | Outbox implemented | CONFLICT |
| SENTINEL_AUTH_TONG_HOP_v3.3.md note | "CHƯA HIỆN THỰC" (not implemented) | ACTUAL |
| app/auth.py | No outbox writes | ACTUAL |
| infra/postgres/schema-core-v3.3.sql | outbox_events table exists | INFRA |

**Evidence:**
```python
# app/auth.py - login() does NOT write to outbox_events
# Only direct LoginAttempt creation
la = LoginAttempt(...)
db.add(la)
db.commit()
```

**Classification:** DOCUMENTATION_ACCURACY
**Severity:** HIGH
**Note:** The documentation acknowledges this with "2026-10-05: CHƯA HIỆN THỰC"

---

## C-03: Critical → LOCK_USER vs. REVOKE_SESSIONS

| Artifact | Claim | Status |
|----------|-------|--------|
| Earlier docs/diagrams | CRITICAL → LOCK_USER | OBSOLETE |
| DECISIONS-DETECTION-v3.3.md | CRITICAL → REVOKE_SESSIONS | CURRENT |
| app/detection.py RISK_ACTION_MAP | "critical": "REVOKE_SESSIONS" | MATCHES |
| SENTINEL_AUTH_TONG_HOP_v3.3.md | CRITICAL → REVOKE_SESSIONS | MATCHES |

**Evidence:**
```python
# app/detection.py line 97-99
RISK_ACTION_MAP = {
    "high": "REQUIRE_MFA",
    "critical": "REVOKE_SESSIONS",
}
```

**Classification:** OBSOLETE_DOCUMENTATION
**Severity:** LOW
**Note:** Code and current docs are aligned; older diagrams may be stale.

---

## C-04: Alert Escalation State

| Artifact | Claim | Status |
|----------|-------|--------|
| schemas.py TimelineEventType | ESCALATED enum value exists | PRESENT |
| alerts.py AlertStatusEnum | No "escalated" status | CONFLICT |
| schema-detection-v3.3.sql | alert_timeline.event_type includes 'escalated' | PRESENT |
| alert status CHECK | statuses: open, acknowledged, resolved, false_positive | CONFLICT |

**Evidence:**
```python
# app/alerts.py - no escalate action endpoint
# Only acknowledge, resolve, assign

# app/schemas.py - timeline has escalated
class TimelineEventType(str, Enum):
    ESCALATED = "escalated"  # Timeline but no alert status
```

**Classification:** PARTIAL_CONFLICT
**Severity:** MEDIUM
**Resolution:** Alert status does not have "escalated" but timeline does. Document that escalation is a timeline event, not a status change.

---

## C-05: Multiple Active Policies

| Artifact | Claim | Status |
|----------|-------|--------|
| schema-detection-v3.3.sql | CHECK constraint prevents multiple active | INVALID |
| app/detection.py | activate_policy() loops to deactivate others | MATCHES |
| app/detection.py | DB constraint check_chk_single_active_policy | INVALID |

**Evidence:**
```sql
-- schema-detection-v3.3.sql line 58 - INVALID
CONSTRAINT chk_single_active_policy
CHECK (
    NOT (is_active AND EXISTS (
        SELECT 1 FROM policies p2
        WHERE p2.is_active = TRUE AND p2.id != id
    ))
)
-- PostgreSQL error: cannot use subquery in check constraint
```

**Classification:** IMPLEMENTATION_VS_SCHEMA_CONFLICT
**Severity:** BLOCKER
**Note:** DB constraint is invalid. App-level enforcement exists but DB won't validate.

---

## C-06: Multiple Production Models

| Artifact | Claim | Status |
|----------|-------|--------|
| schema-ml-service-v3.3.sql | CHECK prevents multiple is_production=TRUE | INVALID |
| app/ml.py | Only one model loaded at a time | MATCHES |

**Evidence:**
```sql
-- schema-ml-service-v3.3.sql line 37 - INVALID
CONSTRAINT uq_model_active_production
CHECK (
    NOT (is_production AND EXISTS (
        SELECT 1 FROM model_versions mv2
        WHERE mv2.is_production = TRUE AND mv2.id != id
    ))
)
```

**Classification:** IMPLEMENTATION_VS_SCHEMA_CONFLICT
**Severity:** BLOCKER
**Note:** Same issue as C-05.

---

## C-07: Rate Limit Window Reset

| Artifact | Claim | Status |
|----------|-------|--------|
| SENTINEL_AUTH_TONG_HOP_v3.3.md | "5 requests/minute/IP" | MATCHES |
| app/auth.py login() | 5 requests/minute, uses window_start | MATCHES |
| system_settings seed | "window_seconds": 300 (5 min) | CONFLICT |

**Evidence:**
```python
# app/auth.py - hardcoded 5 per minute
if rate and rate.count >= rate.max_count:  # max_count=5
    raise HTTPException(status_code=429)

# system_settings seed - says 300 seconds (5 min) window
('rate_limit.login.window_seconds', '300', 'integer', ...)
```

**Classification:** CONFIG_CONFLICT
**Severity:** LOW
**Note:** Hardcoded logic uses hardcoded 5/min, not the system_settings values.

---

## C-08: CORS Configuration

| Artifact | Claim | Status |
|----------|-------|--------|
| Security best practice | Don't use wildcard with credentials | CONFLICT |
| app/main.py | allow_origins=["*"], allow_credentials=True | VULNERABLE |

**Evidence:**
```python
# app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Wildcard
    allow_credentials=True,     # With credentials!
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Classification:** SECURITY_MISCONFIGURATION
**Severity:** HIGH
**Note:** This combination is insecure and will be rejected by modern browsers.

---

## C-09: INTERNAL_SECRET Default Value

| Artifact | Claim | Status |
|----------|-------|--------|
| Security best practice | Production should reject default secret | CONFLICT |
| app/auth.py, detection.py, ml.py | "changeme-in-production" default | ACCEPTABLE_FOR_DEV |

**Evidence:**
```python
# Multiple files
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "changeme-in-production")
```

**Classification:** DOCUMENTATION_GAP
**Severity:** MEDIUM
**Note:** No startup validation that secret is not default. Production deployment instructions should require changing this.

---

## C-10: MFA IP Binding

| Artifact | Claim | Status |
|----------|-------|--------|
| models.py MfaTransaction | bound_ip is HASHED (inet_type with Text fallback) | CONFLICT |
| detection.py feature ip_address | Stored as INET in login_attempts | CONFLICT |
| auth.py hash_ip() | Hashes IP for bound_ip storage | IMPLEMENTED |

**Evidence:**
```python
# app/auth.py - hashes IP before storing
bound_ip=hash_ip(client_ip)  # "hashlib.sha256(ip.encode()).hexdigest()"

# app/models.py - inet_type which is INET or TEXT
bound_ip: Mapped[Optional[str]] = Column(inet_type(), nullable=True)

# detection.py - ip_address stored as INET
ip_address: Mapped[Optional[str]] = Column(inet_type(), nullable=True)
```

**Classification:** SEMANTIC_INCONSISTENCY
**Severity:** MEDIUM
**Note:** bound_ip is hashed (privacy), but there's no check that compares hashed IPs. The binding is effectively stored but never validated against client's hashed IP.

---

## C-11: Pre-token Check Timeout

| Artifact | Claim | Status |
|----------|-------|--------|
| app/auth.py | PRE_TOKEN_CHECK_TIMEOUT = 3.0 seconds | IMPLEMENTED |
| DECISIONS-DETECTION-v3.3.md | Pre-token check synchronous | MATCHES |
| app/detection.py | ACTION_ENFORCE_TIMEOUT_SECONDS = 3.0 | IMPLEMENTED |

**Classification:** MATCH (good)

---

## C-12: Feature Contract

| Artifact | Claim | Status |
|----------|-------|--------|
| schemas.py ALLOWED_FEATURE_FIELDS | 6 features | MATCHES |
| schema-detection-v3.3.sql | 6 features documented | MATCHES |
| app/detection.py build_features() | Builds exactly 6 features | MATCHES |
| app/ml.py FEATURE_FIELDS | 6 features | MATCHES |

**Classification:** MATCH (good)

---

## C-13: ML Degraded Mode

| Artifact | Claim | Status |
|----------|-------|--------|
| DECISIONS-DETECTION-v3.3.md | "combined = rule_score" when ML fails | MATCHES |
| app/detection.py | combined = rule_score (line 569) | MATCHES |
| test_detection.py | test_ml_failure_falls_back_to_rule_score | MATCHES |

**Classification:** MATCH (good)

---

## C-14: Token Refresh Behavior

| Artifact | Claim | Status |
|----------|-------|--------|
| SENTINEL_AUTH_TONG_HOP_v3.3.md | Token rotation implemented | CONFLICT |
| app/auth.py refresh() | Token rotation implemented | MATCHES |
| docs/requirements | refresh_token_family exists | MATCHES |

**Evidence:**
```python
# app/auth.py - rotation implemented
new_refresh_token = secrets.token_urlsafe(32)
session.refresh_token_hash = hash_token(new_refresh_token)
```

**Classification:** DOCUMENTATION_CONFLICT_RESOLVED
**Note:** Code matches requirements. Earlier docs may have been out of date.

---

## C-15: Refresh Token Family Tracking

| Artifact | Claim | Status |
|----------|-------|--------|
| schemas.sql sessions | refresh_token_family column exists | PRESENT |
| app/auth.py refresh() | Creates new family per refresh | NOT_USED |
| app/auth.py _create_session() | Creates new family | PRESENT |

**Evidence:**
```python
# app/auth.py _create_session() - creates family but never validates it
refresh_token_family=uuid4(),  # New family per login

# app/auth.py refresh() - rotates but no family tracking
new_refresh_token = secrets.token_urlsafe(32)
session.refresh_token_hash = hash_token(new_refresh_token)
# NO CHECK: if token_family used before, invalidate entire family
```

**Classification:** DESIGN_NOT_IMPLEMENTED
**Severity:** MEDIUM
**Note:** refresh_token_family column exists but reuse detection is not implemented.

---

## C-16: Session JWT Validation

| Artifact | Claim | Status |
|----------|-------|--------|
| SENTINEL_AUTH_TONG_HOP_v3.3.md | "JWT token management" | CONFLICT |
| app/auth.py | Tokens are opaque random strings, NOT JWT | ACTUAL |

**Evidence:**
```python
# app/auth.py _create_session()
access_token = secrets.token_urlsafe(32)  # Random string, not JWT
refresh_token = secrets.token_urlsafe(32)  # Random string, not JWT
# Stored as SHA256 hash

# app/auth.py - no JWT validation middleware
# Only hash comparison in database
```

**Classification:** ARCHITECTURE_CONFLICT
**Severity:** HIGH
**Note:** The documentation describes "JWT" but implementation uses opaque tokens stored in DB. This is simpler but changes revocation semantics.

---

## C-17: REQUIRE_MFA Semantics

| Artifact | Claim | Status |
|----------|-------|--------|
| internal_actions.py | REQUIRE_MFA sets detection_mfa_once + revokes sessions | MATCHES |
| test_alert_actions.py | Documents the behavior | MATCHES |
| SENTINEL_AUTH_TONG_HOP_v3.3.md ADR-009 | REQUIRE_MFA always revokes sessions | MATCHES |

**Classification:** MATCH (good - recently fixed)

---

## C-18: Account Lock Mechanism

| Artifact | Claim | Status |
|----------|-------|--------|
| schemas.sql users | status can be 'locked' | PRESENT |
| app/auth.py | Checks user.status == "locked" | PRESENT |
| lock mechanism | When does account lock? | MISSING |

**Evidence:**
```python
# app/auth.py - checks for locked status
if user.status == "locked":
    raise HTTPException(status_code=423, detail="Account is locked")

# But failed_login_count is tracked and could trigger lock...
if user.failed_login_count >= 5:  # NOT CHECKED
    user.status = "locked"  # NOT DONE
```

**Classification:** MISSING_FEATURE
**Severity:** MEDIUM
**Note:** No auto-lock mechanism after N failed attempts. The counter exists but is never used to trigger lock.

---

## Conflict Summary Table

| ID | Conflict | Severity | Classification | Status |
|----|----------|----------|----------------|--------|
| C-01 | 3 services vs 1 app | MEDIUM | DOCUMENTATION | Needs documentation |
| C-02 | Outbox not implemented | HIGH | DOCUMENTATION | Acknowledged in docs |
| C-03 | LOCK_USER vs REVOKE | LOW | OBSOLETE | Resolved in code |
| C-04 | Escalation state | MEDIUM | PARTIAL | Needs clarification |
| C-05 | Multiple active policies | BLOCKER | DB_CONSTRAINT | Invalid constraint |
| C-06 | Multiple prod models | BLOCKER | DB_CONSTRAINT | Invalid constraint |
| C-07 | Rate limit window | LOW | CONFIG | Low priority |
| C-08 | CORS wildcard | HIGH | SECURITY | Should fix |
| C-09 | Default secret | MEDIUM | DOC_GAP | Should document |
| C-10 | MFA IP binding | MEDIUM | SEMANTIC | Stored but not validated |
| C-11 | Pre-token timeout | - | MATCH | Good |
| C-12 | Feature contract | - | MATCH | Good |
| C-13 | ML degraded mode | - | MATCH | Good |
| C-14 | Token refresh | - | MATCH | Good |
| C-15 | Token family | MEDIUM | DESIGN | Not implemented |
| C-16 | JWT vs opaque tokens | HIGH | ARCHITECTURE | Implementation differs |
| C-17 | REQUIRE_MFA | - | MATCH | Good |
| C-18 | Auto-lock | MEDIUM | MISSING | Feature gap |

---

## Resolution Priority

### Immediate (Blockers)
1. **C-05, C-06:** Fix invalid PostgreSQL CHECK constraints

### High Priority
2. **C-08:** Fix CORS configuration
3. **C-16:** Document that opaque tokens are used, not JWT
4. **C-01:** Document single-process prototype vs. three-service target

### Medium Priority
5. **C-10:** Implement or remove MFA IP binding
6. **C-15:** Implement refresh token family tracking
7. **C-18:** Implement account auto-lock or remove counter
8. **C-04:** Clarify escalation as timeline event

### Low Priority
9. **C-07:** Use system_settings for rate limit config
10. **C-09:** Document secret change requirement
11. **C-03:** Update old diagrams
