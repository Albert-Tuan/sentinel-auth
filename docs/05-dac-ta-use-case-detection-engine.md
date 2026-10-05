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
1. Core App gửi POST /api/v1/internal/login-events
   (Header: X-Internal-Secret)
2. Detection Engine kiểm tra secret → 401 nếu sai
3. Kiểm tra event_id đã tồn tại chưa (idempotency)
   - Đã có → trả lại login_attempt_id cũ, HTTP 202
4. Validate payload → 422 nếu sai định dạng
5. Lưu LoginAttempt (status = 'pending')
6. Chạy scoring pipeline (UC-DE-02 → 04 → 03 → 05 → 06)
7. Commit risk_assessments + alerts
8. Nếu risk_level ∈ {high, critical} → gọi POST /api/v1/internal/actions về Core App
9. Trả về HTTP 202 Accepted
```

> **Lưu ý 2026-10-05 — hiện trạng thực tế.** Mã trả `202 Accepted` vì đây là ngữ nghĩa
> REST đúng, **không** phải vì xử lý chạy nền. `process_attempt()` được `await` **ngay
> trong request handler** (`app/detection.py`), và `enforce_action_in_core()` cũng chạy
> trong cùng request đó. Core App vẫn **không cần** chờ kết quả để trả token cho user vì
> đã có cổng `pre-token-check` chặn trước (xem `DECISIONS-DETECTION-v3.3.md` mục 10).
>
> Nếu sau này tách scoring ra worker nền thì câu chữ "bất đồng bộ" mới đúng. Hiện tại
> ghi vậy để không ai hiểu nhầm là có hàng đợi xử lý.

#### Request Schema
```json
{
  "event_id": "UUID",
  "user_id": "UUID | null",
  "username_attempted": "string",
  "outcome": "success | failure | locked | rate_limited | mfa_required | mfa_success | mfa_failure",
  "mfa_used": "boolean",
  "ip_address": "string | null",
  "user_agent": "string | null",
  "timestamp": "ISO 8601",
  "request_id": "UUID | null",
  "features": { } // optional: 6 features nếu Core App đã tính sẵn
}
```

#### Response
```json
{
  "status": "accepted",
  "event_id": "UUID",
  "login_attempt_id": "UUID",
  "processing": "pending"
}
```

#### Alternative Flows
- **AF-01:** Sai định dạng payload → HTTP 422 Unprocessable Entity
- **AF-02:** Thiếu/sai `X-Internal-Secret` → HTTP 401 Unauthorized
- **AF-03:** `event_id` trùng → HTTP 202 với `login_attempt_id` cũ (idempotent,
  **không** tạo bản ghi trùng)
- **AF-04:** Lỗi trong scoring → `login_attempts.status = 'failed'`, ghi
  `detection_logs.reason = 'unhandled_exception'`, HTTP 202 vẫn trả về
  (đăng nhập không bị chặn vì lỗi hệ thống)

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
| `average_login_interval_seconds` | Integer | Historical timestamps |
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
3. POST /api/v1/internal/ml/score với request_id
   (Header: X-Internal-Secret)
4. Đợi response (timeout: 5 giây)
5. Parse normalized_anomaly_score
6. Lưu vào risk_assessments.ml_score
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

| Mã | Tình huống | `ml_status` | `ml_score` | Hành động |
|-----|-----------|-------------|-----------|-----------|
| **AF-01** | ML timeout (> 5s) | `unavailable` | `NULL` | `combined = rule_score` |
| **AF-02** | ML trả 4xx/5xx | `error` | `NULL` | `combined = rule_score` |
| **AF-03** | ML trả payload sai định dạng | `error` | `NULL` | `combined = rule_score` |

> **Không** dùng giá trị ML mặc định `0.5` khi ML lỗi. Giá trị `0.5` là "bình thường
> vừa phải" — nó sẽ **che mất** việc thiếu tín hiệu ML và làm giảm mức rủi ro.
> Đặt `ml_score = NULL` khiến hệ thống dùng `rule_score` nguyên vẹn, thận trọng hơn.

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
1. Lấy active policy (is_active = true)
2. Parse rules từ policies.rules (JSONB)
3. Validate từng rule — rule sai bị BỎ QUA, ghi log, không làm hỏng phần còn lại
4. Tính mẫu số = Σ weight của TẤT CẢ rule đã bật
5. Với mừng rule đã bật:
   a. Đọc features[rule.field]
   b. Áp dụng rule.operator với rule.value
   c. Nếu chạy → tử số += rule.score × rule.weight
6. rule_score = min(1.0, tử số / mẫu số)
7. Ghi mỗi rule vào detection_logs với score_contribution
8. Lưu vào risk_assessments
```

