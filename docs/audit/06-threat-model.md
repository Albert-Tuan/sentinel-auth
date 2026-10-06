# Sentinel Auth - Threat Model

## 1. Threat Model Methodology

This threat model applies actual attack paths against the Sentinel Auth system architecture, focusing on authentication, session management, and detection capabilities.

## 2. Asset Inventory

| Asset | Classification | Owner | Sensitivity |
|-------|---------------|-------|-------------|
| User credentials | CRITICAL | Users | Password must remain secret |
| Session tokens | CRITICAL | Users | Valid for 1 hour |
| Refresh tokens | CRITICAL | Users | Valid for 7 days |
| MFA codes | HIGH | Users | Single-use |
| User PII (email, IP) | MEDIUM | Users | Privacy-sensitive |
| Detection rules | HIGH | Security Team | Operational security |
| Alert data | HIGH | SOC | Incident response |
| Audit logs | HIGH | Compliance | Non-repudiation |

## 3. Attacker Profiles

| Attacker | Capability | Motivation | Threat Level |
|----------|------------|------------|--------------|
| External attacker (credential stuffing) | Automated attacks | Financial gain | HIGH |
| External attacker (brute force) | Manual/automated | Account takeover | MEDIUM |
| Malicious insider | Legitimate access | Data theft, sabotage | CRITICAL |
| Compromised insider | Stolen credentials | Financial gain | HIGH |
| SOC analyst (rogue) | Alert access | Unauthorized access | HIGH |
| Script kiddie | Standard tools | Entertainment | LOW |

## 4. Attack Trees

### 4.1 Unauthorized Session Creation

```
[Unauthorized Session]
    │
    ├── [Valid Credentials]
    │       │
    │       ├── [Brute Force Credentials] → MITIGATED (rate limiting)
    │       ├── [Credential Stuffing] → MITIGATED (detection rules)
    │       └── [Phished Credentials] → DETECTION ONLY
    │
    └── [Session Fixation/Hijack]
            │
            ├── [Token Theft] → MITIGATED (token hashing, short TTL)
            └── [XSS/CSRF] → REDUCED (HttpOnly cookies, CORS config)
```

### 4.2 MFA Bypass

```
[MFA Bypass]
    │
    ├── [Intercept OTP]
    │       ├── [Email Interception] → OUT OF SCOPE (email security)
    │       └── [Social Engineering] → OUT OF SCOPE (human factors)
    │
    ├── [OTP Replay]
    │       └── [Concurrent Use] → VULNERABLE (race condition)
    │
    └── [MFA Bypass via Detection Failure]
            │
            ├── [Detection Down] → MITIGATED (fail-open with reconciliation)
            └── [Bypass Pre-token Check] → MITIGATED (enforced after detection)
```

### 4.3 Session Hijacking

```
[Session Hijacking]
    │
    ├── [Token Theft]
    │       ├── [Network Sniffing] → MITIGATED (HTTPS)
    │       ├── [Log Exposure] → MITIGATED (token hashing in DB)
    │       └── [Memory Dump] → OUT OF SCOPE (host security)
    │
    └── [Session Fixation]
            └── [Attacker Sets Token] → MITIGATED (tokens generated server-side)
```

## 5. Threat-Specific Analysis

### T-01: Credential Stuffing

| Attribute | Value |
|-----------|-------|
| Asset | User accounts |
| Attacker | External automated |
| Entry Point | POST /api/v1/auth/login |
| Attack Vector | Automated login attempts with leaked credentials |
| Existing Mitigation | Rate limiting (5/min), Detection Engine rules |
| Gap | Detection is async, pre-token check may not catch all |
| Impact | Mass account takeover |
| Residual Risk | MEDIUM |

**Attack Sequence:**
1. Obtain list of leaked credentials
2. Automate login attempts against /api/v1/auth/login
3. Rate limiting triggers at 5/min per IP
4. Detection Engine evaluates login attempt
5. If HIGH/CRITICAL → MFA required or session revoked
6. Attacker moves to next account

