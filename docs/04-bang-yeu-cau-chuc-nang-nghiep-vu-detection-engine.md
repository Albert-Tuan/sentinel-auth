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

**Endpoint:** `POST /api/v1/internal/ml/score`
**Header:** `X-Internal-Secret: <shared_secret>`
**Timeout:** 5 giây

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

> `normalized_anomaly_score` trong response được lưu vào cột `ml_score` của
> bảng `risk_assessments`. Tên `anomaly_score` **không** tồn tại trong database —
> xem `docs/DECISIONS-DETECTION-v3.3.md` mục 4.1.

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

**Fallback behavior** (`ml_status` lưu trong `risk_assessments`):

| Tình huống | `ml_status` | `ml_score` | `combined_score` |
|-----------|-------------|-----------|------------------|
| ML trả kết quả bình thường | `success` | giá trị 0–1 | `w_rule × rule + w_ml × ml` |
| ML timeout (> 5 giây) | `unavailable` | `NULL` | `rule_score` |
| ML trả lỗi 4xx/5xx | `error` | `NULL` | `rule_score` |
| ML trả payload không hợp lệ | `error` | `NULL` | `rule_score` |

Quy tắc xử lý:
1. **Không** chia lại trọng số — `combined_score = rule_score` nguyên vẹn
2. Ghi cảnh báo vào `detection_logs` với `stage = 'ml_call'`
3. Tiếp tục xử lý, **không** trả lỗi cho Core App
4. Ghi notification đến monitoring system

> **Vì sao không chia lại trọng số?** Nếu chia lại (`combined = rule_score`), tổng điểm
> sẽ bằng `0.7583` — **cao hơn** so với khi có ML (`0.7353`). Đây là hành vi **có chủ
> đích**: không có tín hiệu ML thì hệ thống thận trọng hơn, chứ không phải lạc quan hơn.

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

**Cấu trúc quy tắc (trong `policies.rules` — JSONB):**

Mỗi quy tắc có **7 trường bắt buộc**. Nguồn sự thật:
`docs/DECISIONS-DETECTION-v3.3.md` mục 1.

```json
{
  "rules": [
    {
      "name": "unusual_hour",
      "field": "hour_of_day",
      "operator": "not_between",
      "value": [7, 22],
      "weight": 0.30,
      "score": 0.80,
      "enabled": true,
      "description": "Login outside 07:00-22:59 local time"
    },
    {
      "name": "multiple_failures",
      "field": "fail_count_24h",
      "operator": ">=",
      "value": 3,
      "weight": 0.40,
      "score": 0.90,
      "enabled": true,
      "description": "3 or more failed attempts in the last 24h"
    },
    {
      "name": "new_device",
      "field": "new_device",
      "operator": "==",
      "value": true,
      "weight": 0.20,
      "score": 0.50,
      "enabled": true,
      "description": "Login from a device not seen before"
    },
    {
      "name": "high_deviation",
      "field": "deviation_score",
      "operator": ">=",
      "value": 0.70,
      "weight": 0.30,
      "score": 0.70,
      "enabled": true,
      "description": "Behaviour deviates strongly from the user baseline"
    }
  ]
}
```

| Trường | Bắt buộc | Ràng buộc | Ý nghĩa |
|--------|----------|-----------|---------|
| `name` | ✓ | duy nhất trong policy | Tên quy tắc hiển thị cho SOC |
| `field` | ✓ | 1 trong 6 đặc trưng | **Tên đặc trưng** được đối chiếu |
| `operator` | ✓ | xem bảng dưới | Phép so sánh |
| `value` | ✓ | phù hợp với `operator` | Giá trị so sánh |
| `weight` | ✓ | `0 ≤ w ≤ 1` | **Độ tin cậy** của quy tắc |
| `score` | ✓ | `0 ≤ s ≤ 1` | **Mức nghiêm trọng** khi rule chạy |
| `enabled` | ✓ | — | Có dùng quy tắc này không |
| `description` | ❌ | — | Giải thích cho người đọc |

**Sáu phép so sánh (`operator`) hỗ trợ:**

