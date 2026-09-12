# BẢNG YÊU CẦU CHỨC NĂNG NGHIỆP VỤ — ML SERVICE
## Phiên bản 2.0 — Dựa trên Schema v3 & Implementation thực tế

> **Nguồn:** `app/ml.py`, `app/detection.py`, `app/schemas.py`, `infra/postgres/schema-v3.sql`
> **Ngày:** 2026-09-12
> **Trạng thái:** Hoàn chỉnh — Sửa đổi từ bản gốc của thành viên ML

---

## MỤC LỤC

1. Vai trò và phạm vi của ML Service
2. Đầu vào của ML Service (Feature Contract)
3. Đầu ra của ML Service
4. Quy trình xử lý nội bộ
5. Quan hệ với Use Case chung của hệ thống
6. Ranh giới trách nhiệm
7. Yêu cầu phi chức năng
8. Model Lifecycle
9. Alignment với Database Schema

---

## 1. VAI TRÒ VÀ PHẠM VI CỦA ML SERVICE

### 1.1. Mô tả tổng quan

**ML Service** là thành phần xử lý nội bộ của Sentinel Auth, phụ trách đánh giá mức bất thường của hành vi đăng nhập. Thành phần này **không phải actor người dùng** và không có Use Case riêng theo góc nhìn nghiệp vụ.

### 1.2. Vị trí trong kiến trúc