**Gap:** Detection is primarily async. Pre-token check catches some but attacker could:
- Use IPs not flagged by detection
- Stay below detection thresholds
- Exploit detection downtime (fail-open)

### T-02: Password Brute Force

| Attribute | Value |
|-----------|-------|
| Asset | User accounts |
| Attacker | External automated |
| Entry Point | POST /api/v1/auth/login |
| Attack Vector | Systematic password guessing |
| Existing Mitigation | Rate limiting, failed login counter |
| Gap | Rate limit per IP, not per account |
| Impact | Single account compromise |
| Residual Risk | MEDIUM |

**Attack Sequence:**
1. Identify target username
2. Attempt passwords at 1/second (below rate limit)
3. After 5 failed attempts from different IPs, account not locked
4. Continue until password found

**Gap:** Rate limiting is per-IP. Attacker can use multiple IPs or proxies.

### T-03: MFA OTP Replay (Race Condition)

| Attribute | Value |
|-----------|-------|
| Asset | MFA verification |
| Attacker | External |
| Entry Point | POST /api/v1/auth/mfa/verify |
| Attack Vector | Concurrent OTP verification |
| Existing Mitigation | verified_at check |
| Gap | Race condition allows double-use |
| Impact | Create multiple sessions from one OTP |
| Residual Risk | HIGH |

**Attack Sequence:**
1. Attacker obtains legitimate OTP via email
2. Submit OTP from two concurrent requests
3. Race: both requests see verified_at=None
4. Both create sessions

**Code Evidence:**
```python
# app/auth.py - vulnerable pattern
if notification.verified_at:  # Read
    raise HTTPException(400, detail="MFA code already used")
# ... verification ...
notification.verified_at = now  # Write
```

**Required Fix:** Use `SELECT FOR UPDATE` or optimistic locking.

### T-04: X-Forwarded-For Spoofing

| Attribute | Value |
|-----------|-------|
| Asset | Rate limiting, MFA binding, detection |
| Attacker | External |
| Entry Point | Any authenticated endpoint |
| Attack Vector | Forge X-Forwarded-For header |
| Existing Mitigation | Depends on deployment |
| Gap | If not behind trusted proxy, spoofable |
| Impact | Bypass rate limiting, detection evasion |
| Residual Risk | CRITICAL (if direct exposure) |

**Attack Sequence:**
1. Send request with `X-Forwarded-For: <spoofed_ip>`
2. Rate limiting counts spoofed IP instead of real IP
3. Attacker appears from different IPs each request
4. Rate limit never triggers
5. Detection features based on IP are ineffective

**Deployment Dependency:**
- **Direct exposure:** ATTACKER CAN SPOOF
- **Behind nginx with `proxy_set_header X-Real-IP`:** Only last IP trusted
- **Behind AWS ALB:** Depends on configuration

### T-05: Token Refresh Replay

| Attribute | Value |
|-----------|-------|
| Asset | Session tokens |
| Attacker | External with token access |
| Entry Point | POST /api/v1/auth/refresh |
| Attack Vector | Replay intercepted refresh token |
| Existing Mitigation | Token hash validation |
| Gap | No family tracking or reuse detection |
| Impact | Attacker can use stolen token |
| Residual Risk | HIGH |

**Attack Sequence:**
1. Attacker intercepts refresh token
2. Legitimate user refreshes (gets new tokens)
3. Attacker uses old refresh token
4. Both token pairs work (until old one expires)

**Gap:** No refresh token rotation or family invalidation.

### T-06: Session Not Revoked After Privilege Change

| Attribute | Value |
|-----------|-------|
| Asset | Session tokens |
| Attacker | Malicious insider |
| Entry Point | N/A (passive) |
| Attack Vector | Use existing session after role removal |
| Existing Mitigation | NONE |
| Gap | Session validity independent of role |
| Impact | Former admin continues with old session |
| Residual Risk | HIGH |

**Attack Sequence:**
1. User has SECURITY_ADMIN role, has active session
2. Administrator removes SECURITY_ADMIN role
3. User continues using existing session
4. Session remains valid until expiry (1 hour)

