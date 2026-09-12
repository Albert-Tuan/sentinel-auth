# Database Schema v4 - 3NF Analysis

## Phân tích: Tại sao số bảng tăng?

### Sự thật

| Schema | Tables | Lý do |
|--------|--------|-------|
| v3.1 | 19 | Chỉ có core tables, dùng TEXT enums |
| v4 | 17 core | Giữ nguyên 17 core tables |
| v4 | 18 ref | **Đây là lý do tăng: tách enums ra reference tables** |

**Thực tế:** Chỉ thêm **18 reference tables** cho lookup data, không phải thêm business logic.

---

## Reference Tables là gì?

### Trước (v3.1) - Dùng CHECK constraints
```sql
CREATE TABLE alerts (
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'resolved', 'false_positive')),
    risk_level TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical'))
);
```

### Sau (v4) - Reference tables
```sql
CREATE TABLE ref_alert_status (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_vi TEXT NOT NULL,
    is_open BOOLEAN NOT NULL,
    is_resolved BOOLEAN NOT NULL
);

CREATE TABLE alerts (
    status_id TEXT NOT NULL REFERENCES ref_alert_status(id)
);
```

### Tại sao tách ra?
| Lý do | Giải thích |
|-------|-------------|
| **Data Integrity** | FK constraint ngăn insert giá trị không hợp lệ |
| **Maintainability** | Thêm/trigger value mới không cần ALTER TABLE |
| **i18n** | Lưu cả name_vi (Vietnamese) |
| **Metadata** | Thêm is_open, is_resolved, color_hex... |
| **3NF Compliance** | Loại bỏ transitive dependency |

---

## Quan hệ thực tế vs Suy đoán

### Quan hệ CHẮC CHẮN (có trong requirements)

| From | To | Type | Cardinality | Mandatory | Ghi chú |
|------|----|------|-------------|-----------|---------|
| `users` | `user_roles` | 1:N | 1 user → N roles | Mandatory | Rõ ràng |
| `user_roles` | `ref_roles` | N:1 | N assignments → 1 role | Mandatory | FK constraint |
| `users` | `sessions` | 1:N | 1 user → N sessions | Mandatory | ON DELETE CASCADE |
| `users` | `mfa_transactions` | 1:N | 1 user → N MFA attempts | Optional | User có thể chưa MFA |
| `mfa_transactions` | `mfa_notifications` | 1:1 | 1 MFA → 1 notification | Mandatory | Mỗi MFA có notification |
| `users` | `login_attempts` | 1:N | 1 user → N login attempts | Optional | Failed login không có user_id |
| `login_attempts` | `risk_assessments` | 1:1 | 1 login → 1 assessment | **Suy đoán** | Có thể không có nếu login thất bại sớm |
| `login_attempts` | `alerts` | 1:N | 1 login → N alerts | Optional | Chỉ tạo khi risk cao |
| `alerts` | `alert_timeline` | 1:N | 1 alert → N timeline events | Optional | Có thể chưa có action |

### Quan hệ SUY ĐOÁN (cần xác nhận)

| From | To | Type | Cardinality | Lý do suy đoán |
|------|----|------|-------------|----------------|
| `login_attempts` | `risk_assessments` | 1:1 | 1:1 | Giả định mỗi login đều có assessment, nhưng có thể bypass detection |
| `policy_versions` | `login_attempts` | 1:N | 1 policy → N logins | Giả định policy được áp dụng cho mọi login |
| `policy_versions` | `risk_assessments` | 1:N | 1 policy → N assessments | Phụ thuộc vào login_attempts |
| `login_attempts` | `detection_logs` | 1:N | 1 login → N logs | Có thể không log nếu detection bị disable |

### Quan hệ KHÔNG CÓ TRONG REQUIREMENTS

| From | To | Type | Ghi chú |
|------|----|------|---------|
| `users` | `soc_analysts` | 1:1 | ⚠️ **Suy đoán:** SOC analyst là user đặc biệt |
| `sessions` | `ip_addresses` | N:1 | ⚠️ **Suy đoán:** Mỗi session có 1 IP |

---

## ERD v4 - Chi tiết với Cardinalities

