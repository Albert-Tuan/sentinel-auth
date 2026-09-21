# BẢNG YÊU CẦU CHỨC NĂNG NGHIỆP VỤ - DETECTION ENGINE

> **Phiên bản:** 3.3  
> **Ngày:** 2026-09-13  
> **Trạng thái:** Hoàn thành thiết kế

---

## 1. MỤC ĐÍCH

Tài liệu này mô tả các yêu cầu chức năng nghiệp vụ của **Detection Engine** - thành phần xử lý phát hiện bất thường trong hệ thống Sentinel Auth.

---

## 2. TỔNG QUAN CHỨC NĂNG

| Mã | Nhóm chức năng | Số lượng YC |
|----|----------------|-------------|
| DE-01xx | Tiếp nhận sự kiện | 2 |
| DE-02xx | Feature Engineering | 2 |
| DE-03xx | ML Integration | 2 |
| DE-04xx | Rule Engine | 2 |
| DE-05xx | Risk Scoring | 2 |
| DE-06xx | Alert Management | 3 |
| DE-07xx | SOC Workflow | 3 |

---

## 3. YÊU CẦU CHỨC NĂNG CHI TIẾT

### 3.1 Nhóm tiếp nhận sự kiện (DE-01xx)

#### DE-01: Nhận LoginEvent

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-01 |
| **Tên** | Nhận LoginEvent |
| **Mô tả** | Tiếp nhận event đăng nhập từ Core App qua HTTP POST |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |
| **Nguồn yêu cầu** | Core App |

**Input:**
```json
{
  "event_id": "UUID",
  "user_id": "UUID | null",
  "username_attempted": "string",
  "outcome": "success | failed",
  "mfa_used": "boolean",
  "ip_address": "string (IP format)",
  "user_agent": "string",
  "timestamp": "ISO 8601"
}
```

**Xử lý:**
1. Validate schema của event
2. Lưu vào bảng `login_attempts`
3. Trigger feature building pipeline
4. Trả về acknowledgment

**Output:**
- HTTP 202 Accepted
- Login attempt ID để track

---

#### DE-02: Xác thực event source

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-02 |
| **Tên** | Xác thực event source |
| **Mô tả** | Chỉ chấp nhận events từ Core App (internal service) |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Xử lý:**
1. Kiểm tra API key/secret của Core App
2. Validate request signature
3. Rate limit per source

---

### 3.2 Nhóm Feature Engineering (DE-02xx)

#### DE-03: Feature Building

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-03 |
| **Tên** | Feature Building |
| **Mô tả** | Tạo 6 features từ login event để phục vụ ML inference |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Features được tạo:**

| Feature | Kiểu | Range | Nguồn |
|---------|------|-------|-------|
| `hour_of_day` | Integer | 0-23 | timestamp |
| `fail_count_24h` | Integer | ≥0 | Tra cứu login_attempts |
| `ip_change_rate_7d` | Float | 0-1 | Tra cứu history |
| `new_device` | Boolean | true/false | So sánh user_agent |
| `average_login_interval_seconds` | Integer | ≥0 | Tính từ history |
| `deviation_score` | Float | 0-1 | So sánh baseline |

---

#### DE-04: Feature Validation

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-04 |
| **Tên** | Feature Validation |
| **Mô tả** | Kiểm tra features trước khi gửi ML |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Validation rules:**
1. Tất cả features phải có mặt
2. Type phải đúng
3. Range phải trong giới hạn
4. Missing features → fallback default values

---

### 3.3 Nhóm ML Integration (DE-03xx)

#### DE-05: Gọi ML Service

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-05 |
| **Tên** | Gọi ML Service |
| **Mô tả** | Gửi ML request lên ML Service để inference |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |
| **Timeout** | 5 giây |

