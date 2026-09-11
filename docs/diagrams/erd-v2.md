# Sentinel Auth - Entity Relationship Diagram v2

> Database schema cho Sentinel Auth dựa trên `schema-v2.sql` và `app/models.py`
>
> **12 tables** | **13 foreign keys** | **2 one-to-one** | **11 one-to-many**

---

## Mermaid ERD

```mermaid
erDiagram
    %% ============================================================================
    %% ROLES (Reference Table)
    %% ============================================================================
    roles {
        text id PK "Primary Key: USER, SECURITY_ADMIN, SOC_ANALYST, SECURITY_MANAGER"
        text name "Display name"
        text description "Mô tả vai trò"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% USERS (Core Entity)
    %% ============================================================================
    users {
        uuid id PK "Primary Key"
        text username UK "3-50 chars, alphanumeric + underscore"
        text password_hash "Argon2id hash"
        text email "Email address (nullable)"
        text full_name "Tên đầy đủ (nullable)"
        text status "active | suspended | locked"
        boolean admin_mfa_required "Yêu cầu MFA khi đăng nhập admin"
        boolean detection_mfa_once "Yêu cầu MFA 1 lần sau detection"
        timestamptz last_login_at "Thời gian đăng nhập cuối"
        int failed_login_count "Số lần đăng nhập thất bại"
        timestamptz locked_at "Thời gian bị khóa"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto)"
    }

    %% ============================================================================
    %% USER_ROLES (Junction Table)
    %% ============================================================================
    user_roles {
        uuid user_id PK, FK "FK → users.id"
        text role_id PK, FK "FK → roles.id"
        timestamptz assigned_at "Thời gian gán"
        uuid assigned_by FK "FK → users.id (nullable)"
    }

    %% ============================================================================
    %% SESSIONS
    %% ============================================================================
    sessions {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id"
        text access_token_hash "SHA256 hash của access token"
        text refresh_token_hash "SHA256 hash của refresh token"
        uuid refresh_token_family "Cho refresh token rotation"
        text token_jti UK "JWT ID cho revoke riêng lẻ"
        timestamptz expires_at "Thời gian hết hạn"
        timestamptz last_activity_at "Hoạt động cuối"
        timestamptz revoked_at "Thời gian thu hồi (nullable)"
        inet ip_address "Địa chỉ IP"
        text user_agent "User Agent string"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto)"
    }

    %% ============================================================================
    %% PRE_AUTH_TRANSACTIONS (MFA)
    %% ============================================================================
    pre_auth_transactions {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id"
        text mfa_type "persistent | one_time"
        timestamptz expires_at "Thời gian hết hạn OTP"
        text status "pending | completed | expired | failed"
        text bound_ip "Hash IP đã bind"
        uuid notification_id FK "FK → mfa_notifications.id"
        int fail_count "Số lần sai OTP"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto)"
    }

    %% ============================================================================
    %% MFA_NOTIFICATIONS (Email OTP Lifecycle)
    %% ============================================================================
    mfa_notifications {
        uuid id PK "Primary Key"
        uuid pre_auth_transaction_id FK "FK → pre_auth_transactions.id"
        text channel "email (mở rộng SMS/TOTP sau)"
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

    %% ============================================================================
    %% RATE_LIMITS (Composite PK)
    %% ============================================================================
    rate_limits {
        inet ip_address PK "Primary Key (part 1)"
        text action PK "Primary Key (part 2): login, api, etc."
        int count "Số request trong window"
        int max_count "Giới hạn request"
        timestamptz window_start "Bắt đầu window"
    }

    %% ============================================================================
    %% POLICY_VERSIONS (Detection Rules)
    %% ============================================================================
    policy_versions {
        uuid id PK "Primary Key"
        text version UK "v1.0, v2.1, etc."
        text description "Mô tả phiên bản"
        jsonb rules_json "JSON chứa rules: geo_block, new_country, etc."
        jsonb weights "{\"rule\": 0.4, \"ml\": 0.6}"
        jsonb thresholds "{\"challenge\": 0.3, \"block\": 0.7}"
        boolean is_active "Chỉ 1 phiên bản active"
        uuid created_by_user_id FK "FK → users.id (nullable)"
        timestamptz created_at "Thời gian tạo"
        timestamptz activated_at "Thời gian kích hoạt (nullable)"
        timestamptz deactivated_at "Thời gian hủy kích hoạt (nullable)"
    }

    %% ============================================================================
    %% LOGIN_ATTEMPTS (Audit Trail)
    %% ============================================================================
    login_attempts {
        uuid id PK "Primary Key"
        uuid user_id FK "FK → users.id (nullable)"
        text username_attempted "Username đã thử (cho failed login)"
        timestamptz occurred_at "Thời gian xảy ra"
        text outcome "success | failure | mfa_required | mfa_success | mfa_failed | blocked | locked | rate_limited"
        inet source_ip "Địa chỉ IP nguồn"
        text user_agent "User Agent string"
        boolean rate_limited "Có bị rate limit không"
        uuid policy_version_id FK "FK → policy_versions.id (nullable)"
        uuid request_id "UUID cho distributed tracing"
        jsonb detection_features "Raw features vector"
        uuid primary_alert_id FK "FK → alerts.id (nullable)"
        text risk_level "low | medium | high | critical"
        boolean mfa_used "Có sử dụng MFA không"
        text detection_decision "allow | challenge | block"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto)"
    }

    %% ============================================================================
    %% RISK_ASSESSMENTS (1:1 with LoginAttempt)
    %% ============================================================================
    risk_assessments {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK, UK "FK → login_attempts.id (UNIQUE)"
        uuid policy_version_id FK "FK → policy_versions.id (nullable)"
        numeric rule_score "Điểm từ rule engine (0.0000-1.0000)"
        numeric anomaly_score "Điểm bất thường từ ML"
        numeric ml_score "Điểm từ ML model"
        text ml_status "success | unavailable | error"
        text ml_model_version "Phiên bản ML model"
        jsonb rule_hits "Array các rule đã trigger"
        jsonb ml_features_used "Features thực tế dùng"
        numeric combined_score "Kết hợp: w1*rule + w2*ml"
        text risk_level "low | medium | high | critical"
        text decision "allow | challenge | block"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% DETECTION_LOGS (Audit Trail)
    %% ============================================================================
    detection_logs {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK "FK → login_attempts.id (nullable)"
        uuid request_id "UUID cho distributed tracing"
        text stage "rule | ml | combined | action"
        text stage_detail "geo_block, asn_reputation, ml_inference, etc."
        uuid rule_id "Reference đến rule trong policy_version"
        text rule_name "Tên rule đã evaluate"
        numeric score "Điểm của rule/evaluation"
        text decision "allow | challenge | block"
        text reason "Lý do quyết định"
        jsonb details "Chi tiết bổ sung"
        timestamptz created_at "Thời gian tạo"
    }

    %% ============================================================================
    %% ALERTS (SOC Workflow)
    %% ============================================================================
    alerts {
        uuid id PK "Primary Key"
        uuid login_attempt_id FK "FK → login_attempts.id"
        uuid policy_version_id FK "FK → policy_versions.id (nullable)"
        uuid request_id "UUID cho distributed tracing"
        text status "open | acknowledged | resolved | false_positive"
        text risk_level "low | medium | high | critical"
        text detection_reason "Lý do ngắn gọn tạo alert"
        jsonb detection_scores "Snapshot scores tại thời điểm tạo"
        text assigned_to "SOC analyst được gán"
        text resolved_by "Người resolve"
        timestamptz resolved_at "Thời gian resolve"
        text notes "Ghi chú của SOC"
        timestamptz created_at "Thời gian tạo"
        timestamptz updated_at "Thời gian cập nhật (auto)"
    }

    %% ============================================================================
    %% AUDIT_LOGS (Immutable Audit Trail)
    %% ============================================================================
    audit_logs {
        uuid id PK "Primary Key"
        uuid request_id "UUID cho distributed tracing"
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

    %% ============================================================================
    %% RELATIONSHIPS
    %% ============================================================================

    %% User -> UserRoles (1:N)
    users ||--o{ user_roles : "has roles"
    roles ||--o{ user_roles : "assigned to"

    %% User -> Sessions (1:N)
    users ||--o{ sessions : "owns sessions"

    %% User -> PreAuth (1:N)
    users ||--o{ pre_auth_transactions : "initiates MFA"

    %% PreAuth <-> MfaNotification (1:1)
    pre_auth_transactions ||--|| mfa_notifications : "creates notification"

    %% User -> PolicyVersions (1:N, creator)
    users ||--o{ policy_versions : "creates"

    %% User -> LoginAttempts (1:N)
    users ||--o{ login_attempts : "performs"

    %% LoginAttempts -> RiskAssessments (1:1)
    login_attempts ||--|| risk_assessments : "evaluated by"

    %% LoginAttempts -> DetectionLogs (1:N)
    login_attempts ||--o{ detection_logs : "generates"

    %% LoginAttempts -> Alerts (1:N)
    login_attempts ||--o{ alerts : "triggers"

    %% LoginAttempts -> Self (primary_alert_id)
    login_attempts ||--o| alerts : "primary alert"

    %% PolicyVersions -> LoginAttempts (1:N)
    policy_versions ||--o{ login_attempts : "applied to"

    %% PolicyVersions -> RiskAssessments (1:N)
    policy_versions ||--o{ risk_assessments : "used in"

    %% PolicyVersions -> Alerts (1:N)
    policy_versions ||--o{ alerts : "context for"
```