**Required Decision:** Should role revocation invalidate sessions?

### T-07: Detection Fail-Open Window

| Attribute | Value |
|-----------|-------|
| Asset | Session tokens |
| Attacker | External |
| Entry Point | POST /api/v1/auth/login |
| Attack Vector | Exploit Detection Engine downtime |
| Existing Mitigation | Async reconciliation |
| Gap | Fail-open allows unscored login |
| Impact | Attacker gets session during Detection outage |
| Residual Risk | MEDIUM (with reconciliation) |

**Attack Sequence:**
1. Attacker has valid credentials
2. Detection Engine goes down
3. Pre-token check fails open
4. Session issued without risk scoring
5. Attacker uses session
6. Detection comes back up
7. Reconciliation revokes session (if scheduled)

**Gap:** Reconciliation function exists but is never scheduled.

### T-08: Outbox Event Loss

| Attribute | Value |
|-----------|-------|
| Asset | Login events |
| Attacker | N/A (system failure) |
| Entry Point | N/A |
| Attack Vector | App crash after commit, before event sent |
| Existing Mitigation | NONE (outbox not implemented) |
| Gap | Login succeeds but Detection never receives event |
| Impact | No detection for that login |
| Residual Risk | CRITICAL |

**Attack Sequence:**
1. User logs in successfully
2. Login attempt committed to DB
3. Application crashes before sending event
4. Login not scored by Detection
5. If suspicious login, no alert generated

**Gap:** Outbox pattern not implemented.

### T-09: SQL Injection via Input Fields

| Attribute | Value |
|-----------|-------|
| Asset | Database |
| Attacker | External |
| Entry Point | All endpoints accepting user input |
| Attack Vector | Malformed input in text fields |
| Existing Mitigation | SQLAlchemy ORM (parameterized queries) |
| Gap | None identified |
| Impact | Data exfiltration or modification |
| Residual Risk | LOW |

**Assessment:** SQLAlchemy ORM provides protection against SQL injection. All user input is passed as parameters, not concatenated.

### T-10: Insecure Direct Object Reference (IDOR)

| Attribute | Value |
|-----------|-------|
| Asset | User sessions and devices |
| Attacker | Authenticated user |
| Entry Point | DELETE /api/v1/auth/sessions/{id} |
| Attack Vector | Modify resource ID to access others' resources |
| Existing Mitigation | Ownership check in code |
| Gap | Authorization checks rely on code, not DB |
| Impact | User can access/modify other users' resources |
| Residual Risk | MEDIUM |

**Evidence:**
```python
# app/auth.py - ownership check exists but...
if target_session.user_id != current_session.user_id:
    raise HTTPException(status_code=403, detail="Cannot revoke session of another user")
```

**Assessment:** Code-level authorization exists. Risk is if code changes.

### T-11: Service Impersonation

| Attribute | Value |
|-----------|-------|
| Asset | Internal API endpoints |
| Attacker | Compromised service |
| Entry Point | Internal HTTP endpoints |
| Attack Vector | Use shared secret from compromised service |
| Existing Mitigation | Shared secret validation |
| Gap | All services share same secret |
| Impact | One compromised service can impersonate all |
| Residual Risk | MEDIUM (acceptable for prototype) |

### T-12: RBAC Bypass

| Attribute | Value |
|-----------|-------|
| Asset | API endpoints |
| Attacker | Any authenticated user |
| Entry Point | All protected endpoints |
| Attack Vector | Call endpoint without required role |
| Existing Mitigation | NONE (placeholder only) |
| Gap | No authorization enforcement |
| Impact | Any user can access SOC/admin endpoints |
| Residual Risk | CRITICAL |

**Evidence:** No JWT validation middleware exists.

### T-13: Alert Timeline Modification

| Attribute | Value |
|-----------|-------|
| Asset | Audit trail |
| Attacker | Rogue SOC analyst |
| Entry Point | SOC endpoints |
| Attack Vector | Modify alert state/timeline |
| Existing Mitigation | NONE (app-level only) |
| Gap | Audit entries can be modified |
| Impact | Evidence tampering |
| Residual Risk | HIGH |

