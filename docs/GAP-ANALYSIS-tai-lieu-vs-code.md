# BÁO CÁO KIỂM TRA VÀ CẢI THIỆN TÀI LIỆU PHÂN TÍCH

## Tổng quan

Ba tài liệu được kiểm tra:
- **DOC-01**: Bảng yêu cầu chức năng nghiệp vụ Core-app
- **DOC-02**: Đặc tả Use Case Core-app
- **DOC-03**: Phân tích đối tượng sử dụng Core-app

Code thực tế: `app/` (FastAPI single-process) với `auth.py`, `detection.py`, `ml.py`, `db.py`, `main.py`.

---

## I. TÌNH TRẠNG CHUNG

| Tiêu chí | Đánh giá |
|---|---|
| Đúng ngữ cảnh dự án | ⚠️ **Có vấn đề** — tài liệu mô tả kiến trúc multi-package (core-app riêng, detection-engine riêng, ml-service riêng), nhưng code hiện tại là **single-process FastAPI** gộp tất cả |
| Nhất quán nội bộ giữa 3 tài liệu | ✅ Tốt |
| Nhất quán với code | ❌ **Không nhất quán** — thiếu SOC, Audit Log, rule_versions, action endpoints |
| Đủ chi tiết để implement | ⚠️ Đủ mô tả nghiệp vụ, thiếu API contract, DB schema đầy đủ |

---

## II. CÁC VẤN ĐỀ CỤ THỂ

### 🔴 Vấn đề lớn nhất: Kiến trúc không khớp

**Tài liệu mô tả:**
- `core-app`: service độc lập, có database riêng
- `detection-engine`: service độc lập, gọi `ml-service`
- `ml-service`: service độc lập
- Giao tiếp: HTTP + async events + Redis

**Code thực tế:**
- **1 process FastAPI** chạy tất cả (`app/`)
- `auth.py`: placeholder (toàn `pass`)
- `detection.py`: placeholder
- `ml.py`: placeholder
- Database: **1 schema public duy nhất** (schema.sql có đủ 8 bảng gộp)

→ **Hệ quả**: Tài liệu DOC-01 mô tả nhiều chức năng không tồn tại trong code:
- `Rate limiting` theo IP (YCNV-CA-03)
- `Audit Log` table và endpoint (YCNV-CA-16)
- `Security Administrator` gán/revoke role, khóa account (YCNV-CA-08~11)
- `Detection action endpoint` với `X-Internal-Secret` (YCNV-CA-13~15)
- `SOC_ANALYST` và `SECURITY_MANAGER` roles
- `rule_versions` versioning (trong schema.sql có bảng nhưng không có API)
- `LoginEvent` push async sang detection-engine (YCNV-CA-12)

### 🔴 Tài liệu thiếu SOC Dashboard và Alert Management

| Chức năng | DOC-01 | DOC-02 | DOC-03 | Code |
|---|---|---|---|---|
| SOC xem alerts | ❌ Không có | ❌ Không có | ❌ Không có | ❌ Không có |
| SOC acknowledge/resolve alert | ❌ Không có | ❌ Không có | ❌ Không có | ❌ Không có |
| Alert state machine (open→ack→resolved) | ❌ Không có | ❌ Không có | ❌ Không có | ⚠️ Có bảng `alerts` trong schema, không có API |
| SOC filter alerts | ❌ Không có | ❌ Không có | ❌ Không có | ❌ Không có |

→ Code có bảng `alerts` và `risk_assessments` trong schema.sql nhưng **không có endpoint** nào để SOC truy cập. DOC-01 mô tả SOC là 1 trong 3 actor chính nhưng không đặc tả chức năng nào cho SOC.

### 🟡 MFA không khớp giữa tài liệu và schema

| Thuộc tính | DOC-01 (YCNV-CA-04) | schema.sql |
|---|---|---|
| Độ dài OTP | 4 số | 6 số |
| Thời gian hiệu lực | 60 giây | Pre-auth transactions: `expires_at` (không quy định rõ) |
| Số lần thử | 3 lần | Không rõ |
| Gửi OTP | Email | Chỉ có `mfa_code_hash` — không có bảng `email_otps` riêng |

### 🟡 Code không implement các endpoint đã mô tả