#### Rule Example
```json
{
  "name": "unusual_hour",
  "field": "hour_of_day",
  "operator": "not_between",
  "value": [7, 22],
  "weight": 0.30,
  "score": 0.80,
  "enabled": true,
  "description": "Login outside 07:00-22:59 local time"
}
```

| Trường | Ý nghĩa |
|--------|---------|
| `name` | Tên quy tắc, duy nhất trong policy |
| `field` | Tên đặc trưng — 1 trong 6 đặc trưng của UC-DE-02 |
| `operator` | `==` `!=` `>` `>=` `<` `<=` `in` `between` `not_between` |
| `value` | Giá trị so sánh (`[min,max]` với `between`/`not_between`) |
| `weight` | Độ tin cậy của rule, `0 ≤ weight ≤ 1` |
| `score` | Mức nghiêm trọng khi rule chạy, `0 ≤ score ≤ 1` |
| `enabled` | Có dùng rule này không |

#### Rule Score Formula
```
                   Σ (rule.score × rule.weight)     ← chỉ rule ĐÃ CHẠY
rule_score = min( 1.0, ─────────────────────────────────────── )
                              Σ rule.weight                 ← rule ĐÃ BẬT
```

> **Công thức chuẩn:** `docs/DECISIONS-DETECTION-v3.3.md` mục 2.1.
> Chia mẫu số là bắt buộc — nếu cộng thẳng, `rule_score` có thể vượt `1.0` và phá
> vỡ công thức `0.4 × rule_score + 0.6 × ml_score`.

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
2. Lấy ml_score + ml_status từ UC-DE-03
3. Lấy weights + thresholds từ policy.config
4. Validate config — sai thì log và dùng giá trị mặc định
5. Nếu ml_status = 'success':
      combined = w_rule × rule_score + w_ml × ml_score
   Nếu ml_status = 'unavailable' hoặc 'error':
      combined = rule_score          (suy giảm êm)
6. Xác định risk_level từ thresholds
7. Xác định decision theo DECISION_MATRIX
8. Lưu vào risk_assessments
```

#### Formula
```
Nếu ML thành công:
  Combined_Score = 0.4 × Rule_Score + 0.6 × ML_Score

Nếu ML không thành công:
  Combined_Score = Rule_Score