```
┌─────────────────────────────────────────────────────────────────┐
│                      SENTINEL AUTH                               │
│                                                                 │
│  ┌──────────┐     ┌──────────────────┐     ┌──────────────┐  │
│  │   User   │────▶│  Auth/MFA Flow   │────▶│    Session   │  │
│  └──────────┘     └────────┬─────────┘     └──────────────┘  │
│                             │                                   │
│                             ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   DETECTION ENGINE                        │  │
│  │                                                          │  │
│  │  ┌────────────┐    ┌────────────┐    ┌────────────┐  │  │
│  │  │  Feature   │───▶│    ML      │───▶│    Risk    │  │  │
│  │  │  Builder   │    │  Service   │    │   Engine   │  │  │
│  │  └────────────┘    └────────────┘    └─────┬──────┘  │  │
│  │                                          │            │  │
│  │  ┌────────────┐    ┌────────────┐       │            │  │
│  │  │Rule Engine │───▶│   Score    │◀──────┘            │  │
│  │  │            │    │  Combine   │                      │  │
│  │  └────────────┘    └────────────┘                      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                             │                                   │
│                             ▼                                   │
│                    ┌──────────────┐                            │
│                    │    Alert     │                            │
│                    │   Engine     │                            │
│                    └──────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3. Chức năng chính

| STT | Chức năng | Mô tả |
|------|-----------|--------|
| 1 | Feature Validation | Nhận và kiểm tra dữ liệu đầu vào theo feature contract |
| 2 | Feature Preprocessing | Tiền xử lý dữ liệu trước khi suy luận (normalization) |
| 3 | Anomaly Detection | Tính raw anomaly score bằng mô hình |
| 4 | Score Calibration | Chuẩn hóa score thành normalized score (0-1) |
| 5 | Result Return | Trả kết quả đánh giá và metadata cho Risk Engine |
| 6 | Status Reporting | Cung cấp trạng thái sẵn sàng của model |

### 1.4. Ranh giới trách nhiệm

| Thực hiện | Trách nhiệm |
|-----------|-------------|
| **ML Service** | Validate feature, chạy inference, chuẩn hóa score, trả anomaly evidence |
| **Detection/Feature Builder** | Tạo feature đúng contract, cung cấp context đầu vào |
| **Risk Engine** | Kết hợp Rule Score + Anomaly Score + context để tạo Total Risk Score |
| **SOC Analyst** | Sử dụng evidence để điều tra và xử lý alert |

### 1.5. Điều KHÔNG thuộc về ML Service

- ❌ Quyết định Allow/Block
- ❌ Tạo alert
- ❌ Gửi notification
- ❌ Lock tài khoản
- ❌ Revoke session
- ❌ Ghi audit log

---

## 2. ĐẦU VÀO CỦA ML SERVICE (FEATURE CONTRACT)

### 2.1. Feature Vector

ML Service nhận một dictionary chứa các features từ Detection/Feature Builder:

| STT | Tên Feature | Kiểu dữ liệu | Mô tả | Nguồn dữ liệu |
|------|-------------|---------------|--------|----------------|
| 1 | `login_hour` | int | Giờ trong ngày (0-23) của lần đăng nhập | `login_attempts.occurred_at` |
| 2 | `login_day` | int | Ngày trong tuần (0-6) | `login_attempts.occurred_at` |
| 3 | `ip_country` | str | Mã quốc gia IP | Feature Builder (IP geolocation) |
| 4 | `ip_reputation` | float | Điểm uy tín IP (0.0-1.0) | Feature Builder (external API) |
| 5 | `user_agent_family` | str | Họ trình duyệt/thiết bị | `login_attempts.user_agent` |
| 6 | `asn_reputation` | float | Điểm uy tín ASN (0.0-1.0) | Feature Builder (external API) |
| 7 | `failed_attempts_1h` | int | Số lần đăng nhập thất bại trong 1 giờ gần nhất | `login_attempts` (count) |
| 8 | `failed_attempts_24h` | int | Số lần đăng nhập thất bại trong 24 giờ gần nhất | `login_attempts` (count) |
| 9 | `geo_velocity_kmh` | float | Vận tốc di chuyển theo địa lý (km/h) | Feature Builder (IP geo) |
| 10 | `login_streak` | int | Số lần đăng nhập liên tiếp gần đây | Feature Builder (history) |
| 11 | `is_known_device` | bool | Thiết bị đã từng được sử dụng | `user_trusted_devices` |
| 12 | `is_known_ip` | bool | IP đã từng được sử dụng | `login_attempts` (history) |
| 13 | `mfa_used_recently` | bool | MFA đã được sử dụng gần đây | `pre_auth_transactions` |

### 2.2. Feature Schema Version

```json
{
  "version": "1.0",
  "features": [
    {"name": "login_hour", "type": "int", "range": [0, 23], "required": true},
    {"name": "login_day", "type": "int", "range": [0, 6], "required": false},
    {"name": "ip_country", "type": "str", "required": false},
    {"name": "ip_reputation", "type": "float", "range": [0.0, 1.0], "required": false},
    {"name": "user_agent_family", "type": "str", "required": false},
    {"name": "asn_reputation", "type": "float", "range": [0.0, 1.0], "required": false},
    {"name": "failed_attempts_1h", "type": "int", "range": [0, 100], "required": true},
    {"name": "failed_attempts_24h", "type": "int", "range": [0, 1000], "required": true},
    {"name": "geo_velocity_kmh", "type": "float", "range": [0.0, 10000.0], "required": false},
    {"name": "login_streak", "type": "int", "range": [0, 100], "required": false},
    {"name": "is_known_device", "type": "bool", "required": true},
    {"name": "is_known_ip", "type": "bool", "required": false},
    {"name": "mfa_used_recently", "type": "bool", "required": false}
  ]
}
```

### 2.3. Feature Contract Versioning Policy

| Quy tắc | Mô tả |
|---------|--------|
| Version format | `major.minor` (e.g., `1.0`, `1.1`, `2.0`) |
| Breaking change | Tăng major version khi xóa feature hoặc đổi type |
| Non-breaking change | Tăng minor version khi thêm feature mới (optional) |
| Backward compatibility | ML Service phải hỗ trợ tối thiểu 2 version gần nhất |

---

## 3. ĐẦU RA CỦA ML SERVICE

### 3.1. Response Schema

```json
{
  "anomaly_score": 0.75,
  "ml_status": "success",
  "model_version": "1.0.0"
}
```

### 3.2. Field Definitions

| Trường | Kiểu | Mô tả | Ví dụ |
|---------|------|--------|-------|
| `anomaly_score` | float (0.0-1.0) | Điểm bất thường đã được chuẩn hóa. Giá trị lớn hơn thể hiện mức độ lệch cao hơn. | `0.75` |
| `ml_status` | enum | Trạng thái phục vụ: `success`, `unavailable`, `error` | `"success"` |
| `model_version` | string | Phiên bản model được sử dụng | `"1.0.0"` |

### 3.3. ML Status Values

| Giá trị | Mô tả | Hành vi của Risk Engine |
|---------|--------|------------------------|
| `success` | ML inference hoàn thành bình thường | Sử dụng `anomaly_score` trong combined_score |
| `unavailable` | ML service không khả dụng (downtime) | Chỉ sử dụng `rule_score`, cảnh báo degraded |
| `error` | ML inference thất bại (internal error) | Chỉ sử dụng `rule_score`, log lỗi |

### 3.4. Score Semantics

| Score Range | Ý nghĩa | Khuyến nghị xử lý |
|-------------|---------|-------------------|
| 0.0 - 0.2 | Hành vi bình thường | Low risk |
| 0.2 - 0.5 | Có một số bất thường nhẹ | Medium risk |
| 0.5 - 0.8 | Hành vi bất thường đáng kể | High risk |
| 0.8 - 1.0 | Hành vi rất bất thường | Critical risk |

> **Lưu ý:** ML score không phải là xác suất tấn công. Cần hiệu chuẩn xác suất (probability calibration) nếu muốn diễn giải thành xác suất.

---

## 4. QUY TRÌNH XỬ LÝ NỘI BỘ

### 4.1. Activity Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ML SERVICE PROCESSING FLOW                        │
└─────────────────────────────────────────────────────────────────────────┘

  Detection/Feature Builder
         │
         │ POST /internal/v1/ml/score
         │ { features: {...} }
         ▼
  ┌──────────────────────┐
  │ 1. Receive Request    │
  │    + Validate Token  │
  └──────────┬───────────┘
             │ Valid
             ▼
  ┌──────────────────────┐
  │ 2. Feature Schema   │──── Invalid ────▶ Return 400 Bad Request
  │    Validation        │
  └──────────┬───────────┘
             │ Valid
             ▼
  ┌──────────────────────┐
  │ 3. Feature           │
  │    Preprocessing     │
  │    (normalization,   │
  │     missing values)  │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 4. Model Inference   │
  │    (Isolation Forest) │
  │    → raw_score       │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 5. Score Calibration │
  │    raw_score →       │
  │    normalized_score  │
  │    (0.0 - 1.0)      │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 6. Model Status      │
  │    Check             │
  │    (ready/degraded)  │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 7. Return Response   │
  │    { anomaly_score,  │
  │      ml_status,      │
  │      model_version } │
  └──────────────────────┘
             │
             ▼
       Risk Engine
```

