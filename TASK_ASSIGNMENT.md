# TASK ASSIGNMENT - SENTINEL AUTH v3.3

> **Ngày tạo:** 2026-09-21
> **Kiến trúc:** 1 FastAPI monorepo + 3 schema ownership
> **Quy tắc:** Mỗi người CHỈ sửa folder/file của mình, KHÔNG đụng folder người khác

---

## 🎯 TỔNG QUAN

| Thành viên | Branch | Schema Owner | Folder Owner |
|-----------|--------|--------------|--------------|
| **Sony** | `core-app` | `core_auth` | `app/api/sony/`, `app/models/sony/`, `app/services/sony/`, `tests/test_sony/` |
| **Tuấn Anh** | `detection-engine` | `detection_soc` | `app/api/tuananh/`, `app/models/tuananh/`, `app/services/tuananh/`, `tests/test_tuananh/` |
| **Khang** | `ml-service` | `ml_manager` | `app/api/khang/`, `app/models/khang/`, `app/services/khang/`, `tests/test_khang/` |

---

## 📁 CẤU TRÚC FOLDER (MỤC TIÊU)

```
sentinel-auth/
├── app/
│   ├── main.py                    # [LEAD ONLY] - Shared entrypoint
│   ├── core/                      # [LEAD ONLY] - Shared config (passwords, settings, tokens)
│   ├── database.py                # [LEAD ONLY] - DB connection
│   ├── api/
│   │   ├── sony/                  # [SONY] - auth_router, user_router
│   │   ├── tuananh/               # [TUẤN ANH] - detection_router, alert_router, admin_router
│   │   └── khang/                 # [KHANG] - ml_router, manager_router
│   ├── models/
│   │   ├── sony/                  # [SONY] - identity, auth, enums
│   │   ├── tuananh/               # [TUẤN ANH] - alerts, policies, login_attempts
│   │   └── khang/                 # [KHANG] - model_versions, inference_logs
│   └── services/
│       ├── sony/                  # [SONY] - authentication, mailer, rate_limit
│       ├── tuananh/               # [TUẤN ANH] - rule_engine, risk_scoring, soc_workflow
│       └── khang/                 # [KHANG] - ml_inference, model_registry
├── infra/postgres/
│   ├── schema-sony.sql            # [SONY] - core_auth schema
│   ├── schema-tuananh.sql         # [TUẤN ANH] - detection_soc schema
│   └── schema-khang.sql           # [KHANG] - ml_manager schema
├── tests/
│   ├── test_sony/                 # [SONY]
│   ├── test_tuananh/              # [TUẤN ANH]
│   └── test_khang/                # [KHANG]
├── docker-compose.yml             # [LEAD]
├── requirements.txt               # [LEAD + MEMBERS add deps riêng]
└── README.md                      # [LEAD]
```

---

## 🚫 QUY TẮC PHÂN QUYỀN

### ✅ Được phép
- Tự do sửa file trong folder của mình
- Thêm dependencies mới vào `requirements.txt` (ghi comment tên mình)
- Tạo migrations cho schema của mình
- Commit + push lên branch riêng

### ❌ KHÔNG được
- Sửa file trong folder của người khác
- Sửa `app/main.py`, `app/core/`, `app/database.py` (cần tạo issue cho lead)
- Sửa `schema-*.sql` của người khác
- Merge trực tiếp vào `main` (chỉ vào `dev`)
- Force push

### 📞 Khi cần sửa shared
1. Tạo issue trên GitHub với label `shared-change`
2. Ping lead (@Albert-Tuan)
3. Chờ approval mới sửa

---

## 👤 SONY - USER & AUTH (Role: USER + AUTHENTICATION)

### Branch: `core-app`

### Schema owner: `core_auth` (13 tables)
- `users`
- `roles`
- `user_roles`
- `sessions`
- `mfa_transactions`
- `mfa_notifications`
- `audit_logs`
- `user_trusted_devices`
- `user_notifications`
- `ip_addresses`
- `rate_limits`
- `system_settings`
- `outbox_events`

