# Sentinel Auth - Complete Database ERD

> Entity Relationship Diagram hoàn chỉnh cho Sentinel Auth v3
>
> **19 tables** | **18 foreign keys** | **2 one-to-one** | **17 one-to-many**

---

## 1. Entity Relationship Diagram (Mermaid)

```mermaid
erDiagram
    %% ========================================================================
    %% ROLES - Reference Table (Seed Data)
    %% ========================================================================
    roles {
        text id PK "Primary Key: USER, SECURITY_ADMIN, SOC_ANALYST, SECURITY_MANAGER"
        text name "Display name (Vietnamese)"
        text description "Mô tả vai trò"
        timestamptz created_at "Thời gian tạo"
    }

    %% ========================================================================
    %% USERS - Core Entity
    %% ========================================================================
    users {
        uuid id PK "Primary Key - gen_random_uuid()"
        text username UK "3-50 chars, alphanumeric + underscore"
        text password_hash "Argon2id hash"
        text email "Email address (nullable, unique)"
        text full_name "Tên đầy đủ (nullable)"
        text status "active | suspended | locked"
        boolean admin_mfa_required "Yêu cầu MFA khi đăng nhập admin"
        boolean detection_mfa_once "Yêu cầu MFA 1 lần sau detection"
        timestamptz last_login_at "Thời gian đăng nhập cuối"
        int failed_login_count "Số lần đăng nhập thất bại"
        timestamptz locked_at "Thời gian bị khóa"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto-update trigger)"
    }

    %% ========================================================================
    %% USER_ROLES - Junction Table
    %% ========================================================================
    user_roles {
        uuid user_id PKFK "FK → users.id (ON DELETE CASCADE)"
        text role_id PKFK "FK → roles.id"
        timestamptz assigned_at "Thời gian gán"
        uuid assigned_by FK "FK → users.id (nullable, ON DELETE SET NULL)"
    }

    %% ========================================================================
    %% SESSIONS - JWT Token Management
    %% ========================================================================
    sessions {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id (ON DELETE CASCADE)"
        text access_token_hash "SHA256 hash của access token"
        text refresh_token_hash "SHA256 hash của refresh token"
        uuid refresh_token_family "UUID - Cho refresh token rotation tracking"
        text token_jti UK "JWT ID - cho revoke riêng lẻ"
        timestamptz expires_at "Thời gian hết hạn"
        timestamptz last_activity_at "Hoạt động cuối"
        timestamptz revoked_at "Thời gian thu hồi (nullable)"
        inet ip_address "Địa chỉ IP"
        text user_agent "User Agent string"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto-update trigger)"
    }

    %% ========================================================================
    %% PRE_AUTH_TRANSACTIONS - MFA Challenge
    %% ========================================================================
    pre_auth_transactions {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id (ON DELETE CASCADE)"
        text mfa_type "persistent | one_time"
        timestamptz expires_at "Thời gian hết hạn OTP"
        text status "pending | completed | expired | failed"
        text bound_ip "Hash IP đã bind"
        uuid notification_id FK "FK → mfa_notifications.id (ON DELETE SET NULL)"
        int fail_count "Số lần sai OTP"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto-update trigger)"
    }

    %% ========================================================================
    %% MFA_NOTIFICATIONS - Email OTP Lifecycle
    %% ========================================================================
    mfa_notifications {
        uuid id PK "Primary Key"
        uuid pre_auth_transaction_id FK "FK → pre_auth_transactions.id (ON DELETE CASCADE)"
        text channel "email | sms | totp (mở rộng sau)"
        text recipient "Email hoặc SĐT"
        text mfa_code_hash "Argon2id hash của OTP 6 số"
        timestamptz sent_at "Thời gian gửi"
        timestamptz delivered_at "Thời gian delivered (nullable)"
        timestamptz failed_at "Thời gian thất bại (nullable)"
        text failure_reason "Lý do thất bại (nullable)"
        timestamptz expires_at "Thời gian hết hạn"
        timestamptz verified_at "Thời gian verify thành công (nullable)"
        timestamptz created_at "Thời gian tạo"
    }

    %% ========================================================================
    %% RATE_LIMITS - Composite Primary Key
    %% ========================================================================
    rate_limits {
        inet ip_address PK "Primary Key (part 1)"
        text action PK "Primary Key (part 2): login, api, etc."
        int count "Số request trong window"
        int max_count "Giới hạn request"
        timestamptz window_start "Bắt đầu window"
    }

    %% ========================================================================
    %% POLICY_VERSIONS - Detection Rules Versioning
    %% ========================================================================
    policy_versions {
        uuid id PK "Primary Key"
        text version UK "v1.0, v2.1, etc. - UNIQUE"
        text description "Mô tả phiên bản"
        jsonb rules_json "JSON chứa rules: geo_block, new_country, etc."
        jsonb weights "{\"rule\": 0.4, \"ml\": 0.6}"
        jsonb thresholds "{\"challenge\": 0.3, \"block\": 0.7}"
        boolean is_active "Chỉ 1 phiên bản active tại thời điểm"
        uuid created_by_user_id FK "FK → users.id (ON DELETE SET NULL)"
        timestamptz created_at "Thời gian tạo"
        timestamptz activated_at "Thời gian kích hoạt (nullable)"
        timestamptz deactivated_at "Thời gian hủy kích hoạt (nullable)"
    }

    %% ========================================================================
    %% LOGIN_ATTEMPTS - Audit Trail & Detection Source
    %% ========================================================================
    login_attempts {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id (ON DELETE SET NULL)"
        text username_attempted "Username đã thử (cho failed login)"
        timestamptz occurred_at "Thời gian xảy ra"
        text outcome "success | failure | mfa_required | mfa_success | mfa_failed | blocked | locked | rate_limited"
        inet source_ip "Địa chỉ IP nguồn"
        text user_agent "User Agent string"
        boolean rate_limited "Có bị rate limit không"
        uuid policy_version_id FK "FK → policy_versions.id (ON DELETE SET NULL)"
        uuid request_id "UUID - Distributed tracing"
        jsonb detection_features "Raw features vector cho debugging"
        uuid primary_alert_id FK "FK → alerts.id (ON DELETE SET NULL)"
        text risk_level "low | medium | high | critical"
        boolean mfa_used "Có sử dụng MFA không"
        text detection_decision "allow | challenge | block"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto-update trigger)"
    }

    %% ========================================================================
    %% RISK_ASSESSMENTS - Per Login Attempt (1:1)
    %% ========================================================================
    risk_assessments {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK UK "FK → login_attempts.id (ON DELETE CASCADE) - UNIQUE"
        uuid policy_version_id FK "FK → policy_versions.id (ON DELETE SET NULL)"
        numeric rule_score "Điểm từ rule engine (0.0000-1.0000)"
        numeric anomaly_score "Điểm bất thường từ ML"
        numeric ml_score "Điểm từ ML model"
        text ml_status "success | unavailable | error"
        text ml_model_version "Phiên bản ML model"
        jsonb rule_hits "Array các rule đã trigger"
        jsonb ml_features_used "Features thực tế dùng cho ML"
        numeric combined_score "Kết hợp: w1*rule + w2*ml"
        text risk_level "low | medium | high | critical"
        text decision "allow | challenge | block"
        timestamptz created_at "Thời gian tạo"
    }

    %% ========================================================================
    %% DETECTION_LOGS - Audit Trail for ML/Rule
    %% ========================================================================
    detection_logs {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK "FK → login_attempts.id (ON DELETE SET NULL)"
        uuid request_id "UUID - Distributed tracing"
        text stage "rule | ml | combined | action"
        text stage_detail "geo_block, asn_reputation, ml_inference, etc."
        uuid rule_id "Reference đến rule trong policy_version"
        text rule_name "Tên rule đã evaluate"
        numeric score "Điểm của rule/evaluation (0.0000-1.0000)"
        text decision "allow | challenge | block"
        text reason "Lý do quyết định"
        jsonb details "Chi tiết bổ sung"
        timestamptz created_at "Thời gian tạo"
    }

    %% ========================================================================
    %% ALERTS - SOC Workflow
    %% ========================================================================
    alerts {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK "FK → login_attempts.id (ON DELETE CASCADE)"
        uuid policy_version_id FK "FK → policy_versions.id (ON DELETE SET NULL)"
        uuid request_id "UUID - Distributed tracing"
        text status "open | acknowledged | resolved | false_positive"
        text risk_level "low | medium | high | critical"
        text detection_reason "Lý do ngắn gọn tạo alert"
        jsonb detection_scores "Snapshot scores tại thời điểm tạo"
        text assigned_to "SOC analyst được gán"
        text resolved_by "Người resolve"
        timestamptz resolved_at "Thời gian resolve"
        text notes "Ghi chú của SOC"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto-update trigger)"
    }

    %% ========================================================================
    %% AUDIT_LOGS - Immutable Audit Trail
    %% ========================================================================
    audit_logs {
        uuid id PK "Primary Key"
        uuid request_id "UUID - Distributed tracing"
        text actor "user_id hoặc 'system:detection-engine'"
        text action "role_assigned | user_locked | session_revoked | alert_resolved"
        text resource "user | session | role | alert | policy_version"
        uuid resource_id "ID của resource bị thay đổi"
        jsonb before_state "State trước thay đổi"
        jsonb after_state "State sau thay đổi"
        text change_reason "Lý do thay đổi"
        inet ip_address "IP của actor"
        text user_agent "User Agent của actor"
        timestamptz created_at "Thời gian tạo (immutable)"
    }

    %% ========================================================================
    %% USER_TRUSTED_DEVICES - Remember This Device
    %% ========================================================================
    user_trusted_devices {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id (ON DELETE CASCADE)"
        text device_fingerprint "Hash device characteristics"
        text device_name "Tên thiết bị (user-provided)"
        inet last_ip "IP cuối dùng"
        text last_user_agent "User-Agent cuối"
        timestamptz last_used_at "Lần cuối sử dụng"
        timestamptz expires_at "Hết hạn (NULL = vĩnh viễn)"
        timestamptz created_at "Thời gian tạo"
    }

    %% ========================================================================
    %% ALERT_TIMELINE - SOC Collaboration Audit Trail
    %% ========================================================================
    alert_timeline {
        uuid id PK "Primary Key"
        uuid alert_id FK "FK → alerts.id (ON DELETE CASCADE)"
        text event_type "created | assigned | unassigned | acknowledged | escalated | note_added | status_changed | resolved"
        text actor "user_id hoặc system"
        text old_value "Giá trị cũ"
        text new_value "Giá trị mới"
        text comment "Bình luận SOC"
        inet ip_address "IP của actor"
        timestamptz created_at "Thời gian tạo"
    }

    %% ========================================================================
    %% SYSTEM_SETTINGS - Dynamic Configuration
    %% ========================================================================
    system_settings {
        text key PK "Primary Key: mfa.otp_length, rate_limit.login.max_attempts, etc."
        text value "Giá trị cấu hình"
        text value_type "string | integer | boolean | json"
        text description "Mô tả setting"
        text category "mfa | rate_limit | detection | auth | notification | general"
        uuid updated_by FK "FK → users.id (ON DELETE SET NULL)"
        timestamptz updated_at "Thời gian cập nhật"
    }

    %% ========================================================================
    %% OUTBOX_EVENTS - Transactional Outbox Pattern (ADR-002)
    %% ========================================================================
    outbox_events {
        uuid id PK "Primary Key"
        text aggregate_type "login_attempt | alert | user | session"
        uuid aggregate_id "ID của aggregate root"
        text event_type "LoginAttemptCreated | AlertCreated | ..."
        int version "Version cho event sourcing"
        jsonb payload "Event data"
        jsonb headers "Optional: correlation_id, causation_id"
        text status "pending | processing | published | failed"
        int retry_count "Số lần retry"
        int max_retries "Số lần retry tối đa"
        text last_error "Lỗi cuối cùng"
        timestamptz created_at "Thời gian tạo"
        timestamptz published_at "Thời gian publish thành công"
    }

    %% ========================================================================
    %% USER_NOTIFICATIONS - In-App Notifications
    %% ========================================================================
    user_notifications {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id (ON DELETE CASCADE)"
        text type "mfa_success | new_login | account_locked | ..."
        text title "Tiêu đề thông báo"
        text body "Nội dung thông báo"
        text link "URL để navigate"
        text priority "low | normal | high | urgent"
        boolean read "Đã đọc chưa"
        timestamptz read_at "Thời gian đọc"
        timestamptz expires_at "Hết hạn (nullable)"
        timestamptz created_at "Thời gian tạo"
    }

    %% ========================================================================
    %% RELATIONSHIPS
    %% ========================================================================

    %% === CORE AUTH RELATIONSHIPS ===

    %% Roles → UserRoles (1:N)
    roles ||--o{ user_roles : "assigned to"

    %% Users → UserRoles (1:N)
    users ||--o{ user_roles : "has roles"

    %% Users → Sessions (1:N)
    users ||--o{ sessions : "owns"

    %% Users → PreAuthTransactions (1:N)
    users ||--o{ pre_auth_transactions : "initiates MFA"

    %% Users → LoginAttempts (1:N)
    users ||--o{ login_attempts : "performs"

    %% Users → TrustedDevices (1:N)
    users ||--o{ user_trusted_devices : "registers"

    %% Users → Notifications (1:N)
    users ||--o{ user_notifications : "receives"

    %% Users → SystemSettings (1:N)
    users ||--o{ system_settings : "updates"

    %% Users → PolicyVersions (1:N, creator)
    users ||--o{ policy_versions : "creates"

    %% === MFA RELATIONSHIPS ===

    %% PreAuth → MfaNotification (1:1)
    pre_auth_transactions ||--|| mfa_notifications : "creates notification"

    %% PreAuth → Sessions (user after MFA completes)
    users ||--o{ sessions : "gets session after MFA"

    %% === DETECTION RELATIONSHIPS ===

    %% PolicyVersions → LoginAttempts (1:N)
    policy_versions ||--o{ login_attempts : "applied to"

    %% PolicyVersions → RiskAssessments (1:N)
    policy_versions ||--o{ risk_assessments : "used in"

    %% PolicyVersions → Alerts (1:N)
    policy_versions ||--o{ alerts : "context for"

    %% LoginAttempts → RiskAssessments (1:1)
    login_attempts ||--|| risk_assessments : "evaluated by"

    %% LoginAttempts → DetectionLogs (1:N)
    login_attempts ||--o{ detection_logs : "generates"

    %% LoginAttempts → Alerts (1:N)
    login_attempts ||--o{ alerts : "triggers"

    %% LoginAttempts → PrimaryAlert (1:1, self-reference)
    login_attempts ||--o| alerts : "primary alert"

    %% === SOC RELATIONSHIPS ===

    %% Alerts → AlertTimeline (1:N)
    alerts ||--o{ alert_timeline : "has timeline"

    %% === USER_ROLES RELATIONSHIPS ===

    %% UserRoles → AssignedBy (self-reference)
    user_roles }o..|| users : "assigned by"
```