### 4.2. Processing Steps Detail

| Bước | Mô tả | Error Handling |
|------|--------|----------------|
| 1. Receive | Nhận request từ internal endpoint | - |
| 2. Validate | Kiểm tra `x_internal_token` | 401 Unauthorized |
| 3. Schema check | Validate feature schema version và required fields | 400 Bad Request |
| 4. Preprocess | Fill missing values với defaults, normalize ranges | - |
| 5. Inference | Chạy model.predict(features) | Catch exception → error status |
| 6. Calibrate | Map raw_score → normalized_score | - |
| 7. Response | Trả về ScoreResponse | - |

### 4.3. Algorithm: Isolation Forest (Baseline)

```
Baseline Implementation:
- Algorithm: Isolation Forest
- n_estimators: 100
- contamination: 0.1
- max_samples: 256

Score Interpretation:
- Lower scores = more isolated (more anomalous)
- Higher scores = less isolated (normal behavior)
- Result inverted: 1 - original_score → anomaly_score
```

---

## 5. QUAN HỆ VỚI USE CASE CHUNG CỦA HỆ THỐNG

### 5.1. ML Service Integration Points

| Use Case | Actor | Vai trò của ML Service |
|---------|-------|------------------------|
| **UC-08** - Xem Risk Evidence | SOC Analyst | Hiển thị `anomaly_score`, `ml_status`, `model_version` cùng `rule_score` và `combined_score` |
| **UC-09** - Điều tra Alert | SOC Analyst | ML evidence hỗ trợ chuyên viên đánh giá vì sao một login event bị coi là đáng ngờ |
| **UC-06** - SOC Dashboard | SOC Analyst | Có thể dùng anomaly/risk aggregate như một nguồn dữ liệu tổng hợp |
| **UC-20** - Management Dashboard | Security Manager | Có thể sử dụng dữ liệu aggregate từ risk/alert; không truy cập trực tiếp ML Service |

### 5.2. Data Flow trong Login Flow

