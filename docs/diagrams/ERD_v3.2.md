# Database Schema v3.2 - Balanced Normalization

> Schema tối giản ở mức vừa phải - Cân bằng giữa đơn giản và 3NF

---

## Design Decisions & Options Selected

### Options được chọn cho v3.2

| # | Câu hỏi | Options | **Chọn** | Lý do |
|---|---------|---------|---------|-------|
| 1 | **Actor là gì?** | A) User only<br>B) User + System<br>C) User + System + API Key | **B) User + System** | Audit logs có thể từ user hoặc system |
| 2 | **SOC Analyst là gì?** | A) User đặc biệt<br>B) Entity riêng | **A) User đặc biệt** | Đơn giản, dùng role để phân biệt |
| 3 | **Alert với Login?** | A) 1:1<br>B) 1:N | **B) 1:N** | 1 login có thể tạo nhiều alert types |
| 4 | **Risk Assessment?** | A) Mọi Login<br>B) Chỉ high-risk | **A) Mọi Login** | Detection engine đánh giá mọi login |
| 5 | **Xóa User → Sessions?** | A) CASCADE<br>B) SET NULL<br>C) RESTRICT | **A) CASCADE** | User xóa → sessions cũng xóa |
| 6 | **MFA 1:1 Notification?** | A) Có<br>B) Không | **A) Có** | Mỗi MFA transaction = 1 notification |
| 7 | **Failed Login có User?** | A) Có<br>B) Không | **B) Không** | Failed login có thể không có user_id |
| 8 | **IP Tracking?** | A) Chỉ IP<br>B) IP + Geolocation | **A) Chỉ IP** | Tối giản, geolocation tách sau |
| 9 | **Detection Rules?** | A) JSON trong Policy<br>B) Bảng riêng | **A) JSON trong Policy** | Đơn giản, versioning dễ |
| 10 | **Audit Logs?** | A) Có<br>B) Không | **A) Có** | Security app cần audit trail |
| 11 | **Outbox Pattern?** | A) Có<br>B) Không | **A) Có** | Đảm bảo event delivery |
| 12 | **Rate Limits?** | A) Bảng riêng<br>B) Cache/Redis | **A) Bảng riêng** | Persistence cho rate limiting |

---

## Schema Overview