**Request:**
```json
{
  "request_id": "UUID (echo)",
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

**Response:**
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

---

#### DE-06: ML Fallback

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-06 |
| **Tên** | ML Fallback |
| **Mô tả** | Xử lý graceful degradation khi ML Service unavailable |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Fallback behavior:**
1. ML timeout → sử dụng rule_score với weight cao hơn
2. ML error → log error, proceed với rule-only scoring
3. ML degraded → warn nhưng vẫn sử dụng
4. Notification đến monitoring system

---

### 3.4 Nhóm Rule Engine (DE-04xx)

#### DE-07: Rule Evaluation

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-07 |
| **Tên** | Rule Evaluation |
| **Mô tả** | Đánh giá rules với features để tính rule_score |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Rule structure (trong policies):**
```json
{
  "rules": [
    {
      "id": "R001",
      "name": "Unusual Hour Login",
      "condition": "hour_of_day >= 23 OR hour_of_day <= 5",
      "weight": 0.3,
      "score": 0.8
    },
    {
      "id": "R002", 
      "name": "Multiple Failures",
      "condition": "fail_count_24h >= 3",
      "weight": 0.4,
      "score": 0.9
    },
    {
      "id": "R003",
      "name": "New Device",
      "condition": "new_device == true",
      "weight": 0.2,
      "score": 0.5
    }
  ]
}
```

**Rule Score Calculation:**
```
rule_score = Sum(triggered_rule.score × rule.weight)
```

---

#### DE-08: Active Policy Selection

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-08 |
| **Tên** | Active Policy Selection |
| **Mô tả** | Chọn policy đang active để đánh giá |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Selection logic:**
1. Lấy policy có `is_active = true` và version mới nhất
2. Nếu không có active policy → sử dụng default policy
3. Log policy selection decision

---

### 3.5 Nhóm Risk Scoring (DE-05xx)

#### DE-09: Risk Score Calculation

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-09 |
| **Tên** | Risk Score Calculation |
| **Mô tả** | Tính combined risk score từ rule và ML scores |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Formula:**
```
Risk_Score = w_rule × Rule_Score + w_ml × ML_Score

