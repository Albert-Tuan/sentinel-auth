# BẢNG YÊU CẦU CHỨC NĂNG NGHIỆP VỤ - SENTINEL AUTH
## Phiên bản 2.0 — Dựa trên Schema v3 & Implementation thực tế

> **Nguồn:** `app/auth.py`, `app/detection.py`, `app/models.py`, `app/schemas.py`, `infra/postgres/schema-v3.sql`
> **Ngày:** 2026-09-12
> **Trạng thái:** Hoàn chỉnh — Sửa đổi từ bản gốc của thành viên ML

---

## MỤC LỤC

1. Đối tượng sử dụng phần mềm
2. Master Matrix: Actor - Business Function - Requirement - Use Case
3. Yêu cầu chức năng nghiệp vụ theo đối tượng
   - 3.1. User
   - 3.2. SOC Analyst
   - 3.3. Security Administrator
   - 3.4. Security Manager
4. Quy định nghiệp vụ cốt lõi
5. Danh sách Use Case chi tiết
6. Sơ đồ kiến trúc và luồng
7. Chức năng nội bộ của hệ thống

---

## 1. ĐỐI TƯỢNG SỬ DỤNG PHẦN MỀM

| STT | Đối tượng | Mã | Mô tả |
|------|-----------|-----|-------|
| 1 | Người dùng/nhân viên | USER | Sử dụng tài khoản của tổ chức để đăng nhập, thực hiện MFA, quản lý phiên của chính mình và phản hồi khi phát hiện lần đăng nhập bất thường. |
| 2 | Chuyên viên giám sát an toàn thông tin | SOC_ANALYST | Theo dõi login event và cảnh báo, xem bằng chứng rủi ro, điều tra incident, phân loại kết quả và yêu cầu hành động bảo vệ. |
| 3 | Quản trị viên bảo mật/hệ thống | SECURITY_ADMIN | Quản lý tài khoản, role, MFA/chính sách xác thực, rule/threshold, audit và các tham số bảo mật của hệ thống. |
| 4 | Quản lý an toàn thông tin | SECURITY_MANAGER | Theo dõi dashboard tổng hợp, xu hướng rủi ro và báo cáo; chủ yếu có quyền xem và đánh giá tổng thể. |

---

## 2. MASTER MATRIX: ACTOR - BUSINESS FUNCTION - REQUIREMENT - USE CASE

