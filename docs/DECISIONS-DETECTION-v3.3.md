# Quyết định Chuẩn Hoá (Canonical Decisions) — Sentinel Auth v3.3

> **Mục đích của tài liệu này:** đây là **nguồn sự thật duy nhất** (single source of truth) cho các
> quyết định kỹ thuật của Detection Engine. Khi có mâu thuẫn giữa các tài liệu hoặc giữa tài liệu
> và code, **tài liệu này thắng**.
>
> **Ngày chốt:** 2026-10-04
> **Cập nhật:** 2026-10-05 — bổ sung quyết định 8-11 về luồng cấp token có kiểm duyệt
> (risk gate), hành động bảo vệ tự động và khôi phục sau sự cố.
>
> **Trạng thái:** Đã chốt, áp dụng cho toàn bộ tài liệu và code

---

## 0. Tóm tắt 11 quyết định

| # | Vấn đề | Quyết định chuẩn | Lý do |
|---|--------|-------------------|-------|
| 1 | Cấu trúc quy tắc (rule) | `name` + `field` + `operator` + `value` + `weight` + `score` + `enabled` | Vừa so sánh được bằng code, vừa giữ mức độ nghiêm trọng |
| 2 | Ngưỡng mức rủi ro | `low=0.25`, `medium=0.50`, `high=0.75` | Đặc tả v3.3 là bản cuối, khớp TASK_ASSIGNMENT |
| 3 | Gộp nhiều rule | `(Σ score×weight) / (Σ weight của rule đã bật)` → chặn trên 1.0 | Giữ `rule_score` luôn trong [0,1] để phép cộng với `ml_score` có ý nghĩa |
| 4 | Tên cột điểm ML | `ml_score` (bỏ `anomaly_score` trong DB) | Một tên gọi duy nhất, khớp công thức |
| 5 | Tên bảng chính sách | `policies` (đã đúng), nhưng `rules` + `config` gộp trong JSONB | Đã đúng ở v3.3 — giữ nguyên |
| 6 | Đường dẫn API nội bộ | `/api/v1/internal/*` | Đúng như `docs/diagrams/README.md` |
| 7 | Phạm vi code | Sửa `app/*.py` cho khớp v3.3 | Tránh 2 nguồn sự thật |
| **8** | **Thời điểm kiểm duyệt trước khi cấp token** | **Risk gate đồng bộ, chỉ gate `high`/`critical`** | **Mục 10** |
| **9** | **`critical` gửi hành động nào** | **`REVOKE_SESSIONS` (không `LOCK_USER`)** | **Mục 11** |
| **10** | **Cổng kiểm duyệt lỗi thì làm gì** | **Fail open — vẫn cho đăng nhập** | **Mục 10.4** |
| **11** | **`REQUIRE_MFA` có thu hồi phiên sống không** | **Có, thu hồi luôn** | **Mục 11.3** |

---

## 1. Cấu trúc quy tắc (rule) — CHUẨN

### 1.1. Định dạng chuẩn

Quy tắc lưu trong `policies.rules` (JSONB), mỗi phần tử có **7 trường**:

```json
{
    "name": "unusual_hour",
    "field": "hour_of_day",
    "operator": "not_between",
    "value": [7, 22],
    "weight": 0.20,
    "score": 0.80,
    "enabled": true,
    "description": "Login outside usual business hours"
}
```

### 1.2. Bảng mô tả 7 trường

| Trường | Kiểu | Bắt buộc | Ràng buộc | Ý nghĩa |
|--------|------|----------|-----------|---------|
| `name` | string | ✓ | duy nhất trong policy | Tên quy tắc, hiển thị cho SOC |
| `field` | string | ✓ | phải là 1 trong 6 đặc trưng | **Tên đặc trưng** được đối chiếu |
| `operator` | string | ✓ | xem bảng 1.3 | Phép so sánh |
| `value` | number \| bool \| array | ✓ | phù hợp với `field` | Giá trị so sánh |
| `weight` | number | ✓ | `0 ≤ weight ≤ 1` | **Độ tin cậy** của quy tắc trong tổng thể |
| `score` | number | ✓ | `0 ≤ score ≤ 1` | **Mức độ nghiêm trọng** khi quy tắc chạy |
| `enabled` | bool | ✓ | — | Có dùng quy tắc này không |

### 1.3. Sáu phép so sánh (`operator`) được hỗ trợ

| `operator` | Ý nghĩa | Ví dụ `value` | Áp dụng cho kiểu |
|------------|---------|---------------|-----------------|
| `==` | Bằng | `true` | bool, number, string |
| `!=` | Không bằng | `0` | number, string |
| `>` | Lớn hơn | `3` | number |
| `>=` | Lớn hơn hoặc bằng | `23` | number |
| `<` | Nhỏ hơn | `5` | number |
| `<=` | Nhỏ hơn hoặc bằng | `5` | number |
| `in` | Thuộc tập hợp | `["1.2.3.0/24"]` | string, number |
| `between` | Trong khoảng đóng | `[7, 22]` | number |
| `not_between` | Ngoài khoảng đóng | `[7, 22]` | number |

