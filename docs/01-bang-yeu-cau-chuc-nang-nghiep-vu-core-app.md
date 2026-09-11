# Bảng yêu cầu chức năng nghiệp vụ của Sentinel Auth

## 1. Mục đích và phạm vi

Sentinel Auth là hệ thống **FastAPI single-process** chạy trong một container duy nhất, xử lý đồng thời cả xác thực người dùng (identity) lẫn phát hiện bất thường đăng nhập (detection) trong cùng một request/response cycle.

Hệ thống **không** dùng Redis, không có background worker, không có async event queue. Tất cả giao tiếp nội bộ (auth ↔ detection ↔ ML) diễn ra inline trong Python process.

### Phạm vi v1

| Thành phần | Có trong v1 |
|---|---|
| User registration & login (password + MFA Email OTP) | ✅ |
| JWT + Session management | ✅ |
| Security Administrator (gán/revoke role, khóa account, MFA toggle) | ✅ |
| Inline detection: rule scoring + ML anomaly scoring | ✅ |
| SOC Alert management (view, acknowledge, resolve) | ✅ |
| Rule versioning | ✅ |
| Audit logging | ✅ |
| Rate limiting (login per IP) | ✅ |
| Detection action enforcement (REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER) | ✅ |

### Ngoài phạm vi v1

- TOTP, SMS OTP, push notification, SMTP ra Internet (Email OTP dùng Mailpit ở dev/demo)
- Multi-package microservice architecture
- SOC Dashboard với chart/graph
- Trusted device management
- Auto-assign special roles on registration

---

## 2. Bảng yêu cầu chức năng

### 2.1 Nhóm: Xác thực & Phiên (Auth & Session)

| Mã | Yêu cầu | Actor | Mô tả | Kết quả chính |
|---|---|---|---|---|
| YCNV-AU-01 | Đăng ký tài khoản | User | Username, email, password hợp lệ. Không trùng. Argon2id hash. | Account mới: role `USER`, `status=ACTIVE`. Không lưu plaintext. |
| YCNV-AU-02 | Đăng nhập | User | Rate limit theo IP. Verify credentials + account status. Không tiết lộ account tồn tại khi sai. | Từ chối / yêu cầu MFA / tạo session/token. |
| YCNV-AU-03 | Chống brute force | Hệ thống | Tối đa 5 request login/phút/IP. Vượt ngưỡng trả `429`. | Rate-limited requests bị chặn. |
| YCNV-AU-04 | MFA Email OTP có điều kiện | User, Admin, Detection | Bật persistent (Admin) → luôn yêu cầu OTP. Bật one-time (Detection) → yêu cầu ở login kế tiếp. | OTP 6 số, 5 phút, sai tối đa 3 lần. |
| YCNV-AU-05 | Vòng đời MFA | Hệ thống | MFA persistent: duy trì đến khi Admin tắt. MFA one-time: xóa sau khi verify thành công. | Phân biệt rõ hai loại MFA. |
| YCNV-AU-06 | JWT và Session | User | Access JWT ngắn hạn + refresh token. Session ghi nhận device/IP/expiry. Chỉ lưu hash. | API protected xác thựn được user + roles; session revoke được. |
| YCNV-AU-07 | Logout và quản lý session | User | Logout phiên hiện tại. Xem session của mình. Revoke session lạ. Không xem/revoke session người khác. | Session bị revoke không còn hợp lệ. |
| YCNV-AU-08 | Refresh token | User | Dùng refresh token để lấy access token mới. | Access token mới, refresh token có thể bị rotate. |

### 2.2 Nhóm: Security Administrator

| Mã | Yêu cầu | Actor | Mô tả | Kết quả chính |
|---|---|---|---|---|
| YCNV-SA-01 | Gán role đặc biệt | Security Administrator | Gán `SECURITY_ADMIN`, `SOC_ANALYST`, `SECURITY_MANAGER`. Multi-role. | Session target bị revoke; login lại nhận JWT mới; audit log. |
| YCNV-SA-02 | Thu hồi role đặc biệt | Security Administrator | Gỡ 1 role, giữ nguyên các role còn lại. Không gỡ role `USER`. | Không gỡ `SECURITY_ADMIN` cuối cùng còn `ACTIVE`. |
| YCNV-SA-03 | Khóa/mở khóa account | Security Administrator | Đổi `status=LOCKED` hoặc `status=ACTIVE`. | Không khóa Security Admin cuối cùng còn `ACTIVE`. |
| YCNV-SA-04 | Bật/tắt MFA persistent | Security Administrator | Cập nhật `admin_mfa_required` của User. | Login tiếp theo theo policy mới. |
| YCNV-SA-05 | Xem danh sách account | Security Administrator | Xem tài khoản, lọc theo role, status. | Danh sách account với thông tin cơ bản. |