| Actor | Mã chức năng | Business Function | Mã yêu cầu | Use Case | Luồng/Sơ đồ liên quan | Mức ưu tiên |
|-------|-------------|-------------------|-----------|----------|------------------------|-------------|
| **USER** | U-01 | Đăng nhập | YCNV-U-01 | UC-01 | Quy trình Login tổng thể | Bắt buộc |
| **USER** | U-02 | Thực hiện MFA | YCNV-U-02 | UC-02 | MFA State | Bắt buộc |
| **USER** | U-03 | Xem và quản lý session của mình | YCNV-U-03 | UC-03 | Session flow | Bắt buộc |
| **USER** | U-04 | Xác nhận/báo cáo lần đăng nhập | YCNV-U-04 | UC-04 | Incident/feedback flow | Nên có |
| **USER** | U-05 | Quản lý thiết bị tin cậy | YCNV-U-05 | UC-05 | Trusted device flow | Mở rộng |
| **USER** | U-06 | Đăng ký tài khoản mới | YCNV-U-06 | UC-22 | Registration flow | Bắt buộc |
| **USER** | U-07 | Làm mới token (refresh) | YCNV-U-07 | UC-23 | Token refresh flow | Bắt buộc |
| **SOC_ANALYST** | S-01 | Theo dõi SOC Dashboard | YCNV-S-01 | UC-06 | Overall activity | Bắt buộc |
| **SOC_ANALYST** | S-02 | Tra cứu lịch sử đăng nhập | YCNV-S-02 | UC-07 | Login event flow | Bắt buộc |
| **SOC_ANALYST** | S-03 | Xem bằng chứng Rule/ML/Risk | YCNV-S-03 | UC-08 | Risk flow | Bắt buộc |
| **SOC_ANALYST** | S-04 | Tiếp nhận và điều tra Alert | YCNV-S-04 | UC-09 | Incident State | Bắt buộc |
| **SOC_ANALYST** | S-05 | Phân loại kết quả điều tra | YCNV-S-05 | UC-10 | Incident State | Bắt buộc |
| **SOC_ANALYST** | S-06 | Yêu cầu hành động bảo vệ | YCNV-S-06 | UC-11 | Response flow | Bắt buộc |
| **SOC_ANALYST** | S-07 | Đóng hồ sơ Incident | YCNV-S-07 | UC-12 | Incident State | Bắt buộc |
| **SECURITY_ADMIN** | A-01 | Quản lý tài khoản và role | YCNV-A-01 | UC-13 | Account management flow | Bắt buộc |
| **SECURITY_ADMIN** | A-02 | Quản lý MFA/Auth Policy | YCNV-A-02 | UC-14 | Policy flow | Bắt buộc |
| **SECURITY_ADMIN** | A-03 | Quản lý RuleSet/Threshold | YCNV-A-03 | UC-15 | Rule configuration flow | Bắt buộc |
| **SECURITY_ADMIN** | A-04 | Cấu hình kênh cảnh báo | YCNV-A-04 | UC-16 | Notification flow | Nên có |
| **SECURITY_ADMIN** | A-05 | Quản lý Trust/Block List | YCNV-A-05 | UC-17 | Trust/block flow | Mở rộng |
| **SECURITY_ADMIN** | A-06 | Tra cứu Audit Log | YCNV-A-06 | UC-18 | Audit flow | Bắt buộc |
| **SECURITY_ADMIN** | A-07 | Quản lý tham số vận hành | YCNV-A-07 | UC-19 | Configuration flow | Nên có |
| **SECURITY_MANAGER** | M-01 | Xem Dashboard tổng hợp và xu hướng | YCNV-M-01 | UC-20 | Management dashboard | Bắt buộc |
| **SECURITY_MANAGER** | M-02 | Xem/Xuất báo cáo tổng hợp | YCNV-M-02 | UC-21 | Reporting flow | Bắt buộc |

---

## 3. YÊU CẦU CHỨC NĂNG NGHIỆP VỤ THEO ĐỐI TƯỢNG

### 3.1. USER (Người dùng)

| Mã | Công việc | Loại công việc | Quy định liên quan | Kết quả |
|-----|-----------|----------------|---------------------|---------|
| YCNV-U-01 | Đăng nhập | Xử lý/Lưu trữ | U-QĐ-01 | Đăng nhập được cho phép, yêu cầu MFA hoặc bị từ chối. Mọi lần đăng nhập tạo LoginAttempt record. |
| YCNV-U-02 | Thực hiện MFA | Xác thực | U-QĐ-02 | MFA thành công tạo phiên; thất bại/hết hạn không tạo phiên. |
| YCNV-U-03 | Xem và thu hồi session | Tra cứu/Lưu trữ | U-QĐ-03 | User chỉ thao tác với session thuộc chính mình. |
| YCNV-U-04 | Xác nhận hoặc báo cáo login attempt | Lưu trữ | U-QĐ-04 | Phản hồi được gắn với login event/alert tương ứng. |
| YCNV-U-05 | Quản lý thiết bị tin cậy | Lưu trữ | U-QĐ-05 | Thiết bị được thêm/gỡ khỏi danh sách tin cậy theo chính sách. |
| YCNV-U-06 | Đăng ký tài khoản mới | Lưu trữ | U-QĐ-06 | Tạo tài khoản mới với role USER, hash password bằng Argon2id. |
| YCNV-U-07 | Làm mới token | Xử lý | U-QĐ-07 | Access token mới được cấp phát, refresh token có thể được rotate. |