```
1. User submits login credentials
         │
         ▼
2. Auth module validates credentials
         │
         ▼
3. Detection module calls ML Service
         │
         ▼
4. ML Service returns { anomaly_score, ml_status, model_version }
         │
         ▼
5. Detection module combines rule_score + anomaly_score → combined_score
         │
         ▼
6. Decision: allow / challenge / block
         │
         ▼
7. If high risk: Create Alert with detection_scores
```

---

## 6. RANH GIỚI TRÁCH NHIỆM

### 6.1. ML Service Responsibilities

| Trách nhiệm | Chi tiết |
|-------------|----------|
| **Feature Validation** | Đảm bảo features đúng schema trước khi inference |
| **Model Loading** | Load model từ model registry khi khởi động |
| **Inference** | Chạy prediction và trả kết quả |
| **Health Check** | Cung cấp endpoint `/health` để check model status |
| **Error Handling** | Xử lý graceful degradation khi model không khả dụng |

### 6.2. External Dependencies

| Dependency | Interface | Fallback |
|------------|-----------|----------|
| **Detection Engine** | Internal HTTP API (`/internal/v1/ml/score`) | - |
| **Feature Builder** | Part of Detection Engine | - |
| **Risk Engine** | Part of Detection Engine | - |
| **Model Registry** | File system / S3 | Load bundled model |

### 6.3. Security Boundaries

| Boundary | Protection |
|----------|------------|
| ML Service → Detection Engine | Internal network only, `x_internal_token` header |
| ML Service → External APIs | None (stateless inference) |
| Audit | All ML calls logged via Detection Engine |

---

## 7. YÊU CẦU PHI CHỨC NĂNG

### 7.1. Performance Requirements

| Metric | Target | Ghi chú |
|--------|--------|---------|
| Latency P50 | < 50ms | Single inference |
| Latency P95 | < 200ms | Single inference |
| Latency P99 | < 500ms | Single inference |
| Throughput | > 100 req/s | Per instance |
| Model Load Time | < 5s | Cold start |

### 7.2. Availability Requirements

| Metric | Target | Ghi chú |
|--------|--------|---------|
| Uptime | 99.9% | Per month |
| Degraded Mode | Graceful | Return `ml_status: unavailable` |
| Recovery | Automatic | Auto-reload model on failure |

### 7.3. Scalability Requirements

| Aspect | Requirement |
|--------|-------------|
| Horizontal Scaling | Support multiple instances |
| Load Balancing | Round-robin hoặc least-connections |
| State | Stateless (no shared state) |

### 7.4. Monitoring Requirements

| Metric | Alert |
|--------|-------|
| `ml_status = error` rate > 5% | Alert PagerDuty |
| Latency P95 > 500ms | Alert monitoring |
| Model load failure | Alert immediately |

---

## 8. MODEL LIFECYCLE

### 8.1. Model Registry

```
models/
├── sentinel-anomaly-v1/
│   ├── model.pkl           # Serialized model
│   ├── metadata.json       # Model metadata
│   ├── features.json       # Feature schema
│   └── training_data/      # Reference training data stats
└── sentinel-anomaly-v2/
    └── ...
```

### 8.2. Metadata Schema

```json
{
  "name": "sentinel-anomaly-v1",
  "version": "1.0.0",
  "algorithm": "IsolationForest",
  "trained_at": "2026-01-15T00:00:00Z",
  "training_samples": 100000,
  "contamination": 0.1,
  "features_used": ["login_hour", "failed_attempts_1h", ...],
  "performance_metrics": {
    "auc": 0.92,
    "precision_at_10pct": 0.85
  },
  "status": "production"
}
```

### 8.3. Model Versioning Policy

| Event | Action |
|-------|--------|
| Model update (bug fix) | Increment patch: `1.0.0` → `1.0.1` |
| Feature change (non-breaking) | Increment minor: `1.0.0` → `1.1.0` |
| Breaking change (feature removed) | Increment major: `1.0.0` → `2.0.0` |
| Model rollback | Revert to previous version in registry |

### 8.4. Retraining Schedule

| Trigger | Frequency | Owner |
|---------|-----------|-------|
| Scheduled | 3 tháng | ML Team |
| Performance degraded | Ad-hoc | ML Team |
| Significant data drift | Ad-hoc | ML Team |
| Security incident | Ad-hoc | ML Team |