Trong đó:
- w_rule = 0.4 (configurable)
- w_ml = 0.6 (configurable)
- Rule_Score = Sum(triggered_rule.score × rule.weight)
- ML_Score = normalized_anomaly_score
```

**Config (trong policy):**
```json
{
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

#### DE-10: Risk Level Classification

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-10 |
| **Tên** | Risk Level Classification |
| **Mô tả** | Phân loại mức độ rủi ro dựa trên risk score |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Classification:**

| Risk Level | Threshold | Action | Description |
|------------|-----------|--------|-------------|
| LOW | < 0.25 | ALLOW | Đăng nhập bình thường |
| MEDIUM | 0.25 - 0.50 | ALLOW_LOG | Cho phép, ghi log cảnh báo |
| HIGH | 0.50 - 0.75 | REQUIRE_MFA | Yêu cầu xác thực MFA |
| CRITICAL | > 0.75 | BLOCK_ALERT | Chặn và tạo alert |

---

### 3.6 Nhóm Alert Management (DE-06xx)

#### DE-11: Alert Creation

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-11 |
| **Tên** | Alert Creation |
| **Mô tả** | Tạo alert khi risk_level = HIGH hoặc CRITICAL |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Alert data:**
```json
{
  "login_attempt_id": "UUID",
  "policy_id": "UUID",
  "risk_level": "HIGH | CRITICAL",
  "detection_reason": "Rule: Multiple Failures, ML: unusual_time",
  "detection_scores": {
    "rule_score": 0.45,
    "ml_score": 0.72,
    "combined": 0.72
  },
  "status": "open"
}
```

---

#### DE-12: Alert Assignment

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-12 |
| **Tên** | Alert Assignment |
| **Mô tả** | Tự động assign alert cho SOC analyst |
| **Đối tượng** | Hệ thống, SOC Analyst |
| **Ưu tiên** | Bắt buộc |

**Assignment logic:**
1. Round-robin cho analysts đang active
2. Respect max_alerts limit
3. CRITICAL alerts → ưu tiên cao hơn
4. Manual reassignment bởi Security Admin

---

#### DE-13: Alert Actions

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-13 |
| **Tên** | Alert Actions |
| **Mô tả** | Các actions có thể thực hiện trên alert |
| **Đối tượng** | SOC Analyst |
| **Ưu tiên** | Bắt buộc |

**Available actions:**
- `ACK`: Tiếp nhận alert
- `ESCALATE`: Eskalate lên Security Manager
- `INVESTIGATE`: Bắt đầu điều tra
- `RESOLVE`: Đóng alert (có resolution)
- `FALSE_POSITIVE`: Đánh dấu false positive

---

### 3.7 Nhóm SOC Workflow (DE-07xx)

#### DE-14: SOC Dashboard Data

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-14 |
| **Tên** | SOC Dashboard Data |
| **Mô tả** | Cung cấp data cho SOC Dashboard |
| **Đối tượng** | SOC Analyst |
| **Ưu tiên** | Bắt buộc |

**Dashboard metrics:**
- Tổng số alerts theo status
- Alerts theo risk level
- Alerts theo thời gian (chart)
- Top violation reasons
- SOC analyst workload

---

#### DE-15: Alert Timeline

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-15 |
| **Tên** | Alert Timeline |
| **Mô tả** | Ghi lại toàn bộ actions trên alert |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Timeline events:**
```json
{
  "alert_id": "UUID",
  "event_type": "created | acknowledged | escalated | resolved",
  "actor_id": "UUID",
  "actor_type": "user | system",
  "old_value": "string",
  "new_value": "string",
  "comment": "string",
  "created_at": "TIMESTAMPTZ"
}
```

---

#### DE-16: Action Request to Core

| Thuộc tính | Giá trị |
|------------|---------|
| **Mã YC** | DE-16 |
| **Tên** | Action Request to Core |
| **Mô tả** | Gửi yêu cầu action về Core App |
| **Đối tượng** | Hệ thống |
| **Ưu tiên** | Bắt buộc |

**Action types:**

| Action | Trigger | Target |
|--------|---------|--------|
| `REQUIRE_MFA` | HIGH | user_id |
| `REVOKE_SESSIONS` | CRITICAL | user_id |
| `LOCK_USER` | CRITICAL | user_id |
| `RATE_LIMIT_IP` | HIGH | ip_address |

---

## 4. BẢNG TỔNG HỢP

| Mã YC | Tên chức năng | Nhóm | Ưu tiên |
|-------|--------------|------|---------|
| DE-01 | Nhận LoginEvent | Tiếp nhận sự kiện | Bắt buộc |
| DE-02 | Xác thực event source | Tiếp nhận sự kiện | Bắt buộc |
| DE-03 | Feature Building | Feature Engineering | Bắt buộc |
| DE-04 | Feature Validation | Feature Engineering | Bắt buộc |
| DE-05 | Gọi ML Service | ML Integration | Bắt buộc |
| DE-06 | ML Fallback | ML Integration | Bắt buộc |
| DE-07 | Rule Evaluation | Rule Engine | Bắt buộc |
| DE-08 | Active Policy Selection | Rule Engine | Bắt buộc |
| DE-09 | Risk Score Calculation | Risk Scoring | Bắt buộc |
| DE-10 | Risk Level Classification | Risk Scoring | Bắt buộc |
| DE-11 | Alert Creation | Alert Management | Bắt buộc |
| DE-12 | Alert Assignment | Alert Management | Bắt buộc |
| DE-13 | Alert Actions | Alert Management | Bắt buộc |
| DE-14 | SOC Dashboard Data | SOC Workflow | Bắt buộc |
| DE-15 | Alert Timeline | SOC Workflow | Bắt buộc |
| DE-16 | Action Request to Core | SOC Workflow | Bắt buộc |

---

## 5. NGHIỆP VỤ LIÊN QUAN

### 5.1 Cross-Service Flow

```
[Core App]
    │ LoginEvent
    ▼
[Detection Engine]
    │
    ├─► [Feature Building]
    │        │
    │        ▼
    │   [ML Service]
    │        │
    │◄───────┘ ML Response
    │
    ├─► [Rule Engine]
    │        │
    │◄───────┘ Rule Scores
    │
    ├─► [Risk Scoring]
    │        │
    │◄───────┘ Risk Level
    │
    ├─► [Alert Creation] (if HIGH/CRITICAL)
    │        │
    │◄───────┘ Alert ID
    │
    └─► [Action to Core]
             REQUIRE_MFA / LOCK_USER / etc.
```

---

**Document Version:** 3.3  
**Last Updated:** 2026-09-13  
**Status:** ✅ Design Complete