Tất cả function trong `auth.py`, `detection.py`, `ml.py` đều là `pass` + `return rỗng`. Không có:
- Argon2id password hashing
- JWT creation/verification
- Rate limiting
- MFA code generation
- Login attempt logging
- Risk scoring logic

### 🟡 Thiếu API contract đầy đủ

DOC-01/DOC-02 mô tả nghiệp vụ rõ ràng nhưng thiếu:
- HTTP method + path chính xác cho mỗi endpoint
- Request/Response schema (JSON fields)
- HTTP status codes trả về
- Error response format
- Header requirements (`X-Internal-Secret`, `Authorization`)

### 🟡 Thiếu detection_logs endpoint

DOC-01 (YCPNC-06) nói "Core-app và các service khác không chia sẻ database" nhưng schema.sql có bảng `detection_logs` trong **cùng schema public**. Nếu detection chạy inline trong single-process, bảng này dùng được. Nhưng không có endpoint để query.

### 🟡 Thiếu Rule Versioning endpoint

schema.sql có bảng `rule_versions` nhưng không có API endpoint nào để:
- Xem danh sách rule versions
- Create/update rule version
- Get active rule version

### 🟡 Thiếu SOC Alert state machine trong DOC-02

DOC-02 chỉ có 9 UC, trong đó **không có UC nào cho SOC**. Alert state machine (`open → acknowledged → resolved / false_positive`) được đề cập trong schema nhưng không có use case mô tả.

---

## III. BẢNG TỔNG HỢP CÁC CHỨC NĂNG

### 3.1. Những gì Tài liệu nói — Code KHÔNG có

| Mã | Chức năng | Mức độ nghiêm trọng |
|---|---|---|
| YCNV-CA-03 | Rate limiting theo IP | Cao |
| YCNV-CA-08~11 | Security Admin: gán/revoke role, khóa account, bật/tắt MFA | **Rất cao** |
| YCNV-CA-13~15 | Action endpoint nội bộ (REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER, RATE_LIMIT_IP) | **Rất cao** |
| YCNV-CA-16 | Audit Log endpoint | Cao |
| YCNV-CA-12 | LoginEvent async push | Cao |
| — | SOC Alert management endpoints | **Rất cao** |
| — | Rule versioning API | Trung bình |
| — | Detection logs API | Trung bình |
| YCPNC-07 | Email OTP via Mailpit/SMTP | Trung bình |

### 3.2. Những gì Code có — Tài liệu KHÔNG mô tả

| Tính năng | Code | Tài liệu |
|---|---|---|
| Bảng `risk_assessments` | ✅ Có | ❌ Không đặc tả |
| Bảng `detection_logs` | ✅ Có | ❌ Không đặc tả |
| Bảng `rule_versions` | ✅ Có | ❌ Không đặc tả |
| Bảng `alerts` (SOC) | ✅ Có | ❌ Không mô tả endpoint |
| `/internal/v1/detect` endpoint | ✅ Có (placeholder) | ⚠️ Có mô tả nghiệp vụ, thiếu API contract |
| `/internal/v1/ml/score` endpoint | ✅ Có (placeholder) | ⚠️ Thiếu API contract |
| MFA 6 số (code) vs 4 số (tài liệu) | 6 số | 4 số |

### 3.3. Những gì CẢ hai đều CÓ

| Chức năng | Trạng thái |
|---|---|
| User đăng ký | ✅ Tài liệu OK, code placeholder |
| User đăng nhập | ✅ Tài liệu OK, code placeholder |
| MFA verify | ✅ Tài liệu OK, code placeholder |
| User logout | ✅ Tài liệu OK, code placeholder |
| JWT/session management | ✅ Tài liệu OK, code placeholder |
| PostgreSQL schema | ✅ Cơ bản khớp, thiếu 1 số chi tiết |

---

## IV. CÁC CẢI THIỆN CẦN THIẾT

### 4.1. Cải thiện Kiến trúc (Ưu tiên CAO)

**Vấn đề**: Tài liệu mô tả multi-package, code là single-process.

**Hướng xử lý** — chọn 1 trong 2:

| Phương án | Ưu điểm | Nhược điểm |
|---|---|---|
| **A. Giữ single-process (Recommended)** | Đơn giản, deploy dễ, tất cả inline | Không scale độc lập |
| **B. Tách multi-package** | Scale độc lập, clear separation | Phức tạp hơn nhiều |