### Folder owner
```
app/api/sony/
├── __init__.py
├── auth_router.py        # UC-AU-02, UC-AU-05
├── user_router.py        # UC-AU-01 (đăng ký)
├── mfa_router.py         # UC-AU-03 (email OTP)
├── session_router.py     # UC-AU-04 (logout, refresh)
└── trusted_device_router.py  # UC-AU-05

app/models/sony/
├── __init__.py
├── identity.py           # User, Role, UserRole
├── session.py            # Session model
├── mfa.py                # MfaTransaction, MfaNotification
├── audit.py              # AuditLog
├── device.py             # UserTrustedDevice
├── outbox.py             # OutboxEvent (transactional)
├── enums.py              # UserStatus, MfaType, MfaStatus
└── notifications.py      # UserNotification

app/services/sony/
├── __init__.py
├── authentication.py     # Login logic, password verify
├── password_service.py   # Hash/verify
├── token_service.py      # JWT issue/verify
├── mailer.py             # OTP email service
├── mfa_service.py        # MFA workflow
├── rate_limit_service.py # Rate limiting
└── outbox_service.py     # Publish events to detection-engine
```

### Use Cases phụ trách
| UC | Tên | Actor | Độ ưu tiên |
|----|------|-------|-----------|
| UC-AU-01 | Đăng ký tài khoản | User | 🔴 Bắt buộc |
| UC-AU-02 | Đăng nhập | User | 🔴 Bắt buộc |
| UC-AU-03 | Xác minh Email OTP | User | 🔴 Bắt buộc |
| UC-AU-04 | Logout và quản lý session | User | 🔴 Bắt buộc |
| UC-AU-05 | Refresh token | User | 🔴 Bắt buộc |
| UC-AU-05-2 | Quản lý thiết bị tin cậy | User | 🟡 Nên có |

### Deliverables
- [ ] `infra/postgres/schema-sony.sql` (13 tables từ `schema-core-v3.3.sql`)
- [ ] `app/api/sony/*.py` - 5 routers
- [ ] `app/models/sony/*.py` - 8 models
- [ ] `app/services/sony/*.py` - 7 services
- [ ] `tests/test_sony/test_authentication.py`
- [ ] `tests/test_sony/test_mfa.py`
- [ ] `tests/test_sony/test_session.py`
- [ ] `tests/test_sony/conftest.py`
- [ ] Outbox: publish `LoginEvent` event sau mỗi login attempt

### Contract với services khác (KHÔNG tự ý sửa, dùng đúng spec)
```json
// Publish to outbox
{
  "event_type": "LoginEvent",
  "payload": {
    "event_id": "uuid",
    "user_id": "uuid or null",
    "username_attempted": "string",
    "outcome": "success | failed",
    "mfa_used": "boolean",
    "ip_address": "string",
    "user_agent": "string",
    "timestamp": "ISO 8601"
  }
}
```

### Tài liệu tham chiếu
- `docs/01-bang-yeu-cau-chuc-nang-nghiep-vu-core-app.md`
- `docs/02-dac-ta-use-case-core-app.md` → UC-AU-*
- `docs/03-phan-tich-doi-tuong-su-dung-phan-mem-core-app.md`
- `infra/postgres/schema-core-v3.3.sql` (cắt 13 tables)

---

## 👤 TUẤN ANH - SOC ANALYST + SECURITY ADMIN + DETECTION ENGINE

### Branch: `detection-engine`

### Schema owner: `detection_soc` (7 tables)
- `policies`
- `login_attempts`
- `risk_assessments`
- `detection_logs`
- `alerts`
- `alert_timeline`
- `soc_analysts`

### Folder owner
```
app/api/tuananh/
├── __init__.py
├── detection_router.py    # UC-DE-01 (nhận LoginEvent)
├── alert_router.py        # UC-SOC-01 (danh sách alerts)
├── soc_workflow_router.py # UC-SOC-02/03 (acknowledge/resolve)
├── admin_router.py        # UC-SA-01/02 (admin endpoints)
├── audit_router.py        # UC-SA-03 (audit logs)
├── dashboard_router.py    # UC-DE-08 (SOC dashboard)
└── policy_router.py       # UC-DE-15 (quản lý policies)

app/models/tuananh/
├── __init__.py
├── login_attempt.py       # LoginAttempt
├── risk_assessment.py     # RiskAssessment
├── detection_log.py       # DetectionLog
├── alert.py               # Alert
├── alert_timeline.py      # AlertTimeline
├── policy.py              # Policy
├── soc_analyst.py         # SocAnalyst
└── enums.py               # RiskLevel, AlertStatus, Outcome

app/services/tuananh/
├── __init__.py
├── rule_engine.py         # UC-DE-04
├── feature_builder.py     # UC-DE-02 (6 features)
├── risk_scoring.py        # UC-DE-05
├── ml_client.py           # UC-DE-03 (HTTP client → khang)
├── soc_workflow.py        # UC-DE-09 → UC-DE-13
├── dashboard_service.py   # UC-DE-08
├── admin_service.py       # UC-SA-01 → UC-SA-03
└── policy_service.py      # UC-DE-15
```