### 3.2. SOC ANALYST (Chuyên viên SOC)

| Mã | Công việc | Loại công việc | Quy định liên quan | Kết quả |
|-----|-----------|----------------|---------------------|---------|
| YCNV-S-01 | Xem SOC Dashboard | Tra cứu/Tổng hợp | S-QĐ-01 | Hiển thị chỉ số login/alert/incident gần thời gian thực. |
| YCNV-S-02 | Tra cứu login event | Tra cứu | S-QĐ-02 | Lọc theo thời gian, user, IP, mức rủi ro, trạng thái. |
| YCNV-S-03 | Xem Rule/ML/Risk evidence | Tra cứu | S-QĐ-03 | Hiển thị rule hit, anomaly score, total risk và context. |
| YCNV-S-04 | Tiếp nhận/điều tra alert | Lưu trữ | S-QĐ-04 | Alert chuyển trạng thái hợp lệ và lưu timeline. |
| YCNV-S-05 | Phân loại kết quả điều tra | Lưu trữ | S-QĐ-05 | Kết quả: resolved, false_positive hoặc tiếp tục theo dõi. |
| YCNV-S-06 | Yêu cầu hành động bảo vệ | Lưu trữ/Điều khiển | S-QĐ-06 | Sinh yêu cầu MFA lại, revoke session, rate limit hoặc khóa tạm thời theo quyền. |
| YCNV-S-07 | Đóng incident | Lưu trữ | S-QĐ-07 | Incident kết thúc và có lịch sử xử lý đầy đủ trong alert_timeline. |

### 3.3. SECURITY ADMINISTRATOR (Quản trị viên)

| Mã | Công việc | Loại công việc | Quy định liên quan | Kết quả |
|-----|-----------|----------------|---------------------|---------|
| YCNV-A-01 | Quản lý tài khoản và role | Lưu trữ | A-QĐ-01 | Tạo/cập nhật trạng thái, gán/thu hồi role và ghi audit. |
| YCNV-A-02 | Quản lý MFA/Auth Policy | Lưu trữ/Cấu hình | A-QĐ-02 | Cập nhật chính sách MFA/xác thực áp dụng cho login sau đó. |
| YCNV-A-03 | Quản lý RuleSet/Threshold | Lưu trữ/Cấu hình | A-QĐ-03 | Rule/threshold hợp lệ được áp dụng cho detection. |
| YCNV-A-04 | Cấu hình kênh cảnh báo | Lưu trữ/Cấu hình | A-QĐ-04 | Hệ thống biết kênh nhận cảnh báo và trạng thái cấu hình. |
| YCNV-A-05 | Quản lý Trust/Block List | Lưu trữ | A-QĐ-05 | Thêm/gỡ đối tượng tin cậy hoặc chặn có lý do và thời hạn nếu có. |
| YCNV-A-06 | Tra cứu Audit Log | Tra cứu | A-QĐ-06 | Truy vết được các thao tác quan trọng. |
| YCNV-A-07 | Quản lý tham số vận hành | Lưu trữ/Cấu hình | A-QĐ-07 | Cập nhật timeout, retention hoặc tham số được phép cấu hình qua system_settings. |

### 3.4. SECURITY MANAGER (Quản lý)

| Mã | Công việc | Loại công việc | Quy định liên quan | Kết quả |
|-----|-----------|----------------|---------------------|---------|
| YCNV-M-01 | Xem dashboard tổng hợp/xu hướng | Tổng hợp/Tra cứu | M-QĐ-01 | Hiển thị dữ liệu aggregate phục vụ quản lý. |
| YCNV-M-02 | Xem/Xuất báo cáo tổng hợp | Kết xuất | M-QĐ-02 | Sinh báo cáo tổng hợp phù hợp quyền quản lý. |