### 8.5. Rollback Procedure

```
1. Deploy detects model performance degradation
         │
         ▼
2. Alert triggered → ML Team notified
         │
         ▼
3. ML Team evaluates → Decision to rollback
         │
         ▼
4. Update model registry symlink to previous version
         │
         ▼
5. Reload model → New requests use old model
         │
         ▼
6. Monitor for 24h → Confirm stability
```

---

## 9. ALIGNMENT VỚI DATABASE SCHEMA

### 9.1. Tables sử dụng ML Service

| Table | ML-Related Fields | Usage |
|-------|------------------|-------|
| `login_attempts` | `detection_features` (JSONB) | Store raw features for debugging |
| `risk_assessments` | `ml_score`, `ml_status`, `ml_model_version`, `ml_features_used` | Store ML results |
| `detection_logs` | `stage='ml'`, `score`, `details` | Audit trail |
| `policy_versions` | `weights`, `thresholds` | Configure ML weight in scoring |
| `system_settings` | `detection.ml_weight`, `detection.rule_weight` | Dynamic weight configuration |

### 9.2. ML Data Flow in Database

```
login_attempts
    │
    │ (on login)
    ▼
risk_assessments (INSERT)
    ├── login_attempt_id: FK → login_attempts.id
    ├── ml_score: anomaly_score from ML Service
    ├── ml_status: success/unavailable/error
    ├── ml_model_version: model version used
    ├── ml_features_used: features actually used
    └── anomaly_score: same as ml_score (alias)
    │
    ▼
detection_logs (INSERT)
    ├── stage: 'ml'
    ├── stage_detail: 'ml_inference'
    ├── score: anomaly_score
    └── details: { ml_status, features_used }
```

### 9.3. Risk Assessment Schema Alignment

```python
# Current implementation: app/detection.py
class ScoreResponse(BaseModel):
    anomaly_score: float
    ml_status: str  # 'success' | 'unavailable' | 'error'
    model_version: Optional[str] = None

# Stored in risk_assessments table
class RiskAssessment:
    ml_score: Optional[float]      # = anomaly_score
    ml_status: Optional[str]       # from ML response
    ml_model_version: Optional[str]  # from ML response
    ml_features_used: Optional[dict] # features passed to ML
```

### 9.4. Feature Contract vs Database Storage

| Feature Contract Field | Database Storage | Notes |
|-----------------------|------------------|-------|
| `login_hour` | `EXTRACT(HOUR FROM occurred_at)` | Computed at runtime |
| `failed_attempts_1h` | `COUNT(*)` from `login_attempts` | Query at runtime |
| `is_known_device` | `EXISTS` in `user_trusted_devices` | Check at runtime |
| `geo_velocity_kmh` | Not stored | Computed by Feature Builder |

---

## PHỤ LỤC

### A. API Reference

#### POST /internal/v1/ml/score

**Request:**
```json
{
  "features": {
    "login_hour": 14,
    "failed_attempts_1h": 3,
    "failed_attempts_24h": 10,
    "is_known_device": false,
    "geo_velocity_kmh": 500.0
  }
}
```

**Response:**
```json
{
  "anomaly_score": 0.75,
  "ml_status": "success",
  "model_version": "1.0.0"
}
```

#### GET /internal/v1/ml/health

**Response:**
```json
{
  "status": "ok",
  "model_name": "sentinel-anomaly-v1",
  "model_version": "1.0.0"
}
```

### B. Error Codes

| HTTP Code | ML Status | Meaning |
|-----------|-----------|---------|
| 200 | success | Inference completed |
| 401 | - | Invalid internal token |
| 500 | error | Internal ML error |
| 503 | unavailable | ML service down |

### C. Glossary

| Term | Definition |
|------|------------|
| Anomaly Score | Score indicating how anomalous a login attempt is (0-1) |
| Isolation Forest | ML algorithm used for anomaly detection |
| Feature Vector | Set of features passed to ML model |
| Score Calibration | Process of normalizing raw scores to 0-1 range |
| Model Registry | Repository for model versions and metadata |

---

> **Tổng kết:** ML Service là thành phần nội bộ, stateless, cung cấp anomaly scoring cho Detection Engine. Nhận feature vector, trả anomaly score với metadata. Hỗ trợ graceful degradation khi ML không khả dụng.