```mermaid
erDiagram
    %% ============================================================================
    %% REFERENCE TABLES (Lookup - Seed Data)
    %% ============================================================================
    ref_roles {
        text id PK "USER, SECURITY_ADMIN, SOC_ANALYST, SECURITY_MANAGER"
        text name "English name"
        text name_vi "Vietnamese name"
        text description "Mô tả"
        int sort_order "Thứ tự hiển thị"
        bool is_system "Role hệ thống"
        timestamptz created_at
    }

    ref_alert_status {
        text id PK "open, acknowledged, resolved, false_positive"
        text name "English"
        text name_vi "Vietnamese"
        bool is_open "Còn mở"
        bool is_resolved "Đã đóng"
        int sort_order
        timestamptz created_at
    }

    ref_risk_level {
        text id PK "low, medium, high, critical"
        text name "English"
        text name_vi "Vietnamese"
        numeric score_min "0.00"
        numeric score_max "1.00"
        text color_hex "#RRGGBB"
        int sort_order
        timestamptz created_at
    }

    ref_detection_decision {
        text id PK "allow, challenge, block"
        text name "English"
        text name_vi "Vietnamese"
        text description "Mô tả"
        int sort_order
        timestamptz created_at
    }

    ref_mfa_type {
        text id PK "one_time, persistent"
        text name "English"
        text description "Mô tả"
        timestamptz created_at
    }

    ref_mfa_transaction_status {
        text id PK "pending, completed, expired, failed"
        text name "English"
        text description "Mô tả"
        int sort_order
        timestamptz created_at
    }

    ref_login_outcome {
        text id PK "success, failure, mfa_required, mfa_success, mfa_failed, blocked, locked, rate_limited"
        text name "English"
        text name_vi "Vietnamese"
        bool is_success "Là login thành công"
        bool is_mfa_related "Liên quan MFA"
        int sort_order
        timestamptz created_at
    }

    ref_notification_type {
        text id PK "mfa_success, new_login, account_locked, ..."
        text name "English"
        text name_vi "Vietnamese"
        text description "Mô tả"
        text default_priority "normal, high, urgent"
        timestamptz created_at
    }

    %% ============================================================================
    %% CORE TABLES
    %% ============================================================================

    users {
        uuid id PK "gen_random_uuid()"
        text username UK "3-50 chars"
        text password_hash "Argon2id"
        text email UK "nullable"
        text full_name "nullable"
        text status_id FK "→ ref_user_status(id)"
        bool admin_mfa_required "Yêu cầu MFA admin"
        bool detection_mfa_once "MFA 1 lần sau detection"
        timestamptz last_login_at "nullable"
        int failed_login_count "default 0"
        timestamptz locked_at "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    user_roles {
        uuid id PK "Primary Key"
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text role_id FK "→ ref_roles(id)"
        timestamptz assigned_at
        uuid assigned_by FK "→ users(id), nullable"
    }

    sessions {
        uuid id PK
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text access_token_hash
        text refresh_token_hash "nullable"
        uuid refresh_token_family "nullable"
        text token_jti UK "nullable"
        timestamptz expires_at
        timestamptz last_activity_at "nullable"
        timestamptz revoked_at "nullable"
        uuid ip_address_id FK "→ ip_addresses(id), nullable"
        text user_agent "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    ip_addresses {
        uuid id PK
        inet ip_address UK "IP duy nhất"
        text country_code "nullable"
        text country_name "nullable"
        text city "nullable"
        text isp "nullable"
        text asn "nullable"
        bool is_proxy "default FALSE"
        bool is_vpn "default FALSE"
        bool is_tor "default FALSE"
        timestamptz first_seen_at
        timestamptz last_seen_at
    }

    mfa_transactions {
        uuid id PK
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text mfa_type_id FK "→ ref_mfa_type(id)"
        text status_id FK "→ ref_mfa_transaction_status(id)"
        uuid bound_ip_id FK "→ ip_addresses(id), nullable"
        uuid notification_id "nullable - FK sau khi tạo mfa_notifications"
        int fail_count "default 0"
        timestamptz expires_at
        timestamptz created_at
        timestamptz updated_at
    }

    mfa_notifications {
        uuid id PK
        uuid mfa_transaction_id FK "→ mfa_transactions(id), ON DELETE CASCADE"
        text channel_id FK "→ ref_mfa_channel(id)"
        text recipient "Email hoặc SĐT"
        text mfa_code_hash
        timestamptz sent_at
        timestamptz delivered_at "nullable"
        timestamptz failed_at "nullable"
        text failure_reason "nullable"
        timestamptz expires_at
        timestamptz verified_at "nullable"
        timestamptz created_at
    }

    policy_versions {
        uuid id PK
        text version UK "v1.0, v2.1"
        text description "nullable"
        jsonb rules_json "Rules array"
        jsonb weights_json "{\"rule\": 0.4, \"ml\": 0.6}"
        jsonb thresholds_json "{\"challenge\": 0.3, \"block\": 0.7}"
        bool is_active "Chỉ 1 active"
        uuid created_by_user_id FK "→ users(id), nullable"
        timestamptz created_at
        timestamptz activated_at "nullable"
        timestamptz deactivated_at "nullable"
    }

    login_attempts {
        uuid id PK
        uuid user_id FK "→ users(id), nullable, ON DELETE SET NULL"
        text username_attempted "nullable - cho failed login"
        timestamptz occurred_at
        text outcome_id FK "→ ref_login_outcome(id)"
        uuid source_ip_id FK "→ ip_addresses(id), nullable"
        text user_agent "nullable"
        bool rate_limited "default FALSE"
        uuid policy_version_id FK "→ policy_versions(id), nullable"
        uuid request_id "UUID cho tracing"
        jsonb detection_features "nullable"
        uuid primary_alert_id "nullable - FK sau khi tạo alerts"
        text risk_level_id FK "→ ref_risk_level(id), nullable"
        bool mfa_used "default FALSE"
        text detection_decision_id FK "→ ref_detection_decision(id), nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    risk_assessments {
        uuid id PK
        uuid login_attempt_id FK UK "→ login_attempts(id), UNIQUE"
        uuid policy_version_id FK "→ policy_versions(id), nullable"
        numeric rule_score "nullable"
        numeric anomaly_score "nullable"
        numeric ml_score "nullable"
        text ml_status_id FK "→ ref_ml_status(id), nullable"
        text ml_model_version "nullable"
        jsonb rule_hits "nullable"
        jsonb ml_features_used "nullable"
        numeric combined_score "nullable"
        text risk_level_id FK "→ ref_risk_level(id), nullable"
        text detection_decision_id FK "→ ref_detection_decision(id), nullable"
        timestamptz created_at
    }

    detection_logs {
        uuid id PK
        uuid login_attempt_id FK "→ login_attempts(id), nullable"
        uuid request_id "nullable"
        text stage_id FK "→ ref_detection_stage(id)"
        text stage_detail "nullable"
        uuid rule_id "nullable"
        text rule_name "nullable"
        numeric score "nullable"
        text decision_id FK "→ ref_detection_decision(id), nullable"
        text reason "nullable"
        jsonb details "nullable"
        timestamptz created_at
    }

    soc_analysts {
        uuid id PK
        uuid user_id FK UK "→ users(id), ON DELETE CASCADE, UNIQUE"
        text display_name "nullable"
        bool is_active "default TRUE"
        int max_alerts "default 50"
        timestamptz created_at
        timestamptz updated_at
    }

    alerts {
        uuid id PK
        uuid login_attempt_id FK "→ login_attempts(id), ON DELETE CASCADE"
        uuid policy_version_id FK "→ policy_versions(id), nullable"
        uuid request_id "nullable"
        text status_id FK "→ ref_alert_status(id)"
        text risk_level_id FK "→ ref_risk_level(id), nullable"
        text detection_reason "nullable"
        jsonb detection_scores "nullable"
        uuid assigned_to_id FK "→ soc_analysts(id), nullable"
        uuid resolved_by_id FK "→ soc_analysts(id), nullable"
        timestamptz resolved_at "nullable"
        text notes "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    alert_timeline {
        uuid id PK
        uuid alert_id FK "→ alerts(id), ON DELETE CASCADE"
        text event_type_id FK "→ ref_alert_event_type(id)"
        uuid actor_id FK "→ users(id), nullable"
        text actor_type "user | system"
        text old_value "nullable"
        text new_value "nullable"
        text comment "nullable"
        uuid ip_address_id FK "→ ip_addresses(id), nullable"
        timestamptz created_at
    }

    user_trusted_devices {
        uuid id PK
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text device_fingerprint
        text device_name "nullable"
        uuid last_ip_id FK "→ ip_addresses(id), nullable"
        text last_user_agent "nullable"
        timestamptz last_used_at
        timestamptz expires_at "nullable - NULL = vĩnh viễn"
        timestamptz created_at
    }

    system_settings {
        uuid id PK
        text key UK "mfa.otp_length, ..."
        text value
        text value_type_id FK "→ ref_settings_value_type(id)"
        text description "nullable"
        text category_id FK "→ ref_settings_category(id)"
        uuid updated_by FK "→ users(id), nullable"
        timestamptz updated_at
    }

    outbox_events {
        uuid id PK
        text aggregate_type "login_attempt, alert, user, session"
        uuid aggregate_id "ID của aggregate"
        text event_type "LoginAttemptCreated, ..."
        int version "default 1"
        jsonb payload "Event data"
        jsonb headers "nullable"
        text status_id FK "→ ref_outbox_status(id)"
        int retry_count "default 0"
        int max_retries "default 3"
        text last_error "nullable"
        timestamptz created_at
        timestamptz published_at "nullable"
    }

    user_notifications {
        uuid id PK
        uuid user_id FK "→ users(id), ON DELETE CASCADE"
        text type_id FK "→ ref_notification_type(id)"
        text title
        text body
        text link "nullable"
        text priority_id FK "→ ref_notification_priority(id)"
        bool read "default FALSE"
        timestamptz read_at "nullable"
        timestamptz expires_at "nullable"
        timestamptz created_at
    }

    %% ============================================================================
    %% RELATIONSHIPS - Chi tiết
    %% ============================================================================

    %% Users → User Roles (1:N, Mandatory)
    users ||--o{ user_roles : "assigns"
    ref_roles ||--o{ user_roles : "defines"

    %% User Roles → Assigned By (self-ref, Optional)
    user_roles }o..|| users : "assigned by"

    %% Users → Sessions (1:N, Mandatory)
    users ||--o{ sessions : "creates"

    %% Sessions → IP (N:1, Optional)
    sessions }o--|| ip_addresses : "from IP"

    %% Users → MFA Transactions (1:N, Optional)
    users ||--o{ mfa_transactions : "initiates"

    %% MFA Transactions → Status (N:1, Mandatory)
    mfa_transactions }o--|| ref_mfa_transaction_status : "has status"

    %% MFA Transactions → MFA Notifications (1:1, Mandatory)
    mfa_transactions ||--|| mfa_notifications : "creates"

    %% MFA Transactions → IP (N:1, Optional)
    mfa_transactions }o--|| ip_addresses : "bound to"

    %% Login Attempts → Users (N:1, Optional)
    login_attempts }o--|| users : "performed by"

    %% Login Attempts → Outcome (N:1, Mandatory)
    login_attempts }o--|| ref_login_outcome : "has outcome"

    %% Login Attempts → IP (N:1, Optional)
    login_attempts }o--|| ip_addresses : "from IP"

    %% Login Attempts → Risk Assessment (1:1, ⚠️ SUY ĐOÁN)
    login_attempts ||--|| risk_assessments : "evaluated by"

    %% Login Attempts → Alerts (1:N, Optional)
    login_attempts ||--o{ alerts : "triggers"

    %% Login Attempts → Detection Logs (1:N, Optional)
    login_attempts ||--o{ detection_logs : "generates"

    %% Alerts → Login Attempt (N:1, Mandatory)
    alerts }o--|| login_attempts : "for login"

    %% Alerts → SOC Analysts (N:1, Optional)
    alerts }o--|| soc_analysts : "assigned to"

    %% SOC Analysts → Users (1:1, ⚠️ SUY ĐOÁN)
    soc_analysts ||--|| users : "is a"

    %% Alerts → Alert Timeline (1:N, Optional)
    alerts ||--o{ alert_timeline : "has"

    %% Alert Timeline → Event Type (N:1, Mandatory)
    alert_timeline }o--|| ref_alert_event_type : "of type"

    %% Alert Timeline → Users (N:1, Optional)
    alert_timeline }o--|| users : "by actor"

    %% Login Attempts → Policy (N:1, Optional)
    login_attempts }o--|| policy_versions : "policy applied"

    %% Risk Assessment → Policy (N:1, Optional)
    risk_assessments }o--|| policy_versions : "evaluated with"

    %% Alerts → Policy (N:1, Optional)
    alerts }o--|| policy_versions : "context"

    %% Users → Trusted Devices (1:N, Optional)
    users ||--o{ user_trusted_devices : "registers"

    %% Trusted Devices → IP (N:1, Optional)
    user_trusted_devices }o--|| ip_addresses : "last seen from"

    %% Users → Notifications (1:N, Optional)
    users ||--o{ user_notifications : "receives"

    %% Notifications → Type (N:1, Mandatory)
    user_notifications }o--|| ref_notification_type : "of type"

    %% Notifications → Priority (N:1, Mandatory)
    user_notifications }o--|| ref_notification_priority : "has priority"
```