---

## 4. QUY ĐỊNH NGHIỆP VỤ CỐT LÕI

| Mã | Tên quy định | Mô tả |
|----|-------------|-------|
| **U-QĐ-01** | Quy định đăng nhập | Tài khoản phải ở trạng thái `active` mới được đăng nhập. Mọi kết quả xác thực cuối cùng đều phải sinh `LoginAttempt`. Kết quả có thể là `success`, `failure`, `mfa_required`, `mfa_success`, `mfa_failed`, `blocked`, `locked`, `rate_limited`. |
| **U-QĐ-02** | Quy định MFA | MFA chỉ tạo session khi challenge hợp lệ và xác minh thành công. Challenge sai quá 3 lần hoặc hết hạn (5 phút) phải kết thúc theo trạng thái tương ứng (`expired`, `failed`). |
| **U-QĐ-03** | Quy định session | User chỉ xem và thu hồi session của chính mình. Session đã bị thu hồi (`revoked_at IS NOT NULL`) không tiếp tục được sử dụng. |
| **U-QĐ-04** | Quy định phản hồi login | Phản hồi phải liên kết đúng login attempt; phản hồi không tự thay đổi kết luận điều tra của SOC. |
| **U-QĐ-05** | Quy định thiết bị tin cậy | Thiết bị được đăng ký qua `user_trusted_devices`. Thiết bị có thể hết hạn hoặc bị gỡ thủ công. |
| **U-QĐ-06** | Quy định đăng ký | Username 3-50 ký tự (a-z, 0-9, _), password tối thiểu 8 ký tự, email hợp lệ. Mặc định gán role USER. |
| **U-QĐ-07** | Quy định token refresh | Refresh token được verify qua hash trong DB. Access token hết hạn sau 15 phút (configurable). |
| **S-QĐ-01** | Quy định dashboard | Dashboard chỉ hiển thị dữ liệu mà actor có quyền xem; số liệu tổng hợp không thay thế dữ liệu điều tra chi tiết. |
| **S-QĐ-02** | Quy định tra cứu login event | Có thể lọc theo: occurred_at, user_id, source_ip, risk_level, outcome. |
| **S-QĐ-03** | Quy định bằng chứng rủi ro | Khi xem một alert phải phân biệt `rule_score` (từ rule engine), `anomaly_score` (từ ML model), và `combined_score` (tổng hợp). ML không được mô tả như xác suất tấn công nếu chưa hiệu chuẩn xác suất. |
| **S-QĐ-04** | Quy định trạng thái alert | Alert chỉ được chuyển theo luồng trạng thái hợp lệ: `open` → `acknowledged` → `resolved`/`false_positive`. Mọi thay đổi được ghi vào `alert_timeline`. |
| **S-QĐ-05** | Quy định kết quả điều tra | Kết quả điều tra được ghi nhận: `resolved` (xác nhận có vấn đề), `false_positive` (cảnh báo sai). |
| **S-QĐ-06** | Quy định response | SOC Analyst yêu cầu hành động bảo vệ theo quyền: `REQUIRE_MFA`, `REVOKE_SESSIONS`, `LOCK_USER`. Hành động phải được audit và ghi vào `detection_logs`. |
| **S-QĐ-07** | Quy định đóng incident | Incident chỉ được đóng khi đã có đầy đủ timeline trong `alert_timeline`. |
| **A-QĐ-01** | Quy định quản trị tài khoản | Mọi thay đổi role/trạng thái tài khoản phải ghi `AuditLog`; không được tự động làm mất toàn bộ quyền quản trị hợp lệ. |
| **A-QĐ-02** | Quy định MFA Policy | MFA có thể là `persistent` (luôn yêu cầu) hoặc `one_time` (chỉ sau detection challenge). |
| **A-QĐ-03** | Quy định RuleSet/Threshold | Rule và threshold phải có cấu hình rõ ràng trong `policy_versions.rules_json`. Chỉ một policy được active tại một thời điểm. |
| **A-QĐ-04** | Quy định cấu hình notification | Cấu hình notification được lưu trong `system_settings` với categories: `notification`, `mfa`, `auth`. |
| **A-QĐ-05** | Quy định Trust/Block List | IP/ASN có thể được block tạm thời hoặc vĩnh viễn. Blocked IP được ghi nhận trong `detection_logs`. |
| **A-QĐ-06** | Quy định Audit Log | Audit Log phải đủ actor, action, resource, thời gian và kết quả; không lưu mật khẩu, OTP, token hoặc secret dạng rõ. |
| **A-QĐ-07** | Quy định system settings | Các tham số vận hành được lưu trong `system_settings`. Chỉ admin mới được cập nhật. |
| **M-QĐ-01** | Quy định quyền Manager | Security Manager chủ yếu dùng dữ liệu tổng hợp/read-only trong baseline. Không có quyền thay đổi cấu hình. |
| **M-QĐ-02** | Quy định báo cáo | Báo cáo phải tuân thủ data retention policy và chỉ export dữ liệu user có quyền. |