```

> **Không chia lại trọng số khi ML lỗi.** Nếu chia lại, `combined` sẽ bằng
> `0.7583` — **cao hơn** so với khi có ML (`0.7353`). Hệ thống thận trọng hơn khi
> thiếu tín hiệu ML, đây là chủ ý thiết kế.
> Nguồn: `docs/DECISIONS-DETECTION-v3.3.md` mục 2.3.

#### Risk Classification
| Điều kiện | `risk_level` | `decision` | Action | Tạo alert? |
|----------|--------------|------------|--------|-----------|
| `combined < 0.25` | `low` | `allow` | ALLOW | ❌ |
| `0.25 ≤ combined < 0.50` | `medium` | `allow` | ALLOW_LOG | ❌ |
| `0.50 ≤ combined < 0.75` | `high` | `challenge` | REQUIRE_MFA | ✅ |
| `combined ≥ 0.75` | `critical` | `block` | BLOCK_ALERT | ✅ |

> Ngưỡng lấy từ `policy.config.thresholds`, mặc định `0.25 / 0.50 / 0.75`.
> Biên `0.75` thuộc về **CRITICAL** (không phải HIGH).

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
  "risk_level": "high",
  "detection_reason": "REQUIRE_MFA: combined=0.7353 (rule=0.7583, ml=0.72)",
  "detection_scores": {
    "rule_score": 0.7583,
    "ml_score": 0.72,
    "combined_score": 0.7353,
    "ml_status": "success",
    "ml_model_version": "v1.0-isolation-forest",
    "rule_hits": [
      {
        "rule_name": "multiple_failures",
        "triggered": true,
        "score": 0.90,
        "weight": 0.40,
        "score_contribution": 0.3000
      }
    ],
    "ml_reason_codes": ["high_fail_count", "unusual_time"]
  },
  "assigned_to_id": null
}
```

> `risk_level` lưu bằng **chữ thường** (`high`, `critical`) — khớp với CHECK
> constraint trong schema. `assigned_to_id` để `null` ngay khi tạo; phân phối
> round-robin cho SOC analyst là bước tiếp theo của workflow, không chặn việc
> tạo alert.

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
   - high     → REQUIRE_MFA
   - critical → REVOKE_SESSIONS
2. Build action payload
3. POST /api/v1/internal/actions to Core App
   (Header: X-Internal-Secret)
