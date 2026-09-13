# ĐẶC TẢ USE CASE - DETECTION ENGINE

> **Phiên bản:** 3.3  
> **Ngày:** 2026-09-13  
> **Trạng thái:** Hoàn thành thiết kế

---

## 1. MỤC ĐÍCH

Tài liệu này mô tả chi tiết các Use Case của **Detection Engine** trong hệ thống Sentinel Auth.

---

## 2. DANH SÁCH USE CASE TỔNG HỢP

| UC | Tên Use Case | Actor chính | Ưu tiên |
|----|--------------|-------------|----------|
| UC-DE-01 | Nhận LoginEvent | Core App | Bắt buộc |
| UC-DE-02 | Build Features | Hệ thống | Bắt buộc |
| UC-DE-03 | Gọi ML Service | Hệ thống | Bắt buộc |
| UC-DE-04 | Evaluate Rules | Hệ thống | Bắt buộc |
| UC-DE-05 | Calculate Risk Score | Hệ thống | Bắt buộc |
| UC-DE-06 | Tạo Alert | Hệ thống | Bắt buộc |
| UC-DE-07 | Gửi Action về Core | Hệ thống | Bắt buộc |
| UC-DE-08 | Xem SOC Dashboard | SOC Analyst | Bắt buộc |
| UC-DE-09 | Tiếp nhận Alert | SOC Analyst | Bắt buộc |
| UC-DE-10 | Điều tra Alert | SOC Analyst | Bắt buộc |
| UC-DE-11 | Xem Evidence | SOC Analyst | Bắt buộc |
| UC-DE-12 | Phân loại Alert | SOC Analyst | Bắt buộc |
| UC-DE-13 | Yêu cầu Action | SOC Analyst | Bắt buộc |
| UC-DE-14 | Tra cứu Login History | SOC Analyst | Bắt buộc |
| UC-DE-15 | Quản lý Policy | Security Admin | Bắt buộc |

---

## 3. USE CASE CHI TIẾT

### 3.1 UC-DE-01: Nhận LoginEvent

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-01 |
| **Tên** | Nhận LoginEvent |
| **Actor chính** | Core App |
| **Actor phụ** | - |
| **Mô tả ngắn** | Tiếp nhận event đăng nhập từ Core App để xử lý detection |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. Core App gửi POST /internal/login-events
2. Detection Engine validate request
3. Lưu LoginAttempt vào database
4. Trigger async processing
5. Trả về HTTP 202 Accepted
```

#### Request Schema
```json
{
  "event_id": "UUID",
  "user_id": "UUID | null",
  "username_attempted": "string",
  "outcome": "success | failed",
  "mfa_used": "boolean",
  "ip_address": "string",
  "user_agent": "string",
  "timestamp": "ISO 8601"
}
```

#### Response
```json
{
  "login_attempt_id": "UUID",
  "status": "accepted",
  "processing_url": "/api/v1/login-attempts/{id}"
}
```

#### Alternative Flows
- **AF-01:** Invalid payload → HTTP 400 Bad Request
- **AF-02:** Unauthorized source → HTTP 401 Unauthorized
- **AF-03:** Duplicate event_id → HTTP 409 Conflict (return existing ID)

---

### 3.2 UC-DE-02: Build Features

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-02 |
| **Tên** | Build Features |
| **Actor chính** | Hệ thống (automatic) |
| **Mô tả ngắn** | Tạo 6 ML features từ login event |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. Triggered bởi UC-DE-01
2. Extract hour_of_day từ timestamp
3. Query fail_count_24h từ login_attempts
4. Calculate ip_change_rate_7d
5. Check new_device từ user_agent history
6. Calculate average_login_interval_seconds
7. Calculate deviation_score
8. Lưu features vào risk_assessment record
```

#### Features Output
| Feature | Type | Source |
|---------|------|--------|
| `hour_of_day` | Integer | timestamp |
| `fail_count_24h` | Integer | Database query |
| `ip_change_rate_7d` | Float | Historical IP analysis |
| `new_device` | Boolean | User agent comparison |
| `avg_login_interval_seconds` | Integer | Historical timestamps |
| `deviation_score` | Float | Baseline comparison |