---

## 2. Relationship Summary Table

| # | From Entity | To Entity | Cardinality | Type | Description |
|---|-------------|-----------|-------------|------|-------------|
| 1 | `roles` | `user_roles` | 1:N | Standard | Role được gán cho nhiều user |
| 2 | `users` | `user_roles` | 1:N | Standard | User có nhiều role |
| 3 | `user_roles` | `users` | N:1 | Self-ref | Assigned_by reference |
| 4 | `users` | `sessions` | 1:N | Standard | User có nhiều session |
| 5 | `users` | `pre_auth_transactions` | 1:N | Standard | User khởi tạo MFA |
| 6 | `pre_auth_transactions` | `mfa_notifications` | 1:1 | Standard | MFA tạo notification |
| 7 | `users` | `login_attempts` | 1:N | Standard | User thực hiện login |
| 8 | `users` | `user_trusted_devices` | 1:N | Standard | User đăng ký thiết bị |
| 9 | `users` | `user_notifications` | 1:N | Standard | User nhận thông báo |
| 10 | `users` | `system_settings` | 1:N | Standard | Admin cập nhật settings |
| 11 | `users` | `policy_versions` | 1:N | Standard | User tạo policy |
| 12 | `login_attempts` | `risk_assessments` | 1:1 | Standard | Mỗi login có 1 assessment |
| 13 | `login_attempts` | `detection_logs` | 1:N | Standard | Login tạo nhiều log |
| 14 | `login_attempts` | `alerts` | 1:N | Standard | Login tạo nhiều alert |
| 15 | `login_attempts` | `alerts` | 1:1 | Self-ref | Primary alert |
| 16 | `policy_versions` | `login_attempts` | 1:N | Standard | Policy applied to login |
| 17 | `policy_versions` | `risk_assessments` | 1:N | Standard | Policy used in assessment |
| 18 | `policy_versions` | `alerts` | 1:N | Standard | Policy context for alert |
| 19 | `alerts` | `alert_timeline` | 1:N | Standard | Alert có timeline |