| `operator` | Ý nghĩa | `value` | Kiểu áp dụng |
|------------|---------|---------|------------|
| `==` | Bằng | đơn | bool, number, string |
| `!=` | Không bằng | đơn | number, string |
| `>` `>=` `<` `<=` | So sánh số | đơn | number |
| `in` | Thuộc tập hợp | `[v1, v2, ...]` | string, number |
| `between` | Trong khoảng đóng | `[min, max]` | number |
| `not_between` | Ngoài khoảng đóng | `[min, max]` | number |

**Sáu `field` hợp lệ** (đúng bằng 6 đặc trưng của DE-04):

`hour_of_day`, `fail_count_24h`, `ip_change_rate_7d`, `new_device`,
`average_login_interval_seconds`, `deviation_score`

> **Xử lý quy tắc sai cấu hình:** nếu `field` không thuộc danh sách trên, quy tắc bị
> **bỏ qua** (không tính vào mẫu số) và ghi cảnh báo vào `detection_logs` với
> `stage = 'rule_evaluation'`, `reason = 'unknown_feature'`. Hệ thống **không** ném
> exception — một quy tắc sai không được làm hỏng toàn bộ chấm điểm.

**Cách tính Rule Score:**
```
rule_score = min( 1.0,
                  Σ (rule.score × rule.weight)     ← chỉ rule đã chạy
                  ─────────────────────────────────
                  Σ rule.weight                    ← TẤT CẢ rule đã bật
                )
```

> **Lưu ý về việc chia mẫu số:** cột `detection_logs.score_contribution` lưu giá trị
> `(rule.score × rule.weight) / Σ weight`, nên **cộng lại các `score_contribution` sẽ
> ra đúng `rule_score`** — SOC có thể tự kiểm chứng mà không cần biết công thức.
> Mẫu số dùng **tất cả rule đang bật**, kể cả rule không chạy, để việc bật/tắt một
> rule chỉ tác động tới những rule còn lại một cách nhất quán.

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
1. Lấy policy duy nhất có `is_active = true`
2. Nếu **không** có active policy → cho phép đăng nhập (`low` / `allow`), ghi log
   `detection_logs` với `stage = 'scoring'`, `reason = 'no_policy'`
3. Ghi log policy selection decision vào `detection_logs`

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

**Công thức chuẩn** (xem `docs/DECISIONS-DETECTION-v3.3.md` mục 2):

```
Bước 1 - Rule_Score:
  Rule_Score = min( 1.0,
                    Σ (rule.score × rule.weight)      ← chỉ rule đã chạy
                    ─────────────────────────────────
                    Σ rule.weight                     ← TẤT CẢ rule đã bật
                  )
  (không có rule nào bật → Rule_Score = 0.0)

Bước 2 - ML_Score:
  ML_Score = normalized_anomaly_score  (trả về từ ML Service)
  = NULL nếu ML lỗi hoặc timeout > 5 giây

Bước 3 - Combined_Score:
  Nếu ML thành công:
    Combined_Score = w_rule × Rule_Score + w_ml × ML_Score
  Nếu ML thất bại (suy giảm êm):
    Combined_Score = Rule_Score
```

Trong đó:

| Ký hiệu | Ý nghĩa | Mặc định |
|---------|---------|----------|
| `w_rule` | Trọng số điểm quy tắc | `0.4` |
| `w_ml` | Trọng số điểm ML | `0.6` |
| `rule.score` | Mức nghiêm trọng của rule (0–1) | theo từng rule |
| `rule.weight` | Độ tin cậy của rule (0–1) | theo từng rule |

**Vì sao phải chia mẫu số?** Nếu cộng thẳng `Σ (score × weight)`, 5 rule cùng chạy
có thể cho điểm vượt quá `1.0`, phá vỡ công thức `w_rule × Rule_Score + w_ml × ML_Score`
(vốn giả định cả hai vế nằm trong `[0, 1]`). Chia cho tổng trọng số giữ được bất biến này.

**Ví dụ tính tay** (chính sách mặc định `v1.0`, `Σ weight = 1.20`):