4. Log vào detection_logs stage = 'action_sent'
```

> Detection Engine **không** tự khoá tài khoản — nó **yêu cầu** Core App thực hiện.
> Core App mới là nơi duy trì `users`, `sessions` nên mới có quyền thay đổi.

> **`critical` KHÔNG gửi `LOCK_USER`** (cập nhật 2026-10-05). Vì `false positive` của ML
> là tình huống thường gặp, khoá tài khoản sẽ chặn oan người dùng hợp lệ tới khi admin
> mở khoá. `REVOKE_SESSIONS` cắt quyền kẻ tấn công nhưng đảo ngược được. Xem
> `DECISIONS-DETECTION-v3.3.md` mục 11.2.

#### Action Payload
```json
{
  "action": "REQUIRE_MFA",
  "target_user_id": "UUID",
  "reason": "COMBINE: 0.7353 - rule 0.7583 + high_deviation",
  "alert_id": "UUID",
  "severity": "high",
  "idempotency_key": "string (optional)"
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
1. SOC Analyst truy cập `GET /api/v1/soc/dashboard`
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
`GET /api/v1/alerts/{id}/evidence`

```json
{
  "alert": {
    "id": "UUID",
    "login_attempt_id": "UUID",
    "status": "open",
    "risk_level": "high",
    "detection_reason": "REQUIRE_MFA: combined=0.7353 (rule=0.7583, ml=0.72)",
    "detection_scores": { }
  },
  "login_attempt": {
    "id": "UUID",
    "event_id": "UUID",
    "timestamp": "2026-10-04T02:15:00Z",
    "outcome": "failure",
    "username_attempted": "alice",
    "ip_address": "203.0.113.42",
    "user_agent": "Mozilla/5.0 ...",
    "mfa_used": false
  },
  "risk_assessment": {
    "rule_score": 0.7583,
    "ml_score": 0.72,
    "combined_score": 0.7353,
    "ml_status": "success",
    "ml_model_version": "v1.0-isolation-forest",
    "ml_reason_codes": ["high_fail_count", "unusual_time"],
    "ml_features_used": {
      "hour_of_day": 2,
      "fail_count_24h": 5,
      "ip_change_rate_7d": 0.40,
      "new_device": true,
      "average_login_interval_seconds": 900,
      "deviation_score": 0.80
    },
    "rule_hits": [
      {
        "rule_name": "unusual_hour",
        "triggered": true,
        "score": 0.80,
        "weight": 0.30,
        "score_contribution": 0.2000
      },
      {
        "rule_name": "multiple_failures",
        "triggered": true,
        "score": 0.90,
        "weight": 0.40,
        "score_contribution": 0.3000
      }
    ],
    "risk_level": "high",
    "decision": "challenge"
  },
  "detection_logs": [
    {
      "stage": "rule_evaluation",
      "rule_name": "unusual_hour",
      "triggered": true,
      "score_contribution": 0.2000,
      "reason": "Login outside 07:00-22:59 local time"
    },
    {
      "stage": "ml_call",
      "stage_detail": "ml_inference",
      "reason": null
    },
    {
      "stage": "scoring",
      "stage_detail": "final_decision",
      "decision": "challenge",
      "reason": "rule=0.7583, ml=0.72, combined=0.7353, level=high, action=REQUIRE_MFA"
    }
  ],
  "timeline": []
}
```

> **SOC có thể tự kiểm chứng:** cộng các `rule_hits[].score_contribution` sẽ ra
> đúng `rule_score` (0.2000 + 0.3000 + các rule khác = 0.7583). Nhờ định nghĩa
> `score_contribution = (score × weight) / Σ weight` trong
> `docs/DECISIONS-DETECTION-v3.3.md` mục 4.5.

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
| Action | Target | Mô tả | Tự động? |
|--------|--------|--------|----------|
| `REQUIRE_MFA` | user_id | Đặt cờ one-time **+ thu hồi mọi phiên đang hoạt động** | ✅ (`high`) |
| `REVOKE_SESSIONS` | user_id | Thu hồi tất cả sessions | ✅ (`critical`) |
| `LOCK_USER` | user_id | Khoá tài khoản + thu hồi phiên | ❌ SOC thủ công |
| `FORCE_LOGOUT` | user_id | Đăng xuất cưỡng bức (giống `REVOKE_SESSIONS`) | ❌ SOC thủ công |

> Đây là **4 action duy nhất** mà `SecurityAction` enum định nghĩa trong code. Các action
> như `UNLOCK_USER`, `RESET_MFA`, `BLOCK_IP` **không tồn tại** — mọi hành động ngoài danh
> sách bị từ chối ở tầng Pydantic (422) trước khi tới handler.
>
> Cả 4 action đều trả `details.sessions_revoked` = số phiên đã thu hồi.

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

`POST /api/v1/policies` — body của request:

```json
{
  "version": "v1.0",
  "name": "Default Detection Policy",
  "description": "Default policy for v1.0 with basic rules",
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
  ],
  "config": {
    "weights": { "rule": 0.4, "ml": 0.6 },
    "thresholds": { "low": 0.25, "medium": 0.50, "high": 0.75 }
  }
}
```

**Ràng buộc khi tạo policy:**

| Đối tượng | Ràng buộc | Mã lỗi |
|-----------|-----------|---------|
| `version` | Khớp `^v\d+(\.\d+)*$`, duy nhất | 409 Conflict |
| `rules[].name` | Duy nhất trong policy | 422 |
| `rules[].field` | 1 trong 6 đặc trưng | 422 |
| `rules[].operator` | 1 trong 9 phép so sánh | 422 |
| `rules[].value` | Đúng kiểu theo `operator` | 422 |
| `rules[].weight`, `score` | `0 ≤ x ≤ 1` | 422 |
| `config.weights` | `rule + ml = 1.0` | 422 |
| `config.thresholds` | `low ≤ medium ≤ high`, trong `[0, 1]` | 422 |

**Khi kích hoạt** (`POST /api/v1/policies/{id}/activate`):
- Validate lại toàn bộ rules + config
- Nếu có vấn đề → HTTP 400 với danh sách `problems`
- Nếu hợp lệ → deactivate policy đang active, activate policy mới
- Trả `{"status": "activated", "version": "v1.0"}`

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
