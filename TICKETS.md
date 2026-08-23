# Tickets — sentinel-auth

> Tài liệu này là **LỚP 2** trong bộ 3 lớp plan. Mỗi ticket là self-contained, khai báo blocking edges, có thể làm song song khi blockers đã xong.
>
> Quy ước đánh mã: `TICKET-{MODULE}-{STORY}-{NN}`
> - `MODULE`: `CORE` | `DET` | `ML` | `INFRA` | `DOCS`
> - `STORY`: viết tắt (vd: `AUTH`, `RULE`, `MLAPI`)
> - `NN`: số thứ tự

---

## Tổng quan dependency graph

```
[INFRA-01 docker skeleton] ──► [INFRA-02 OpenAPI spec] ──► [INFRA-03 ERD doc]
                                          │
                                          ▼
        ┌─────────────────────────────────┼─────────────────────────────────┐
        ▼                                 ▼                                 ▼
[CORE-* tickets]                    [DET-* tickets]                    [ML-* tickets]
        │                                 │                                 │
        └─────────────────────────────────┼─────────────────────────────────┘
                                          ▼
                            [INFRA-04 end-to-end test]
                                          │
                                          ▼
                            [DOCS-01 báo cáo Word mục 3.1]
```

---

## Tickets INFRA (chung, do tôi/Cursor làm)

### TICKET-INFRA-01 — Docker skeleton
**Priority**: P0 — chặn tất cả các ticket khác.
**Mô tả**: Tạo `docker-compose.yml` ở root repo với 3 services (core-app, detection-engine, ml-service) + 2 Postgres instances (1 cho core_app, 1 cho detection_engine+ml_service) hoặc 1 Postgres với 3 schemas (tùy quyết ở PLAN). Mount volume, network chung.
**Acceptance criteria**:
- `docker-compose up -d` chạy thành công.
- Mỗi service có healthcheck endpoint `/health` trả 200.
- Tôi có thể truy cập Swagger UI của cả 3 service.
**Files tạo**: `docker-compose.yml`, `core-app/Dockerfile`, `detection-engine/Dockerfile`, `ml-service/Dockerfile`, `.env.example`.
**Estimate**: 2 giờ.

### TICKET-INFRA-02 — OpenAPI contract
**Priority**: P0 — chặn CORE/DET/ML.
**Mô tả**: Viết OpenAPI 3.0 spec định nghĩa tất cả endpoint giữa 3 service (đã liệt kê trong PLAN.md mục 3) và giữa user với hệ thống (auth, dashboard).
**Acceptance criteria**:
- File `docs/api-contract.yml` đầy đủ.
- Mỗi service có thể copy phần của mình để generate code (FastAPI tự động).
- Có 1 endpoint Swagger chung cho cả hệ thống.
**Estimate**: 3 giờ.

### TICKET-INFRA-03 — ERD diagram
**Priority**: P1 — cần cho báo cáo 3.1.
**Mô tả**: Vẽ ERD cho cả 3 schema (core_app, detection_engine, ml_service) bằng PlantUML hoặc Mermaid, lưu `docs/erd.puml` và `docs/diagrams/erd.png`.
**Acceptance criteria**:
- ERD hiển thị đủ 18 entity từ PLAN mục 4.
- Quan hệ primary key / foreign key rõ ràng.
- Có legend giải thích ký hiệu.
**Estimate**: 1 giờ.

### TICKET-INFRA-04 — End-to-end smoke test
**Priority**: P1 — sau khi 3 service có flow cơ bản.
**Mô tả**: Viết script `tests/e2e/test_smoke.py` chạy flow: user login → detection nhận event → ml trả score → alert được tạo nếu HIGH.
**Acceptance criteria**:
- Script chạy được trên môi trường docker-compose.
- Pass/Fail rõ ràng.
- Logging chi tiết để debug.
**Estimate**: 2 giờ.