> **Lưu ý triển khai:** `value` với `between` / `not_between` phải là mảng **đúng 2 phần tử** `[min, max]`.
> `in` nhận mảng các giá trị hợp lệ. Các toán tử khác nhận giá trị đơn.

### 1.4. Sáu `field` hợp lệ

`field` **phải** là một trong 6 đặc trưng (features) của UC-DE-02:

| `field` | Kiểu | Khoảng |
|---------|------|--------|
| `hour_of_day` | integer | 0–23 |
| `fail_count_24h` | integer | ≥ 0 |
| `ip_change_rate_7d` | float | 0–1 |
| `new_device` | bool | — |
| `average_login_interval_seconds` | integer | ≥ 0 |
| `deviation_score` | float | 0–1 |

> **Ràng buộc:** nếu `field` không thuộc danh sách này → quy tắc bị **bỏ qua** và ghi cảnh báo
> vào `detection_logs` (stage `rule_evaluation`, `reason = "unknown_feature"`). Hệ thống
> **không** được ném exception — một quy tắc sai cấu hình không được làm hỏng toàn bộ chấm điểm.

### 1.5. Ví dụ chính thức — chính sách mặc định `v1.0`

Đây là nguồn sự thật cho seed data trong `infra/postgres/schema-detection-v3.3.sql`:

```json
[
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
        "description": "Behaviour deviates strongly from the user's own baseline"
    }
]
```

**Tổng `Σ weight` của các rule đã bật = 0.30 + 0.40 + 0.20 + 0.30 = 1.20**

### 1.6. Quy tắc bị loại khỏi mẫu số

`field` không hợp lệ (1.4) → **không tính vào mẫu số**. Nhờ vậy một quy tắc cấu hình sai
không làm thay đổi kết quả tính của các quy tắc hợp lệ.

---

## 2. Công thức gộp điểm — CHUẨN

### 2.1. Bước 1: Điểm quy tắc (`rule_score`)

```
Đóng_góp(rule) = rule.score × rule.weight          (chỉ với rule.enabled = true và rule chạy)

rule_score = min( 1.0,
                  Σ Đóng_góp(rule) / Σ rule.weight      ← mẫu số: các rule ĐÃ BẬT
                )
```

**Nếu không có rule nào được bật** → `rule_score = 0.0`.

### 2.2. Bước 2: Điểm ML (`ml_score`)

`ml_score` = giá trị `normalized_anomaly_score` trả về từ ML Service, đã chuẩn hoá về `[0, 1]`.

| Tình huống | `ml_score` | `ml_status` |
|-----------|------------|-------------|
| ML trả kết quả bình thường | giá trị 0–1 | `success` |
| ML timeout (> 5 giây) | `NULL` | `unavailable` |
| ML trả lỗi (4xx/5xx) | `NULL` | `error` |

### 2.3. Bước 3: Điểm gộp (`combined_score`)

**Trường hợp ML thành công:**
```
combined_score = w_rule × rule_score + w_ml × ml_score
```

**Trường hợp ML không thành công (suy giảm êm):**
```
combined_score = rule_score
```

Lưu ý: khi ML lỗi, `combined_score` **bằng đúng** `rule_score` — trọng số
không được chia lại, vì như vậy tổng điểm sẽ tự nhiên thấp hơn (thận trọng hơn),
đúng tinh thần "không có tín hiệu ML thì đừng phóng đại mức rủi ro".

### 2.4. Bước 4: Xếp mức rủi ro

| Mức | Điều kiện | Giá trị `risk_level` |
|-----|-----------|---------------------|
| Thấp | `combined_score < thresholds.low` | `low` |
| Trung bình | `low ≤ combined_score < thresholds.medium` | `medium` |
| Cao | `medium ≤ combined_score < thresholds.high` | `high` |
| Nghiêm trọng | `combined_score ≥ thresholds.high` | `critical` |

### 2.5. Bước 5: Quyết định hành động

| Mức | Hành động | `decision` | Tạo cảnh báo? |
|-----|-----------|------------|----------------|
| Thấp | `ALLOW` | `allow` | ❌ |
| Trung bình | `ALLOW_LOG` | `allow` | ❌ |
| Cao | `REQUIRE_MFA` | `challenge` | ✅ |
| Nghiêm trọng | `BLOCK_ALERT` | `block` | ✅ |

> **Điểm cần lưu ý:** `risk_level = "high"` **luôn** sinh cảnh báo, kể cả khi
> `decision = "challenge"` (người dùng vẫn được vào nhưng phải qua MFA).
> Đây là chủ ý: cảnh báo cho SOC để họ theo dõi xu hướng.

---

## 3. Ngưỡng mức rủi ro — CHUẨN

### 3.1. Giá trị mặc định

```json
{
    "weights":    { "rule": 0.4, "ml": 0.6 },
    "thresholds": { "low": 0.25, "medium": 0.50, "high": 0.75 }
}
```