---

## Relationship Summary Table

| # | From | To | Type | Mandatory | Cardinality | Certainty |
|---|------|----|------|-----------|-------------|-----------|
| 1 | `users` | `user_roles` | Standard | ✅ Yes | 1:N | **Chắc chắn** |
| 2 | `ref_roles` | `user_roles` | Standard | ✅ Yes | 1:N | **Chắc chắn** |
| 3 | `user_roles` | `users` | Self-ref | ❌ No | N:1 | **Chắc chắn** |
| 4 | `users` | `sessions` | Standard | ✅ Yes | 1:N | **Chắc chắn** |
| 5 | `sessions` | `ip_addresses` | Standard | ❌ No | N:1 | **Suy đoán** |
| 6 | `users` | `mfa_transactions` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 7 | `mfa_transactions` | `ref_mfa_transaction_status` | Lookup | ✅ Yes | N:1 | **Chắc chắn** |
| 8 | `mfa_transactions` | `mfa_notifications` | 1:1 | ✅ Yes | 1:1 | **Chắc chắn** |
| 9 | `mfa_transactions` | `ip_addresses` | Standard | ❌ No | N:1 | **Suy đoán** |
| 10 | `users` | `login_attempts` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 11 | `login_attempts` | `ref_login_outcome` | Lookup | ✅ Yes | N:1 | **Chắc chắn** |
| 12 | `login_attempts` | `ip_addresses` | Standard | ❌ No | N:1 | **Chắc chắn** |
| 13 | `login_attempts` | `risk_assessments` | 1:1 | ❌ No | 1:1 | ⚠️ **Suy đoán** |
| 14 | `login_attempts` | `alerts` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 15 | `login_attempts` | `detection_logs` | Standard | ❌ No | 1:N | ⚠️ **Suy đoán** |
| 16 | `login_attempts` | `policy_versions` | Standard | ❌ No | N:1 | ⚠️ **Suy đoán** |
| 17 | `risk_assessments` | `policy_versions` | Standard | ❌ No | N:1 | ⚠️ **Suy đoán** |
| 18 | `alerts` | `login_attempts` | Standard | ✅ Yes | N:1 | **Chắc chắn** |
| 19 | `alerts` | `soc_analysts` (assigned) | Standard | ❌ No | N:1 | **Suy đoán** |
| 20 | `alerts` | `soc_analysts` (resolved) | Standard | ❌ No | N:1 | **Suy đoán** |
| 21 | `soc_analysts` | `users` | 1:1 | ✅ Yes | 1:1 | ⚠️ **Suy đoán** |
| 22 | `alerts` | `alert_timeline` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 23 | `alert_timeline` | `ref_alert_event_type` | Lookup | ✅ Yes | N:1 | **Chắc chắn** |
| 24 | `alert_timeline` | `users` | Standard | ❌ No | N:1 | **Chắc chắn** |
| 25 | `alerts` | `policy_versions` | Standard | ❌ No | N:1 | **Suy đoán** |
| 26 | `users` | `user_trusted_devices` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 27 | `user_trusted_devices` | `ip_addresses` | Standard | ❌ No | N:1 | **Suy đoán** |
| 28 | `users` | `user_notifications` | Standard | ❌ No | 1:N | **Chắc chắn** |
| 29 | `user_notifications` | `ref_notification_type` | Lookup | ✅ Yes | N:1 | **Chắc chắn** |
| 30 | `user_notifications` | `ref_notification_priority` | Lookup | ✅ Yes | N:1 | **Chắc chắn** |

---

## Legend

| Symbol | Meaning |
|--------|---------|
| `||` | Exactly one (Mandatory) |
| `}o` | Zero or more (Optional) |
| `o|` | Zero or one (Optional) |
| `}o||` | N:1 relationship |
| `||--||` | 1:1 relationship |
| `||--o{` | 1:N relationship |
| ⚠️ **Suy đoán** | Cần xác nhận với stakeholder |

---

## Checklist cho Stakeholder xác nhận

- [ ] **risk_assessments**: Mỗi login_attempt đều có 1 risk_assessment?
- [ ] **policy_versions**: Có áp dụng cho mọi login_attempt?
- [ ] **detection_logs**: Có log cho mọi detection stage?
- [ ] **soc_analysts**: Là user đặc biệt hay entity riêng?
- [ ] **IP binding**: Session/MFA có bind với IP không?
