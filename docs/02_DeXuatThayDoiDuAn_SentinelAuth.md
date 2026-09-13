# ĐỀ XUẤT THAY ĐỔI DỰ ÁN SENTINEL AUTH
## Dựa trên đánh giá tài liệu nghiệp vụ & ML Service

> **Ngày:** 2026-09-12
> **Nguồn:** So sánh tài liệu gốc của thành viên ML với codebase hiện tại
> **Trạng thái:** Đề xuất - Cần review và approve

---

## TỔNG QUAN

Sau khi đánh giá hai tài liệu:
1. **Bảng nghiệp vụ** (bản gốc ML)
2. **Bảng yêu cầu ML Service** (bản gốc ML)

Và đối chiếu với codebase hiện tại (`app/`, `infra/postgres/schema-v3.sql`), chúng tôi đề xuất các thay đổi sau để đảm bảo:
- Tài liệu phản ánh đúng implementation
- Implementation đáp ứng đầy đủ requirements
- Không có gaps giữa specification và code

---

## I. THAY ĐỔI VỀ TÀI LIỆU

### I.1. Hoàn thiện Bảng Yêu Cầu Chức Năng Nghiệp Vụ

| # | Thay đổi | Lý do | Priority |
|---|-----------|-------|----------|
| 1 | Thêm **UC-22: Đăng ký tài khoản** và **UC-23: Refresh token** | Đã implement trong `app/auth.py` nhưng chưa có trong tài liệu | HIGH |
| 2 | Bổ sung **S-QĐ-02, S-QĐ-05, S-QĐ-07** | Các quy định SOC bị trùng/thiếu trong bản gốc | MEDIUM |
| 3 | Thêm **M-QĐ-02** cho báo cáo Manager | Không có mô tả trong bản gốc | MEDIUM |
| 4 | Bổ sung **Use Case Specification chi tiết** | Hiện chỉ có mã UC, cần Pre/Post conditions | LOW |

### I.2. Hoàn thiện Bảng Yêu Cầu ML Service

| # | Thay đổi | Lý do | Priority |
|---|-----------|-------|----------|
| 1 | Thêm **default threshold** cho `is_anomaly` | Hiện chỉ ghi "theo config" - cần chỉ định rõ | HIGH |
| 2 | Thêm **Model Lifecycle** section | Không có kế hoạch retraining, rollback | HIGH |
| 3 | Làm rõ **deviation_score** | Mơ hồ - ai tính? ML hay Feature Builder? | MEDIUM |
| 4 | Thêm **Performance/SLA requirements** | Không có latency expectations | MEDIUM |
| 5 | Thêm **Feature Contract Versioning Policy** | Không có policy cho schema changes | MEDIUM |

---

## II. THAY ĐỔI VỀ IMPLEMENTATION

### II.1. High Priority (Cần làm ngay)

#### 1. Align ML Feature Contract với DetectionFeatureVector

**Current Issue:**
- ML Service (`app/ml.py`) sử dụng features không đồng nhất với Detection Engine (`app/detection.py`)

**Proposed:**
```python
# app/schemas.py - DetectionFeatureVector
class DetectionFeatureVector(BaseModel):
    login_hour: Optional[int] = None
    login_day: Optional[int] = None
    ip_country: Optional[str] = None
    ip_reputation: Optional[float] = None
    user_agent_family: Optional[str] = None
    asn_reputation: Optional[float] = None
    failed_attempts_1h: int = 0
    failed_attempts_24h: int = 0
    geo_velocity_kmh: Optional[float] = None
    login_streak: int = 0
    is_known_device: bool = False
    is_known_ip: bool = False
    mfa_used_recently: bool = False
```

**Changes:**
| File | Change | Status |
|------|--------|--------|
| `app/detection.py` | Cập nhật `ml_score()` để sử dụng `DetectionFeatureVector` | TODO |
| `app/ml.py` | Update `ScoreRequest` để align với 13 features | TODO |

#### 2. Implement Missing Alert Timeline Feature

**Current Issue:**
- `alert_timeline` table đã có trong schema-v3.sql nhưng chưa implement API

**Proposed:**
```python
# app/alerts.py - New endpoints
@router.post("/api/v1/alerts/{alert_id}/timeline")
async def create_timeline_event(...)

@router.get("/api/v1/alerts/{alert_id}/timeline")
async def get_timeline_events(...)
```

**Timeline Event Types:**
- `created` - Auto-generated khi alert được tạo
- `assigned` - Khi gán cho SOC analyst
- `acknowledged` - Khi SOC acknowledge
- `note_added` - Khi SOC thêm ghi chú
- `status_changed` - Khi thay đổi trạng thái
- `resolved` - Khi resolved/false_positive

#### 3. Implement Trusted Device Feature

**Current Issue:**
- `user_trusted_devices` table đã có nhưng chưa implement logic

**Proposed:**
```python
# app/trusted_devices.py - New module
@router.post("/api/v1/devices/trust")
async def trust_device(...)

@router.delete("/api/v1/devices/{device_id}")
async def untrust_device(...)

@router.get("/api/v1/devices")
async def list_trusted_devices(...)
```