### TICKET-INFRA-05 — Database migration scripts (Alembic)
**Priority**: P1 — sau khi INFRA-01.
**Mô tả**: Tạo Alembic migration cho cả 3 schema. Init cho cả 3 service, migration đầu tiên tạo tables theo PLAN mục 4.
**Acceptance criteria**:
- `alembic upgrade head` chạy thành công cho cả 3 DB.
- Tables đúng schema như PLAN.
- TimescaleDB extension được enable và `login_events` là hypertable.
**Estimate**: 2 giờ.

---

## Tickets CORE-APP (Sony)

### TICKET-CORE-AUTH-01 — User registration & password hashing
**Blockers**: INFRA-01, INFRA-02.
**Mô tả**: API đăng ký user (admin tạo), hash mật khẩu Argon2id, validate password theo AuthPolicy.
**Endpoints**: `POST /api/v1/users`, `GET /api/v1/users/{id}`.
**Acceptance**: 
- Tạo user mới, hash lưu DB không thể giải mã.
- Validate password ≥ 8 ký tự, có chữ hoa, chữ thường, số.
- Unit test ≥ 3 case.
**Estimate**: 3 giờ.

### TICKET-CORE-AUTH-02 — Login endpoint
**Blockers**: TICKET-CORE-AUTH-01.
**Mô tả**: `POST /api/v1/auth/login` nhận username/password, kiểm tra tài khoản ACTIVE, xác minh password, tạo `LoginEvent` (gọi detection-engine ngay sau đó), trả session token.
**Acceptance**:
- 200 OK trả access_token + refresh_token.
- 401 nếu sai mật khẩu, không leak thông tin user tồn tại hay không.
- 423 (Locked) nếu quá số lần sai.
- Rate limit 5 lần/phút/IP.
- Test happy path + 3 case lỗi.
**Estimate**: 4 giờ.

### TICKET-CORE-AUTH-03 — MFA challenge
**Blockers**: TICKET-CORE-AUTH-02.
**Mô tả**: API sinh OTP (TOTP hoặc email-based cho demo), lưu hash vào `mfa_challenges`, endpoint verify OTP, tạo session.
**Endpoints**: `POST /api/v1/auth/mfa/challenge`, `POST /api/v1/auth/mfa/verify`.
**Acceptance**:
- OTP hết hạn sau 60 giây.
- Sai OTP quá 3 lần → khóa tạm challenge.
- Test happy + fail + expire.
**Estimate**: 4 giờ.

### TICKET-CORE-AUTH-04 — Role-based access control (RBAC)
**Blockers**: TICKET-CORE-AUTH-01.
**Mô tả**: Middleware kiểm tra role của user (USER/SOC_ANALYST/SECURITY_ADMIN/SECURITY_MANAGER) trước khi cho truy cập endpoint.
**Acceptance**:
- Mỗi endpoint khai báo role yêu cầu (qua dependency injection).
- 403 nếu không đủ quyền.
- Test 4 role × 3 endpoint.
**Estimate**: 2 giờ.

### TICKET-CORE-USER-01 — User management API (Admin)
**Blockers**: TICKET-CORE-AUTH-04.
**Mô tả**: CRUD user, gán role, khóa/mở khóa user.
**Endpoints**: `GET/POST/PATCH/DELETE /api/v1/users`, `POST /api/v1/users/{id}/lock`, `POST /api/v1/users/{id}/unlock`.
**Acceptance**:
- Soft delete (không xóa vĩnh viễn).
- Mỗi thao tác ghi AuditLog.
- Pagination, search.
**Estimate**: 4 giờ.

### TICKET-CORE-USER-02 — Session & trusted device management
**Blockers**: TICKET-CORE-AUTH-02.
**Mô tả**: API liệt kê session, thu hồi session, quản lý trusted device.
**Endpoints**: `GET /api/v1/users/me/sessions`, `DELETE /api/v1/sessions/{id}`, `GET/POST/DELETE /api/v1/users/me/devices`.
**Acceptance**:
- User chỉ thấy session của mình.
- Thu hồi session làm token vô hiệu ngay lập tức.
- Test cross-user access bị chặn.
**Estimate**: 3 giờ.