### 3.2. Ràng buộc khi kiểm tra

| Trường | Ràng buộc |
|--------|-----------|
| `weights.rule` | `0 ≤ w ≤ 1` |
| `weights.ml` | `0 ≤ w ≤ 1` |
| `weights.rule + weights.ml` | `= 1.0` (nếu cả hai khác 0) |
| `thresholds.low` | `0 ≤ t ≤ 1` |
| `thresholds.medium` | `thresholds.low ≤ t ≤ 1` |
| `thresholds.high` | `thresholds.medium ≤ t ≤ 1` |

### 3.3. Cảnh báo khi cấu hình sai

Nếu `thresholds` vi phạm ràng buộc (ví dụ `low = 0.8`, `medium = 0.3`):
- **Không** ném exception
- Ghi cảnh báo vào `detection_logs` (stage `scoring`, `reason = "invalid_thresholds"`)
- **Dùng giá trị mặc định** (0.25 / 0.50 / 0.75) để tiếp tục xử lý

### 3.4. Ví dụ tính tay chuẩn

```
Đặc trưng:  hour_of_day = 2,  fail_count_24h = 5,  new_device = true,  deviation_score = 0.8

Quy tắc chạy:
  unusual_hour       → score 0.80 × weight 0.30 = 0.240
  multiple_failures  → score 0.90 × weight 0.40 = 0.360
  new_device         → score 0.50 × weight 0.20 = 0.100
  high_deviation     → score 0.70 × weight 0.30 = 0.210
  ────────────────────────────────────────────────────────
  Tổng tử số     = 0.910
  Tổng mẫu số   = 1.20
  rule_score      = 0.910 / 1.20 = 0.758

ML trả về: ml_score = 0.72,  ml_status = success

combined_score = 0.4 × 0.758 + 0.6 × 0.72
              = 0.3032 + 0.432
              = 0.7352  →  làm tròn NUMERIC(5,4) = 0.7352

0.50 ≤ 0.7352 < 0.75  →  mức CAO  →  REQUIRE_MFA + tạo cảnh báo
```

### 3.5. Ví dụ khi ML lỗi

```
Cùng đặc trưng trên, nhưng ML Service timeout.

combined_score = rule_score = 0.758

0.75 ≤ 0.758  →  mức NGHIÊM TRỌNG  →  BLOCK_ALERT + REVOKE_SESSIONS

Ghi chú: chính sách nghiêm ngặt hơn khi không có tín hiệu ML —
đây là hành vi CÓ CHỦ ĐÍCH, không phải bug.

Lưu ý: `BLOCK_ALERT` **không** khoá tài khoản. Hành động gửi đi là
`REVOKE_SESSIONS` (mục 11) — người dùng phải đăng nhập lại và qua MFA.
Xem mục 11.2 để hiểu vì sao không dùng `LOCK_USER`.
```

---

## 4. Tên cột và trường — CHUẨN

### 4.1. Bảng `risk_assessments`

| Cột | Kiểu | Bắt buộc | Ghi chú |
|------|------|----------|---------|
| `rule_score` | `NUMERIC(5,4)` | ✓ | 0–1 |
| `ml_score` | `NUMERIC(5,4)` | NULL | 0–1, NULL khi ML lỗi |
| `combined_score` | `NUMERIC(5,4)` | ✓ | 0–1 |
| `ml_status` | `TEXT` | ✓ | `success` \| `unavailable` \| `error` |
| `ml_model_version` | `TEXT` | NULL | ví dụ `v1.0-isolation-forest` |
| `rule_hits` | `JSONB` | NULL | mảng rule đã chạy |
| `ml_reason_codes` | `JSONB` | NULL | mã lý do từ ML |
| `ml_features_used` | `JSONB` | NULL | 6 đặc trưng đã dùng |
| `risk_level` | `TEXT` | ✓ | `low` \| `medium` \| `high` \| `critical` |
| `decision` | `TEXT` | ✓ | `allow` \| `challenge` \| `block` |

> **Đã bỏ:** cột `anomaly_score`. Trong toàn bộ hệ thống chỉ dùng **`ml_score`**.
> Tên `anomaly_score` chỉ tồn tại ở **biểu phản hồi HTTP của ML Service** vì
> đó là tên trường trong hợp đồng API do nhóm ML Service sở hữu.

### 4.2. Vì sao bỏ `anomaly_score`

| Vấn đề khi giữ cả hai | Giải pháp |
|----------------------|-----------|
| Hai cột chứa cùng một giá trị → dễ ghi sai, dễ đọc nhầm | Một cột `ml_score` duy nhất |
| `rule_score` có 2 nguồn khác nhau trong tài liệu (`ML_Score` vs `anomaly_score`) | Thống nhất theo công thức |
| Schema v2 (`app/models.py`) đã có cả hai | Bỏ theo v3.3 |

### 4.3. Bảng `detection_logs`