```
Đặc trưng: hour_of_day=2, fail_count_24h=5, new_device=true, deviation_score=0.8

  unusual_hour       0.80 × 0.30 = 0.240
  multiple_failures  0.90 × 0.40 = 0.360
  new_device         0.50 × 0.20 = 0.100
  high_deviation     0.70 × 0.30 = 0.210
  ─────────────────────────────────────────
  Tử số   = 0.910
  Mẫu số  = 1.20
  Rule_Score = 0.910 / 1.20 = 0.7583

  ML_Score = 0.72 (thành công)
  Combined = 0.4 × 0.7583 + 0.6 × 0.72 = 0.7353
  → 0.50 ≤ 0.7353 < 0.75  →  HIGH  →  REQUIRE_MFA + tạo alert
```

> **Lưu ý:** khi ML lỗi, `Combined_Score = Rule_Score = 0.7583` → rơi vào mức
> **CRITICAL**. Chính sách nghiêm hơn khi không có tín hiệu ML — đây là hành vi
> **có chủ đích**, không phải lỗi.

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

**Phân loại** (ngưỡng lấy từ `policies.config.thresholds`):

| Risk Level | Điều kiện | `decision` | Action | Tạo alert? | Mô tả |
|------------|----------|------------|--------|-----------|-------|
| `low` | `combined < 0.25` | `allow` | ALLOW | ❌ | Đăng nhập bình thường |
| `medium` | `0.25 ≤ combined < 0.50` | `allow` | ALLOW_LOG | ❌ | Cho phép, ghi log cảnh báo |
| `high` | `0.50 ≤ combined < 0.75` | `challenge` | REQUIRE_MFA | ✅ | Yêu cầu xác thực MFA |
| `critical` | `combined ≥ 0.75` | `block` | BLOCK_ALERT | ✅ | Chặn, thu hồi phiên, khóa tài khoản |

> **Mức cao (HIGH) luôn sinh cảnh báo**, kể cả khi người dùng vẫn được vào sau
> bước MFA. Cảnh báo vẫn được tạo để SOC theo dõi xu hướng tấn công.

**Ràng buộc khi cấu hình `thresholds`:**

| Trường | Ràng buộc |
|--------|-----------|
| `low` | `0 ≤ low ≤ 1` |
| `medium` | `low ≤ medium ≤ 1` |
| `high` | `medium ≤ high ≤ 1` |

Nếu `thresholds` vi phạm (ví dụ `low = 0.8`, `medium = 0.3`):
- **Không** ném exception
- Ghi cảnh báo vào `detection_logs` với `stage = 'scoring'`, `reason = 'invalid_thresholds'`
- **Dùng giá trị mặc định** `0.25 / 0.50 / 0.75` để tiếp tục xử lý

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

**Endpoint:** `POST /api/v1/internal/actions` (Detection Engine → Core App)
**Header:** `X-Internal-Secret: <shared_secret>`

**Action types:**

| Action | Trigger | Target | Tác dụng |
|--------|---------|--------|----------|
| `REQUIRE_MFA` | `high` | `user_id` | Bắt xác thực 2 lớp ở lần đăng nhập kế tiếp |
| `REVOKE_SESSIONS` | `critical` | `user_id` | Thu hồi toàn bộ phiên đang hoạt động |
| `LOCK_USER` | `critical` | `user_id` | Khoá tài khoản + thu hồi phiên |
| `FORCE_LOGOUT` | do SOC yêu cầu | `user_id` | Đăng xuất cưỡng bức |

**Request:**
```json
{
  "action": "LOCK_USER",
  "target_user_id": "UUID",
  "reason": "COMBINE: 0.7812 - rule 0.7583 + high_deviation",
  "alert_id": "UUID",
  "severity": "critical",
  "idempotency_key": "string (optional)"
}
```

> Chính sách `RATE_LIMIT_IP` **không** nằm trong phạm vi v3.3 — rate limiting do
> Core App thực hiện qua `login_attempts.outcome = 'rate_limited'`.

---

## 4. BẢNG TỔNG HỢP

> Nguồn sự thật cho mọi quyết định kỹ thuật: `docs/DECISIONS-DETECTION-v3.3.md`

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