**Implementation:**
- Generate device fingerprint từ User-Agent, Accept-Language, Screen resolution
- Check trusted device trong login flow → skip MFA nếu trusted
- Auto-expire sau configurable TTL (default: 30 days)

### II.2. Medium Priority (Cần làm trong Sprint tiếp theo)

#### 4. Implement User Notifications

**Current Issue:**
- `user_notifications` table đã có nhưng chưa implement notification generation

**Proposed Notifications:**
| Type | Trigger | Content |
|------|---------|---------|
| `mfa_success` | MFA verified | "Mã MFA đã được xác minh thành công" |
| `mfa_failed` | MFA failed 3 times | "Đăng nhập bị từ chối do sai mã MFA" |
| `new_login` | Login from new IP/device | "Đăng nhập mới từ {location}" |
| `account_locked` | Account locked | "Tài khoản đã bị tạm khóa" |

#### 5. Implement SOC Dashboard API

**Current Issue:**
- SOC Dashboard (UC-06) chưa có API endpoints

**Proposed Endpoints:**
```python
@router.get("/api/v1/soc/dashboard/stats")
async def get_dashboard_stats(...)

@router.get("/api/v1/soc/dashboard/activity")
async def get_recent_activity(...)
```

**Metrics:**
- Total alerts (open/acknowledged/resolved)
- Alerts by risk level
- Recent login attempts
- Top risky users

#### 6. Implement Management Dashboard API

**Current Issue:**
- Management Dashboard (UC-20, UC-21) chưa có API

**Proposed Endpoints:**
```python
@router.get("/api/v1/management/dashboard")
async def get_management_dashboard(...)

@router.get("/api/v1/management/reports")
async def generate_report(...)
```

### II.3. Low Priority (Backlog)

#### 7. Add External IP Geolocation Integration

**Current:**
- `ip_country` và `geo_velocity_kmh` chưa có source data

**Proposed:**
- Tích hợp với IP geolocation API (e.g., MaxMind, IP-API)
- Cache results để giảm API calls

#### 8. Implement System Settings API

**Current:**
- `system_settings` table đã có seed data nhưng chưa có CRUD API

**Proposed:**
```python
@router.get("/api/v1/admin/settings")
async def list_settings(...)

@router.put("/api/v1/admin/settings/{key}")
async def update_setting(...)
```

#### 9. Add Rate Limit Configuration API

**Current:**
- Rate limits hardcoded trong code

**Proposed:**
- Đọc từ `system_settings`:
  - `rate_limit.login.max_attempts`
  - `rate_limit.login.window_seconds`
  - `rate_limit.api.max_requests`

---

## III. ALIGNMENT ISSUES GIỮA TÀI LIỆU VÀ CODE

### III.1. Features không match

| ML Feature Document | Implementation | Status |
|---------------------|-----------------|--------|
| `hour_of_day` | `login_hour` | ✅ Match (renamed) |
| `fail_count_24h` | `failed_attempts_24h` | ✅ Match |
| `ip_change_rate_7d` | ❌ Not implemented | 🔴 Missing |
| `new_device` | `is_known_device` | ✅ Match (negated) |
| `average_login_interval_seconds` | ❌ Not implemented | 🔴 Missing |
| `deviation_score` | ❌ Not implemented | 🔴 Missing |

### III.2. API Endpoints không đồng nhất

| Document | Proposed Endpoint | Implementation | Status |
|----------|-------------------|----------------|--------|
| Auth | POST /api/v1/auth/login | ✅ Implemented | ✅ |
| Auth | POST /api/v1/auth/mfa/verify | ✅ Implemented | ✅ |
| Auth | GET /api/v1/auth/sessions | ✅ Implemented | ✅ |
| SOC | GET /api/v1/alerts | ❌ Not implemented | 🔴 Missing |
| SOC | GET /api/v1/alerts/{id}/evidence | ❌ Not implemented | 🔴 Missing |
| SOC | POST /api/v1/alerts/{id}/actions | ❌ Not implemented | 🔴 Missing |
| Admin | GET /api/v1/admin/users | ❌ Not implemented | 🔴 Missing |
| Admin | GET /api/v1/admin/audit-logs | ❌ Not implemented | 🔴 Missing |
| ML | POST /internal/v1/ml/score | ✅ Implemented | ✅ |
| ML | GET /internal/v1/ml/health | ✅ Implemented | ✅ |

---

## IV. RECOMMENDED SPRINT PLAN

### Sprint 1: Core Auth & Detection (2 weeks)

- [ ] Align ML feature contract
- [ ] Implement Alert Timeline API
- [ ] Implement Trusted Device feature
- [ ] Implement SOC Alert CRUD API
- [ ] Update documentation

### Sprint 2: SOC Operations (2 weeks)

- [ ] Implement SOC Dashboard API
- [ ] Implement User Notification system
- [ ] Implement Security Action enforcement (REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER)
- [ ] Implement Audit Log API

### Sprint 3: Admin & Management (2 weeks)

- [ ] Implement Admin User Management API
- [ ] Implement Policy Versioning API
- [ ] Implement System Settings API
- [ ] Implement Management Dashboard API