### TICKET-CORE-INTEG-01 — Push login event to detection-engine
**Blockers**: TICKET-CORE-AUTH-02, INFRA-01.
**Mô tả**: Sau khi xác thực, fire-and-forget gửi `LoginEvent` đến `detection-engine` qua HTTP. Dùng httpx async, có retry 3 lần.
**Acceptance**:
- Event được gửi không block response cho user (background task).
- Nếu detection-engine down, log warning, không fail login.
- Test mock detection-engine nhận đúng payload.
**Estimate**: 2 giờ.

### TICKET-CORE-INTEG-02 — Receive action from detection-engine
**Blockers**: TICKET-CORE-AUTH-04, TICKET-CORE-USER-02.
**Mô tả**: Endpoint `/internal/users/{id}/actions` nhận yêu cầu từ detection-engine: REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER, RATE_LIMIT_IP. Áp dụng action lên user/session thật.
**Acceptance**:
- Mỗi action có audit log.
- REVOKE_SESSIONS invalid token ngay.
- LOCK_USER set `status = LOCKED` + `locked_until`.
- Test 4 action types.
**Estimate**: 3 giờ.

### TICKET-CORE-ATK-01 — Attack scripts (cho demo)
**Blockers**: TICKET-CORE-AUTH-02.
**Mô tả**: Script sinh traffic login giả để demo hệ thống phát hiện:
- Normal login (10 user mỗi 30 phút).
- Brute force (5 user, 100 lần sai/IP).
- Impossible travel (1 user login HCM rồi 5 phút sau login từ US).
- New device lúc 3 giờ sáng.
**Acceptance**:
- Mỗi scenario chạy được 1 lệnh.
- Output log thấy alert tương ứng được tạo.
**Estimate**: 3 giờ.

---

## Tickets DETECTION-ENGINE (Tuấn Anh)

### TICKET-DET-RULE-01 — Rule data model & seed
**Blockers**: INFRA-01, INFRA-05.
**Mô tả**: Tạo model `Rule` trong SQLAlchemy. Seed 6 rule từ day2.docx mục 5.3 (RULE-001 đến RULE-006).
**Acceptance**:
- 6 rule được insert với weight + threshold mặc định.
- Admin có thể bật/tắt qua API.
**Estimate**: 2 giờ.

### TICKET-DET-RULE-02 — Rule evaluation engine
**Blockers**: TICKET-DET-RULE-01.
**Mô tả**: Implement 6 rule (RULE-001..006). Mỗi rule là 1 class implement interface `evaluate(event) -> Optional[RuleHit]`.
**Acceptance**:
- Mỗi rule có unit test riêng với 2 case (pass/fail).
- Tổng hợp `rule_score = Σ weight_i × hit_i`, chuẩn hóa về [0,1].
- Đo thời gian xử lý < 100ms / event.
**Estimate**: 6 giờ.

### TICKET-DET-RISK-01 — Risk engine aggregation
**Blockers**: TICKET-DET-RULE-02.
**Mô tả**: Nhận `rule_score` từ rule engine + `anomaly_score` từ ml-service → tính `total_risk_score = 0.4×rule + 0.6×anomaly` (trọng số cấu hình), map sang `risk_level`: LOW <0.3, MEDIUM <0.6, HIGH <0.85, CRITICAL ≥0.85.
**Acceptance**:
- Test 5 case boundary (0, 0.29, 0.3, 0.6, 0.85, 1.0).
- Lưu `RiskScore` row.
- Configurable weights (đọc từ env hoặc DB).
**Estimate**: 3 giờ.

### TICKET-DET-ALERT-01 — Alert & Incident management
**Blockers**: TICKET-DET-RISK-01.
**Mô tả**: Khi `risk_level = HIGH hoặc CRITICAL`, tạo `Alert(status=NEW)` + `Incident(status=OPEN)`. Gửi notification qua Telegram (fake OK).
**Acceptance**:
- API list/get/update status alert.
- Filter theo level, status, thời gian.
- Pagination.
**Estimate**: 4 giờ.