**Total: 19 relationships | 2 one-to-one | 17 one-to-many**

---

## 3. Foreign Key Reference

| # | FK Column | References Table | References Column | ON DELETE | ON UPDATE |
|---|-----------|-----------------|------------------|-----------|-----------|
| 1 | `user_roles.user_id` | `users` | `id` | CASCADE | - |
| 2 | `user_roles.role_id` | `roles` | `id` | - | - |
| 3 | `user_roles.assigned_by` | `users` | `id` | SET NULL | - |
| 4 | `sessions.user_id` | `users` | `id` | CASCADE | - |
| 5 | `pre_auth_transactions.user_id` | `users` | `id` | CASCADE | - |
| 6 | `pre_auth_transactions.notification_id` | `mfa_notifications` | `id` | SET NULL | - |
| 7 | `mfa_notifications.pre_auth_transaction_id` | `pre_auth_transactions` | `id` | CASCADE | - |
| 8 | `policy_versions.created_by_user_id` | `users` | `id` | SET NULL | - |
| 9 | `login_attempts.user_id` | `users` | `id` | SET NULL | - |
| 10 | `login_attempts.policy_version_id` | `policy_versions` | `id` | SET NULL | - |
| 11 | `login_attempts.primary_alert_id` | `alerts` | `id` | SET NULL | - |
| 12 | `risk_assessments.login_attempt_id` | `login_attempts` | `id` | CASCADE | - |
| 13 | `risk_assessments.policy_version_id` | `policy_versions` | `id` | SET NULL | - |
| 14 | `detection_logs.login_attempt_id` | `login_attempts` | `id` | SET NULL | - |
| 15 | `alerts.login_attempt_id` | `login_attempts` | `id` | CASCADE | - |
| 16 | `alerts.policy_version_id` | `policy_versions` | `id` | SET NULL | - |
| 17 | `user_trusted_devices.user_id` | `users` | `id` | CASCADE | - |
| 18 | `alert_timeline.alert_id` | `alerts` | `id` | CASCADE | - |
| 19 | `user_notifications.user_id` | `users` | `id` | CASCADE | - |
| 20 | `system_settings.updated_by` | `users` | `id` | SET NULL | - |