### Sprint 4: Integration & Polish (2 weeks)

- [ ] Add IP Geolocation integration
- [ ] Add Rate Limit configuration
- [ ] Add remaining ML features (ip_change_rate, avg_interval, deviation_score)
- [ ] Performance testing
- [ ] Security review

---

## V. OPEN QUESTIONS

| # | Question | Impact | Owner |
|---|----------|--------|-------|
| 1 | ML model nào sẽ được sử dụng cho production? Isolation Forest? LOF? | HIGH | ML Team |
| 2 | Ai chịu trách nhiệm retraining ML model? | HIGH | ML Team |
| 3 | Feature `deviation_score` - tính ở đâu? | MEDIUM | ML Team |
| 4 | IP geolocation service nào? MaxMind? Free API? | MEDIUM | DevOps |
| 5 | Notification channels nào được hỗ trợ? Email only? SMS? Push? | MEDIUM | Product |

---

## VI. FILES CREATED/UPDATED

### Files

| File | Action | Description |
|------|--------|-------------|
| `docs/diagrams/ERD_v4_DETAILED.md` | ✅ | ERD v4 chi tiết với PK/FK/Quan hệ |
| `infra/postgres/schema-v4-3nf.sql` | ✅ | Schema SQL v4 (3NF) |
| `infra/postgres/migrations/004_normalize_to_3nf.sql` | ✅ | Migration script |
| `docs/02_DeXuatThayDoiDuAn_SentinelAuth.md` | Updated | Đề xuất thay đổi (document này) |
| `docs/02_BangYeuCauChucNangNghiepVu_SentinelAuth_v2.md` | ✅ | Bảng YCNV v2 |
| `docs/02_BangYeuCauMLService_SentinelAuth_v2.md` | ✅ | Bảng ML Service v2 |

### Removed Files (Cleanup)

| File | Lý do |
|------|--------|
| `docs/diagrams/erd-v2.*`, `docs/diagrams/erd-v3.*` | Phiên bản cũ, trùng lặp |
| `docs/schema-v2-design-notes.md` | Không còn cần thiết |
| `docs/TASK-core-app-design-detail.md` | Nội dung đã lỗi thời |
| `docs/GAP-ANALYSIS-tai-lieu-vs-code.md` | Không còn cần thiết |
| `docs/01-*.md`, `docs/02-*.md`, `docs/03-*.md` | Document cũ, đã có phiên bản mới |
| `docs/workflows.mmd` | Không sử dụng |
| `docs/generate_reports.py` | Không sử dụng |
| `docs/diagrams/*.uml` (wf*) | Đã có .drawio |
| `docs/diagrams/render_svg.py`, `generate_puml.py` | Không sử dụng |

---

## VII. IMPLEMENTATION STATUS

### ✅ Completed (Items đã implement)

| # | Item | Files | Status |
|---|------|-------|--------|
| 1 | Align ML Feature Contract v2 | `app/ml.py` | ✅ Done |
| 2 | Alert Timeline API | `app/alerts.py`, `app/models.py` | ✅ Done |
| 3 | Trusted Device Feature | `app/devices.py`, `app/models.py` | ✅ Done |
| 4 | SOC Alert CRUD API | `app/alerts.py` | ✅ Done |
| 5 | Database Schema v3.1 | `infra/postgres/schema-complete.sql` | ✅ Done |
| 6 | ERD Complete | `docs/diagrams/ERD_COMPLETE.md` | ✅ Done |

### 📋 Pending (Items còn lại)

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 1 | User Notification System | MEDIUM | Cần implement `app/notifications.py` |
| 2 | SOC Dashboard API | MEDIUM | Cần implement `app/soc_dashboard.py` |
| 3 | Management Dashboard API | MEDIUM | Cần implement `app/management.py` |
| 4 | Admin User Management API | MEDIUM | Cần implement `app/admin.py` |
| 5 | System Settings CRUD | MEDIUM | Cần implement `app/settings.py` |
| 6 | IP Geolocation Integration | LOW | External API integration |
| 7 | Missing ML Features | HIGH | `ip_change_rate_7d`, `avg_interval`, `deviation_score` |

### 📋 Pending (Items còn lại)

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 1 | User Notification System | MEDIUM | Cần implement `app/notifications.py` |
| 2 | SOC Dashboard API | MEDIUM | Cần implement `app/soc_dashboard.py` |
| 3 | Management Dashboard API | MEDIUM | Cần implement `app/management.py` |
| 4 | Admin User Management API | MEDIUM | Cần implement `app/admin.py` |
| 5 | System Settings CRUD | MEDIUM | Cần implement `app/settings.py` |
| 6 | IP Geolocation Integration | LOW | External API integration |
| 7 | Missing ML Features | HIGH | `ip_change_rate_7d`, `avg_interval`, `deviation_score` |

---

## VIII. APPROVAL

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Technical Lead | | | |
| ML Team Lead | | | |
| Product Owner | | | |

---

> **Document Status:** Draft - Pending Review
> **Next Action:** Team review meeting to prioritize and assign owners