### Use Cases phụ trách
| UC | Tên | Actor | Độ ưu tiên |
|----|------|-------|-----------|
| UC-DE-01 | Nhận LoginEvent | Core App | 🔴 Bắt buộc |
| UC-DE-02 | Build Features (6 features) | Hệ thống | 🔴 Bắt buộc |
| UC-DE-03 | Gọi ML Service | Hệ thống | 🔴 Bắt buộc |
| UC-DE-04 | Evaluate Rules | Hệ thống | 🔴 Bắt buộc |
| UC-DE-05 | Calculate Risk Score | Hệ thống | 🔴 Bắt buộc |
| UC-DE-06 | Tạo Alert | Hệ thống | 🔴 Bắt buộc |
| UC-DE-07 | Gửi Action về Core | Hệ thống | 🔴 Bắt buộc |
| UC-DE-08 | Xem SOC Dashboard | SOC Analyst | 🔴 Bắt buộc |
| UC-DE-09 | Tiếp nhận Alert | SOC Analyst | 🔴 Bắt buộc |
| UC-DE-10 | Điều tra Alert | SOC Analyst | 🔴 Bắt buộc |
| UC-DE-11 | Xem Evidence | SOC Analyst | 🔴 Bắt buộc |
| UC-DE-12 | Phân loại Alert | SOC Analyst | 🔴 Bắt buộc |
| UC-DE-13 | Yêu cầu Action | SOC Analyst | 🔴 Bắt buộc |
| UC-DE-14 | Tra cứu Login History | SOC Analyst | 🔴 Bắt buộc |
| UC-DE-15 | Quản lý Policy | Security Admin | 🔴 Bắt buộc |
| UC-SOC-01 | Xem danh sách alerts | SOC Analyst | 🔴 Bắt buộc |
| UC-SOC-02 | Acknowledge alert | SOC Analyst | 🔴 Bắt buộc |
| UC-SOC-03 | Resolve alert | SOC Analyst | 🔴 Bắt buộc |
| UC-SA-01 | Quản lý account | Security Admin | 🔴 Bắt buộc |
| UC-SA-02 | Rule Versioning | Security Admin | 🔴 Bắt buộc |
| UC-SA-03 | Xem Audit Logs | Security Admin | 🔴 Bắt buộc |

### Deliverables
- [ ] `infra/postgres/schema-tuananh.sql` (7 tables từ `schema-detection-v3.3.sql`)
- [ ] `app/api/tuananh/*.py` - 7 routers
- [ ] `app/models/tuananh/*.py` - 8 models
- [ ] `app/services/tuananh/*.py` - 8 services
- [ ] `tests/test_tuananh/test_rule_engine.py`
- [ ] `tests/test_tuananh/test_risk_scoring.py`
- [ ] `tests/test_tuananh/test_soc_workflow.py`
- [ ] `tests/test_tuananh/conftest.py`
- [ ] HTTP client gọi sang Khang: `POST /internal/score`

### Risk Scoring Formula
```
Risk_Score = 0.4 × Rule_Score + 0.6 × ML_Score
```

| Risk Level | Threshold | Action |
|-----------|-----------|--------|
| LOW | < 0.25 | Allow |
| MEDIUM | 0.25 - 0.50 | Allow (log) |
| HIGH | 0.50 - 0.75 | Challenge (MFA) |
| CRITICAL | > 0.75 | Block + Alert |

### Tài liệu tham chiếu
- `docs/04-bang-yeu-cau-chuc-nang-nghiep-vu-detection-engine.md`
- `docs/05-dac-ta-use-case-detection-engine.md` → UC-DE-*, UC-SOC-*
- `docs/06-phan-tich-doi-tuong-su-dung-detection-engine.md`
- `infra/postgres/schema-detection-v3.3.sql` (cắt 7 tables)

---

## 👤 KHANG - SECURITY MANAGER + ML SERVICE

### Branch: `ml-service`