---

## Relationship Summary

| From | To | Type | Description |
|------|-----|------|-------------|
| `users` | `user_roles` | 1:N | User có nhiều role |
| `roles` | `user_roles` | 1:N | Role được gán cho nhiều user |
| `users` | `sessions` | 1:N | User có nhiều session |
| `users` | `pre_auth_transactions` | 1:N | User khởi tạo MFA |
| `pre_auth_transactions` | `mfa_notifications` | 1:1 | MFA transaction tạo notification |
| `users` | `policy_versions` | 1:N | User tạo policy version |
| `users` | `login_attempts` | 1:N | User thực hiện login |
| `login_attempts` | `risk_assessments` | 1:1 | Mỗi login có 1 risk assessment |
| `login_attempts` | `detection_logs` | 1:N | Login tạo nhiều detection log |
| `login_attempts` | `alerts` | 1:N | Login có thể tạo nhiều alert |
| `policy_versions` | `login_attempts` | 1:N | Policy được áp dụng cho login |
| `policy_versions` | `risk_assessments` | 1:N | Policy dùng trong assessment |
| `policy_versions` | `alerts` | 1:N | Policy context cho alert |

---

## Key Design Decisions

### 1. Composite PK cho Rate Limits
```
rate_limits: (ip_address, action) → Composite Primary Key
```
Thay vì dùng UUID riêng, composite key `(ip, action)` là natural key.

