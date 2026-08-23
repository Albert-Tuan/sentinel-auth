# Plan tổng thể — sentinel-auth

> Tài liệu này là **LỚP 1** trong bộ 3 lớp plan: (1) Plan tổng thể, (2) Tickets cho từng module, (3) Roadmap 4 tuần. Trước khi code, cần đọc hết 3 lớp.

## 1. Tầm nhìn & nguyên tắc

- **Mục tiêu cuối**: có một hệ thống chạy được (3 service + Postgres + 1 frontend) + báo cáo Word mục 3.1 đầy đủ Use-case / Class / Sequence diagram.
- **Nguyên tắc thiết kế**:
  - **Contract-first**: API giữa 3 service định nghĩa trước (OpenAPI schema), 3 người code song song mà không phải chờ nhau.
  - **Module độc lập theo ranh giới nhân sự**: core-app, detection-engine, ml-service giao tiếp qua HTTP, không share DB (mỗi service có schema riêng hoặc instance riêng).
  - **Synthetic data first**: tạo dataset login giả từ đầu để cả 3 service đều có thể chạy end-to-end trước khi đụng vào ML thật.
  - **Báo cáo là first-class output**: mỗi UC viết code xong đều có sẵn trong `docs/yeu-cau-chuc-nang-3.1.md`, không phải viết lại.

## 2. Kiến trúc đã chốt

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (chọn sau)                       │
│             Streamlit / Next.js / React SPA                 │
└─────────────────────────────────────────────────────────────┘
            │              │              │
            ▼              ▼              ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   core-app       │ │ detection-engine │ │   ml-service      │
│   (Sony)         │ │  (Tuấn Anh)      │ │   (Khang)         │
│                  │ │                  │ │                   │
│ - Auth (JWT)     │ │ - Rule Engine    │ │ - Feature         │
│ - User/Role      │ │ - Risk Engine    │ │   Pipeline         │
│ - Session/MFA    │ │ - Alert Engine   │ │ - IsolationForest │
│ - Login API      │ │ - SOC Dashboard  │ │ - Inference API  │
│                  │ │   (HTML hoặc SPA)│ │                   │
└──────────────────┘ └──────────────────┘ └──────────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────────┐ ┌──────────────────────────────────────┐
│   PostgreSQL     │ │ PostgreSQL + TimescaleDB            │
│   core_app DB    │ │ detection_db (LoginEvent hypertable)│
└──────────────────┘ │ + ml_db (model artifacts)           │
                     └──────────────────────────────────────┘
