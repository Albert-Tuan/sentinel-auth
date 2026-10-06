# Sentinel Auth - Trust Boundaries

## 1. Trust Boundary Overview

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL ZONE                                    │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────┐          │
│  │   Browser   │    │  Mobile App     │    │  Admin Portal      │          │
│  │  (User)     │    │  (User)         │    │  (SOC/Admin)       │          │
│  └──────┬──────┘    └────────┬────────┘    └──────────┬──────────┘          │
│         │                      │                        │                       │
│         │ HTTPS               │ HTTPS                  │ HTTPS                 │
└─────────┼──────────────────────┼────────────────────────┼──────────────────────┘
          │                      │                        │
          ▼                      ▼                        ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                           UNTRUSTED ZONE                                      │
│                                                                                │
│  Reverse Proxy / Load Balancer                                                 │
│  (May terminate TLS, sets X-Forwarded-For)                                   │
│                                                                                │
└────────────────────────────────────┬───────────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                            TRUSTED ZONE                                        │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐  │
│  │                    SINGLE FASTAPI APPLICATION                              │  │
│  │                                                                         │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │  │
│  │  │   Core App   │  │   Detection  │  │    ML        │                │  │
│  │  │  (Logical)  │  │   Engine     │  │   Service    │                │  │
│  │  │              │  │  (Logical)  │  │  (Logical)  │                │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │  │
│  │         │                  │                  │                       │  │
│  │         │   Internal HTTP Calls (shared secret)                       │  │
│  │         └──────────────────┼──────────────────┘                       │  │
│  │                            │                                          │  │
│  │                            ▼                                          │  │
│  │                   ┌──────────────┐                                  │  │
│  │                   │   Shared     │                                  │  │
│  │                   │   Database   │                                  │  │
│  │                   │  (All Tables) │                                  │  │
│  │                   └──────────────┘                                  │  │
│  │                                                                         │  │
│  └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Email/SMS      │  │   Database      │  │   Monitoring    │             │
│  │  Provider       │  │   Server        │  │   System       │             │
│  │  (External)     │  │   (Trusted)     │  │   (Optional)   │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Trust Boundary Matrix

| From | To | Protocol | Auth | Encryption | Notes |
|------|-----|----------|------|------------|-------|
| Browser | Reverse Proxy | HTTPS | None | TLS 1.2+ | TLS termination here |
| Reverse Proxy | Core App | HTTP | X-Forwarded-For | None (internal) | Trust depends on proxy config |
| Core App | Detection Engine | HTTP | X-Internal-Secret | None (internal) | Same process in prototype |
| Detection Engine | ML Service | HTTP | X-Internal-Secret | None (internal) | Same process in prototype |
| Detection Engine | Core App | HTTP | X-Internal-Secret | None (internal) | Callback pattern |
| Core App | Email Provider | SMTP/SMTP+TLS | None | STARTTLS | Placeholder implementation |
| Any | PostgreSQL | PostgreSQL | Password (env var) | TLS (if configured) | Single database in prototype |

## 3. IP Trust Model

### 3.1 Current Implementation

```python
def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
```

### 3.2 Trust Assessment

| Assumption | Status | Risk |
|-----------|--------|------|
| X-Forwarded-For is trusted | ⚠️ CONDITIONAL | **HIGH** if not behind trusted proxy |
| request.client.host is accurate | ⚠️ DEPENDS | Low if directly exposed |
| No IP spoofing possible | ❌ FALSE | Depends on deployment |

### 3.3 Deployment Scenarios

**Scenario A: Direct Exposure**
```
Client → Core App (directly exposed to internet)
```
- `X-Forwarded-For` is USER-CONTROLLED
- **IP-based controls are BYPASSABLE**
- Risk: HIGH

**Scenario B: Behind Trusted Proxy**
```
Client → nginx → Core App
```
- nginx strips/validates X-Forwarded-For
- `X-Forwarded-For` from nginx is TRUSTED
- Risk: LOW (if nginx is configured correctly)

**Scenario C: Behind Load Balancer**
```
Client → AWS ALB → Core App
```
- ALB sets X-Forwarded-For
- Must configure ALB to trust only itself
- Risk: MEDIUM (configuration-dependent)

### 3.4 Recommendations

1. **Document the deployment assumption explicitly**
2. **If direct exposure, reject X-Forwarded-For entirely**
3. **If behind proxy, configure trusted proxy list**
4. **Add warning in configuration about IP spoofing risk**