**Nếu chọn A (giữ single-process)** → Cập nhật DOC-01:
- Xóa phần "Core-app có database riêng"
- Xóa "detection-engine là service riêng, gọi ml-service"
- Mô tả: "FastAPI single-process xử lý auth + detection + ML inline trong 1 request"
- Mô tả: "Không Redis, không background worker, không async event queue"

**Nếu chọn B (tách multi-package)** → Cần viết lại code hoàn chỉnh.

### 4.2. Bổ sung SOC Alert Management (Ưu tiên RẤT CAO)

Tài liệu thiếu hoàn toàn phần này dù SOC là 1 trong 3 actor chính.

**Cần thêm vào DOC-01 (bảng yêu cầu):**

| Mã | Nhóm | Yêu cầu |
|---|---|---|
| YCNV-SOC-01 | SOC Alerts | SOC xem danh sách alerts, lọc theo status (open/acknowledged/resolved), risk_level (low/medium/high/critical) |
| YCNV-SOC-02 | SOC Alerts | SOC xem chi tiết alert: login_attempt, risk scores, thời gian, rule hit |
| YCNV-SOC-03 | SOC Alerts | SOC acknowledge alert → chuyển open → acknowledged, ghi assigned_to và notes |
| YCNV-SOC-04 | SOC Alerts | SOC resolve alert → chuyển acknowledged → resolved hoặc false_positive, ghi resolved_by, resolved_at |

**Cần thêm vào DOC-02 (use case):**

| Mã | Tên UC | Actor | Mô tả |
|---|---|---|---|
| UC-CA-10 | Xem danh sách alerts | SOC Analyst | Xem, lọc alerts theo status và risk_level |
| UC-CA-11 | Acknowledge alert | SOC Analyst | Ghi nhận đã xem xét, chuyển trạng thái |
| UC-CA-12 | Resolve alert | SOC Analyst | Xác nhận đã xử lý, chuyển resolved hoặc false_positive |

**Cần thêm vào DOC-03 (phân tích đối tượng):**

Thêm actor **SOC Analyst** với đầy đủ chức năng (hiện tại DOC-03 chỉ đề cập User và Security Administrator).

### 4.3. Cập nhật MFA Specification (Ưu tiên CAO)

| Vấn đề | Sửa đổi |
|---|---|
| OTP 4 số (tài liệu) vs 6 số (code/schema) | Thống nhất: **6 số** |
| 60 giây expiry (tài liệu) | Thống nhất: **5 phút** (300 giây) |
| 3 lần thử (tài liệu) | ✅ Giữ nguyên |
| Email OTP (tài liệu) vs `mfa_code_hash` (schema) | Cần bổ sung: OTP được hash trước khi lưu |

### 4.4. Bổ sung Security Admin Management (Ưu tiên RẤT CAO)

**Thêm vào DOC-01 bảng yêu cầu:**

| Mã | Nhóm | Yêu cầu |
|---|---|---|
| YCNV-SM-01 | Security Admin | Admin xem danh sách tài khoản, lọc theo role, status |
| YCNV-SM-02 | Security Admin | Admin gán role đặc biệt (SECURITY_ADMIN, SOC_ANALYST, SECURITY_MANAGER) |
| YCNV-SM-03 | Security Admin | Admin thu hồi role đặc biệt (không gỡ USER) |
| YCNV-SM-04 | Security Admin | Admin khóa/mở khóa tài khoản |
| YCNV-SM-05 | Security Admin | Admin bật/tắt MFA persistent cho User |
| YCNV-SM-06 | Security Admin | Admin revoke session từ xa |

**Thêm vào DOC-02 (use case):**

| Mã | Tên UC | Actor |
|---|---|---|
| UC-CA-05 | Gán/thu hồi role | Security Administrator |
| UC-CA-06 | Khóa account | Security Administrator |
| UC-CA-07 | Bật/tắt MFA persistent | Security Administrator |

*(Hiện tại DOC-02 đã có UC-CA-05~07 nhưng thiếu API contract chi tiết)*

### 4.5. Bổ sung Audit Log Specification (Ưu tiên CAO)