### T-14: ML Evasion

| Attribute | Value |
|-----------|-------|
| Asset | ML scoring |
| Attacker | External |
| Entry Point | POST /api/v1/auth/login |
| Attack Vector | Craft login to evade ML detection |
| Existing Mitigation | Rule Engine backup |
| Gap | Heuristic baseline may miss attacks |
| Impact | Attack undetected |
| Residual Risk | MEDIUM |

## 6. Risk Matrix

| Threat | Likelihood | Impact | Risk Score | Priority |
|--------|------------|--------|------------|----------|
| T-01: Credential Stuffing | HIGH | HIGH | HIGH | P1 |
| T-02: Brute Force | MEDIUM | HIGH | HIGH | P1 |
| T-03: MFA Replay | MEDIUM | HIGH | HIGH | P0 |
| T-04: IP Spoofing | HIGH (if direct) | HIGH | CRITICAL | P0 |
| T-05: Refresh Replay | LOW | MEDIUM | MEDIUM | P2 |
| T-06: Session After Role Change | MEDIUM | HIGH | HIGH | P1 |
| T-07: Detection Fail-Open | LOW | MEDIUM | MEDIUM | P2 |
| T-08: Outbox Event Loss | MEDIUM | CRITICAL | HIGH | P0 |
| T-09: SQL Injection | LOW | CRITICAL | MEDIUM | P3 |
| T-10: IDOR | LOW | MEDIUM | MEDIUM | P2 |
| T-11: Service Impersonation | LOW | MEDIUM | MEDIUM | P3 |
| T-12: RBAC Bypass | HIGH | CRITICAL | CRITICAL | P0 |
| T-13: Timeline Modification | LOW | HIGH | MEDIUM | P2 |
| T-14: ML Evasion | MEDIUM | MEDIUM | MEDIUM | P2 |

## 7. Mitigation Status

| Threat | Mitigation | Status | Notes |
|--------|-----------|--------|-------|
| T-01 | Rate limiting + Detection | PARTIAL | Detection is async |
| T-02 | Rate limiting | PARTIAL | Per-IP only |
| T-03 | verified_at check | VULNERABLE | Race condition exists |
| T-04 | X-Forwarded-For trust | DEPENDS | Deployment-dependent |
| T-05 | Token hashing | PARTIAL | No family tracking |
| T-06 | None | NONE | Decision needed |
| T-07 | Reconciliation | DESIGNED_ONLY | Not scheduled |
| T-08 | Outbox pattern | NOT_IMPLEMENTED | Schema only |
| T-09 | SQLAlchemy ORM | MITIGATED | Low risk |
| T-10 | Code-level checks | MITIGATED | Low risk |
| T-11 | Shared secret | ACCEPTABLE | Prototype only |
| T-12 | None | VULNERABLE | No auth middleware |
| T-13 | App-level only | WEAK | No DB immutability |
| T-14 | Rule backup | MITIGATED | Heuristic baseline |

## 8. Priority Findings

### P0 (Critical - Immediate Action)
1. **T-12 RBAC Bypass:** Implement authorization middleware
2. **T-04 IP Spoofing:** Document and mitigate deployment risk
3. **T-03 MFA Replay:** Fix race condition with proper locking
4. **T-08 Outbox Loss:** Implement outbox pattern

### P1 (High Priority)
5. **T-01 Credential Stuffing:** Enhance detection timeliness
6. **T-02 Brute Force:** Consider per-account rate limiting
7. **T-06 Session After Role Change:** Decide and implement

### P2 (Medium Priority)
8. **T-05 Refresh Replay:** Implement token family tracking
9. **T-07 Fail-Open Window:** Schedule reconciliation worker
10. **T-13 Timeline Modification:** Add DB immutability

### P3 (Low Priority - Future)
11. **T-09 SQL Injection:** Continue using ORM
12. **T-10 IDOR:** Add integration tests
13. **T-11 Service Impersonation:** Plan per-service secrets
14. **T-14 ML Evasion:** Train ML model with real data