---

### 3.3 UC-DE-03: Gọi ML Service

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-03 |
| **Tên** | Gọi ML Service |
| **Actor chính** | Hệ thống (automatic) |
| **Actor phụ** | ML Service |
| **Mô tả ngắn** | Gửi ML request và nhận anomaly score |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. Nhận features từ UC-DE-02
2. Validate features schema
3. POST /internal/score với request_id
4. Đợi response (timeout: 5s)
5. Parse normalized_anomaly_score
6. Lưu vào risk_assessment
```

#### Request
```json
{
  "request_id": "UUID",
  "features": {
    "hour_of_day": 14,
    "fail_count_24h": 2,
    "ip_change_rate_7d": 0.15,
    "new_device": true,
    "average_login_interval_seconds": 28800,
    "deviation_score": 0.3
  }
}
```

#### Response
```json
{
  "request_id": "UUID",
  "normalized_anomaly_score": 0.72,
  "is_anomaly": true,
  "model_version": "v1.0-isolation-forest",
  "reason_codes": ["unusual_time", "new_device"],
  "model_status": "ready"
}
```

#### Alternative Flows
- **AF-01:** ML timeout → Use fallback (rule-only scoring)
- **AF-02:** ML error → Log error, continue with default ML score = 0.5

---

### 3.4 UC-DE-04: Evaluate Rules

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-04 |
| **Tên** | Evaluate Rules |
| **Actor chính** | Hệ thống (automatic) |
| **Mô tả ngắn** | Đánh giá active policy rules |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. Lấy active policy
2. Parse rules từ policy.rules (JSONB)
3. Với mỗi rule:
   a. Evaluate condition với features
   b. Nếu triggered → add score × weight
4. Tính tổng rule_score
5. Lưu vào risk_assessment
6. Log detection_log entry
```

#### Rule Example
```json
{
  "id": "R001",
  "name": "Unusual Hour Login",
  "condition": "hour_of_day >= 23 OR hour_of_day <= 5",
  "weight": 0.3,
  "score": 0.8
}
```

#### Rule Score Formula
```
rule_score = Σ (triggered_rule.score × rule.weight)
```

---

### 3.5 UC-DE-05: Calculate Risk Score

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-05 |
| **Tên** | Calculate Risk Score |
| **Actor chính** | Hệ thống (automatic) |
| **Mô tả ngắn** | Tính combined risk score |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. Lấy rule_score từ UC-DE-04
2. Lấy ml_score từ UC-DE-03
3. Lấy weights từ policy config
4. Tính: risk_score = w_rule × rule_score + w_ml × ml_score
5. Xác định risk_level từ thresholds
6. Lưu vào risk_assessment
```

#### Formula
```
Risk_Score = 0.4 × Rule_Score + 0.6 × ML_Score
```

#### Risk Classification
| Score Range | Risk Level | Action |
|-------------|------------|--------|
| < 0.25 | LOW | ALLOW |
| 0.25 - 0.50 | MEDIUM | ALLOW_LOG |
| 0.50 - 0.75 | HIGH | REQUIRE_MFA |
| > 0.75 | CRITICAL | BLOCK_ALERT |

---

### 3.6 UC-DE-06: Tạo Alert

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-06 |
| **Tên** | Tạo Alert |
| **Actor chính** | Hệ thống (automatic) |
| **Mô tả ngắn** | Tạo alert khi risk level cao |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. Kiểm tra risk_level từ UC-DE-05
2. Nếu HIGH hoặc CRITICAL:
   a. Tạo Alert record
   b. Assign cho SOC analyst (round-robin)
   c. Tạo timeline entry (created)
   d. Gửi notification (nếu configured)
3. Nếu LOW hoặc MEDIUM:
   a. Chỉ log, không tạo alert
```