## 4. Internal Service Authentication

### 4.1 Current Implementation

```python
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "changeme-in-production")

def verify_internal_secret(x_internal_secret: Optional[str]) -> None:
    if not x_internal_secret or x_internal_secret != internal_secret():
        raise HTTPException(status_code=401, ...)
```

### 4.2 Trust Assessment

| Aspect | Status | Risk |
|--------|--------|------|
| Secret stored in env | ✅ SECURE | Env vars are safer than code |
| Default value exists | ⚠️ WARNING | Must be changed in production |
| Secret compared safely | ✅ SECURE | Timing-safe comparison not needed (single process) |
| All services share secret | ⚠️ ACCEPTABLE | Prototype assumption |

### 4.3 Production Requirements

1. **Generate strong random secret** (minimum 32 bytes)
2. **Rotate secret periodically**
3. **Use different secrets per service** (future)
4. **Implement secret injection** (Kubernetes secrets, Vault, etc.)

## 5. Database Trust

### 5.1 Current Implementation

```python
database_url = os.getenv(
    "DATABASE_URL", 
    "postgresql://sentinel:sentinel@localhost:5432/sentinel"
)
```

### 5.2 Trust Assessment

| Aspect | Status | Risk |
|--------|--------|------|
| Single database | ⚠️ NOTE | Prototype consolidation |
| Credentials in env | ✅ SECURE | Not in code |
| Same session for all | ⚠️ NOTE | No service isolation |
| Cross-table access | ⚠️ WARNING | Detection can access core tables |

### 5.3 Multi-Database Concerns

**Current:** Single DATABASE_URL shared by all logical services
**Documented:** Three separate databases

**Risk:** In single-database mode, all tables coexist. There's no DB-level enforcement that Detection Engine only accesses detection tables.

## 6. Data Sensitivity Matrix

| Data Type | Classification | Storage | Encryption | Access Control |
|-----------|---------------|---------|------------|----------------|
| Password hashes | SECRET | Argon2 hash | N/A | Internal only |
| Access tokens | HIGHLY CONFIDENTIAL | SHA256 hash | N/A | Session validation |
| Refresh tokens | HIGHLY CONFIDENTIAL | SHA256 hash | N/A | Session validation |
| OTP codes | CONFIDENTIAL | Argon2 hash | N/A | Single-use |
| MFA codes | CONFIDENTIAL | Argon2 hash | N/A | Single-use |
| User email | PII | Plain text | DB encryption (if enabled) | Authenticated users |
| User IP | PII | INET type | DB encryption (if enabled) | SOC only |
| Session IP | PII | FK to ip_addresses | DB encryption (if enabled) | SOC only |
| Audit logs | CONFIDENTIAL | Plain text JSON | DB encryption (if enabled) | Admin only |
| Detection scores | INTERNAL | JSON | N/A | SOC only |
| ML features | INTERNAL | JSON | N/A | ML service only |

## 7. Failure Mode Trust Boundaries

| Failure | Trust Impact | Recovery |
|---------|--------------|----------|
| Database unavailable | All services fail | Graceful degradation |
| Detection Engine unavailable | Fail-open for auth | Asynchronous reconciliation |
| ML Service unavailable | Graceful degradation (rule-only) | Returns to rule_score |
| Email provider unavailable | MFA cannot be delivered | MFA verification blocked |
| Outbox poller dies | Events not delivered | Manual intervention |
| Session DB corruption | All sessions invalidated | Force re-authentication |

## 8. Security Boundaries Summary

### 8.1 Strong Boundaries (Enforced)
- ✅ User authentication (password verification)
- ✅ MFA verification (OTP validation)
- ✅ Token hashing (SHA256)
- ✅ Internal API secret validation
- ✅ Input validation (Pydantic)

### 8.2 Weak Boundaries (Needs Improvement)
- ⚠️ IP-based controls (X-Forwarded-For trust)
- ⚠️ RBAC (authorization not enforced)
- ⚠️ Database access control (no service isolation)
- ⚠️ Audit log immutability (no DB enforcement)

### 8.3 Missing Boundaries (Not Implemented)
- ❌ Token expiration enforcement at request time
- ❌ Role change → session invalidation
- ❌ IP-based anomaly detection (spoofable)
- ❌ DB-level immutability for audit logs
- ❌ Schema-level service isolation
