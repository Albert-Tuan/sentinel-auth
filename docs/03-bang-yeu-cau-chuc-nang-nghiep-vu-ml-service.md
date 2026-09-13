# Bảng yêu cầu chức năng nghiệp vụ của ML Service

## 1. Mục đích và phạm vi

ML Service là thành phần xử lý nội bộ của `sentinel-auth`: nhận feature vector từ Detection Engine, đánh giá mức bất thường bằng mô hình Anomaly Detection (Isolation Forest), và trả kết quả về Detection Engine.

**ML Service không có Use Case với actor con người.** Kết quả ML được sử dụng bên trong các Use Case của Detection Engine và SOC.

## 2. Bảng yêu cầu chức năng

| Mã | Nhóm chức năng | Đối tượng/nguồn gọi | Yêu cầu nghiệp vụ | Kết quả chính |
|---|---|---|---|---|
| YCNV-ML-01 | Nhận ML Request | Detection Engine | Nhận request với 6 features qua HTTP endpoint nội bộ có shared secret. Validate feature schema. | Request được xử lý; trả ML response. |
| YCNV-ML-02 | Validate Features | Hệ thống | Kiểm tra feature schema/version, validate data types và ranges. | Trả lỗi validation nếu invalid. |
| YCNV-ML-03 | Feature Preprocessing | Hệ thống | Tiền xử lý dữ liệu theo pipeline đã dùng khi training (normalization, encoding,...). | Features sẵn sàng cho inference. |
| YCNV-ML-04 | ML Inference | Hệ thống | Chạy Isolation Forest model để tính raw anomaly score. | Raw anomaly score. |
| YCNV-ML-05 | Score Normalization | Hệ thống | Calibrate raw score thành Normalized Anomaly Score (0-1). | Normalized score, is_anomaly flag. |
| YCNV-ML-06 | Reason Codes Generation | Hệ thống | Sinh reason codes (unusual_time, new_device, etc.) từ feature analysis nếu pipeline hỗ trợ. | Array of reason_codes. |
| YCNV-ML-07 | Trả ML Response | Hệ thống | Trả về normalized_anomaly_score, is_anomaly, model_version, reason_codes, model_status. | Detection Engine nhận đầy đủ evidence. |
| YCNV-ML-08 | Model Health Check | Hệ thống | Cung cấp endpoint health để Detection Engine biết model status (ready/degraded/error). | Model availability status. |
| YCNV-ML-09 | Model Management | ML Operator (future) | Load/unload model versions, xem model registry. | Model versioning và rollback. |
| YCNV-ML-10 | Fallback Handling | Hệ thống | Khi model không khả dụng, trả model_status != ready để Detection Engine fallback. | Graceful degradation. |

## 3. Yêu cầu phi chức năng và bảo mật

| Mã | Yêu cầu |
|---|---|
| YCPNC-ML-01 | ML Service không verify JWT của user. Chỉ verify shared secret với Detection Engine. |
| YCPNC-ML-02 | ML Service down không được làm detection fail hoàn toàn. Detection Engine fallback sang Rule Score only. |
| YCPNC-ML-03 | Normalized score = 0 có nghĩa là bình thường, score = 1 có nghĩa là bất thường nhất. |
| YCPNC-ML-04 | is_anomaly được xác định theo threshold đã config trong model. |
| YCPNC-ML-05 | Model không được coi là xác suất tấn công. Đây là anomaly score, không phải threat probability. |
| YCPNC-ML-06 | ML Service và Detection Engine không chia sẻ database. Chỉ giao tiếp qua HTTP contract. |

## 4. Ngoài phạm vi phiên bản 1

- Model training/updating tự động
- Online learning
- Multiple model support (chỉ 1 Isolation Forest baseline)
- Probabilistic calibration
- Feature importance analysis

## 5. Contract với Detection Engine

### ML Request (Detection Engine → ML Service)

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

### ML Response (ML Service → Detection Engine)

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

## 6. Features Contract

| Feature | Kiểu dữ liệu | Ý nghĩa |
|---------|---------------|---------|
| `hour_of_day` | Integer (0-23) | Giờ trong ngày của lần đăng nhập |
| `fail_count_24h` | Integer | Số lần đăng nhập thất bại trong 24 giờ gần nhất |
| `ip_change_rate_7d` | Float (0-1) | Mức/tỷ lệ thay đổi IP trong 7 ngày gần nhất |
| `new_device` | Boolean | Đánh dấu thiết bị mới so với lịch sử quan sát |
| `average_login_interval_seconds` | Integer | Khoảng thời gian trung bình giữa các lần đăng nhập |
| `deviation_score` | Float (0-1) | Mức lệch của hành vi hiện tại so với behavioral baseline |
