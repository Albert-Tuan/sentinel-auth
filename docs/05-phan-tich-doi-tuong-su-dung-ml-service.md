# Phân tích đối tượng sử dụng ML Service

## 1. Đối tượng sử dụng trong phạm vi ML Service

ML Service chỉ có **một đối tượng service nội bộ** làm actor:

| STT | Đối tượng | Mô tả |
|---|---|---|
| 1 | Detection Engine | Service nội bộ gửi ML Request và nhận ML Response. |

> **Lưu ý:** ML Service không có actor con người. Không có SOC Analyst, Security Administrator, hay Security Manager tương tác trực tiếp với ML Service.

## 2. Chức năng của Detection Engine

### 2.1 Detection Engine

| Mã | Chức năng | Mô tả |
|---|---|---|
| DE-01 | Gửi ML Request | Gửi 6 features lên ML Service để đánh giá anomaly. |
| DE-02 | Nhận ML Response | Nhận normalized_anomaly_score, is_anomaly, model_version, reason_codes. |
| DE-03 | Xử lý ML Unavailable | Khi ML Service không khả dụng, fallback sang Rule Score only. |

## 3. Ma trận chức năng theo đối tượng

| Chức năng | Detection Engine | ML Operator (future) |
|---|:---:|:---:|
| Gửi ML Request | ✓ | - |
| Nhận ML Response | ✓ | - |
| Health Check | ✓ | - |
| Load/Unload Model | - | ✓ (future) |
| Xem Model Registry | - | ✓ (future) |

## 4. Quan hệ với Detection Engine

```
┌─────────────────────────────────────────────────────────────────┐
│                    DETECTION ENGINE                              │
│  ┌───────────────┐      ┌───────────────┐      ┌─────────────┐ │
│  │   core-app    │ ───► │ LoginEvent    │      │ ml-service  │ │
│  └───────────────┘      └───────────────┘      └──────┬──────┘ │
│  ┌───────────────┐      ┌───────────────┐             │         │
│  │   core-app    │ ◄── │    Action    │ ◄──────────┘         │
│  └───────────────┘      └───────────────┘      ML Request       │
└─────────────────────────────────────────────────────────────────┘
```

### 4.1 Detection Engine → ML Service

- **Gửi ML Request**: 6 features
- **Nhận ML Response**: normalized_anomaly_score, is_anomaly, reason_codes, model_status
- **Contract**: HTTP JSON với shared secret

### 4.2 ML Service → Detection Engine

- **Trả Response**: anomaly score và metadata
- **Báo Health**: model availability status

## 5. Ranh giới trách nhiệm

| Thành phần | Trách nhiệm |
|-------------|-------------|
| **Detection/Feature Builder** | Tạo features đúng contract, cung cấp context đầu vào cho ML |
| **ML Service** | Validate features, chạy inference, chuẩn hóa score, trả anomaly evidence |
| **Detection Engine** | Kết hợp Rule Score + Anomaly Score + context để tạo Total Risk Score |

## 6. Entities chính (ML Service Internal)

### 6.1 ML Request (from Detection Engine)

```json
{
  "request_id": "uuid",
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

### 6.2 ML Response (to Detection Engine)

```json
{
  "request_id": "uuid",
  "normalized_anomaly_score": 0.72,
  "is_anomaly": true,
  "model_version": "v1.0-isolation-forest",
  "reason_codes": ["unusual_time", "new_device"],
  "model_status": "ready"
}
```

### 6.3 Model Registry (internal)

```json
{
  "model_id": "uuid",
  "name": "isolation-forest-v1",
  "version": "v1.0",
  "algorithm": "IsolationForest",
  "status": "active|archived",
  "training_date": "ISO8601",
  "metrics": {
    "precision": 0.85,
    "recall": 0.78,
    "f1_score": 0.81
  },
  "loaded_at": "ISO8601"
}
```

## 7. ML Service không thuộc phạm vi

| Không có | Lý do |
|----------|-------|
| SOC Analyst | ML Service không có UI cho analyst |
| Security Administrator | Không có Use Case quản lý model |
| Security Manager | Không có dashboard ML trực tiếp |
| End User | ML Service là service nội bộ |

## 8. Features Contract

| Feature | Kiểu | Range | Ý nghĩa |
|---------|------|-------|---------|
| `hour_of_day` | Integer | 0-23 | Giờ trong ngày |
| `fail_count_24h` | Integer | ≥0 | Số lần fail trong 24h |
| `ip_change_rate_7d` | Float | 0-1 | Tỷ lệ thay đổi IP |
| `new_device` | Boolean | true/false | Thiết bị mới |
| `average_login_interval_seconds` | Integer | ≥0 | Khoảng login TB |
| `deviation_score` | Float | 0-1 | Mức lệch baseline |