### 2.3 Nhóm: Detection Engine (Inline)

| Mã | Yêu cầu | Actor | Mô tả | Kết quả chính |
|---|---|---|---|---|
| YCNV-DE-01 | Inline detection | Hệ thống | Gọi rule scoring + ML scoring inline trong login request. Trả combined risk. | `rule_score`, `anomaly_score`, `ml_score`, `risk_level` (low/medium/high/critical). |
| YCNV-DE-02 | Rule scoring | Hệ thống | Áp dụng rule set đang active. Mỗi rule trả score 0.0–1.0. Combined rule_score. | Rule_scores, rule_name hit. |
| YCNV-DE-03 | ML anomaly scoring | Hệ thường | Gọi ML model scoring với feature vector từ login context. Trả anomaly_score 0.0–1.0. | Anomaly score + ML status (success/unavailable/error). |
| YCNV-DE-04 | Risk decision | Hệ thống | Kết hợp rule_score + ml_score → risk_level. Quyết định `allow` / `challenge` / `block`. | Endpoint `/internal/v1/detect` trả decision + scores. |
| YCNV-DE-05 | ML score endpoint | Hệ thống | Endpoint `/internal/v1/ml/score` nhận features vector, trả anomaly_score. | Mirror ml-service scoring trong-process. |
| YCNV-DE-06 | Ghi detection log | Hệ thống | Lưu từng bước detection (rule, ml, combined) vào bảng `detection_logs`. | Audit trail cho replay và debug. |

### 2.4 Nhóm: SOC Alert Management

| Mã | Yêu cầu | Actor | Mô tả | Kết quả chính |
|---|---|---|---|---|
| YCNV-SOC-01 | Xem danh sách alerts | SOC Analyst | Xem alerts, lọc theo `status` (open/acknowledged/resolved/false_positive) và `risk_level`. Phân trang. | Danh sách alerts với thông tin cơ bản. |
| YCNV-SOC-02 | Xem chi tiết alert | SOC Analyst | Xem chi tiết: login_attempt, risk scores, rule hit, thời gian, IP, user-agent. | Alert với full context. |
| YCNV-SOC-03 | Acknowledge alert | SOC Analyst | Ghi nhận đã xem xét. Chuyển `open` → `acknowledged`. Ghi `assigned_to` và `notes`. | Alert có assignee. |
| YCNV-SOC-04 | Resolve alert | SOC Analyst | Kết thúc xử lý. Chuyển `acknowledged` → `resolved` hoặc `false_positive`. Ghi `resolved_by`, `resolved_at`. | Alert có resolved state. |

### 2.5 Nhóm: Rule Versioning

| Mã | Yêu cầu | Actor | Mô tả | Kết quả chính |
|---|---|---|---|---|
| YCNV-RV-01 | Xem rule versions | Security Administrator | Xem danh sách rule versions, trạng thái active/inactive. | Danh sách versions. |
| YCNV-RV-02 | Tạo rule version | Security Administrator | Tạo version mới với rule set JSON. Chưa activate. | Version mới có thể test trước khi activate. |
| YCNV-RV-03 | Activate/deactivate rule version | Security Administrator | Đặt version active. Chỉ 1 version active tại mỗi thời điểm. Deactivate version cũ. | Login dùng rule set mới. |

### 2.6 Nhóm: Audit & Security Actions

| Mã | Yêu cầu | Actor | Mô tả | Kết quả chính |
|---|---|---|---|---|
| YCNV-AD-01 | Ghi Audit Log | Hệ thống | Lưu actor, action, resource, before/after state, timestamp, reason, IP. | Có thể truy vết. Không log password/OTP/JWT/email plaintext. |
| YCNV-AD-02 | Xem Audit Logs | Security Administrator | Xem audit trail, lọc theo actor, action, resource, khoảng thời gian. | Danh sách audit entries. |
| YCNV-AD-03 | Enforce action (internal) | Hệ thống | Nhận action từ detection logic: `REQUIRE_MFA`, `REVOKE_SESSIONS`, `LOCK_USER`. Áp dụng tại chỗ. | Action được thực thi ngay trong process. |
| YCNV-AD-04 | Login Event logging | Hệ thống | Ghi login_attempt vào bảng `login_attempts` sau mỗi xác thực. | Phục vụ detection và audit. |

