# Sentinel Auth - Open Design Decisions

## 1. DEC-OPEN-001: Service Architecture

**Question:** Is the current single-FastAPI-process prototype intended to eventually split into three independently deployed services?

**Why This Must Be Decided:** The entire deployment model, database strategy, and inter-service communication patterns depend on this.

**Current Behavior:** Single FastAPI application with all routers mounted, single DATABASE_URL.

**Evidence:**
- `app/main.py` includes all routers
- `Dockerfile` builds single service
- Documentation describes three services

**Option A: Keep Single Process**
- Simpler deployment
- No service mesh needed
- Update documentation to reflect single-process architecture
- Consider adding logical service labels

**Option B: Split Into Three Services**
- Update `main.py` to three separate apps
- Configure separate DATABASE_URLs per service
- Add inter-service authentication
- Update Docker compose for 3 services

**Trade-offs:**
- Option A: Simpler, faster for prototype, harder to scale independently
- Option B: More realistic, production-ready, more operational complexity

**Recommended:** Option A (document clearly) with Option B as future migration path

**Blocks Implementation:** YES (deployment model undefined)

---

## 2. DEC-OPEN-002: Role Change → Session Invalidation

**Question:** When a user's role is removed or privilege revoked, should existing sessions become invalid?

**Why This Must Be Decided:** This affects the security model for de-provisioning.

**Current Behavior:** No session invalidation on role change. Sessions remain valid until natural expiry.

**Evidence:** No code implements session revocation on role change.

**Option A: Sessions Remain Valid**
- Simpler implementation
- Users might retain access after de-provisioning
- Security risk for insider threat

**Option B: Immediate Session Invalidation**
- More secure
- Requires tracking active sessions for each user
- More complex implementation

**Trade-offs:**
- Option A: Lower security, simpler
- Option B: Higher security, requires tracking user roles in session context

**Recommended:** Option B for production, document security policy clearly

**Blocks Implementation:** YES (security invariant undefined)

---

## 3. DEC-OPEN-003: IP Spoofing Prevention

**Question:** Should the system trust X-Forwarded-For header, and if so, how to ensure only legitimate proxies can set it?

**Why This Must Be Decided:** Affects rate limiting, MFA binding, and detection features.

**Current Behavior:** Accepts X-Forwarded-For from any source.

**Evidence:**
```python
def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
```

**Option A: Reject X-Forwarded-For Entirely**
- Most secure
- Rate limiting uses actual client IP (if available)
- May break legitimate users behind corporate proxies

**Option B: Trust X-Forwarded-For (Documented)**
- Configure trusted proxy list
- Require proxy to strip client-supplied X-Forwarded-For
- Most common production setup

**Option C: Use X-Real-IP Only**
- nginx sets this after sanitizing
- Simpler than X-Forwarded-For parsing

**Trade-offs:**
- Option A: Breaks some legitimate deployments
- Option B: Requires correct proxy configuration
- Option C: Simpler but less flexible

**Recommended:** Option B with documentation, add middleware configuration

**Blocks Implementation:** YES (rate limiting ineffective if spoofable)

---

## 4. DEC-OPEN-004: Outbox Pattern Implementation

**Question:** Should the outbox pattern be implemented for reliable login event delivery to Detection Engine?

**Why This Must Be Decided:** Without it, login events can be lost if the application crashes after DB commit.

**Current Behavior:** Direct HTTP call or no call (depending on flow), events lost if crash occurs.

**Evidence:**
- `outbox_events` table exists but is not written to
- `app/auth.py` does not write to outbox
- No poller/worker exists

**Option A: Implement Full Outbox**
- Most reliable
- Requires background worker
- More complex

**Option B: Direct HTTP with Retry**
- Simpler
- Can lose events if crash occurs
- Pre-token check provides some mitigation

**Option C: Accept Event Loss**
- Simplest
- Detection may miss some events
- Not acceptable for production

**Trade-offs:**
- Option A: Highest reliability, highest complexity
- Option B: Good balance, some risk
- Option C: Not acceptable

**Recommended:** Option A (full outbox) for production, Option B as minimum

**Blocks Implementation:** YES (event delivery unreliable)

---

## 5. DEC-OPEN-005: Authorization Enforcement

**Question:** Should the system implement full JWT validation with role-based access control, or defer to future implementation?

**Why This Must Be Decided:** Current endpoints accept requests without verifying user identity or roles.

**Current Behavior:** All endpoints accessible without authentication.

**Evidence:**
- No JWT validation middleware
- `verify_internal_token()` only checks shared secret
- `get_actor_id()` returns None or from request body

**Option A: Implement Full RBAC Now**
- Complete security model
- Significant implementation effort
- Proper authorization for all endpoints

**Option B: Stub with Warning Logs**
- Quick prototype
- Logs unauthorized access attempts
- Doesn't actually prevent access

**Option C: Document as Out of Scope**
- Clear scope definition
- Development only
- Not suitable for production

**Recommended:** Option A with proper JWT validation middleware

**Blocks Implementation:** YES (security model incomplete)

---

## 6. DEC-OPEN-006: Account Auto-Lock Policy

**Question:** Should accounts be automatically locked after N failed login attempts?

**Why This Must Be Decided:** The `failed_login_count` exists but is never used to trigger lockout.

**Current Behavior:** Counter increments but never triggers lockout.