**Total: 20 foreign keys**

---

## 4. Unique Constraints

| # | Table | Columns | Type | Description |
|---|-------|---------|------|-------------|
| 1 | `users` | `username` | UNIQUE | Username không trùng |
| 2 | `users` | `email` | UNIQUE (partial) | Email không trùng (nếu not null) |
| 3 | `sessions` | `token_jti` | UNIQUE | JWT ID không trùng |
| 4 | `policy_versions` | `version` | UNIQUE | Version không trùng |
| 5 | `risk_assessments` | `login_attempt_id` | UNIQUE | 1 assessment per login |
| 6 | `user_roles` | `(user_id, role_id)` | COMPOSITE PK | Unique user-role pair |
| 7 | `rate_limits` | `(ip_address, action)` | COMPOSITE PK | Unique per IP-action |

---

## 5. Index Summary

| Table | Indexes | Purpose |
|-------|---------|---------|
| `users` | 4 | username lookup, email lookup, status filter |
| `user_roles` | 2 | user_id, role_id |
| `sessions` | 4 | user_id, token hash, expiry, jti |
| `pre_auth_transactions` | 4 | user_id, status, expiry, composite |
| `mfa_notifications` | 3 | transaction_id, recipient, expiry |
| `rate_limits` | 1 | window cleanup |
| `policy_versions` | 2 | version, is_active |
| `login_attempts` | 6 | user_id, occurred_at, outcome, risk_level, request_id, username |
| `risk_assessments` | 2 | login_attempt_id, risk_level |
| `detection_logs` | 3 | login_attempt_id, stage, request_id |
| `alerts` | 5 | login_attempt_id, status, risk_level, assigned_to, created_at |
| `audit_logs` | 5 | actor, action, resource, created_at, request_id |
| `user_trusted_devices` | 3 | user_id, fingerprint, active devices |
| `alert_timeline` | 3 | alert_id, created_at, actor |
| `system_settings` | 1 | category |
| `outbox_events` | 3 | pending, aggregate, event_type |
| `user_notifications` | 4 | user_id, unread, created_at, expires |