#### Alert Data
```json
{
  "login_attempt_id": "UUID",
  "policy_id": "UUID",
  "status": "open",
  "risk_level": "HIGH",
  "detection_reason": "ML: unusual_time, new_device",
  "detection_scores": {
    "rule_score": 0.45,
    "ml_score": 0.72,
    "combined": 0.62
  },
  "assigned_to_id": "UUID"
}
```

---

### 3.7 UC-DE-07: Gửi Action về Core

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-07 |
| **Tên** | Gửi Action về Core |
| **Actor chính** | Hệ thống (automatic) |
| **Actor phụ** | Core App |
| **Mô tả ngắn** | Gửi yêu cầu security action |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. Dựa trên risk_level từ UC-DE-05:
   - HIGH → REQUIRE_MFA
   - CRITICAL → BLOCK + Alert (UC-DE-06)
2. Build action payload
3. POST /internal/actions to Core App
4. Log action sent
```

#### Action Payload
```json
{
  "action": "REQUIRE_MFA",
  "target": {
    "type": "user_id",
    "value": "UUID"
  },
  "reason": "Risk score exceeded threshold",
  "risk_level": "high",
  "login_attempt_id": "UUID"
}
```

---

### 3.8 UC-DE-08: Xem SOC Dashboard

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-08 |
| **Tên** | Xem SOC Dashboard |
| **Actor chính** | SOC Analyst |
| **Mô tả ngắn** | Xem tổng quan alerts và metrics |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. SOC Analyst truy cập /api/v1/dashboard
2. System lấy:
   - Alerts count by status
   - Alerts count by risk_level
   - Recent alerts (last 24h)
   - Top violation reasons
   - Analyst workload stats
3. Trả về dashboard data
```

#### Dashboard Response
```json
{
  "summary": {
    "total_open": 45,
    "total_acknowledged": 12,
    "total_resolved_today": 8,
    "critical_count": 3
  },
  "by_risk_level": {
    "HIGH": 25,
    "CRITICAL": 3
  },
  "by_status": {
    "open": 30,
    "acknowledged": 12,
    "resolved": 8
  },
  "recent_alerts": [...],
  "top_reasons": [...]
}
```

---

### 3.9 UC-DE-09: Tiếp nhận Alert

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-09 |
| **Tên** | Tiếp nhận Alert |
| **Actor chính** | SOC Analyst |
| **Mô tả ngắn** | SOC analyst tiếp nhận alert để điều tra |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. SOC Analyst chọn alert
2. System kiểm tra quyền (assigned_to hoặc is_manager)
3. Update alert status → acknowledged
4. Ghi timeline entry
5. Trả về alert details
```

#### Alternative Flows
- **AF-01:** Alert đã assigned cho người khác → HTTP 409 Conflict
- **AF-02:** SOC Analyst không có quyền → HTTP 403 Forbidden

---

### 3.10 UC-DE-10: Điều tra Alert

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-10 |
| **Tên** | Điều tra Alert |
| **Actor chính** | SOC Analyst |
| **Mô tả ngắn** | Xem chi tiết alert và login attempt |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. SOC Analyst chọn alert đã acknowledged
2. System trả về:
   - Alert details
   - Login attempt info
   - Risk assessment (rule + ML scores)
   - Detection logs
   - Timeline
3. SOC Analyst review thông tin
```

---

### 3.11 UC-DE-11: Xem Evidence

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-11 |
| **Tên** | Xem Evidence |
| **Actor chính** | SOC Analyst |
| **Mô tả ngắn** | Xem chi tiết rule/ML evidence |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. SOC Analyst yêu cầu xem evidence
2. System trả về:
   - Triggered rules với scores
   - ML model response
   - Features used
   - Historical comparison data