**Evidence:**
```python
# app/auth.py - increments but never locks
user.failed_login_count += 1
# No check: if failed_login_count >= N: user.status = "locked"
```

**Option A: Auto-lock After N Failures**
- Standard security practice
- Requires unlock mechanism
- Need to decide N (5? 10?)

**Option B: Detection-Based Locking Only**
- Detection Engine handles lock decisions
- `failed_login_count` for forensics only
- Simpler

**Option C: Manual Admin Lock Only**
- Admin manually locks accounts
- Clear responsibility
- May be too slow for brute force

**Recommended:** Option A with N=5, include auto-unlock after 30 minutes

**Blocks Implementation:** NO (security hardening)

---

## 7. DEC-OPEN-007: Refresh Token Family Tracking

**Question:** Should refresh token reuse be detected and invalidate the entire token family?

**Why This Must Be Decided:** Affects token rotation security.

**Current Behavior:** Tokens rotate but reuse is not detected.

**Evidence:**
- `refresh_token_family` column exists
- `refresh()` creates new family but doesn't track
- No family invalidation logic

**Option A: Implement Family Tracking**
- Detect token theft (attacker uses stolen token)
- Invalidate entire family on reuse
- Standard OAuth 2.0 practice

**Option B: Keep Simple Rotation**
- Each refresh creates new token
- No family tracking
- Attacker can use stolen token until expiry

**Trade-offs:**
- Option A: Better security, more complexity
- Option B: Simpler, less secure

**Recommended:** Option A for production

**Blocks Implementation:** NO (security hardening)

---

## 8. DEC-OPEN-008: MFA IP Binding

**Question:** Should MFA verification be bound to the same IP that initiated the challenge?

**Why This Must Be Decided:** Affects MFA security model.

**Current Behavior:** `bound_ip` stored but never validated.

**Evidence:**
```python
# app/auth.py - stores hashed IP
bound_ip=hash_ip(client_ip)

# app/auth.py mfa_verify() - never checks bound_ip
# No validation that verify request IP == bound_ip
```

**Option A: Implement IP Binding**
- More secure
- OTP intercepted cannot be used from different IP
- May break mobile users (IP changes)

**Option B: Remove IP Binding**
- Simpler
- More user-friendly
- Relies on OTP security alone

**Recommended:** Option B (remove bound_ip column) or Option A with proper IP change handling

**Blocks Implementation:** NO (feature incomplete but not blocking)

---

## 9. DEC-OPEN-009: Reconciliation Worker Scheduling

**Question:** Should `rescore_failed_attempts()` be scheduled automatically, and if so, how?

**Why This Must Be Decided:** Affects fail-open recovery.

**Current Behavior:** Function exists but never called.

**Evidence:**
- `app/detection.py rescore_failed_attempts()` exists
- No cron, scheduler, or periodic task configured
- No integration with application lifecycle

**Option A: Background Thread**
- Runs within application process
- Simple deployment
- Single instance only

**Option B: External Cron Job**
- Standard cron setup
- Can run on any instance
- Requires cron configuration

**Option C: Celery/Task Queue**
- Distributed task queue
- Best for multi-instance
- More operational complexity

**Recommended:** Option B (cron) as minimum, Option A for single instance

**Blocks Implementation:** YES (fail-open recovery undefined)

---

## 10. DEC-OPEN-010: Token Expiration Enforcement

**Question:** Should expired tokens be checked against the database on each request, or rely solely on JWT expiration?

**Why This Must Be Decided:** Affects revocation effectiveness.

**Current Behavior:** Tokens are opaque strings; validation checks DB.

**Evidence:**
```python
# devices.py - checks expiration against DB
Session.expires_at > datetime.utcnow()

# But auth.py refresh() only checks local time
if session.expires_at < datetime.utcnow():
    raise HTTPException(...)
```

**Option A: Always Check DB**
- Guarantees revocation takes effect
- Higher latency
- Database load

**Option B: JWT Expiry + Async Revocation**
- Lower latency
- Revocation delayed
- Current implementation

**Trade-offs:**
- Option A: Strongest consistency
- Option B: Better performance

**Recommended:** Document the trade-off; current implementation is acceptable for most use cases

**Blocks Implementation:** NO (design decision documented)

---

## Decision Summary

| ID | Question | Priority | Blocks | Status |
|----|----------|----------|--------|--------|
| DEC-001 | Service Architecture | HIGH | YES | OPEN |
| DEC-002 | Role Change → Session | HIGH | YES | OPEN |
| DEC-003 | IP Spoofing | HIGH | YES | OPEN |
| DEC-004 | Outbox Pattern | HIGH | YES | OPEN |
| DEC-005 | Authorization | CRITICAL | YES | OPEN |
| DEC-006 | Auto-Lock | MEDIUM | NO | OPEN |
| DEC-007 | Token Family | MEDIUM | NO | OPEN |
| DEC-008 | MFA IP Binding | MEDIUM | NO | OPEN |
| DEC-009 | Reconciliation | HIGH | YES | OPEN |
| DEC-010 | Token Expiry | LOW | NO | OPEN |

## Decisions Required Before Continuing

**Critical Path:**
1. DEC-005: Authorization must be defined
2. DEC-001: Architecture must be clarified
3. DEC-004: Outbox or alternative must be defined

**Security Path:**
4. DEC-003: IP trust must be defined
5. DEC-002: Session invalidation must be defined

**Reliability Path:**
6. DEC-009: Reconciliation must be scheduled