**Total: 50 indexes**

---

## 6. Trigger Summary

| Table | Trigger | Event | Action |
|-------|---------|-------|--------|
| `users` | `trg_users_updated_at` | BEFORE UPDATE | Auto-update `updated_at` |
| `sessions` | `trg_sessions_updated_at` | BEFORE UPDATE | Auto-update `updated_at` |
| `pre_auth_transactions` | `trg_pre_auth_updated_at` | BEFORE UPDATE | Auto-update `updated_at` |
| `policy_versions` | `trg_policy_updated_at` | BEFORE UPDATE | Auto-update `updated_at` |
| `login_attempts` | `trg_login_attempts_updated_at` | BEFORE UPDATE | Auto-update `updated_at` |
| `alerts` | `trg_alerts_updated_at` | BEFORE UPDATE | Auto-update `updated_at` |
| `system_settings` | `trg_system_settings_updated_at` | BEFORE UPDATE | Auto-update `updated_at` |

**Total: 7 auto-update triggers**

---

## 7. Check Constraints

| Table | Constraint | Check |
|-------|------------|-------|
| `users` | `chk_username_length` | `length(username) BETWEEN 3 AND 50` |
| `users` | `chk_username_chars` | `username ~ '^[a-zA-Z0-9_]+$'` |
| `users` | `chk_email_format` | Email format validation |
| `users` | `status` | `status IN ('active', 'suspended', 'locked')` |
| `pre_auth_transactions` | `mfa_type` | `mfa_type IN ('persistent', 'one_time')` |
| `pre_auth_transactions` | `status` | `status IN ('pending', 'completed', 'expired', 'failed')` |
| `login_attempts` | `outcome` | 8 outcome values |
| `login_attempts` | `risk_level` | `risk_level IN ('low', 'medium', 'high', 'critical')` |
| `login_attempts` | `detection_decision` | `detection_decision IN ('allow', 'challenge', 'block')` |
| `risk_assessments` | `ml_status` | `ml_status IN ('success', 'unavailable', 'error')` |
| `risk_assessments` | `risk_level` | `risk_level IN ('low', 'medium', 'high', 'critical')` |
| `risk_assessments` | `decision` | `decision IN ('allow', 'challenge', 'block')` |
| `detection_logs` | `stage` | `stage IN ('rule', 'ml', 'combined', 'action')` |
| `detection_logs` | `decision` | `decision IN ('allow', 'challenge', 'block')` |
| `alerts` | `status` | `status IN ('open', 'acknowledged', 'resolved', 'false_positive')` |
| `alerts` | `risk_level` | `risk_level IN ('low', 'medium', 'high', 'critical')` |
| `rate_limits` | `chk_rate_count` | `count >= 0` |
| `rate_limits` | `chk_rate_max` | `max_count > 0` |
| `alert_timeline` | `event_type` | 8 event types |
| `system_settings` | `value_type` | `value_type IN ('string', 'integer', 'boolean', 'json')` |
| `system_settings` | `category` | 6 categories |
| `outbox_events` | `status` | `status IN ('pending', 'processing', 'published', 'failed')` |
| `user_notifications` | `type` | 9 notification types |
| `user_notifications` | `priority` | `priority IN ('low', 'normal', 'high', 'urgent')` |