```

#### Evidence Response
```json
{
  "login_attempt_id": "UUID",
  "risk_assessment": {
    "rule_score": 0.45,
    "ml_score": 0.72,
    "combined": 0.62
  },
  "rule_evidence": [
    {
      "rule_id": "R001",
      "rule_name": "Unusual Hour Login",
      "triggered": true,
      "condition": "hour_of_day >= 23",
      "actual_value": "3",
      "score_contribution": 0.24
    }
  ],
  "ml_evidence": {
    "model_version": "v1.0-isolation-forest",
    "normalized_score": 0.72,
    "reason_codes": ["unusual_time", "new_device"],
    "features": {...}
  }
}
```

---

### 3.12 UC-DE-12: Phân loại Alert

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-12 |
| **Tên** | Phân loại Alert |
| **Actor chính** | SOC Analyst |
| **Mô tả ngắn** | Phân loại alert resolution |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. SOC Analyst hoàn thành điều tra
2. Chọn resolution type:
   - RESOLVED: Threat là thật
   - FALSE_POSITIVE: Không phải threat
   - ESCALATED: Cần Security Manager review
3. Nhập notes (bắt buộc)
4. System update alert status
5. Ghi timeline entry
6. Nếu ESCALATED → notify Security Manager
```

#### Resolution Types
| Type | Mô tả |
|------|--------|
| `RESOLVED` | Threat confirmed, action taken |
| `FALSE_POSITIVE` | Legitimate login flagged incorrectly |
| `ESCALATED` | Need higher authority decision |

---

### 3.13 UC-DE-13: Yêu cầu Action

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-13 |
| **Tên** | Yêu cầu Action |
| **Actor chính** | SOC Analyst |
| **Actor phụ** | Core App |
| **Mô tả ngắn** | Request security action on user/account |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. SOC Analyst quyết định action cần thiết
2. Chọn action type
3. Nhập reason
4. System gửi action request đến Core App
5. Ghi timeline entry
6. SOC Analyst notify khi completed
```

#### Available Actions
| Action | Target | Mô tả |
|--------|--------|--------|
| `LOCK_USER` | user_id | Khóa tài khoản |
| `UNLOCK_USER` | user_id | Mở khóa tài khoản |
| `REVOKE_SESSIONS` | user_id | Thu hồi tất cả sessions |
| `RESET_MFA` | user_id | Reset MFA setup |
| `BLOCK_IP` | ip_address | Thêm vào block list |

---

### 3.14 UC-DE-14: Tra cứu Login History

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-14 |
| **Tên** | Tra cứu Login History |
| **Actor chính** | SOC Analyst |
| **Mô tả ngắn** | Tìm kiếm login attempts |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow
```
1. SOC Analyst nhập search criteria:
   - user_id / username
   - date range
   - ip_address
   - outcome (success/failed)
   - risk_level