| Cột | Kiểu | Ghi chú |
|------|------|---------|
| `login_attempt_id` | `UUID` NULL | `ON DELETE SET NULL` |
| `request_id` | `UUID` NULL | dùng để đối chiếu chéo |
| `stage` | `TEXT` | 4 giá trị, xem 4.4 |
| `stage_detail` | `TEXT` NULL | chi tiết cụ thể |
| `rule_id` | `UUID` NULL | tương lai dùng UUID cho rule |
| `rule_name` | `TEXT` NULL | tên rule (khóa chính hiện tại) |
| `triggered` | `BOOLEAN` NULL | rule có chạy không |
| `score_contribution` | `NUMERIC(5,4)` NULL | **đóng góp sau khi chuẩn hoá** (xem 4.5) |
| `decision` | `TEXT` NULL | `allow` \| `challenge` \| `block` |
| `reason` | `TEXT` NULL | giải thích |
| `details` | `JSONB` NULL | dữ liệu bổ sung |

### 4.4. Bốn giá trị của `stage`

| `stage` | Khi nào ghi | `stage_detail` gợi ý |
|---------|-------------|---------------------|
| `rule_evaluation` | Sau khi chấm xong quy tắc | tên rule |
| `ml_call` | Sau khi gọi ML (kể cả khi lỗi) | `ml_inference` hoặc lý do lỗi |
| `scoring` | Sau khi gộp điểm và xếp mức | `final_decision` |
| `action_sent` | Sau khi quyết định hành động | `alert_created` / `no_alert` / tên action |

### 4.5. Ý nghĩa cột `score_contribution`

Giá trị này là **phần đóng góp thực tế** của rule vào `rule_score` **sau khi đã chia mẫu số**:

```
score_contribution = (rule.score × rule.weight) / Σ weight_của_rule_đã_bật
```

Với ví dụ 3.4:
- `unusual_hour` → `0.240 / 1.20 = 0.2000`
- `multiple_failures` → `0.360 / 1.20 = 0.3000`
- `new_device` → `0.100 / 1.20 = 0.0833`
- `high_deviation` → `0.210 / 1.20 = 0.1750`
- **Tổng = 0.7583 ≈ `rule_score`** ✅

> Nhờ định nghĩa này, SOC có thể **cộng lại** các `score_contribution` để kiểm chứng
> `rule_score` mà không cần biết công thức bên trong.

### 4.6. Bảng `alerts` — `detection_scores`

```json
{
    "rule_score": 0.7580,
    "ml_score": 0.7200,
    "combined_score": 0.7352,
    "rule_hits": [
        { "rule_name": "multiple_failures", "triggered": true, "score_contribution": 0.3000 }
    ],
    "ml_reason_codes": ["high_fail_count", "unusual_time"],
    "ml_status": "success"
}
```

---

## 5. Đường dẫn API nội bộ — CHUẨN

### 5.1. Nguyên tắc

Mọi endpoint dành cho giao tiếp **service-to-service** đều:
- Có tiền tố `/api/v1/internal/`
- Yêu cầu header `X-Internal-Secret`
- Không dùng JWT (vì ML Service không có người dùng con người — dùng `X-Internal-Secret` cho service-to-service)

### 5.2. Bảng đầy đủ

| Method | Đường dẫn | Bên gọi → Bên nhận | Mô tả |
|--------|-----------|---------------------|--------|
| `POST` | `/api/v1/internal/pre-token-check` | Core App → Detection | Chấm điểm **trước khi cấp token** (mục 10) |
| `POST` | `/api/v1/internal/login-events` | Core App → Detection | Nhận sự kiện đăng nhập (UC-DE-01) |
| `GET`  | `/api/v1/internal/login-attempts/{id}` | Core App → Detection | Theo dõi trạng thái xử lý |
| `POST` | `/api/v1/internal/ml/score` | Detection → ML Service | Yêu cầu chấm điểm (UC-DE-03) |
| `GET`  | `/api/v1/internal/ml/health` | Detection → ML Service | Kiểm tra sức khoẻ + phiên bản mô hình |
| `GET`  | `/api/v1/internal/ml/features` | Detection → ML Service | Hợp đồng 6 đặc trưng |
| `POST` | `/api/v1/internal/actions` | Detection → Core App | Yêu cầu hành động bảo vệ (UC-DE-07) |
| `GET`  | `/api/v1/internal/users/{id}` | Detection → Core App | Kiểm tra vai trò người dùng (WF-3) |

> **Hai chiều Core App ↔ Detection:** `/pre-token-check` đi **Core → Detection**
> (cổng kiểm duyệt, đồng bộ), còn `/actions` đi **Detection → Core** (thu hồi
> hậu kỳ, bất đồng bộ về mặt điện toán nhưng chạy trong cùng request chấm điểm).
> Xem mục 10 và mục 11.

> **Lưu ý về `/health`:** mỗi service có **endpoint health riêng** để tránh xung đột
> khi nhiều service cùng mount vào một ứng dụng:
>
> | Service | Health endpoint |
> |---------|----------------|
> | Detection Engine | `GET /api/v1/internal/health` |
> | ML Service | `GET /api/v1/internal/ml/health` |
> | Core App | `GET /health` |