---

## 5. DANH SÁCH USE CASE CHI TIẾT

| Mã UC | Tên Use Case | Actor chính | Yêu cầu nguồn | Ưu tiên |
|-------|-------------|-------------|----------------|---------|
| UC-01 | Đăng nhập | User | YCNV-U-01 | Bắt buộc |
| UC-02 | Thực hiện MFA | User | YCNV-U-02 | Bắt buộc |
| UC-03 | Xem và quản lý session của mình | User | YCNV-U-03 | Bắt buộc |
| UC-04 | Xác nhận/báo cáo lần đăng nhập | User | YCNV-U-04 | Nên có |
| UC-05 | Quản lý thiết bị tin cậy | User | YCNV-U-05 | Mở rộng |
| UC-06 | Theo dõi SOC Dashboard | SOC Analyst | YCNV-S-01 | Bắt buộc |
| UC-07 | Tra cứu lịch sử đăng nhập | SOC Analyst | YCNV-S-02 | Bắt buộc |
| UC-08 | Xem bằng chứng Rule/ML/Risk | SOC Analyst | YCNV-S-03 | Bắt buộc |
| UC-09 | Tiếp nhận và điều tra Alert | SOC Analyst | YCNV-S-04 | Bắt buộc |
| UC-10 | Phân loại kết quả điều tra | SOC Analyst | YCNV-S-05 | Bắt buộc |
| UC-11 | Yêu cầu hành động bảo vệ | SOC Analyst | YCNV-S-06 | Bắt buộc |
| UC-12 | Đóng hồ sơ Incident | SOC Analyst | YCNV-S-07 | Bắt buộc |
| UC-13 | Quản lý tài khoản và role | Security Administrator | YCNV-A-01 | Bắt buộc |
| UC-14 | Quản lý MFA/Auth Policy | Security Administrator | YCNV-A-02 | Bắt buộc |
| UC-15 | Quản lý RuleSet/Threshold | Security Administrator | YCNV-A-03 | Bắt buộc |
| UC-16 | Cấu hình kênh cảnh báo | Security Administrator | YCNV-A-04 | Nên có |
| UC-17 | Quản lý Trust/Block List | Security Administrator | YCNV-A-05 | Mở rộng |
| UC-18 | Tra cứu Audit Log | Security Administrator | YCNV-A-06 | Bắt buộc |
| UC-19 | Quản lý tham số vận hành | Security Administrator | YCNV-A-07 | Nên có |
| UC-20 | Xem Dashboard tổng hợp và xu hướng | Security Manager | YCNV-M-01 | Bắt buộc |
| UC-21 | Xem/Xuất báo cáo tổng hợp | Security Manager | YCNV-M-02 | Bắt buộc |
| UC-22 | Đăng ký tài khoản mới | User | YCNV-U-06 | Bắt buộc |
| UC-23 | Làm mới token (Refresh) | User | YCNV-U-07 | Bắt buộc |