### Schema owner: `ml_manager` (3 tables + 1 view)
- `model_versions`
- `inference_logs`
- `feature_statistics`
- `manager_dashboard` (view tổng hợp từ detection_soc)

### Folder owner
```
app/api/khang/
├── __init__.py
├── ml_router.py              # UC-ML-01 → UC-ML-07 (nhận score request từ tuananh)
├── model_registry_router.py  # UC-ML-09 (quản lý model versions)
├── health_router.py          # UC-ML-08
├── manager_router.py         # UC-M-01, UC-M-02 (dashboard + reports)
└── reports_router.py         # Xuất báo cáo tổng hợp

app/models/khang/
├── __init__.py
├── model_version.py          # ModelVersion
├── inference_log.py          # InferenceLog
├── feature_statistics.py     # FeatureStatistics
└── enums.py                  # ModelStatus

app/services/khang/
├── __init__.py
├── ml_inference.py           # UC-ML-04 (Isolation Forest predict)
├── model_registry.py         # UC-ML-09
├── score_normalizer.py       # UC-ML-05 (calibrate 0-1)
├── reason_code_generator.py  # UC-ML-06
├── feature_preprocessor.py   # UC-ML-03
├── drift_monitor.py          # UC-ML-10 (data drift detection)
└── report_service.py         # Tổng hợp data cho Manager
```

### Use Cases phụ trách
| UC | Tên | Actor | Độ ưu tiên |
|----|------|-------|-----------|
| UC-ML-01 | Nhận ML Request | Detection Engine | 🔴 Bắt buộc |
| UC-ML-02 | Validate Features | Hệ thống | 🔴 Bắt buộc |
| UC-ML-03 | Feature Preprocessing | Hệ thống | 🔴 Bắt buộc |
| UC-ML-04 | ML Inference | Hệ thống | 🔴 Bắt buộc |
| UC-ML-05 | Score Normalization | Hệ thống | 🔴 Bắt buộc |
| UC-ML-06 | Generate Reason Codes | Hệ thống | 🔴 Bắt buộc |
| UC-ML-07 | Trả ML Response | Hệ thống | 🔴 Bắt buộc |
| UC-ML-08 | Health Check | Hệ thống | 🔴 Bắt buộc |
| UC-ML-09 | Model Management | Security Admin | 🔴 Bắt buộc |
| UC-ML-10 | Fallback Handling | Hệ thống | 🔴 Bắt buộc |
| UC-M-01 | Xem Dashboard tổng hợp | Security Manager | 🔴 Bắt buộc |
| UC-M-02 | Xuất báo cáo tổng hợp | Security Manager | 🔴 Bắt buộc |

### Deliverables
- [ ] `infra/postgres/schema-khang.sql` (3 tables + 1 view)
- [ ] `app/api/khang/*.py` - 6 routers
- [ ] `app/models/khang/*.py` - 4 models
- [ ] `app/services/khang/*.py` - 7 services
- [ ] `app/ml_models/` (lưu file `.pkl` model)
- [ ] `tests/test_khang/test_ml_inference.py`
- [ ] `tests/test_khang/test_model_registry.py`
- [ ] `tests/test_khang/conftest.py`
- [ ] **Train script:** `scripts/train_model.py` (tạo initial model.pkl)

### Features contract (đồng nhất với Tuấn Anh)
```json
{
  "hour_of_day": "int 0-23",
  "fail_count_24h": "int >=0",
  "ip_change_rate_7d": "float 0-1",
  "new_device": "boolean",
  "average_login_interval_seconds": "int >=0",
  "deviation_score": "float 0-1"
}
```

### ML Response contract
```json
{
  "request_id": "uuid",
  "normalized_anomaly_score": "float 0-1",
  "is_anomaly": "boolean",
  "model_version": "string",
  "reason_codes": ["unusual_time", "new_device"],
  "model_status": "ready | degraded | error"
}
```

### Manager Dashboard APIs
- `GET /manager/dashboard/overview` - tổng số alerts, users, anomalies 7 ngày qua
- `GET /manager/reports/alerts-by-day?from=...&to=...`
- `GET /manager/reports/top-risk-users`
- `GET /manager/reports/model-performance`
- `GET /manager/reports/export/pdf` - báo cáo tổng hợp