### 5.3. Endpoint cho con người (SOC, Admin)

| Method | Đường dẫn | Mô tả |
|--------|-----------|--------|
| `POST` | `/api/v1/auth/login` | Đăng nhập (trả opaque bearer token) |
| `GET`  | `/api/v1/alerts` | Danh sách cảnh báo (lọc + phân trang) |
| `GET`  | `/api/v1/alerts/{id}` | Chi tiết cảnh báo |
| `GET`  | `/api/v1/alerts/{id}/evidence` | Hồ sơ điều tra đầy đủ (UC-DE-11) |
| `POST` | `/api/v1/alerts/{id}/acknowledge` | Tiếp nhận |
| `POST` | `/api/v1/alerts/{id}/resolve` | Kết luận / báo nhầm |
| `POST` | `/api/v1/alerts/{id}/escalate` | Chuyển cấp |
| `POST` | `/api/v1/alerts/{id}/actions` | Yêu cầu hành động bảo vệ (UC-DE-13) |
| `GET`  | `/api/v1/alerts/{id}/timeline` | Dòng thời gian (DE-15) |
| `POST` | `/api/v1/alerts/{id}/timeline` | Thêm ghi chú |
| `GET`  | `/api/v1/soc/dashboard` | Số liệu bảng điều khiển (UC-DE-14) |
| `GET`  | `/api/v1/login-attempts` | Tra cứu lịch sử đăng nhập (UC-DE-14) |
| `GET`  | `/api/v1/policies` | Danh sách chính sách (UC-DE-15) |
| `POST` | `/api/v1/policies` | Tạo chính sách (UC-DE-15) |
| `POST` | `/api/v1/policies/{id}/activate` | Kích hoạt chính sách (UC-DE-15) |

> **Bốn hành động bảo vệ** dùng chung cho cả hai endpoint `/actions`:
> `REQUIRE_MFA`, `REVOKE_SESSIONS`, `LOCK_USER`, `FORCE_LOGOUT`.
> Xem mục 11 về hành vi của từng hành động.

### 5.4. Mã lỗi chuẩn

| Mã | Khi nào |
|-----|--------|
| `400 Bad Request` | Sai định dạng, sai kiểu, vi phạm ràng buộc nghiệp vụ (VD: chuyển trạng thái không hợp lệ) |
| `401 Unauthorized` | Thiếu/sai `X-Internal-Secret`, hoặc bearer token không hợp lệ hoặc hết hạn |
| `403 Forbidden` | Đã xác thực nhưng không đủ quyền |
| `404 Not Found` | Không tìm thấy tài nguyên |
| `408 Request Timeout` | ML Service vượt quá 5 giây |
| `409 Conflict` | `event_id` trùng, hoặc cảnh báo đã có người xử lý |
| `202 Accepted` | Đã nhận, đang xử lý nền |
| `500 Internal Server Error` | Lỗi không mong muốn |

---

## 6. Cấu trúc bảng `policies` — xác nhận

Giữ nguyên thiết kế v3.3: **một** bảng `policies`, gộp `rules` + `config` trong JSONB.

```sql
CREATE TABLE IF NOT EXISTS policies (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version     TEXT NOT NULL UNIQUE,          -- 'v1.0', 'v2.0'
    name        TEXT,
    description TEXT,
    rules       JSONB NOT NULL DEFAULT '[]',   -- xem mục 1
    config      JSONB NOT NULL DEFAULT '{}',   -- { weights, thresholds }
    is_active   BOOLEAN NOT NULL DEFAULT FALSE,
    created_by  UUID,                          -- tham chiếu users.id ở core-db
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at     TIMESTAMPTZ,
    deactivated_at   TIMESTAMPTZ,

    CONSTRAINT chk_single_active_policy CHECK (...)
);
```

**Quyết định này giữ nguyên vì:**
- Schema SQL v3.3 đã có sẵn và là bản cuối
- ERD v3.3 mô tả khớp
- Tách `weights` / `thresholds` thành cột riêng (như schema v2 trong `app/models.py`)
  là dấu hiệu chưa hoàn thiện thiết kế → đã gộp vào `config`

---

## 7. Bảng "đã bỏ" — những thứ không dùng nữa