### TICKET-DET-INTEG-01 — Receive login event from core-app
**Blockers**: TICKET-DET-RULE-01.
**Mô tả**: Endpoint `/internal/login-events` nhận event từ core-app. Lưu `LoginEvent` vào TimescaleDB hypertable. Trigger rule + ml evaluation.
**Acceptance**:
- Validate schema nghiêm ngặt.
- Idempotency: nếu event_id đã tồn tại → bỏ qua.
- Test concurrent insert không lỗi.
**Estimate**: 3 giờ.

### TICKET-DET-INTEG-02 — Call ml-service for anomaly score
**Blockers**: TICKET-DET-INTEG-01, TICKET-ML-API-01.
**Mô tả**: Sau khi nhận event, build feature vector, gọi `ml-service /internal/ml/score`, lưu `AnomalyScore`.
**Acceptance**:
- Timeout 500ms.
- Retry 2 lần nếu lỗi.
- Fallback anomaly_score = 0 nếu fail hết.
- Test với ml-service mock.
**Estimate**: 3 giờ.

### TICKET-DET-INTEG-03 — Push action to core-app
**Blockers**: TICKET-DET-ALERT-01.
**Mô tả**: Khi alert level = CRITICAL, gọi `core-app /internal/users/{id}/actions` với action REVOKE_SESSIONS hoặc LOCK_USER.
**Acceptance**:
- Configurable actions theo level.
- Ghi log khi gọi.
**Estimate**: 2 giờ.

### TICKET-DET-API-01 — SOC Dashboard API
**Blockers**: TICKET-DET-ALERT-01.
**Mô tả**: API cho SOC frontend:
- `GET /api/v1/alerts` (filter, paginate)
- `GET /api/v1/alerts/{id}` (kèm rule_hits, risk_score, anomaly_score, login_event)
- `PATCH /api/v1/alerts/{id}` (status update + notes)
- `GET /api/v1/login-events` (search theo user, IP, time)
- `GET /api/v1/dashboard/stats` (count by level, trend 7 ngày)
**Acceptance**:
- Mỗi API có OpenAPI doc.
- Test integration với database seed data.
**Estimate**: 5 giờ.

### TICKET-DET-AUDIT-01 — Audit log cho mọi thay đổi
**Blockers**: TICKET-DET-RULE-01.
**Mô tả**: Middleware tự động ghi AuditLog cho mọi PATCH/POST/DELETE. Capture actor (từ JWT), resource, before/after state.
**Acceptance**:
- API `GET /api/v1/audit-logs` với filter.
- AuditLog không thể sửa/xóa qua UI.
**Estimate**: 3 giờ.

---

## Tickets ML-SERVICE (Khang)

### TICKET-ML-DATA-01 — Synthetic data generator
**Blockers**: INFRA-01.
**Mô tả**: Script `scripts/generate_synthetic.py` sinh 10.000 login event với 70% bình thường + 30% bất thường. Lưu vào detection_db (qua detection-engine endpoint hoặc trực tiếp hypertable nếu được phép).
**Features**:
- hour_of_day: 0-23
- fail_count_window_24h: 0-20
- ip_change_rate_7d: 0-1
- new_device_flag: bool
- avg_time_between_logins_sec: 60-86400
- deviation_score: 0-1
**Acceptance**:
- File CSV/Parquet xuất ra ngoài.
- Insert vào DB thành công.
- Reproducible (random_state=42).
**Estimate**: 4 giờ.

### TICKET-ML-FEAT-01 — Feature pipeline
**Blockers**: TICKET-ML-DATA-01.
**Mô tả**: Module `app/features.py` nhận LoginEvent → trả FeatureVector (dict). Query DB để lấy history user (fail count, IP change rate, etc.).
**Acceptance**:
- Test với 5 user khác nhau, kết quả feature hợp lý.
- Query DB hiệu quả (có index).
**Estimate**: 4 giờ.