---

## 6. SƠ ĐỒ KIẾN TRÚC VÀ LUỒNG

### 6.1. Sơ đồ quy trình đăng nhập tổng thể

```
┌──────────┐
│  User    │
│ Login    │
└────┬─────┘
     │ POST /api/v1/auth/login
     ▼
┌─────────────────────────────┐
│  1. Rate Limit Check       │
│     rate_limits table      │
└──────────────┬──────────────┘
                │ OK
                ▼
┌─────────────────────────────┐
│  2. Credential Verify       │
│     users + password_hash   │
└──────────────┬──────────────┘
                │ Valid
                ▼
┌─────────────────────────────┐
│  3. Account Status Check    │
│     status != 'locked'      │
└──────────────┬──────────────┘
                │ OK
                ▼
┌─────────────────────────────┐
│  4. MFA Required?           │
│     admin_mfa_required OR   │
│     detection_mfa_once      │
└──────────────┬──────────────┘
                │
        ┌───────┴───────┐
        │YES            │NO
        ▼               ▼
┌───────────────┐ ┌─────────────────┐
│ Create        │ │ Create Session  │
│ PreAuth + OTP │ │ + JWT Tokens    │
│ Send Email    │ │ Return to User  │
└───────┬───────┘ └─────────────────┘
        │ POST /api/v1/auth/mfa/verify
        │ (User submits OTP)
        ▼
┌─────────────────────────────┐
│  5. Verify OTP             │
│     Argon2id compare        │
│     Check expiry + fail_cnt │
└──────────────┬──────────────┘
                │ Success
                ▼
┌─────────────────────────────┐
│  Create Session            │
│  + JWT Tokens              │
└─────────────────────────────┘
```

### 6.2. Sơ đồ luồng trạng thái Alert/Incident

```
                    ┌──────────┐
                    │   NEW    │
                    │  (open)  │
                    └────┬─────┘
                         │ acknowledge
                         ▼
               ┌──────────────────┐
               │ ACKNOWLEDGED     │
               └────────┬─────────┘
                        │
          ┌─────────────┼─────────────┐
          │investigate  │escalate     │resolve
          ▼             ▼             ▼
    ┌───────────┐ ┌─────────┐ ┌──────────┐
    │ INVESTIGATING │ │(internal)│ │ RESOLVED│
    └─────┬─────┘ └─────────┘ └────┬─────┘
          │                         │
          │         ┌───────────────┘
          │         │false_positive
          │         ▼
          │   ┌─────────────┐
          │   │FALSE_POSITIVE│
          │   └─────────────┘
          │         │
          └─────────┘
                │
                ▼
          ┌──────────┐
          │  CLOSED │
          └──────────┘
```

### 6.3. Sơ đồ luồng trạng thái MFA Challenge

```
┌─────────────┐
│  PENDING    │
└──────┬──────┘
       │ verify success
       ▼
┌─────────────┐
│  COMPLETED  │
└─────────────┘

┌─────────────┐     fail_count >= 3
│  PENDING    │──────────────────┐
└──────┬──────┘                  │
       │                         ▼
       │ expire              ┌─────────┐
       └──────────────┐      │ FAILED  │
                       │      └─────────┘
                       ▼
                 ┌──────────┐
                 │ EXPIRED  │
                 └──────────┘
```

### 6.4. Use Case Diagram tổng thể