| Đã bỏ | Bị thay bằng | Lý do |
|-------|-------------|-------|
| Bảng `policy_versions` | `policies` (v3.3) | Đổi tên + gộp `rules`/`weights`/`thresholds` |
| Cột `policy_version_id` | `policy_id` | Đổi tên theo v3.3 |
| Cột `rules_json` | `rules` (JSONB) | Trùng với schema v3.3 |
| Cột `weights` (riêng) | `config.weights` | Gộp |
| Cột `thresholds` (riêng) | `config.thresholds` | Gộp |
| Cột `created_by_user_id` | `created_by` | Đổi tên theo v3.3 |
| Cột `risk_assessments.anomaly_score` | `ml_score` | Một tên gọi duy nhất |
| Cột `login_attempts.occurred_at` | `timestamp` | Đổi tên theo v3.3 |
| Cột `login_attempts.source_ip` | `ip_address` | Đổi tên theo v3.3 |
| Cột `login_attempts.rate_limited` | — | V3.3 dùng `outcome='rate_limited'` |
| Cột `login_attempts.detection_features` | `risk_assessments.ml_features_used` | Chỉ giữ 1 nơi lưu đặc trưng |
| Cột `detection_logs.score` | `score_contribution` | Tên rõ nghĩa hơn |
| Ngưỡng `0.2 / 0.5 / 0.8` | `0.25 / 0.50 / 0.75` | Chuẩn v3.3 |
| `max` trong gộp rule | Cộng có trọng số + chuẩn hoá | Xem mục 2 |
| Trường `condition` dạng text | `field` + `operator` + `value` | Kiểm tra bằng code, không phải parse |
| Prefix `/internal/v1/` | `/api/v1/internal/` | Chuẩn của dự án |
| `ml_score` tính bằng heuristic | Gọi HTTP `/api/v1/internal/ml/score` | Theo UC-DE-03 |

---

## 10. Cổng kiểm duyệt trước khi cấp token (risk gate) — CHUẨN

> Bổ sung 2026-10-05. Xem `app/auth.py::_pre_token_risk` và
> `app/detection.py::pre_token_check`.

### 10.1. Vấn đề

Mô hình bất đồng bộ thuần: Core App cấp token **ngay** sau khi xác thực mật khẩu,
Detection chấm điểm sau. Với token thời hạn 1 giờ, kẻ đánh cắp được mật khẩu có
**tối đa 1 giờ** dùng hệ thống trước khi bị thu hồi.

### 10.2. Quyết định: gate có điều kiện theo rủi ro

Không gate mọi đăng nhập (sẽ thêm 2-5 giây độ trễ cho **mọi** người dùng, kể cả
đăng nhập bình thường). Chỉ gate khi mức rủi ro đã vượt ngưỡng:

| `risk_level` | Hành động của Core App | Có tạo session/token? |
|--------------|------------------------|----------------------|
| `low` | Cấp token ngay | ✅ Có |
| `medium` | Cấp token ngay | ✅ Có |
| `high` | **Giữ token, bắt MFA** | ❌ Không |
| `critical` | **Giữ token, bắt MFA** | ❌ Không |

Hằng số: `GATED_RISK_LEVELS = {"high", "critical"}`.

### 10.3. Luồng xử lý

```
Client → POST /api/v1/auth/login
Core App: rate limit → xác thực mật khẩu → kiểm tra status
         │
         ├─→ POST {DETECTION_URL}/api/v1/internal/pre-token-check   (timeout 3s)
         │        ├─ risk_level ∈ {high, critical} → đặt detection_mfa_once = true
         │        │                                    → phát MFA challenge, KHÔNG cấp token
         │        └─ risk_level ∈ {low, medium}      → tiếp tục, cấp token bình thường
         │
         ├─ admin_mfa_required? → MFA challenge (không cấp token)
         └─ không → _create_session() → trả token
```

**Điểm quan trọng:** cổng nằm **sau** bước xác thực mật khẩu và **trước** khi tạo
session. Người dùng đúng định danh nhưng bị nghi ngờ vẫn phải qua MFA; người dùng sai
mật khẩu không tốn một lượt gọi Detection.

### 10.4. Quyết định: FAIL OPEN

**Nếu cổng không hoạt động → vẫn cho đăng nhập.** Cụ thể, trả về "cho qua" khi:

| Tình huống | Xử lý |
|-----------|--------|
| Timeout quá 3 giây | Cho qua, ghi log cảnh báo |
| Không kết nối được (`ConnectError`) | Cho qua, ghi log cảnh báo |
| HTTP ≥ 400 | Cho qua |
| Body không phải JSON | Cho qua |
| Response có `degraded: true` | Cho qua |
| `RUN_PRE_TOKEN_CHECK=0` | Không gọi, cho qua |

**Lý do:** Detection Engine sập mà khoá cả hệ thống là kết quả tệ hơn nhiều so với
lọt **một** lần đăng nhập không được chấm điểm. Còn khi hạ tầng ổn định, cổng có tác
dụng. Việc thu hồi vẫn được bảo đảm bởi đường hậu kỳ ở mục 11 — tức là lựa chọn
"fail open" **không** đánh đổi bằng mất an toàn, chỉ đổi **thời điểm** phát hiện.

### 10.5. Hợp đồng `POST /api/v1/internal/pre-token-check`

Request:
```json
{
  "username": "alice",
  "user_id": "b1f2...",           // null nếu chưa xác định được user
  "ip_address": "203.0.113.5",
  "user_agent": "Mozilla/5.0 ...",
  "timestamp": "2026-10-05T04:10:00Z",
  "features": { "hour_of_day": 4 }  // optional, core-app gửi sẵn nếu có
}
```

