# Sentinel Auth — Full Entity Relationship Diagram (Schema v3)

> Generated from: `infra/postgres/schema-v3.sql`
> Total: **17 tables** | **15 foreign keys** | **17 relationships**

---

## Mermaid ERD

```mermaid
erDiagram
    %% ============================================================================
    %% ROLES - Reference Table (Reference Data)
    %% ============================================================================
    roles {
        text id PK "Primary Key"
        text name "Display name"
        text description "Mô tả vai trò"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% USERS - Core Entity
    %% ============================================================================
    users {
        uuid id PK "Primary Key"
        text username UK "Username (unique, 3-50 chars)"
        text password_hash "Argon2id hash"
        text email "Email (nullable)"
        text full_name "Tên đầy đủ"
        text status "active | suspended | locked"
        boolean admin_mfa_required "Yêu cầu MFA admin"
        boolean detection_mfa_once "MFA 1 lần sau detection"
        timestamptz last_login_at "Login cuối"
        int failed_login_count "Số lần login thất bại"
        timestamptz locked_at "Thời gian bị khóa"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Auto-update"
    }

    %% ============================================================================
    %% USER_ROLES - Junction Table (Many-to-Many)
    %% ============================================================================
    user_roles {
        uuid user_id PK, FK "FK → users.id"
        text role_id PK, FK "FK → roles.id"
        timestamptz assigned_at "Thời gian gán"
        uuid assigned_by FK "FK → users.id (nullable)"
    }

    %% ============================================================================
    %% SESSIONS - User Sessions with JWT
    %% ============================================================================
    sessions {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id"
        text access_token_hash "SHA256 hash"
        text refresh_token_hash "Refresh token hash"
        uuid refresh_token_family "Token rotation family"
        text token_jti UK "JWT ID (unique)"
        timestamptz expires_at "Hết hạn"
        timestamptz last_activity_at "Hoạt động cuối"
        timestamptz revoked_at "Thu hồi (nullable)"
        inet ip_address "IP address"
        text user_agent "User Agent"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Auto-update"
    }

    %% ============================================================================
    %% PRE_AUTH_TRANSACTIONS - MFA Challenge
    %% ============================================================================
    pre_auth_transactions {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id"
        text mfa_type "persistent | one_time"
        timestamptz expires_at "Hết hạn OTP"
        text status "pending | completed | expired | failed"
        text bound_ip "Hashed IP"
        uuid notification_id FK "FK → mfa_notifications.id"
        int fail_count "Số lần sai OTP"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Auto-update"
    }

    %% ============================================================================
    %% MFA_NOTIFICATIONS - Email/SMS OTP Lifecycle
    %% ============================================================================
    mfa_notifications {
        uuid id PK "Primary Key"
        uuid pre_auth_transaction_id FK "FK → pre_auth_transactions.id"
        text channel "email | sms (future)"
        text recipient "Email/SĐT"
        text mfa_code_hash "Argon2id hash OTP"
        timestamptz sent_at "Thời gian gửi"
        timestamptz delivered_at "Delivered (nullable)"
        timestamptz failed_at "Thất bại (nullable)"
        text failure_reason "Lý do thất bại"
        timestamptz expires_at "Hết hạn"
        timestamptz verified_at "Verify thành công"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% RATE_LIMITS - Rate Limiting (Composite PK)
    %% ============================================================================
    rate_limits {
        inet ip_address PK "Primary Key (part 1)"
        text action PK "Primary Key (part 2)"
        int count "Số request"
        int max_count "Giới hạn"
        timestamptz window_start "Bắt đầu window"
    }

    %% ============================================================================
    %% POLICY_VERSIONS - Detection Rules Versioning
    %% ============================================================================
    policy_versions {
        uuid id PK "Primary Key"
        text version UK "v1.0, v2.1 (unique)"
        text description "Mô tả"
        jsonb rules_json "Rules: geo_block, new_country..."
        jsonb weights "{\"rule\": 0.4, \"ml\": 0.6}"
        jsonb thresholds "{\"challenge\": 0.3, \"block\": 0.7}"
        boolean is_active "Chỉ 1 active"
        uuid created_by_user_id FK "FK → users.id"
        timestamptz created_at "Thời gian tạo"
        timestamptz activated_at "Kích hoạt"
        timestamptz deactivated_at "Hủy kích hoạt"
    }

    %% ============================================================================
    %% LOGIN_ATTEMPTS - Audit Trail
    %% ============================================================================
    login_attempts {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id (nullable)"
        text username_attempted "Username đã thử"
        timestamptz occurred_at "Thời gian xảy ra"
        text outcome "success | failure | mfa_required..."
        inet source_ip "IP nguồn"
        text user_agent "User Agent"
        boolean rate_limited "Rate limited?"
        uuid policy_version_id FK "FK → policy_versions.id"
        uuid request_id "Distributed tracing"
        jsonb detection_features "Features vector"
        uuid primary_alert_id FK "FK → alerts.id"
        text risk_level "low | medium | high | critical"
        boolean mfa_used "Có dùng MFA?"
        text detection_decision "allow | challenge | block"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Auto-update"
    }

    %% ============================================================================
    %% RISK_ASSESSMENTS - 1:1 with LoginAttempt
    %% ============================================================================
    risk_assessments {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK, UK "FK → login_attempts.id (UNIQUE)"
        uuid policy_version_id FK "FK → policy_versions.id"
        numeric rule_score "Rule engine score"
        numeric anomaly_score "Anomaly score"
        numeric ml_score "ML model score"
        text ml_status "success | unavailable | error"
        text ml_model_version "ML model version"
        jsonb rule_hits "Array rule names triggered"
        jsonb ml_features_used "Features used for ML"
        numeric combined_score "Weighted: w1*rule + w2*ml"
        text risk_level "low | medium | high | critical"
        text decision "allow | challenge | block"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% DETECTION_LOGS - Detection Audit Trail
    %% ============================================================================
    detection_logs {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK "FK → login_attempts.id"
        uuid request_id "Distributed tracing"
        text stage "rule | ml | combined | action"
        text stage_detail "geo_block, asn_reputation..."
        uuid rule_id "Rule reference"
        text rule_name "Rule name"
        numeric score "Score"
        text decision "allow | challenge | block"
        text reason "Lý do"
        jsonb details "Chi tiết"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% ALERTS - SOC Workflow
    %% ============================================================================
    alerts {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK "FK → login_attempts.id"
        uuid policy_version_id FK "FK → policy_versions.id"
        uuid request_id "Distributed tracing"
        text status "open | acknowledged | resolved | false_positive"
        text risk_level "low | medium | high | critical"
        text detection_reason "Lý do ngắn"
        jsonb detection_scores "Scores snapshot"
        text assigned_to "SOC analyst gán"
        text resolved_by "Người resolve"
        timestamptz resolved_at "Thời gian resolve"
        text notes "Ghi chú"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Auto-update"
    }

    %% ============================================================================
    %% AUDIT_LOGS - Immutable Audit Trail
    %% ============================================================================
    audit_logs {
        uuid id PK "Primary Key"
        uuid request_id "Distributed tracing"
        text actor "user_id | system:detection-engine"
        text action "role_assigned | user_locked..."
        text resource "user | session | role | alert..."
        uuid resource_id "Resource ID"
        jsonb before_state "State trước"
        jsonb after_state "State sau"
        text change_reason "Lý do thay đổi"
        inet ip_address "IP actor"
        text user_agent "User Agent"
        timestamptz created_at "Thời gian tạo (immutable)"
    }

    %% ============================================================================
    %% USER_TRUSTED_DEVICES - Remember This Device
    %% ============================================================================
    user_trusted_devices {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id"
        text device_fingerprint "Hash device characteristics"
        text device_name "Tên thiết bị"
        inet last_ip "IP cuối"
        text last_user_agent "User-Agent cuối"
        timestamptz last_used_at "Lần cuối dùng"
        timestamptz expires_at "Hết hạn (NULL=vĩnh viễn)"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% ALERT_TIMELINE - SOC Collaboration Audit Trail
    %% ============================================================================
    alert_timeline {
        uuid id PK "Primary Key"
        uuid alert_id FK "FK → alerts.id"
        text event_type "created | assigned | acknowledged..."
        text actor "user_id | system"
        text old_value "Giá trị cũ"
        text new_value "Giá trị mới"
        text comment "Bình luận SOC"
        inet ip_address "IP actor"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% SYSTEM_SETTINGS - Dynamic Configuration
    %% ============================================================================
    system_settings {
        text key PK "Primary Key (e.g., mfa.otp_length)"
        text value "Giá trị cấu hình"
        text value_type "string | integer | boolean | json"
        text description "Mô tả"
        text category "mfa | rate_limit | detection | auth..."
        uuid updated_by FK "FK → users.id"
        timestamptz updated_at "Auto-update"
    }

    %% ============================================================================
    %% OUTBOX_EVENTS - Transactional Outbox (ADR-002)
    %% ============================================================================
    outbox_events {
        uuid id PK "Primary Key"
        text aggregate_type "login_attempt | alert | user | session"
        uuid aggregate_id "Aggregate root ID"
        text event_type "LoginAttemptCreated | AlertCreated..."
        int version "Event version"
        jsonb payload "Event data"
        jsonb headers "correlation_id, causation_id"
        text status "pending | processing | published | failed"
        int retry_count "Số retry"
        int max_retries "Retry tối đa"
        text last_error "Lỗi cuối"
        timestamptz created_at "Thời gian tạo"
        timestamptz published_at "Publish thành công"
    }

    %% ============================================================================
    %% USER_NOTIFICATIONS - In-App Notifications
    %% ============================================================================
    user_notifications {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id"
        text type "mfa_success | new_login | account_locked..."
        text title "Tiêu đề"
        text body "Nội dung"
        text link "URL navigate"
        text priority "low | normal | high | urgent"
        boolean read "Đã đọc?"
        timestamptz read_at "Thời gian đọc"
        timestamptz expires_at "Hết hạn (nullable)"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% RELATIONSHIPS
    %% ============================================================================

    %% --- Core Relationships ---
    users ||--o{ user_roles : "has roles"
    roles ||--o{ user_roles : "assigned to"

    %% --- Session Management ---
    users ||--o{ sessions : "owns sessions"
    sessions }o--|| users : "session belongs to user"

    %% --- MFA Flow ---
    users ||--o{ pre_auth_transactions : "initiates MFA"
    pre_auth_transactions ||--|| mfa_notifications : "creates notification"

    %% --- Policy Management ---
    users ||--o{ policy_versions : "creates policy"

    %% --- Login Flow ---
    users ||--o{ login_attempts : "performs login"
    login_attempts ||--o{ alerts : "triggers alerts"

    %% --- Detection ---
    login_attempts ||--|| risk_assessments : "1:1 evaluated"
    login_attempts ||--o{ detection_logs : "generates logs"
    policy_versions ||--o{ login_attempts : "applied to"
    policy_versions ||--o{ risk_assessments : "used in"
    policy_versions ||--o{ alerts : "context for"

    %% --- Self-referential FK ---
    login_attempts ||--o| alerts : "primary alert"

    %% --- v3: Trusted Devices ---
    users ||--o{ user_trusted_devices : "registers devices"

    %% --- v3: SOC Timeline ---
    alerts ||--o{ alert_timeline : "has timeline"

    %% --- v3: System Settings ---
    users ||--o{ system_settings : "updates settings"

    %% --- v3: Notifications ---
    users ||--o{ user_notifications : "receives notifications"

    %% --- v3: Outbox (no FK to external tables) ---
    %% outbox_events stands alone - aggregates from multiple tables
```

