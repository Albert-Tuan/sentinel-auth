# ERD v3.3 - Detection Engine Integration

> Dựa trên ERD v3.2, tích hợp đầy đủ Detection Engine
> Detection Engine có database riêng, giao tiếp qua HTTP với Core-app

---

## Design Decisions từ Detection Engine

| # | Câu hỏi | v3.2 | Cập nhật | Lý do |
|---|---------|------|-----------|-------|
| 1 | SOC Analyst là gì? | Entity riêng `soc_analysts` | **Giữ v3.2** | SOC Analyst có metadata riêng (display_name, max_alerts) |
| 2 | Alert:LoginAttempt? | 1:N | **Giữ v3.2** | `primary_alert_id` cho phép 1 login → nhiều alerts |
| 3 | Detection Logs Stage? | rule/ml/combined/action | **Thêm chi tiết** | rule_evaluation, ml_call, scoring, action_sent |
| 4 | Detection Engine DB? | Chung với Core | **Tách riêng** | Detection Engine có DB riêng |
| 5 | risk_assessments:login_attempts? | ERD gốc khai báo 1:N | **Sửa thành 1:1** | UNIQUE constraint trên login_attempt_id |
| 6 | inference_logs:model_versions? | ERD gốc vẽ nét đứt | **Sửa thành nét liền** | Cùng ml-service-db = FK thật |
| 7 | system_settings.updated_by? | ERD gốc thiếu | **Thêm quan hệ 1:N** | FK có trong schema nhưng thiếu trong ERD |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   SENTINEL AUTH - DATABASE ARCHITECTURE v3.3                │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                             │
│  ┌─────────────────────┐         ┌─────────────────────┐         ┌─────────────────────┐   │
│  │      CORE APP       │         │  DETECTION ENGINE   │         │    ML SERVICE       │   │
│  │    (core-db)        │         │   (detection-db)    │         │   (ml-service-db)   │   │
│  ├─────────────────────┤         ├─────────────────────┤         ├─────────────────────┤   │
│  │ • users             │         │ • policies          │         │ • model_versions   │   │
│  │ • sessions          │         │ • login_attempts    │         │ • inference_logs   │   │
│  │ • mfa_transactions  │         │ • risk_assessments  │         │ • feature_stats    │   │
│  │ • audit_logs        │         │ • detection_logs    │         │                    │   │
│  │ • outbox_events     │         │ • alerts            │         │                    │   │
│  │ • ...               │         │ • alert_timeline    │         │                    │   │
│  └──────────┬──────────┘         └──────────┬──────────┘         └──────────┬──────────┘   │
│             │                              │                              │               │
│             │    HTTP (LoginEvent)        │                              │               │
│             │ ════════════════════════════╪═════════════════════════════►│               │
│             │                              │    HTTP (ML Request)        │               │
│             │    HTTP (Action)             │                              │               │
│             │ ◄═══════════════════════════│                              │               │
│             │                              │                              │               │
└─────────────┼──────────────────────────────┼──────────────────────────────┼───────────────┘
              │                              │                              │
              ▼                              ▼                              ▼