---

## 3. Yêu cầu phi chức năng và bảo mật

| Mã | Yêu cầu |
|---|---|
| YCPNC-01 | Password dùng Argon2id. Không lưu hoặc log plaintext password/OTP/token. |
| YCPNC-02 | API protected dùng JWT hợp lệ. Thiếu quyền trả `403`, token hết hạn/trá trả `401`. |
| YCPNC-02a | RBAC multi-role. JWT mang claim `roles` (mảng). Endpoint cho phép khi có ít nhất 1 role yêu cầu. |
| YCPNC-03 | Internal endpoints (detection, ML, actions) dùng `X-Internal-Secret` header thay vì JWT. |
| YCPNC-04 | Login attempt dùng `id` UUID và timestamp UTC. |
| YCPNC-05 | Tất cả giao tiếp nội bộ (auth ↔ detection ↔ ML) diễn ra inline trong process, không HTTP call ra ngoài. |
| YCPNC-06 | Core data (users, sessions) và detection data (alerts, risk_assessments, detection_logs) cùng trong 1 PostgreSQL database, khác schema hoặc khác bảng. |
| YCPNC-07 | Email OTP ở dev/demo gửi vào Mailpit local (SMTP port 1025). SMTP ra Internet là hướng mở rộng v2. |
| YCPNC-08 | MFA: OTP 6 số, 5 phút hiệu lực, sai tối đa 3 lần. |
| YCPNC-09 | Rate limit: tối đa 5 request login/phút/IP. |

---

## 4. API Contract Summary

### 4.1 Public API (`/api/v1/`)

| Method | Path | Auth | Roles | Mô tả |
|---|---|---|---|---|
| POST | `/auth/register` | None | — | Đăng ký |
| POST | `/auth/login` | None | — | Đăng nhập |
| POST | `/auth/mfa/verify` | None | — | Verify OTP |
| POST | `/auth/refresh` | Refresh token | — | Refresh JWT |
| POST | `/auth/logout` | JWT | USER | Logout |
| GET | `/auth/sessions` | JWT | USER | Xem session của mình |
| DELETE | `/auth/sessions/{id}` | JWT | USER | Revoke session |
| GET | `/admin/users` | JWT | SECURITY_ADMIN | Xem danh sách account |
| POST | `/admin/users/{id}/roles` | JWT | SECURITY_ADMIN | Gán role |
| DELETE | `/admin/users/{id}/roles/{role}` | JWT | SECURITY_ADMIN | Thu hồi role |
| POST | `/admin/users/{id}/lock` | JWT | SECURITY_ADMIN | Khóa account |
| DELETE | `/admin/users/{id}/lock` | JWT | SECURITY_ADMIN | Mở khóa |
| PUT | `/admin/users/{id}/mfa` | JWT | SECURITY_ADMIN | Bật/tắt MFA persistent |
| GET | `/admin/audit-logs` | JWT | SECURITY_ADMIN | Xem audit logs |
| GET | `/admin/rules` | JWT | SECURITY_ADMIN | Xem rule versions |
| POST | `/admin/rules` | JWT | SECURITY_ADMIN | Tạo rule version |
| PUT | `/admin/rules/{id}/activate` | JWT | SECURITY_ADMIN | Activate version |
| GET | `/soc/alerts` | JWT | SOC_ANALYST | Xem alerts |
| GET | `/soc/alerts/{id}` | JWT | SOC_ANALYST | Chi tiết alert |
| PUT | `/soc/alerts/{id}/acknowledge` | JWT | SOC_ANALYST | Acknowledge |
| PUT | `/soc/alerts/{id}/resolve` | JWT | SOC_ANALYST | Resolve/false_positive |

### 4.2 Internal API (`/internal/v1/`)

| Method | Path | Auth | Mô tả |
|---|---|---|---|
| POST | `/detect` | X-Internal-Secret | Inline detection: rule + ML scoring |
| POST | `/ml/score` | X-Internal-Secret | ML scoring với features vector |
| POST | `/actions` | X-Internal-Secret | Enforce security action |
| GET | `/health` | None | Health check |