```

**Quyết định đã chốt** (ghi từ `/grilling`):
- Stack: Python + FastAPI cho cả 3 service.
- Kiến trúc: True microservice (3 process riêng, giao tiếp HTTP).
- DB: PostgreSQL + TimescaleDB extension cho `LoginEvent`.
- ML: Train Isolation Forest thật trên synthetic data.
- Data train: Tôi viết spec, Khang tự implement.
- Frontend: quyết sau.
- Plan: 3 lớp (Plan tổng thể + Tickets + Roadmap).
- Phân chia nhóm: theo module/tech (đúng README).

## 3. Hợp đồng giao tiếp giữa 3 service (API contract)

> Phần này định nghĩa **trước** khi code, để 3 người làm song song.

### 3.1. core-app → detection-engine (gửi login event)
```
POST /internal/login-events
Body: {
  "event_id": "uuid",
  "user_id": "uuid",
  "timestamp": "2026-08-23T22:00:00Z",
  "success": true,
  "source_ip": "1.2.3.4",
  "device_id": "fp-xyz",
  "user_agent": "Mozilla/5.0...",
  "region": "VN-HCM",
  "mfa_used": false,
  "failure_reason": null
}
Response 202: { "accepted": true }
```
core-app gọi **sau khi xác thực xong**, fire-and-forget, không block response cho user.

### 3.2. detection-engine → ml-service (gửi feature vector)
```
POST /internal/ml/score
Body: {
  "event_id": "uuid",
  "user_id": "uuid",
  "features": {
    "hour_of_day": 22,
    "fail_count_window_24h": 3,
    "ip_change_rate_7d": 0.4,
    "new_device_flag": false,
    "avg_time_between_logins_sec": 3600,
    "deviation_score": 0.1
  }
}
Response 200: {
  "event_id": "uuid",
  "anomaly_score": 0.23,
  "is_anomaly": false,
  "model_version": "iforest-v0.1.0",
  "reason_codes": ["unusual_hour"]
}
```
Timeout: 500ms. Nếu ml-service không phản hồi, detection-engine dùng anomaly_score mặc định = 0.

### 3.3. detection-engine → core-app (yêu cầu MFA hoặc khóa user)
```
POST /internal/users/{user_id}/actions
Body: {
  "action": "REQUIRE_MFA" | "REVOKE_SESSIONS" | "LOCK_USER" | "RATE_LIMIT_IP",
  "reason": "alert-id-123",
  "expires_at": "..."  // optional
}
Response 200: { "applied": true }
```
Detection-engine chỉ được **đề xuất**, nhưng core-app là nơi **áp dụng** lên user/session thật. (Tách biệt quyền hành động vs quyền phát hiện.)

### 3.4. SOC Analyst → detection-engine (query dashboard)
```
GET /api/v1/alerts?status=NEW&risk_level=HIGH&from=...&to=...&limit=50
GET /api/v1/alerts/{id}
GET /api/v1/login-events?user_id=...
POST /api/v1/alerts/{id}/status { "status": "ACK" }
```

### 3.5. ml-service (internal)
```
POST /internal/ml/train        # trigger train lại model (admin only)
GET  /internal/ml/model-info  # version + metrics hiện tại
```

## 4. Database schema (định nghĩa trước)

> Mỗi service có schema riêng. Detection-engine dùng TimescaleDB hypertable cho `LoginEvent`.

### 4.1. core_app schema
- `users(id, username, email, password_hash, status, created_at, locked_until)`
- `roles(id, name)` — USER, SOC_ANALYST, SECURITY_ADMIN, SECURITY_MANAGER
- `user_roles(user_id, role_id)`
- `sessions(id, user_id, token, source_ip, device_id, created_at, expires_at, revoked_at)`
- `mfa_challenges(id, user_id, session_id, method, code_hash, expires_at, status)`
- `trusted_devices(id, user_id, device_fingerprint, trust_level, added_at)`
- `auth_policies(id, name, password_min_len, mfa_required, lockout_threshold, session_ttl)`

### 4.2. detection_engine schema (PostgreSQL + TimescaleDB)
- `rules(id, code, name, description, weight, threshold, enabled)`
- `login_events` — **hypertable** theo `timestamp`
  - `id, user_id, timestamp (partition key), success, source_ip, device_id, user_agent, region, mfa_used, failure_reason`
- `rule_hits(id, login_event_id, rule_id, rule_score, hit_at)`
- `risk_scores(id, login_event_id, rule_score, anomaly_score, total_risk_score, risk_level, computed_at)`
- `alerts(id, login_event_id, risk_score_id, level, status, assigned_to, created_at)`
- `incidents(id, alert_id, status, classification, notes, closed_at)`
- `audit_logs(id, actor_id, action, resource, before_state, after_state, timestamp)`
- `trusted_list(id, type, value, mode, note)`

### 4.3. ml_service schema
- `anomaly_scores(id, login_event_id, raw_score, normalized_score, is_anomaly, model_version, model_type, reason_codes, computed_at)`
- `model_versions(id, version, trained_at, metrics_json, status, file_path)`

## 5. Phân công module → người

| Người | Module | Phụ trách | Repo folder |
|-------|--------|-----------|-------------|
| **Sony** | core-app | Auth, User/Role, Session, MFA, Attack scripts (chạy login liên tục để test) | `core-app/` |
| **Tuấn Anh** | detection-engine | Rule Engine, Risk Engine, Alert Engine, SOC Dashboard backend | `detection-engine/` |
| **Khang** | ml-service | Feature Pipeline, Isolation Forest, Inference API, Data generator | `ml-service/` |

**Shared**:
- Tôi (Cursor): tạo `docker-compose.yml`, OpenAPI spec chung, ERD doc, báo cáo mục 3.1.
- Mỗi người **tự viết test cho module của mình** (TDD theo `/tdd`).

## 6. Cấu trúc repo (monorepo)

```
sentinel-auth/
├── README.md
├── CONTEXT.md
├── PLAN.md                      # ← file này (lớp 1)
├── TICKETS.md                   # ← lớp 2
├── ROADMAP.md                   # ← lớp 3
├── docker-compose.yml           # postgres + 3 service + (frontend sau)
├── docs/
│   ├── api-contract.yml         # OpenAPI 3.0 spec chung
│   ├── erd.puml
│   ├── yeu-cau-chuc-nang-3.1.md
│   ├── use-case.puml            # đã render PNG
│   ├── class.puml
│   ├── sequence-*.puml
│   └── diagrams/                # PNG output
├── core-app/                    # Sony
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   └── tests/
│   └── README.md
├── detection-engine/            # Tuấn Anh
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── app/
│   └── tests/
└── ml-service/                  # Khang
    ├── pyproject.toml
    ├── Dockerfile
    ├── app/
    ├── models/                  # trained model files (.pkl hoặc .joblib)
    └── tests/