---

## Relationship Summary Table

| From Entity | To Entity | Relationship | Type | Description |
|-------------|-----------|--------------|------|-------------|
| `users` | `user_roles` | 1:N | Has | User có nhiều roles |
| `roles` | `user_roles` | 1:N | Assigned | Role được gán cho nhiều users |
| `users` | `sessions` | 1:N | Owns | User sở hữu nhiều sessions |
| `users` | `pre_auth_transactions` | 1:N | Initiates | User khởi tạo MFA |
| `pre_auth_transactions` | `mfa_notifications` | 1:1 | Creates | MFA tạo notification |
| `users` | `policy_versions` | 1:N | Creates | User tạo policy |
| `users` | `login_attempts` | 1:N | Performs | User thực hiện login |
| `login_attempts` | `risk_assessments` | 1:1 | Evaluated | Mỗi login có 1 assessment |
| `login_attempts` | `detection_logs` | 1:N | Generates | Login tạo nhiều logs |
| `login_attempts` | `alerts` | 1:N | Triggers | Login trigger alerts |
| `login_attempts` | `alerts` | 1:0..1 | Primary | Login có alert chính |
| `policy_versions` | `login_attempts` | 1:N | Applied | Policy áp dụng cho login |
| `policy_versions` | `risk_assessments` | 1:N | Used | Policy dùng trong assessment |
| `policy_versions` | `alerts` | 1:N | Context | Policy context cho alert |
| `users` | `user_trusted_devices` | 1:N | Registers | User đăng ký thiết bị tin cậy |
| `alerts` | `alert_timeline` | 1:N | Has | Alert có timeline |
| `users` | `system_settings` | 1:N | Updates | Admin cập nhật settings |
| `users` | `user_notifications` | 1:N | Receives | User nhận notifications |