```
┌─────────────────────────────────────────────────────────────┐
│ v3.2 - 21 TABLES                                           │
├─────────────────────────────────────────────────────────────┤
│ CORE TABLES (17)                                           │
│   users, user_roles, sessions                              │
│   mfa_transactions, mfa_notifications                     │
│   policy_versions, login_attempts                           │
│   risk_assessments, detection_logs, alerts                 │
│   alert_timeline, audit_logs                               │
│   user_trusted_devices, system_settings                   │
│   outbox_events, user_notifications, rate_limits           │
│                                                             │
│ NORMALIZED TABLES (4) - 3NF Compliance                    │
│   actors (actor_id + actor_type)                           │
│   soc_analysts (user_id → users)                          │
│   ip_addresses (normalized IP)                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Entity-Relationship Diagram (ERD)

```mermaid
erDiagram

    %% ============================================================================
    %% CORE TABLES
    %% ============================================================================

    users {
        uuid id PK "gen_random_uuid()"
        text username UK "3-50 chars, alphanumeric + underscore"
        text password_hash "Argon2id hash"
        text email UK "nullable"
        text full_name "nullable"
        text status "CHECK: active, suspended, locked"
        bool admin_mfa_required "default FALSE"
        bool detection_mfa_once "default FALSE"
        timestamptz last_login_at "nullable"
        int failed_login_count "default 0"
        timestamptz locked_at "nullable"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    roles {
        text id PK "USER, SECURITY_ADMIN, SOC_ANALYST, SECURITY_MANAGER"
        text name "English name"
        text name_vi "Vietnamese name"
        text description "nullable"
        timestamptz created_at
    }

    user_roles {
        uuid id PK "Primary Key"
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text role_id FK "→ roles(id)"
        timestamptz assigned_at "default NOW()"
        uuid assigned_by FK "→ users(id), nullable, ON DELETE SET NULL"
    }

    sessions {
        uuid id PK
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text access_token_hash "bcrypt hash"
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
        uuid id PK "gen_random_uuid()"
        inet ip_address UK "Unique IP"
        text country_code "nullable - future"
        text country_name "nullable - future"
        bool is_proxy "default FALSE"
        bool is_vpn "default FALSE"
        bool is_tor "default FALSE"
        timestamptz first_seen_at "default NOW()"
        timestamptz last_seen_at "default NOW()"
    }

    mfa_transactions {
        uuid id PK
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text mfa_type "CHECK: one_time, persistent"
        text status "CHECK: pending, completed, expired, failed"
        inet bound_ip "nullable"
        uuid notification_id "nullable"
        int fail_count "default 0"
        timestamptz expires_at "NOT NULL"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    mfa_notifications {
        uuid id PK
        uuid mfa_transaction_id FK "→ mfa_transactions(id), ON DELETE CASCADE"
        text channel "CHECK: email, sms, totp"
        text recipient "email or phone number"
        text mfa_code_hash "bcrypt hash"
        timestamptz sent_at "default NOW()"
        timestamptz delivered_at "nullable"
        timestamptz failed_at "nullable"
        text failure_reason "nullable"
        timestamptz expires_at "NOT NULL"
        timestamptz verified_at "nullable"
        timestamptz created_at "default NOW()"
    }

    policy_versions {
        uuid id PK
        text version UK "v1.0, v2.0"
        text description "nullable"
        jsonb rules_json "Detection rules array"
        jsonb weights_json "{\"rule\": 0.4, \"ml\": 0.6}"
        jsonb thresholds_json "{\"challenge\": 0.3, \"block\": 0.7}"
        bool is_active "Only 1 active at a time"
        uuid created_by_user_id FK "→ users(id), nullable"
        timestamptz created_at "default NOW()"
        timestamptz activated_at "nullable"
        timestamptz deactivated_at "nullable"
    }

    login_attempts {
        uuid id PK
        uuid user_id FK "→ users(id), nullable, ON DELETE SET NULL"
        text username_attempted "nullable - for failed logins"
        timestamptz occurred_at "default NOW()"
        text outcome "CHECK: success, failure, mfa_required, mfa_success, mfa_failed, blocked, locked, rate_limited"
        inet source_ip "nullable"
        text user_agent "nullable"
        bool rate_limited "default FALSE"
        uuid policy_version_id FK "→ policy_versions(id), nullable"
        uuid request_id "default gen_random_uuid()"
        jsonb detection_features "nullable"
        uuid primary_alert_id "nullable - FK added after alerts table"
        text risk_level "CHECK: low, medium, high, critical, nullable"
        bool mfa_used "default FALSE"
        text detection_decision "CHECK: allow, challenge, block, nullable"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    risk_assessments {
        uuid id PK
        uuid login_attempt_id FK UK "→ login_attempts(id), ON DELETE CASCADE, UNIQUE"
        uuid policy_version_id FK "→ policy_versions(id), nullable"
        numeric rule_score "nullable, 0.0000-1.0000"
        numeric anomaly_score "nullable"
        numeric ml_score "nullable"
        text ml_status "CHECK: success, unavailable, error, nullable"
        text ml_model_version "nullable"
        jsonb rule_hits "nullable"
        jsonb ml_features_used "nullable"
        numeric combined_score "nullable"
        text risk_level "CHECK: low, medium, high, critical, nullable"
        text decision "CHECK: allow, challenge, block, nullable"
        timestamptz created_at "default NOW()"
    }

    detection_logs {
        uuid id PK
        uuid login_attempt_id FK "→ login_attempts(id), nullable"
        uuid request_id "nullable"
        text stage "CHECK: rule, ml, combined, action"
        text stage_detail "nullable"
        uuid rule_id "nullable"
        text rule_name "nullable"
        numeric score "nullable"
        text decision "CHECK: allow, challenge, block, nullable"
        text reason "nullable"
        jsonb details "nullable"
        timestamptz created_at "default NOW()"
    }

    soc_analysts {
        uuid id PK
        uuid user_id FK UK "→ users(id), ON DELETE CASCADE, UNIQUE"
        text display_name "nullable"
        bool is_active "default TRUE"
        int max_alerts "default 50"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    alerts {
        uuid id PK
        uuid login_attempt_id FK "→ login_attempts(id), ON DELETE CASCADE"
        uuid policy_version_id FK "→ policy_versions(id), nullable"
        uuid request_id "nullable"
        text status "CHECK: open, acknowledged, resolved, false_positive"
        text risk_level "CHECK: low, medium, high, critical, nullable"
        text detection_reason "nullable"
        jsonb detection_scores "nullable"
        uuid assigned_to_id FK "→ soc_analysts(id), nullable"
        uuid resolved_by_id FK "→ soc_analysts(id), nullable"
        timestamptz resolved_at "nullable"
        text notes "nullable"
        timestamptz created_at "default NOW()"
        timestamptz updated_at "default NOW()"
    }

    alert_timeline {
        uuid id PK
        uuid alert_id FK "→ alerts(id), ON DELETE CASCADE"
        text event_type "CHECK: created, assigned, unassigned, acknowledged, escalated, note_added, status_changed, resolved"
        uuid actor_id FK "→ users(id), nullable"
        text actor_type "CHECK: user, system"
        text old_value "nullable"
        text new_value "nullable"
        text comment "nullable"
        inet ip_address "nullable"
        timestamptz created_at "default NOW()"
    }

    audit_logs {
        uuid id PK
        uuid request_id "nullable"
        uuid actor_id FK "→ users(id), nullable"
        text actor_type "CHECK: user, system"
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
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text device_fingerprint "NOT NULL"
        text device_name "nullable"
        inet last_ip "nullable"
        text last_user_agent "nullable"
        timestamptz last_used_at "default NOW()"
        timestamptz expires_at "nullable - NULL = never expires"
        timestamptz created_at "default NOW()"
    }

    system_settings {
        text key PK "mfa.otp_length, session.access_token_ttl, ..."
        text value "NOT NULL"
        text value_type "CHECK: string, integer, boolean, json"
        text description "nullable"
        text category "CHECK: auth, mfa, rate_limit, detection, notification, general"
        uuid updated_by FK "→ users(id), nullable"
        timestamptz updated_at "default NOW()"
    }

    outbox_events {
        uuid id PK
        text aggregate_type "login_attempt, alert, user, session"
        uuid aggregate_id "NOT NULL"
        text event_type "LoginAttemptCreated, AlertCreated, ..."
        int version "default 1"
        jsonb payload "NOT NULL"
        jsonb headers "nullable"
        text status "CHECK: pending, processing, published, failed"
        int retry_count "default 0"
        int max_retries "default 3"
        text last_error "nullable"
        timestamptz created_at "default NOW()"
        timestamptz published_at "nullable"
    }

    user_notifications {
        uuid id PK
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text type "CHECK: mfa_success, mfa_failed, new_login, password_changed, account_locked, account_unlocked, alert_resolved, system"
        text title "NOT NULL"
        text body "NOT NULL"
        text link "nullable"
        text priority "CHECK: low, normal, high, urgent"
        bool read "default FALSE"
        timestamptz read_at "nullable"
        timestamptz expires_at "nullable"
        timestamptz created_at "default NOW()"
    }

    rate_limits {
        inet ip_address PK "INET"
        text action PK "login, api, ..."
        int count "default 1"
        int max_count "default 5"
        timestamptz window_start "default NOW()"
    }

    %% ============================================================================
    %% RELATIONSHIPS
    %% ============================================================================

    %% Users → User Roles (1:N, Mandatory User)
    users ||--o{ user_roles : "has roles"
    roles ||--o{ user_roles : "assigned to"
    user_roles }o..|| users : "assigned by"

    %% Users → Sessions (1:N, Cascade Delete)
    users ||--o{ sessions : "creates"

    %% Sessions → IP Address (N:1, Optional)
    sessions }o--|| ip_addresses : "from IP"

    %% Users → MFA Transactions (1:N, Optional)
    users ||--o{ mfa_transactions : "initiates"

    %% MFA Transactions → MFA Notifications (1:1, Mandatory)
    mfa_transactions ||--|| mfa_notifications : "creates"

    %% Users → Login Attempts (1:N, Optional - failed logins may not have user)
    users ||--o{ login_attempts : "performs"

    %% Login Attempts → Risk Assessments (1:1, ⚠️ SUY ĐOÁN)
    login_attempts ||--|| risk_assessments : "evaluated by"

    %% Login Attempts → Detection Logs (1:N, Optional)
    login_attempts ||--o{ detection_logs : "generates"

    %% Login Attempts → Alerts (1:N, Optional)
    login_attempts ||--o{ alerts : "triggers"

    %% Alerts → SOC Analysts (N:1, Optional)
    alerts }o--|| soc_analysts : "assigned to"
    alerts }o--|| soc_analysts : "resolved by"

    %% Alerts → Alert Timeline (1:N, Optional)
    alerts ||--o{ alert_timeline : "has"

    %% Alert Timeline → Users (N:1, Optional - actor can be system)
    alert_timeline }o--|| users : "performed by"

    %% Login Attempts → Policy (N:1, Optional)
    login_attempts }o--|| policy_versions : "policy applied"

    %% Risk Assessments → Policy (N:1, Optional)
    risk_assessments }o--|| policy_versions : "evaluated with"

    %% Alerts → Policy (N:1, Optional)
    alerts }o--|| policy_versions : "context"

    %% Users → SOC Analysts (1:1, ⚠️ SUY ĐOÁN)
    users ||--|| soc_analysts : "is analyst"

    %% Users → Trusted Devices (1:N, Optional)
    users ||--o{ user_trusted_devices : "registers"

    %% Users → Notifications (1:N, Optional)
    users ||--o{ user_notifications : "receives"

    %% Users → Audit Logs (1:N, Optional)
    users ||--o{ audit_logs : "actions by"
```

---

## Relationship Matrix

| # | From | To | Type | Mandatory | Cardinality | Certainty |
|---|------|----|------|-----------|-------------|-----------|
| 1 | `users` | `user_roles` | Standard | ✅ Yes | 1:N | **Chắc chắn** |
| 2 | `roles` | `user_roles` | Lookup | ✅ Yes | 1:N | **Chắc chắn** |
| 3 | `user_roles` | `users` | Self-ref | ❌ No | N:1 | **Chắc chắn** |
| 4 | `users` | `sessions` | Standard | ✅ Yes | 1:N | **Chắc chắn** |
| 5 | `sessions` | `ip_addresses` | Standard | ❌ No | N:1 | **Chắc chắn** |
| 6 | `users` | `mfa_transactions` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 7 | `mfa_transactions` | `mfa_notifications` | 1:1 | ✅ Yes | 1:1 | **Chắc chắn** |
| 8 | `users` | `login_attempts` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 9 | `login_attempts` | `risk_assessments` | 1:1 | ❌ No | 1:1 | ⚠️ **Suy đoán** |
| 10 | `login_attempts` | `alerts` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 11 | `login_attempts` | `detection_logs` | Standard | ❌ No | 1:N | **Suy đoán** |
| 12 | `login_attempts` | `policy_versions` | Standard | ❌ No | N:1 | **Suy đoán** |
| 13 | `alerts` | `soc_analysts` | Standard | ❌ No | N:1 | **Chắc chắn** |
| 14 | `users` | `soc_analysts` | 1:1 | ❌ No | 1:1 | ⚠️ **Suy đoán** |
| 15 | `alerts` | `alert_timeline` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 16 | `alert_timeline` | `users` | Standard | ❌ No | N:1 | **Chắc chắn** |
| 17 | `users` | `user_trusted_devices` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 18 | `users` | `user_notifications` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 19 | `users` | `audit_logs` | Standard | ❌ No | 1:N | **Chắc chắn** |

---

## Deletion Rules Summary

| Parent | Child | ON DELETE | Lý do |
|--------|-------|----------|-------|
| `users` | `user_roles` | CASCADE | User xóa → roles cũng xóa |
| `users` | `sessions` | CASCADE | Session không có ý nghĩa khi user xóa |
| `users` | `mfa_transactions` | CASCADE | MFA transactions cần xóa |
| `users` | `login_attempts` | SET NULL | Giữ lại audit trail |
| `users` | `soc_analysts` | CASCADE | Analyst profile xóa |
| `users` | `user_trusted_devices` | CASCADE | Devices cần xóa |
| `users` | `user_notifications` | CASCADE | Notifications không cần giữ |
| `users` | `audit_logs` | SET NULL | Giữ audit trail nhưng bỏ actor |
| `mfa_transactions` | `mfa_notifications` | CASCADE | Notification gắn với MFA |
| `login_attempts` | `risk_assessments` | CASCADE | Assessment gắn với login |
| `login_attempts` | `detection_logs` | SET NULL | Giữ logs nhưng bỏ login ref |
| `login_attempts` | `alerts` | CASCADE | Alerts cần xóa khi login xóa |
| `alerts` | `alert_timeline` | CASCADE | Timeline gắn với alert |

---

## Key Assumptions (Có thể thay đổi)

```sql
-- Assumption 1: SOC Analyst là User đặc biệt (1:1)
-- Nếu muốn User có nhiều analyst profiles → đổi thành 1:N

-- Assumption 2: Risk Assessment cho mọi Login (1:1)
-- Nếu chỉ high-risk → đổi thành 1:0..1

-- Assumption 3: Detection Logs cho mọi Stage (1:N)
-- Nếu có thể disable detection → có thể không có logs

-- Assumption 4: Policy áp dụng cho mọi Login (N:1)
-- Nếu có global vs per-user policy → thêm user_id vào login_attempts
```

---

## File Outputs

1. `infra/postgres/schema-v3.2.sql` - SQL schema hoàn chỉnh
2. `infra/postgres/migrations/005_to_v3.2.sql` - Migration từ v3.1
3. `docs/diagrams/ERD_v3.2.md` - ERD này