Response:
```json
{
  "risk_level": "high",
  "decision": "challenge",
  "require_mfa": true,
  "degraded": false,
  "reason": "challenge"
}
```

> `degraded: true` chỉ xuất hiện khi chính Detection **có** lỗi chấm điểm. Core App
> **phải** fail open theo `degraded`, tuyệt đối không coi đây là rủi ro cao.

### 10.6. Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `DETECTION_URL` | `http://localhost:8001` | Địa chỉ Detection Engine |
| `RUN_PRE_TOKEN_CHECK` | `1` | Đặt `0` để tắt cổng (dev, hoặc khi chưa deploy Detection) |
| `PRE_TOKEN_CHECK_TIMEOUT` | hằng số `3.0` | Timeout cố định trong code |

---

## 11. Hành động bảo vệ tự động (UC-DE-07) — CHUẨN

> Bổ sung 2026-10-05. Xem `app/detection.py::enforce_action_in_core`.

### 11.1. Detection gọi ngược Core App

Sau khi **đã commit** verdict và alert, Detection gọi
`POST {CORE_APP_URL}/api/v1/internal/actions`. Cố ý gọi **sau commit** để Core App
chậm hoặc chết không thể rollback `risk_assessments` / `alerts` đã ghi.

```python
RISK_ACTION_MAP = {
    "high":     "REQUIRE_MFA",
    "critical": "REVOKE_SESSIONS",
}
```

| `risk_level` | Hành động gửi đi | `severity` |
|--------------|------------------|------------|
| `low`, `medium` | *(không gọi)* | — |
| `high` | `REQUIRE_MFA` | `high` |
| `critical` | `REVOKE_SESSIONS` | `critical` |

### 11.2. Vì sao `critical` KHÔNG dùng `LOCK_USER`

`LOCK_USER` sẽ chặn tài khoản vĩnh viễn cho tới khi admin mở khoá. Nếu mô hình ML
báo nhầm, người dùng hợp lệ bị khoá oan và không tự thoát ra được.

`REVOKE_SESSIONS` **rẻ và đảo ngược được**: phiên hiện tại bị cắt, người dùng đăng nhập
lại và qua MFA. Kẻ tấn công mất quyền truy cập, người dùng hợp lệ chỉ tốn thêm một bước
xác thực. Đánh đổi này được chấp nhận vì `false positive` của ML là tình huống thường
gặp, còn hậu quả khoá oan thì nghiêm trọng.

> `LOCK_USER` vẫn tồn tại như hành động **thủ công** cho SOC dùng khi đã điều tra và
> có bằng chứng rõ ràng.

### 11.3. `REQUIRE_MFA` phải thu hồi phiên sống

**Quyết định:** `REQUIRE_MFA` **luôn** thu hồi mọi phiên đang hoạt động của user, không
chỉ đặt cờ one-time.

**Lý do:** cờ `detection_mfa_once` chỉ có tác dụng cho **lần đăng nhập kế tiếp**. Token đã
cấp trước khi Detection chạy vẫn hợp lệ tới hết 1 giờ. Nếu không thu hồi, yêu cầu MFA
trở nên vô nghĩa — người đã có token không cần MFA để tiếp tục dùng hệ thống.

Phạm vi: áp dụng cho **cả hai** đường gọi, để hành vi nhất quán:
- `POST /api/v1/internal/actions` (Detection tự động gọi)
- `POST /api/v1/alerts/{id}/actions` (SOC yêu cầu thủ công)

Response `details` trả về `sessions_revoked` cho cả `REQUIRE_MFA`, `REVOKE_SESSIONS`,
`LOCK_USER` và `FORCE_LOGOUT`.

### 11.4. Đặc tính vận hành

| Đặc tính | Giá trị | Vì sao |
|----------|---------|--------|
| Timeout | 3 giây | Không giữ request chấm điểm mở chờ auth service |
| Lỗi | Nuốt, ghi log, trả `False` | Detection không được chết vì Core App |
| `idempotency_key` | `detection:{attempt_id}:{action}` | Giao lại sau timeout là no-op |
| `alert_id` | Gửi kèm | SOC đối chiếu được giữa 2 DB |

### 11.5. Khôi phục sau sự cố

Khi `process_attempt` ném exception, `LoginAttempt` bị để ở `status = "failed"` mà không
có đánh giá, không có cảnh báo, không có hành động nào được gửi. Hàm
`rescore_failed_attempts()` quét lại các dòng này và chấm lại.

> **Trạng thái:** hàm đã hiện thực và có test, **nhưng chưa được nối vào bộ lập lịch nào.**
> Cần một cron/worker chạy định kỳ — xem mục 12.

### 11.6. Hành vi của `status` trên `LoginAttempt`