| Vấn đề | Cải thiện |
|---|---|
| YCNV-CA-16 chỉ mô tả chung | Cần thêm bảng `audit_logs` trong schema.sql (hiện **không có** bảng này) |
| Không có endpoint xem audit logs | Cần thêm endpoint `/api/v1/admin/audit-logs` |

**Bảng `audit_logs` cần thêm vào schema.sql:**

```sql
CREATE TABLE IF NOT EXISTS audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor       TEXT NOT NULL,          -- user_id hoặc 'system:detection-engine'
    action      TEXT NOT NULL,          -- 'role_assigned', 'user_locked', 'session_revoked', …
    resource    TEXT NOT NULL,          -- 'user', 'session', 'role', …
    resource_id UUID,
    before_state JSONB,
    after_state  JSONB,
    reason      TEXT,
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.6. Bổ sung Detection Internal Endpoints (Ưu tiên CAO)

Tài liệu mô tả action endpoint nhưng thiếu API contract:

| Endpoint | Method | Mô tả |
|---|---|---|
| `/internal/v1/detect` | POST | Inline detection — trả rule_score, anomaly_score, ml_score, risk_level |
| `/internal/v1/ml/score` | POST | ML scoring — nhận features vector, trả anomaly_score |
| `/internal/v1/actions` | POST | Nhận action từ detection (REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER) |

### 4.7. Cập nhật Security Requirements (Ưu tiên TRUNG BÌNH)

- `YCPNC-02b`: "Mọi service verify cùng JWT contract" — không đúng với single-process. Cần xóa.
- `YCPNC-05`: "timeout 5 giây, retry 3 lần" — không còn async communication trong single-process. Cần cập nhật mô tả.
- `YCPNC-06`: "Chỉ tích hợp qua HTTP contract" — không đúng với single-process (cùng process). Cần xóa.

### 4.8. Bổ sung Rule Versioning (Ưu tiên TRUNG BÌNH)

Tài liệu không mô tả rule versioning. Cần thêm:

| Mã | Nhóm | Yêu cầu |
|---|---|---|
| YCNV-RL-01 | Rule Versioning | Admin xem danh sách rule versions |
| YCNV-RL-02 | Rule Versioning | Admin tạo rule version mới |
| YCNV-RL-03 | Rule Versioning | Admin activate/deactivate rule version |

---

## V. KHUYẾN NGHỊ THỨ TỰ ƯU TIÊN

```
P0 (Làm ngay):
  1. Thống nhất kiến trúc: chọn single-process hay multi-package
     → Cập nhật DOC-01 Section 1 (Mục đích và phạm vi)
  
  2. Bổ sung SOC Alert Management (DOC-01 + DOC-02 + DOC-03)
     → SOC là 1 trong 3 actor nhưng tài liệu không mô tả gì
  
  3. Bổ sung Security Admin endpoints (DOC-01 + DOC-02)
     → YCNV-CA-08~11 và UC-CA-05~07 thiếu API contract chi tiết

P1 (Cần làm):
  4. Cập nhật MFA spec (4 số → 6 số, 60s → 5 phút)
  
  5. Bổ sung Audit Log table và endpoint
     → schema.sql thiếu bảng audit_logs
  
  6. Bổ sung Detection internal endpoints API contract
     → /internal/v1/detect, /internal/v1/ml/score, /internal/v1/actions

P2 (Nên làm):
  7. Sửa security requirements mâu thuẫn với single-process
     → Xóa YCPNC-02b, YCPNC-05, YCPNC-06
  
  8. Bổ sung Rule Versioning spec
  
  9. Implement code (hiện tại 100% placeholder)
     → auth.py, detection.py, ml.py toàn `pass`
```

---

## VI. HÀNH ĐỘNG ĐỀ XUẤT

1. **Xác nhận kiến trúc** với thầy/bạn: giữ single-process hay tách multi-package?
2. **Cập nhật DOC-01** sau khi xác nhận kiến trúc
3. **Bổ sung SOC** vào cả 3 tài liệu
4. **Thống nhất MFA spec** (6 số, 5 phút)
5. **Cập nhật DOC-02** với API contract đầy đủ
6. **Thêm Audit Log** vào schema.sql và tài liệu
7. **Implement code** thực tế thay vì placeholder

---

*Tài liệu này được tạo bằng cách đối chiếu 3 tài liệu phân tích với code thực tế tại `app/`, `infra/postgres/schema.sql` và `tests/`.*