---

## Foreign Key Index

| Table | Foreign Keys | References |
|-------|-------------|------------|
| `user_roles` | `user_id`, `role_id`, `assigned_by` | `users.id`, `roles.id`, `users.id` |
| `sessions` | `user_id` | `users.id` |
| `pre_auth_transactions` | `user_id`, `notification_id` | `users.id`, `mfa_notifications.id` |
| `mfa_notifications` | `pre_auth_transaction_id` | `pre_auth_transactions.id` |
| `policy_versions` | `created_by_user_id` | `users.id` |
| `login_attempts` | `user_id`, `policy_version_id`, `primary_alert_id` | `users.id`, `policy_versions.id`, `alerts.id` |
| `risk_assessments` | `login_attempt_id`, `policy_version_id` | `login_attempts.id`, `policy_versions.id` |
| `detection_logs` | `login_attempt_id` | `login_attempts.id` |
| `alerts` | `login_attempt_id`, `policy_version_id` | `login_attempts.id`, `policy_versions.id` |
| `user_trusted_devices` | `user_id` | `users.id` |
| `alert_timeline` | `alert_id` | `alerts.id` |
| `system_settings` | `updated_by` | `users.id` |
| `user_notifications` | `user_id` | `users.id` |

---

## Table Statistics

| # | Table | Columns | PK Type | FK Count | Indexes |
|---|-------|---------|---------|----------|---------|
| 1 | `roles` | 4 | TEXT | 0 | 0 |
| 2 | `users` | 13 | UUID | 0 | 4 |
| 3 | `user_roles` | 4 | Composite (2) | 3 | 2 |
| 4 | `sessions` | 13 | UUID | 1 | 5 |
| 5 | `pre_auth_transactions` | 10 | UUID | 2 | 4 |
| 6 | `mfa_notifications` | 12 | UUID | 1 | 3 |
| 7 | `rate_limits` | 5 | Composite (2) | 0 | 1 |
| 8 | `policy_versions` | 12 | UUID | 1 | 3 |
| 9 | `login_attempts` | 17 | UUID | 3 | 6 |
| 10 | `risk_assessments` | 15 | UUID | 2 | 2 |
| 11 | `detection_logs` | 12 | UUID | 1 | 3 |
| 12 | `alerts` | 14 | UUID | 2 | 5 |
| 13 | `audit_logs` | 12 | UUID | 0 | 5 |
| 14 | `user_trusted_devices` | 9 | UUID | 1 | 3 |
| 15 | `alert_timeline` | 8 | UUID | 1 | 3 |
| 16 | `system_settings` | 7 | TEXT | 1 | 1 |
| 17 | `outbox_events` | 13 | UUID | 0 | 3 |
| 18 | `user_notifications` | 11 | UUID | 1 | 4 |

**Total: 17 tables | 15 unique foreign keys | 50+ indexes**