┌─────────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐
│        CORE DB          │    │     DETECTION DB        │    │      ML SERVICE DB      │
│    (PostgreSQL)          │    │    (PostgreSQL)         │    │    (PostgreSQL)        │
│    13 tables            │    │    7 tables             │    │    3 tables            │
└─────────────────────────┘    └─────────────────────────┘    └─────────────────────────┘
```

---

## Entity-Relationship Diagram (ERD)

```mermaid
erDiagram

    %% ============================================================================
    %% CORE-APP TABLES (core-db)
    %% ============================================================================

    users {
        uuid id PK "gen_random_uuid()"
        text username UK "3-50 chars"
        text password_hash "Argon2id"
        text email UK "nullable"
        text full_name "nullable"
        text status "active|suspended|locked"
        bool admin_mfa_required "default FALSE"
        bool detection_mfa_once "default FALSE"
        timestamptz last_login_at "nullable"
        int failed_login_count "default 0"
        timestamptz locked_at "nullable"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    roles {
        text id PK "USER|SECURITY_ADMIN|SOC_ANALYST|SECURITY_MANAGER"
        text name "English"
        text name_vi "Vietnamese"
        text description "nullable"
        timestamptz created_at
    }

    user_roles {
        uuid id PK
        uuid user_id FK "→ users(id), CASCADE"
        text role_id FK "→ roles(id)"
        timestamptz assigned_at "default NOW()"
        uuid assigned_by FK "→ users(id), nullable"
    }

    sessions {
        uuid id PK
        uuid user_id FK "→ users(id), CASCADE"
        text access_token_hash "NOT NULL"
        text refresh_token_hash "nullable"
        uuid refresh_token_family "nullable"
        text token_jti UK "nullable"
        timestamptz expires_at "NOT NULL"
        timestamptz last_activity_at "nullable"
        timestamptz revoked_at "nullable"
        uuid ip_address_id FK "→ ip_addresses(id), nullable"
        text user_agent "nullable"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    ip_addresses {
        uuid id PK
        inet ip_address UK "NOT NULL"
        text country_code "nullable"
        text country_name "nullable"
        bool is_proxy "default FALSE"
        bool is_vpn "default FALSE"
        bool is_tor "default FALSE"
        timestamptz first_seen_at "default NOW()"
        timestamptz last_seen_at "default NOW()"
    }

    mfa_transactions {
        uuid id PK
        uuid user_id FK "→ users(id), CASCADE"
        text mfa_type "one_time|persistent"
        text status "pending|completed|expired|failed"
        inet bound_ip "nullable"
        uuid notification_id FK "→ mfa_notifications(id), nullable"
        int fail_count "default 0"
        timestamptz expires_at "NOT NULL"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    mfa_notifications {
        uuid id PK
        uuid mfa_transaction_id FK "→ mfa_transactions(id), CASCADE"
        text channel "email|sms|totp"
        text recipient "NOT NULL"
        text mfa_code_hash "NOT NULL"
        timestamptz sent_at "default NOW()"
        timestamptz delivered_at "nullable"
        timestamptz failed_at "nullable"
        text failure_reason "nullable"
        timestamptz expires_at "NOT NULL"
        timestamptz verified_at "nullable"
        timestamptz created_at "default NOW()"
    }

    audit_logs {
        uuid id PK
        uuid request_id "nullable"
        uuid actor_id FK "→ users(id), nullable"
        text actor_type "user|system"
        text action "NOT NULL"
        text resource "NOT NULL"
        uuid resource_id "nullable"
        jsonb before_state "nullable"
        jsonb after_state "nullable"
        text change_reason "nullable"
        inet ip_address "nullable"
        text user_agent "nullable"
        timestamptz created_at "default NOW()"
    }

    user_trusted_devices {
        uuid id PK
        uuid user_id FK "→ users(id), CASCADE"
        text device_fingerprint "NOT NULL"
        text device_name "nullable"
        inet last_ip "nullable"
        text last_user_agent "nullable"
        timestamptz last_used_at "default NOW()"
        timestamptz expires_at "nullable"
        timestamptz created_at "default NOW()"
    }

    system_settings {
        text key PK
        text value "NOT NULL"
        text value_type "string|integer|boolean|json"
        text description "nullable"
        text category "auth|mfa|rate_limit|detection|notification|general"
        uuid updated_by FK "→ users(id), nullable"
        timestamptz updated_at "default NOW()"
    }

    outbox_events {
        uuid id PK
        text aggregate_type "login_attempt|alert|user|session"
        uuid aggregate_id "NOT NULL"
        text event_type "NOT NULL"
        int version "default 1"
        jsonb payload "NOT NULL"
        jsonb headers "nullable"
        text status "pending|processing|published|failed"
        int retry_count "default 0"
        int max_retries "default 3"
        text last_error "nullable"
        timestamptz created_at "default NOW()"
        timestamptz published_at "nullable"
    }

    user_notifications {
        uuid id PK
        uuid user_id FK "→ users(id), CASCADE"
        text type "NOT NULL"
        text title "NOT NULL"
        text body "NOT NULL"
        text link "nullable"
        text priority "low|normal|high|urgent"
        bool read "default FALSE"
        timestamptz read_at "nullable"
        timestamptz expires_at "nullable"
        timestamptz created_at "default NOW()"
    }

    rate_limits {
        inet ip_address PK "INET"
        text action PK
        int count "default 1"
        int max_count "default 5"
        timestamptz window_start "default NOW()"
    }

    %% ============================================================================
    %% DETECTION-ENGINE TABLES (detection-db)
    %% ============================================================================

    policies {
        uuid id PK "gen_random_uuid()"
        text version UK "v1.0, v2.0"
        text name "nullable"
        text description "nullable"
        jsonb rules "NOT NULL, JSONB array"
        jsonb config "NOT NULL: weights, thresholds"
        bool is_active "default FALSE"
        uuid created_by UUID "nullable, reference to users.id in core-db"
        timestamptz created_at "default NOW()"
        timestamptz activated_at "nullable"
        timestamptz deactivated_at "nullable"
    }

    login_attempts_de {
        uuid id PK "gen_random_uuid()"
        uuid event_id "from core-app, for idempotency"
        uuid user_id "nullable, NULL if login failed"
        text username_attempted "nullable"
        text outcome "success|failure|mfa_required|mfa_success|mfa_failed|blocked|locked|rate_limited"
        bool mfa_used "default FALSE"
        inet ip_address "nullable"
        text user_agent "nullable"
        timestamptz timestamp "default NOW()"
        text status "pending|processed|failed"
        uuid policy_id FK "→ policies(id), nullable"
        uuid request_id "default gen_random_uuid()"
        uuid primary_alert_id FK "→ alerts(id), nullable"
        text risk_level "low|medium|high|critical|nullable"
        text detection_decision "allow|challenge|block|nullable"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    risk_assessments {
        uuid id PK
        uuid login_attempt_id FK UK "→ login_attempts(id), CASCADE, UNIQUE (1:1)"
        uuid policy_id FK "→ policies(id), nullable"
        numeric rule_score "nullable, 0.0000-1.0000"
        numeric ml_score "nullable"
        numeric combined_score "nullable"
        text ml_status "success|unavailable|error"
        text ml_model_version "nullable"
        jsonb rule_hits "nullable: array of triggered rules"
        jsonb ml_reason_codes "nullable"
        jsonb ml_features_used "nullable"
        text risk_level "low|medium|high|critical|nullable"
        text decision "allow|challenge|block|nullable"
        timestamptz created_at "default NOW()"
    }

    detection_logs {
        uuid id PK
        uuid login_attempt_id FK "→ login_attempts(id), SET NULL"
        uuid request_id "nullable"
        text stage "rule_evaluation|ml_call|scoring|action_sent"
        text stage_detail "nullable: specific rule name"
        uuid rule_id "nullable"
        text rule_name "nullable"
        bool triggered "nullable"
        numeric score_contribution "nullable"
        text decision "allow|challenge|block|nullable"
        text reason "nullable"
        jsonb details "nullable: error, reason_codes, etc."
        timestamptz created_at "default NOW()"
    }

    soc_analysts {
        uuid id PK
        uuid user_id FK UK "→ users(id) in core-db, CASCADE, UNIQUE"
        text display_name "nullable"
        bool is_active "default TRUE"
        int max_alerts "default 50"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    alerts {
        uuid id PK
        uuid login_attempt_id FK "→ login_attempts(id), CASCADE"
        uuid policy_id FK "→ policies(id), nullable"
        uuid request_id "nullable"
        text status "open|acknowledged|resolved|false_positive"
        text risk_level "low|medium|high|critical|nullable"
        text detection_reason "nullable"
        jsonb detection_scores "nullable"
        uuid assigned_to_id FK "→ soc_analysts(id), nullable"
        uuid resolved_by_id FK "→ soc_analysts(id), nullable"
        timestamptz resolved_at "nullable"
        text resolution "nullable"
        text notes "nullable"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    alert_timeline {
        uuid id PK
        uuid alert_id FK "→ alerts(id), CASCADE"
        text event_type "created|acknowledged|assigned|unassigned|escalated|note_added|status_changed|resolved|false_positive"
        uuid actor_id "nullable, user_id from core-db"
        text actor_type "user|system"
        text old_value "nullable"
        text new_value "nullable"
        text comment "nullable"
        inet ip_address "nullable"
        timestamptz created_at "default NOW()"
    }

    %% ============================================================================
    %% ML-SERVICE TABLES (ml-service-db)
    %% ============================================================================

    model_versions {
        uuid id PK
        text name "NOT NULL"
        text version UK "v1.0-isolation-forest"
        text algorithm "IsolationForest"
        text description "nullable"
        text model_path "Path to model file"
        jsonb config "threshold, metrics, etc."
        text status "staged|active|archived|failed"
        bool is_production "default FALSE"
        timestamptz training_date "nullable"
        timestamptz deployed_at "nullable"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    inference_logs {
        uuid id PK
        uuid request_id UK "NOT NULL"
        uuid model_version_id FK "→ model_versions(id), nullable"
        text model_version_used "NOT NULL"
        jsonb features "6 input features"
        numeric raw_score "nullable"
        numeric normalized_score "0.0000-1.0000"
        bool is_anomaly "NOT NULL"
        jsonb reason_codes "nullable"
        text model_status "ready|degraded|error"
        int processing_time_ms "nullable"
        text error_message "nullable"
        timestamptz created_at "default NOW()"
    }

    feature_statistics {
        uuid id PK
        text feature_name "NOT NULL"
        timestamptz timestamp "default NOW()"
        bigint count "NOT NULL"
        numeric mean "nullable"
        numeric std "nullable"
        numeric min "nullable"
        numeric max "nullable"
        numeric anomaly_rate "nullable"
        timestamptz created_at "default NOW()"
    }

    %% ============================================================================
    %% CROSS-SERVICE RELATIONSHIPS
    %% ============================================================================

    %% Core: Users → Roles (1:N)
    users ||--o{ user_roles : "has"
    roles ||--o{ user_roles : "assigned"
    user_roles }o--|| users : "assigned_by"

    %% Core: Users → Sessions (1:N, CASCADE)
    users ||--o{ sessions : "creates"

    %% Core: Sessions → IP (N:1, OPTIONAL)
    sessions }o--|| ip_addresses : "from"

    %% Core: Users → MFA Transactions (1:N, CASCADE)
    users ||--o{ mfa_transactions : "initiates"

    %% Core: MFA Transaction → Notification (1:1, CASCADE)
    mfa_transactions ||--|| mfa_notifications : "creates"

    %% Core: Users → Audit Logs (1:N, SET NULL)
    users ||--o{ audit_logs : "actions_by"

    %% Core: Users → Trusted Devices (1:N, CASCADE)
    users ||--o{ user_trusted_devices : "registers"

    %% Core: Users → Notifications (1:N, CASCADE)
    users ||--o{ user_notifications : "receives"

    %% Core: Users → System Settings (1:N, OPTIONAL) — updated_by
    users ||--o{ system_settings : "updates"

    %% Detection: Login Attempts Flow
    %% ============================================================================

    %% Core → Detection: LoginEvent triggers LoginAttempt
    login_attempts_de ||--o{ detection_logs : "generates"
    login_attempts_de ||--o{ alerts : "triggers"

    %% Detection: Risk Assessment per Login (1:1) — UNIQUE constraint enforces 1:1
    login_attempts_de ||--|| risk_assessments : "has"

    %% Detection: Login → Primary Alert (1:1, OPTIONAL)
    login_attempts_de ||--o| alerts : "primary_alert"

    %% Detection: Login → Policy (N:1, OPTIONAL)
    login_attempts_de }o--|| policies : "evaluated with"

    %% Detection: Risk Assessment → Policy (N:1, OPTIONAL)
    risk_assessments }o--|| policies : "evaluated with"

    %% Detection: Alerts → Policy (N:1, OPTIONAL)
    alerts }o--|| policies : "context"

    %% ============================================================================
    %% Detection: SOC Workflow
    %% ============================================================================

    %% Alerts → SOC Analysts (N:1, OPTIONAL)
    alerts }o--|| soc_analysts : "assigned_to"
    alerts }o--|| soc_analysts : "resolved_by"

    %% Alerts → Timeline (1:N, CASCADE)
    alerts ||--o{ alert_timeline : "has"

    %% ============================================================================
    %% Detection: SOC Analysts (linked to Core Users)
    %% ============================================================================

    %% SOC Analysts → Core Users (1:1, CASCADE)
    soc_analysts ||--|| users : "is_analyst"

    %% ============================================================================
    %% ML Service: Intra-DB Relationships
    %% ============================================================================

    %% ML Service: inference_logs → model_versions (FK, cùng ml-service-db)
    inference_logs }o--|| model_versions : "references"

    %% Detection Engine calls ML Service (HTTP, cross-service)
    detection_logs }o..|| model_versions : "calls"
```
```

---

## Database Separation

### Core DB Schema

```
┌─────────────────────────────────────────────────────────┐
│  CORE-DB (core-app)                                     │
├─────────────────────────────────────────────────────────┤
│  USERS            │ Core authentication                 │
│  USER_ROLES       │ Role assignments                   │
│  ROLES            │ Role definitions                   │
│  SESSIONS         │ JWT token management               │
│  IP_ADDRESSES     │ Normalized IP tracking              │
│  MFA_TRANSACTIONS │ MFA challenge lifecycle            │
│  MFA_NOTIFICATIONS│ OTP email/SMS tracking             │
│  AUDIT_LOGS       │ Immutable audit trail              │
│  USER_TRUSTED_DEVICES │ Remember-me devices           │
│  SYSTEM_SETTINGS  │ Dynamic configuration               │
│  OUTBOX_EVENTS    │ Transactional outbox               │
│  USER_NOTIFICATIONS│ In-app notifications             │
│  RATE_LIMITS     │ Rate limiting counters               │
└─────────────────────────────────────────────────────────┘
```

### Detection DB Schema

```
┌─────────────────────────────────────────────────────────┐
│  DETECTION-DB (detection-engine)                       │
├─────────────────────────────────────────────────────────┤
│  POLICIES           │ Detection rules + weights (JSONB)│
│  LOGIN_ATTEMPTS    │ All login events from core-app    │
│  RISK_ASSESSMENTS  │ Per-attempt scoring (1:1)         │
│  DETECTION_LOGS    │ Detailed audit trail              │
│  SOC_ANALYSTS      │ Analyst profiles (linked to users)│
│  ALERTS            │ SOC alerts (1:N to login_attempts)│
│  ALERT_TIMELINE    │ SOC action audit trail            │
└─────────────────────────────────────────────────────────┘
```

### ML Service DB Schema (3 tables - optional)

```
┌─────────────────────────────────────────────────────────┐
│  ML-SERVICE-DB (ml-service)                             │
├─────────────────────────────────────────────────────────┤
│  MODEL_VERSIONS    │ Model registry for versioning      │
│  INFERENCE_LOGS   │ Optional inference debugging       │
│  FEATURE_STATISTICS│ Data drift monitoring             │
│                                                          │
│  Note: ML Service is primarily stateless.                │
│  Database is for registry and logging only.              │
└─────────────────────────────────────────────────────────┘
```

---

## Contract: Core ↔ Detection Engine

### LoginEvent (core-app → detection-engine)

```json
{
  "event_id": "uuid",
  "user_id": "uuid | null",
  "username_attempted": "string",
  "outcome": "success | failure | mfa_required | mfa_success | blocked | locked | rate_limited",
  "mfa_used": false,
  "ip_address": "x.x.x.x",
  "user_agent": "string",
  "timestamp": "ISO8601"
}
```

### Action (detection-engine → core-app)

```json
{
  "action": "REQUIRE_MFA | REVOKE_SESSIONS | LOCK_USER | RATE_LIMIT_IP",
  "target": {
    "type": "user_id | ip_address",
    "value": "uuid | x.x.x.x"
  },
  "reason": "string",
  "risk_level": "medium | high | critical",
  "login_attempt_id": "uuid"
}
```

---

## Key Differences from v3.2

| Aspect | v3.2 | v3.3 |
|--------|------|------|
| Database | **Single DB** | **3 Separate DBs** (core + detection + ml-service) |
| Communication | Direct SQL | HTTP REST between services |
| SOC Analyst | `soc_analysts` table | **Giữ nguyên** (linked to users) |
| Alert:Login | **1:N** | **Giữ nguyên** (1:N with primary_alert_id) |
| Detection Logs | 4 stages | **Mở rộng** (rule_evaluation, ml_call, scoring, action_sent) |
| Policy Storage | `policy_versions` (core-db) | `policies` (detection-db, JSONB) |
| ML Service | Không có | **Tách riêng** với model registry |

---

## File Outputs

1. `docs/diagrams/ERD_v3.3.md` - Complete ERD with Mermaid diagram
2. `infra/postgres/schema-core-v3.3.sql` - Core DB schema (13 tables)
3. `infra/postgres/schema-detection-v3.3.sql` - Detection Engine DB schema (7 tables)
4. `infra/postgres/schema-ml-service-v3.3.sql` - ML Service DB schema (3 tables)

---

## Service Summary

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           SENTINEL AUTH - SERVICES                            │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐           │
│  │    CORE-APP     │    │ DETECTION-ENGINE│    │   ML-SERVICE    │           │
│  ├─────────────────┤    ├─────────────────┤    ├─────────────────┤           │
│  │ Port: 8000      │    │ Port: 8001      │    │ Port: 8002      │           │
│  │                  │    │                  │    │                  │           │
│  │ • Auth/Login    │    │ • Rule Engine   │    │ • ML Inference  │           │
│  │ • MFA/OTP       │    │ • Risk Scoring │    │ • Model Registry│           │
│  │ • Session Mgmt  │    │ • Alert Mgmt   │    │ • Health Check  │           │
│  │ • User Mgmt     │    │ • SOC Workflow │    │                  │           │
│  │                  │    │                  │    │                  │           │
│  │                  │    │                  │    │                  │           │
│  │ [core-db]       │    │ [detection-db]  │    │ [ml-service-db] │           │
│  │  13 tables      │    │  7 tables       │    │  3 tables       │           │
│  └────────┬────────┘    └────────┬────────┘    └─────────────────┘           │
│           │                        │                                              │
│           │ LoginEvent             │ ML Request                                   │
│           │ ═══════════════════════╪═══════════════════════                     │
│           │                        │                                              │
│           │ Action                 │                                              │
│           │ ◄══════════════════════│                                              │
│           │                        │                                              │
└───────────┼────────────────────────┼──────────────────────────────────────────────┘
            │                        │
            ▼                        ▼
      ┌───────────┐          ┌───────────┐
      │ CORE DB   │          │DETECTION  │
      │ 13 tables │          │DB 7 tables│
      └───────────┘          └───────────┘