```

## 7. Tech stack chi tiết

### 7.1. Shared
- Python 3.11+
- FastAPI (async)
- Pydantic v2 (validate + serialize)
- SQLAlchemy 2.0 + Alembic (migration)
- pytest + httpx (test)
- Poetry hoặc pip-tools cho dependency
- Docker + docker-compose
- OpenAPI 3.0 (FastAPI tự sinh)

### 7.2. ml-service thêm
- scikit-learn (IsolationForest)
- pandas + numpy (feature engineering)
- joblib (save/load model)
- MLflow (optional, để track model version)

### 7.3. detection-engine thêm
- httpx (gọi ml-service)
- jinja2 (template cho dashboard nếu không có frontend riêng)

### 7.4. Data synthetic
- Một script `ml-service/scripts/generate_synthetic.py` sinh ~ 10.000 dòng login giả:
  - 70% login bình thường (cùng giờ, cùng IP, cùng thiết bị).
  - 30% login bất thường (impossible travel, brute force, new device lúc 3 giờ sáng).
- Lưu vào `login_events` hypertable trong detection_db.

## 8. Yêu cầu dữ liệu cho Khang (data spec)

> Khang tự quyết cách implement, nhưng phải đạt các yêu cầu sau:

1. **Số lượng**: ≥ 10.000 dòng login event.
2. **Phân bố**: 70% bình thường, 30% bất thường (có nhãn để đánh giá).
3. **Features tối thiểu**: hour_of_day, fail_count_window_24h, ip_change_rate_7d, new_device_flag, avg_time_between_logins_sec, deviation_score, source_ip (one-hot hoặc hash), device_id (hash).
4. **Model**: IsolationForest, `contamination=0.3` (do 30% là bất thường), `random_state=42`.
5. **Đánh giá**: Tính precision/recall/F1 trên tập test (80/20 split), lưu vào `model_versions.metrics_json`.
6. **API**: `/internal/ml/score` trả về `normalized_score ∈ [0,1]` và `is_anomaly: bool` với threshold = 0.5.
7. **Reproducibility**: seed random, log model version.
8. **Lưu model**: `ml-service/models/iforest-{version}.joblib`.

## 9. Tiêu chí "done" cho mỗi giai đoạn

- **Giai đoạn 1 (Spec xong)**: OpenAPI spec + ERD + Plan 3 lớp ✅ đang làm.
- **Giai đoạn 2 (Skeleton chạy được)**: `docker-compose up` → 3 service lên, health check pass, Swagger UI truy cập được.
- **Giai đoạn 3 (Core flow)**: User login → core-app tạo session → detection-engine nhận event → gọi ml-service → trả risk score → tạo alert nếu HIGH.
- **Giai đoạn 4 (SOC Dashboard)**: SOC login → xem alerts → chuyển trạng thái → audit log ghi nhận.
- **Giai đoạn 5 (Polish + báo cáo)**: Báo cáo Word có đầy đủ diagram (PNG), test coverage ≥ 60%, README từng service.

## 10. Câu hỏi open

1. Frontend: chọn Streamlit (đơn giản) hay Next.js (đẹp) — quyết khi giai đoạn 2.
2. Có cần MLflow track model không — optional.
3. Có cần rate-limit API gateway không — optional, bỏ qua nếu không có thời gian.
4. Alert qua Telegram có cần test thật không — fake token OK cho demo.

---

**Bước tiếp theo**: đọc `TICKETS.md` (lớp 2) để thấy việc cụ thể cho từng người, rồi `ROADMAP.md` (lớp 3) để biết thứ tự làm.