### TICKET-ML-MODEL-01 — Train Isolation Forest
**Blockers**: TICKET-ML-DATA-01.
**Mô tả**: Script `scripts/train.py` load data → train IsolationForest với contamination=0.3, random_state=42 → save model `.joblib` vào `models/iforest-{version}.joblib`. Tính metrics precision/recall/F1, lưu vào `model_versions` table.
**Acceptance**:
- Model file < 50MB.
- Metrics F1 ≥ 0.6 (target tối thiểu cho synthetic).
- Reproducible.
**Estimate**: 4 giờ.

### TICKET-ML-API-01 — Inference API
**Blockers**: TICKET-ML-MODEL-01, TICKET-ML-FEAT-01.
**Mô tả**: FastAPI endpoint `POST /internal/ml/score` nhận features → load model → predict → chuẩn hóa score về [0,1] (dùng min-max scaling dựa trên training) → trả response.
**Acceptance**:
- Latency < 200ms p95.
- Test 3 case: normal, anomaly, edge case.
**Estimate**: 3 giờ.

### TICKET-ML-MODEL-02 — Model versioning & retrain endpoint
**Blockers**: TICKET-ML-MODEL-01.
**Mô tả**: Table `model_versions` track version + metrics. Endpoint `POST /internal/ml/train` (admin only) trigger train lại. Inference luôn dùng model có status=ACTIVE mới nhất.
**Acceptance**:
- Train xong → mark ACTIVE, version cũ RETIRED.
- Test reload model không cần restart service.
**Estimate**: 3 giờ.

### TICKET-ML-OPS-01 — Healthcheck & model info
**Blockers**: TICKET-ML-API-01.
**Mô tả**: Endpoint `/health` trả 200 + version model hiện tại. Endpoint `/internal/ml/model-info` trả metrics + training date.
**Acceptance**:
- Docker healthcheck dùng `/health`.
- Test fail khi model chưa load.
**Estimate**: 1 giờ.

---

## Tickets DOCS (báo cáo)

### TICKET-DOCS-01 — Render tất cả PlantUML sang PNG
**Blockers**: INFRA-03.
**Mô tả**: Tôi/Cursor chạy PlantUML → sinh PNG cho use-case, class, sequence, erd. Lưu `docs/diagrams/`.
**Acceptance**:
- 7+ PNG files.
- PNG chất lượng đủ chèn Word.
**Estimate**: 30 phút.

### TICKET-DOCS-02 — Hoàn thiện mục 3.1 báo cáo Word
**Blockers**: TICKET-DOCS-01.
**Mô tả**: Đưa 4 sơ đồ (Use-case, Class, 5 Sequence) + đặc tả UC vào file Word báo cáo. Format heading 3.1.1, 3.1.2, 3.1.3, 3.1.4.
**Acceptance**:
- File Word nằm trong `docs/bao-cao-3.1.docx`.
- Heading đúng cấu trúc.
- Ảnh có caption.
**Estimate**: 2 giờ.

### TICKET-DOCS-03 — README từng service
**Blockers**: CORE/USER-01, DET/API-01, ML/API-01.
**Mô tả**: Mỗi service có README riêng: kiến trúc, cách chạy local, API docs, biến môi trường, test.
**Estimate**: 2 giờ.

---

## Tổng kết

| Module | Số ticket | Estimate tổng |
|--------|-----------|---------------|
| INFRA | 5 | 10 giờ |
| CORE (Sony) | 9 | 28 giờ (~3.5 ngày) |
| DET (Tuấn Anh) | 8 | 28 giờ (~3.5 ngày) |
| ML (Khang) | 6 | 19 giờ (~2.5 ngày) |
| DOCS | 3 | 4.5 giờ |

**Cả nhóm song song được**: Sau khi INFRA-01 + INFRA-02 + INFRA-05 xong (khoảng 1-2 ngày đầu), 3 người có thể làm song song độc lập.

---

**Bước tiếp theo**: đọc `ROADMAP.md` để biết thứ tự ticket nào nên làm trước theo tuần.