```mermaid
usecase-diagram
left to right direction

actor User as U
actor SOCAnalyst as S
actor SecurityAdmin as A
actor SecurityManager as M

package "Authentication" {
  usecase "UC-01: Đăng nhập" as UC01
  usecase "UC-02: Thực hiện MFA" as UC02
  usecase "UC-03: Quản lý session" as UC03
  usecase "UC-22: Đăng ký tài khoản" as UC22
  usecase "UC-23: Refresh token" as UC23
}

package "SOC Operations" {
  usecase "UC-06: SOC Dashboard" as UC06
  usecase "UC-07: Tra cứu login event" as UC07
  usecase "UC-08: Xem Risk evidence" as UC08
  usecase "UC-09: Điều tra Alert" as UC09
  usecase "UC-10: Phân loại kết quả" as UC10
  usecase "UC-11: Yêu cầu bảo vệ" as UC11
  usecase "UC-12: Đóng incident" as UC12
}

package "Administration" {
  usecase "UC-13: Quản lý tài khoản" as UC13
  usecase "UC-14: MFA Policy" as UC14
  usecase "UC-15: RuleSet/Threshold" as UC15
  usecase "UC-16: Notification" as UC16
  usecase "UC-18: Audit Log" as UC18
  usecase "UC-19: System Settings" as UC19
}

package "Management" {
  usecase "UC-20: Dashboard" as UC20
  usecase "UC-21: Báo cáo" as UC21
}

U --> UC01
U --> UC02
U --> UC03
U --> UC22
U --> UC23

S --> UC06
S --> UC07
S --> UC08
S --> UC09
S --> UC10
S --> UC11
S --> UC12

A --> UC13
A --> UC14
A --> UC15
A --> UC16
A --> UC18
A --> UC19

M --> UC20
M --> UC21
```

---

## 7. CHỨC NĂNG NỘI BỘ CỦA HỆ THỐNG

> Các thành phần này KHÔNG PHẢI actor người dùng — chúng là các service/chức năng internal

| Thành phần | Vai trò | Implementation Reference |
|------------|---------|--------------------------|
| **Authentication/MFA** | Xác thực credential, quản lý challenge MFA và tạo/thu hồi session. | `app/auth.py` |
| **Login Event Collector** | Tạo và chuẩn hóa sự kiện đăng nhập vào `login_attempts`. | `app/auth.py` |
| **Rule Engine** | Phát hiện mẫu đã biết và tạo `rule_score` từ policy_versions.rules_json. | `app/detection.py:evaluate_rules()` |
| **ML Anomaly Engine** | Phân tích hành vi bất thường và tạo `anomaly_score`. | `app/ml.py` |
| **Risk Engine** | Tổng hợp `rule_score`, `anomaly_score` thành `combined_score`. | `app/detection.py:ml_score()` |
| **Alert/Incident Engine** | Tạo alert, duy trì trạng thái incident và timeline. | `app/detection.py` |
| **Audit Logging** | Ghi vết các thao tác bảo mật/quản trị quan trọng. | `app/models.py:AuditLog` |
| **Feature Builder** | Chuẩn bị feature vector cho ML từ login event data. | `app/detection.py:DetectionFeatureVector` |

---

## PHỤ LỤC: BẢNG DATABASE TƯƠNG ỨNG

| Use Case | Primary Tables | Foreign Keys |
|----------|---------------|--------------|
| UC-01, UC-02 | `users`, `sessions`, `login_attempts`, `pre_auth_transactions`, `mfa_notifications` | user_id, notification_id |
| UC-03 | `sessions`, `users` | user_id |
| UC-06-12 | `alerts`, `login_attempts`, `risk_assessments`, `detection_logs`, `alert_timeline` | alert_id, login_attempt_id |
| UC-13 | `users`, `user_roles`, `roles`, `audit_logs` | user_id, role_id |
| UC-14-15 | `policy_versions`, `system_settings`, `audit_logs` | created_by_user_id |
| UC-18 | `audit_logs`, `users` | actor |
| UC-19 | `system_settings`, `users` | updated_by |
| UC-22 | `users`, `user_roles` | - |

---

> **Tổng kết:** 23 Use Cases | 4 Actors | 27 Business Requirements | 4 System Components