### 2. 1:1 Relationship: LoginAttempt ↔ RiskAssessment
- `login_attempts` lưu event (what happened)
- `risk_assessments` lưu analysis (why the decision was made)

### 3. MFA Lifecycle Tracking
```
pre_auth_transactions (1:1) mfa_notifications
```
Tách riêng để hỗ trợ multi-channel MFA (SMS, TOTP) trong tương lai.

### 4. Distributed Tracing
UUID `request_id` xuyên suốt:
- `login_attempts.request_id`
- `detection_logs.request_id`
- `alerts.request_id`
- `audit_logs.request_id`

---

## Table Statistics

| Table | Columns | PK | FK | Indexes |
|-------|---------|-----|-----|---------|
| `roles` | 4 | 1 | 0 | 0 |
| `users` | 13 | 1 | 0 | 4 |
| `user_roles` | 4 | 2 (composite) | 2 | 2 |
| `sessions` | 13 | 1 | 1 | 5 |
| `pre_auth_transactions` | 10 | 1 | 2 | 4 |
| `mfa_notifications` | 12 | 1 | 1 | 3 |
| `rate_limits` | 5 | 2 (composite) | 0 | 1 |
| `policy_versions` | 12 | 1 | 1 | 3 |
| `login_attempts` | 17 | 1 | 3 | 6 |
| `risk_assessments` | 15 | 1 | 2 | 2 |
| `detection_logs` | 12 | 1 | 1 | 3 |
| `alerts` | 14 | 1 | 2 | 5 |
| `audit_logs` | 12 | 1 | 0 | 5 |

**Total: 12 tables, 143 columns, 13 foreign keys, 43 indexes**