2. System query login_attempts
3. Trả về paginated results
```

#### Query Parameters
| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | Filter by user |
| `username` | string | Filter by username |
| `from_date` | ISO 8601 | Start date |
| `to_date` | ISO 8601 | End date |
| `ip_address` | string | Filter by IP |
| `outcome` | string | success/failed |
| `risk_level` | string | LOW/MEDIUM/HIGH/CRITICAL |
| `page` | integer | Page number |
| `limit` | integer | Items per page |

---

### 3.15 UC-DE-15: Quản lý Policy

| Thuộc tính | Mô tả |
|------------|--------|
| **ID** | UC-DE-15 |
| **Tên** | Quản lý Policy |
| **Actor chính** | Security Admin |
| **Mô tả ngắn** | CRUD policies và activate/deactivate |
| **Ưu tiên** | Bắt buộc |

#### Basic Flow - Create
```
1. Security Admin tạo policy mới
2. Nhập version, name, rules, config
3. System validate JSONB structure
4. Lưu với is_active = false
5. Return policy ID
```

#### Basic Flow - Activate
```
1. Security Admin chọn policy
2. System deactivate all other policies
3. Set is_active = true
4. Ghi audit log
```

#### Policy Structure
```json
{
  "version": "v1.0",
  "name": "Default Detection Policy",
  "rules": [
    {
      "id": "R001",
      "name": "Unusual Hour",
      "condition": "hour_of_day >= 23 OR hour_of_day <= 5",
      "weight": 0.3,
      "score": 0.8
    }
  ],
  "config": {
    "weights": {
      "rule": 0.4,
      "ml": 0.6
    },
    "thresholds": {
      "low": 0.25,
      "medium": 0.50,
      "high": 0.75
    }
  }
}
```

---

## 4. USE CASE DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        USE CASE DIAGRAM - DETECTION ENGINE                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│     ┌─────────────┐                                                         │
│     │  Core App   │                                                         │
│     └──────┬──────┘                                                         │
│            │                                                                 │
│            │ 1. UC-DE-01: Nhận LoginEvent                                   │
│            │ 2. UC-DE-07: Gửi Action về Core                                │
│            ▼                                                                 │
│     ┌─────────────────────────────────────┐                                │
│     │         DETECTION ENGINE             │                                │
│     ├─────────────────────────────────────┤                                │
│     │                                     │                                │
│     │  ┌─────────────────────────────┐   │                                │
│     │  │   Automatic Processing     │   │                                │
│     │  │                             │   │                                │
│     │  │  UC-DE-02: Build Features   │   │                                │
│     │  │  UC-DE-03: Gọi ML Service   │   │                                │
│     │  │  UC-DE-04: Evaluate Rules   │   │                                │
│     │  │  UC-DE-05: Calculate Risk  │   │                                │
│     │  │  UC-DE-06: Tạo Alert        │   │                                │
│     │  │  UC-DE-15: Quản lý Policy   │   │                                │
│     │  └─────────────────────────────┘   │                                │
│     │                                     │                                │
│     │  ┌─────────────────────────────┐   │                                │
│     │  │   SOC Analyst               │   │                                │
│     │  │                             │   │                                │
│     │  │  UC-DE-08: Xem Dashboard    │   │                                │
│     │  │  UC-DE-09: Tiếp nhận Alert  │   │                                │
│     │  │  UC-DE-10: Điều tra Alert   │   │                                │
│     │  │  UC-DE-11: Xem Evidence     │   │                                │
│     │  │  UC-DE-12: Phân loại Alert  │   │                                │
│     │  │  UC-DE-13: Yêu cầu Action   │   │                                │
│     │  │  UC-DE-14: Tra cứu History  │   │                                │
│     │  └─────────────────────────────┘   │                                │
│     │                                     │                                │
│     └──────────────────────┬──────────────┘                                │
│                            │                                                │
│                            │ UC-DE-07: Action Request                        │
│                            ▼                                                │
│                     ┌─────────────┐                                         │
│                     │  Core App   │                                         │
│                     └─────────────┘                                         │
│                                                                             │
│     ┌─────────────┐                                                         │
│     │ ML Service  │◄────────────────────────────────── UC-DE-03: ML Call   │
│     └─────────────┘                                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. SEQUENCE DIAGRAM - AUTOMATIC PROCESSING

```
┌────────────┬────────────────┬────────────────┬────────────────┬────────────┐
│  Core App  │Detection Engine│   ML Service   │Detection Engine│            │
└─────┬──────┴───────┬────────┴───────┬────────┴───────┬────────┴────┘
      │              │                │                │
      │ LoginEvent   │                │                │
      │─────────────►│                │                │
      │              │                │                │
      │              │ 1. Save        │                │
      │              │    LoginAttempt                │
      │              │◄───────►      │                │
      │              │                │                │
      │              │ 2. Build       │                │
      │              │    Features    │                │
      │              │                │                │
      │              │ ML Request    │                │
      │              │───────────────►│                │
      │              │                │                │
      │              │ ML Response   │                │
      │              │◄──────────────│                │
      │              │                │                │
      │              │ 3. Evaluate   │                │
      │              │    Rules       │                │
      │              │                │                │
      │              │ 4. Calculate  │                │
      │              │    Risk Score │                │
      │              │                │                │
      │              │ 5. Create      │                │
      │              │    Alert?      │                │
      │              │                │                │
      │ Action       │                │                │
      │◄─────────────│                │                │
      │              │                │                │
```

---

**Document Version:** 3.3  
**Last Updated:** 2026-09-13  
**Status:** ✅ Design Complete