| `status` | Ý nghĩa | Ai chuyển sang |
|----------|---------|---------------|
| `pending` | Đã nhận, chưa chấm | `receive_login_event` |
| `processed` | Đã chấm xong, có đánh giá | `process_attempt` |
| `failed` | Chấm lỗi, cần chấm lại | handler khi bắt exception |

`rescore_failed_attempts()` chỉ quét `failed`, và `process_attempt` luôn đặt lại
`processed` khi thành công — nên quét lại nhiều lần **không** gây lặp vô hạn.

---

## 12. Việc chưa làm (nợ kỹ thuật)

Ghi lại rõ để không ai hiểu nhầm là đã xong:

| Việc | Trạng thái | Rủi ro nếu bỏ |
|------|-----------|---------------|
| Worker gọi `rescore_failed_attempts()` định kỳ | **Chưa có** | Attempt `failed` không bao giờ được chấm lại |
| Poller `outbox_events` | **Chưa có** | Ghi `LoginAttempt` xong mà Detection chết → mất sự kiện |
| Tái sử dụng token rotation cho refresh | Đã có `refresh_token_family` nhưng chưa dùng để phát hiện replay | Refresh token bị đánh cắp tái sử dụng không bị phát hiện |
| Đối chiếu `risk_assessments` ↔ `sessions` định kỳ | **Chưa có** | Lệch trạng thái giữa 2 DB không được phát hiện |

> **Về poller outbox:** hiện `app/auth.py` ghi thẳng `LoginAttempt` và **không** tạo dòng
> `outbox_events`. Cổng ở mục 10 đã giảm thiểu đáng kể rủi ro trong lúc chờ poller, vì
> `high`/`critical` bị chặn **trước khi** có token. Poller vẫn là câu trả lời đúng cho bài
> toán "sự kiện đã ghi nhưng Detection chết", nên không nên coi là đã giải quyết.

---

## 13. Quy trình đảm bảo không phát sinh mâu thuẫn mới

Mỗi khi thêm/sửa tài liệu hoặc code liên quan tới Detection Engine, chạy checklist sau:

```
□ Tên cột trong SQL == tên trường trong Pydantic == tên trong tài liệu đặc tả
□ Đường dẫn API viết giống nhau ở mọi tài liệu và trong code
□ Công thức gộp điểm viết giống nhau ở mọi nơi
□ Ngưỡng mức rủi ro viết giống nhau ở mọi nơi
□ Ví dụ JSON trong tài liệu parse được bằng json.loads()
□ Nếu đổi schema → cập nhật cả ERD_v3.3.md
□ Nếu đổi API → cập nhật cả wf2_detection.uml, wf3_soc.uml, wf6_ml_inference.uml
□ Nếu đổi hành vi hành động bảo vệ → cập nhật mục 11
□ Nếu đổi cổng kiểm duyệt → cập nhật mục 10 và WF-1_Login.uml
□ Việc chưa làm phải ghi ở mục 12, không được im lặng coi là đã xong
```

---

## 14. Danh sách tài liệu phải cập nhật khi có thay đổi

| Tài liệu | Nội dung liên quan |
|----------|-------------------|
| `docs/04-bang-yeu-cau-chuc-nang-nghiep-vu-detection-engine.md` | Cấu trúc rule, công thức, ngưỡng |
| `docs/05-dac-ta-use-case-detection-engine.md` | Basic flow, evidence response |
| `docs/06-phan-tich-doi-tuong-su-dung-detection-engine.md` | Giao tiếp ML Service |
| `docs/diagrams/ERD_v3.3.md` | Tên cột, cấu trúc bảng |
| `docs/diagrams/wf2_detection.uml` | Đường dẫn, điểm số |
| `docs/diagrams/wf3_soc.uml` | Đường dẫn |
| `docs/diagrams/wf6_ml_inference.uml` | Đường dẫn, trường phản hồi |
| `docs/diagrams/architecture.uml` | Đường dẫn |
| `docs/SENTINEL_AUTH_TONG_HOP_v3.3.md` | Công thức, ngưỡng |
| `docs/Tuần 2 - He thong Quan ly canh bao dang nhap bat thuong.md` | Quy trình tổng quan |
| `infra/postgres/schema-detection-v3.3.sql` | Cấu trúc bảng, seed data |
| `infra/postgres/schema-ml-service-v3.3.sql` | Trường phản hồi ML |
| `TASK_ASSIGNMENT.md` | Công thức, ngưỡng |
| `app/models.py` | Model ORM |
| `app/schemas.py` | Pydantic schema |
| `app/detection.py` | Logic chấm điểm, cổng pre-token, callback hành động |
| `app/auth.py` | Risk gate trước khi cấp token |
| `app/internal_actions.py` | Thực thi hành động bảo vệ |
| `app/alerts.py` | Endpoint SOC |

---

**Phiên bản:** 1.1
**Ngày chốt:** 2026-10-04
**Cập nhật:** 2026-10-05 (mục 10-13: risk gate, hành động tự động, khôi phục sự cố)
**Người chốt:** Nhóm Detection Engine
**Áp dụng cho:** Sentinel Auth v3.3