---

## 8. Table Statistics

| Table | Columns | PK Type | FK Count | Index Count | Trigger Count |
|-------|---------|---------|----------|-------------|---------------|
| `roles` | 4 | Simple | 0 | 0 | 0 |
| `users` | 14 | UUID | 0 | 4 | 1 |
| `user_roles` | 4 | Composite | 2 | 2 | 0 |
| `sessions` | 13 | UUID | 1 | 4 | 1 |
| `pre_auth_transactions` | 10 | UUID | 2 | 4 | 1 |
| `mfa_notifications` | 12 | UUID | 1 | 3 | 0 |
| `rate_limits` | 5 | Composite | 0 | 1 | 0 |
| `policy_versions` | 12 | UUID | 1 | 2 | 1 |
| `login_attempts` | 17 | UUID | 3 | 6 | 1 |
| `risk_assessments` | 15 | UUID | 2 | 2 | 0 |
| `detection_logs` | 12 | UUID | 1 | 3 | 0 |
| `alerts` | 14 | UUID | 2 | 5 | 1 |
| `audit_logs` | 12 | UUID | 0 | 5 | 0 |
| `user_trusted_devices` | 9 | UUID | 1 | 3 | 0 |
| `alert_timeline` | 8 | UUID | 1 | 3 | 0 |
| `system_settings` | 7 | Simple | 1 | 1 | 1 |
| `outbox_events` | 13 | UUID | 0 | 3 | 0 |
| `user_notifications` | 11 | UUID | 1 | 4 | 0 |