### Tài liệu tham chiếu
- `docs/03-bang-yeu-cau-chuc-nang-nghiep-vu-ml-service.md`
- `docs/04-dac-ta-use-case-ml-service.md` → UC-ML-*
- `docs/05-phan-tich-doi-tuong-su-dung-ml-service.md`
- `infra/postgres/schema-ml-service-v3.3.sql` (cắt 3 tables)

---

## 📅 TIMELINE (DỰ KIẾN)

### Tuần 1 (21/09 - 27/09): FOUNDATION
| Công việc | Owner | Deadline |
|-----------|-------|----------|
| Setup local Docker environment | Tất cả | 22/09 |
| Tạo folder structure (`app/api/sony/`...) | Tất cả | 23/09 |
| Tách schema SQL theo ownership | Tất cả | 24/09 |
| Tạo base models (SQLAlchemy) | Tất cả | 26/09 |
| Tạo base conftest + fixtures | Tất cả | 27/09 |

### Tuần 2 (28/09 - 04/10): CORE IMPLEMENTATION
| Công việc | Owner | Deadline |
|-----------|-------|----------|
| Auth flow (login, register, MFA) | Sony | 02/10 |
| Detection pipeline (rule + risk scoring) | Tuấn Anh | 02/10 |
| ML inference + model training | Khang | 02/10 |
| Contract API giữa 3 services | Lead | 03/10 |
| Cross-service integration test | Tất cả | 04/10 |

### Tuần 3 (05/10 - 11/10): WORKFLOWS
| Công việc | Owner | Deadline |
|-----------|-------|----------|
| SOC workflow (acknowledge, resolve) | Tuấn Anh | 08/10 |
| Manager dashboard | Khang | 08/10 |
| Admin endpoints (rule versioning) | Tuấn Anh | 10/10 |
| E2E tests | Tất cả | 11/10 |

### Tuần 4 (12/10 - 18/10): RELEASE
| Công việc | Owner | Deadline |
|-----------|-------|----------|
| Final bug fixing | Tất cả | 15/10 |
| Merge 3 branches → dev | Lead | 16/10 |
| Merge dev → main | Lead | 18/10 |

---

## 🤝 GIAO TIẾP

### Daily standup (15 phút, mỗi sáng 9:00)
- Mỗi người báo: hôm qua làm gì, hôm nay làm gì, có blocker gì
- Format: text trong group chat (không họp)

### Git workflow
```bash
# Mỗi người clone branch của mình
git checkout -b core-app origin/core-app        # Sony
git checkout -b detection-engine origin/detection-engine  # Tuấn Anh
git checkout -b ml-service origin/ml-service    # Khang

# Làm việc và commit
git add .
git commit -m "feat(sony): add login endpoint"

# Push lên branch riêng (KHÔNG push vào dev)
git push origin <branch-của-mình>

# Khi xong task lớn → tạo PR vào dev
# (Lead sẽ review và merge)
```

### Conflict resolution
- 2 người KHÔNG ĐƯỢC sửa cùng file
- Nếu xung đột → Ping group, lead quyết định
- Nếu cần shared change → tạo issue với label `shared-change`

---

## 📞 CONTACT

| Role | Person | Github | Telegram |
|------|--------|--------|----------|
| Lead | Albert-Tuan (Tuấn) | @Albert-Tuan | @tuan_lead |
| Member | Sony | @sony-xxx | @sony_dev |
| Member | Tuấn Anh | @tuananh-xxx | @tuananh_dev |
| Member | Khang | @khang-xxx | @khang_dev |

---

## ❓ FAQ

**Q: Tôi cần sửa `app/main.py` để thêm router của mình?**
A: KHÔNG. Tạo issue `shared-change`, lead sẽ thêm. Hoặc dùng auto-registration qua `app/api/<tên>/__init__.py`.

**Q: Tôi cần dùng model của người khác (ví dụ: User)?**
A: Được, nhưng CHỈ qua SQL JOIN hoặc HTTP API, KHÔNG import model trực tiếp từ folder người khác.

**Q: Test fixture (user mẫu) ở đâu?**
A: Mỗi người tự tạo fixture riêng trong `tests/test_<tên>/conftest.py`.

**Q: Schema khác nhau giữa 3 máy dev?**
A: Mỗi người chạy Docker riêng, schema đồng bộ qua Git (commit SQL sau mỗi thay đổi).

---

**Document Version:** 1.0
**Last Updated:** 2026-09-21
**Status:** ✅ Approved