**Totals: 19 tables | 182 columns | 20 foreign keys | 50 indexes | 7 triggers**

---

## 9. Seed Data

### Roles (Seed)
```sql
INSERT INTO roles (id, name, description) VALUES
    ('USER',              'Người dùng',            'Role nền mặc định'),
    ('SECURITY_ADMIN',    'Quản trị viên bảo mật', 'Quản lý account, rule, audit'),
    ('SOC_ANALYST',       'Phân tích viên SOC',     'Xem, acknowledge, resolve alerts'),
    ('SECURITY_MANAGER',  'Quản lý bảo mật',       'Dashboard, báo cáo');
```

### Default Policy Version (Seed)
```sql
INSERT INTO policy_versions (version, description, rules_json, is_active) VALUES
    ('v1.0', 'Default detection policy', '{
        "rules": [
            {"name": "geo_block", "conditions": {"countries": ["XX"]}, "score": 0.95, "enabled": true},
            {"name": "new_country", "conditions": {"threshold_days": 90}, "score": 0.6, "enabled": true},
            {"name": "asn_reputation", "conditions": {"min_reputation": 0.3}, "score": 0.5, "enabled": true},
            {"name": "failed_attempts", "conditions": {"threshold": 3}, "score": 0.7, "enabled": true},
            {"name": "unusual_hour", "conditions": {"hour_range": [0, 6]}, "score": 0.3, "enabled": true}
        ],
        "weights": {"rule": 0.4, "ml": 0.6},
        "thresholds": {"challenge": 0.3, "block": 0.7}
    }'::jsonb, TRUE);
```

### System Settings (Seed)
```sql
-- MFA Settings
INSERT INTO system_settings (key, value, value_type, description, category) VALUES
    ('mfa.otp_length', '6', 'integer', 'Số chữ số OTP', 'mfa'),
    ('mfa.otp_ttl_seconds', '300', 'integer', 'Thời gian hết hạn OTP (giây)', 'mfa'),
    ('mfa.max_attempts', '3', 'integer', 'Số lần thử OTP tối đa', 'mfa');

-- Rate Limiting
INSERT INTO system_settings (key, value, value_type, description, category) VALUES
    ('rate_limit.login.max_attempts', '5', 'integer', 'Số lần đăng nhập sai tối đa', 'rate_limit'),
    ('rate_limit.login.window_seconds', '300', 'integer', 'Window cho rate limit (giây)', 'rate_limit');

-- Detection
INSERT INTO system_settings (key, value, value_type, description, category) VALUES
    ('detection.rule_weight', '0.4', 'string', 'Trọng số rule engine', 'detection'),
    ('detection.ml_weight', '0.6', 'string', 'Trọng số ML model', 'detection'),
    ('detection.challenge_threshold', '0.3', 'string', 'Ngưỡng challenge MFA', 'detection'),
    ('detection.block_threshold', '0.7', 'string', 'Ngưỡng block', 'detection');

-- Session
INSERT INTO system_settings (key, value, value_type, description, category) VALUES
    ('session.access_token_ttl', '900', 'integer', 'Access token TTL (giây)', 'auth'),
    ('session.refresh_token_ttl', '604800', 'integer', 'Refresh token TTL (giây)', 'auth'),
    ('session.trusted_device_ttl_days', '30', 'integer', 'Trusted device TTL (ngày)', 'auth');
```

---

## 10. Architecture Notes

### Authentication Flow
```
User Login → rate_limits → users → sessions (if MFA not required)
                              ↓
                       pre_auth_transactions → mfa_notifications
                              ↓
                         POST /mfa/verify → sessions
```

### Detection Flow
```
login_attempts → risk_assessments (1:1)
              → detection_logs (1:N)
              → alerts (1:N)
              → primary_alert (1:1, self-ref)
```

### SOC Workflow
```
alerts → alert_timeline (1:N)
       → login_attempts → risk_assessments → detection_logs
```

### User Device Management
```
users → user_trusted_devices (1:N)
      → user_notifications (1:N)
```

### Event Sourcing (ADR-002)
```
Any table → outbox_events → Background worker → External systems
```
