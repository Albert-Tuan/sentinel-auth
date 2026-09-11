# Phân tích đối tượng sử dụng phần mềm Sentinel Auth

## 1. Đối tượng sử dụng trong phạm vi v1

Sentinel Auth có **3 nhóm actor chính** trực tiếp sử dụng hệ thống:

| STT | Đối tượng | Mã | Phạm vi trong v1 |
|---|---|---|---|
| 1 | Người dùng (User) | USER | Đăng ký, login, MFA, quản lý session của mình |
| 2 | Quản trị viên bảo mật (Security Administrator) | SECURITY_ADMIN | Quản lý account, rule versioning, xem audit logs |
| 3 | Phân tích viên SOC (SOC Analyst) | SOC_ANALYST | Xem, acknowledge, resolve alerts |

**Lưu ý về multi-role:** Một tài khoản có thể giữ nhiều role đồng thời. Người có role `SOC_ANALYST` hoặc `SECURITY_MANAGER` vẫn dùng được các chức năng của User (login, MFA, quản lý session) — họ cũng là user bình thường.

---

## 2. Chức năng của từng đối tượng

### 2.1 Người dùng (User) — Role: `USER`

| Mã | Chức năng | Mô tả |
|---|---|---|
| U-01 | Đăng ký | Nhập username, email, password → tạo account với role `USER`. Không tự chọn role đặc biệt. |
| U-02 | Đăng nhập | Gửi username + password → xác thực. Nếu không MFA: nhận JWT + session. Nếu có MFA: nhận OTP challenge. |
| U-03 | Xác minh Email OTP | Nhập OTP 6 số khi bị yêu cầu (Admin bật hoặc detection yêu cầu one-time). |
| U-04 | Đăng xuất | Revoke session hiện tại. |
| U-05 | Xem session của mình | Xem danh sách phiên đang hoạt động: IP, device, thời gian, trạng thái. |
| U-06 | Revoke session lạ | Thu hồi một session thuộc chính mình khi phát hiện bất thường. |
| U-07 | Refresh token | Dùng refresh token lấy access token mới. |

**Giới hạn:** User không tự chọn role, không xem account người khác, không xem audit log, không gọi internal endpoints, không quản lý alerts.

---

### 2.2 Quản trị viên bảo mật (Security Administrator) — Role: `SECURITY_ADMIN`

| Mã | Chức năng | Mô tả |
|---|---|---|
| SA-01 | Xem danh sách account | Xem tất cả tài khoản, lọc theo role, status. |
| SA-02 | Gán role đặc biệt | Thêm `SECURITY_ADMIN`, `SOC_ANALYST`, `SECURITY_MANAGER` cho account. Multi-role. |
| SA-03 | Thu hồi role đặc biệt | Gỡ một role đặc biệt khỏi account, giữ nguyên các role còn lại. Không gỡ role nền `USER`. |
| SA-04 | Khóa account | Đặt `status=LOCKED` để ngăn login. |
| SA-05 | Mở khóa account | Đặt `status=ACTIVE` để cho phép login trở lại. |
| SA-06 | Bật/tắt MFA persistent | Yêu cầu hoặc gỡ yêu cầu Email OTP cho một User (duy trì đến khi tắt). |
| SA-07 | Xem rule versions | Xem danh sách phiên bản rule đã tạo. |
| SA-08 | Tạo rule version | Tạo phiên bản rule mới với rule set JSON. Chưa activate. |
| SA-09 | Activate rule version | Kích hoạt một phiên bản rule, deactivate phiên bản cũ. |
| SA-10 | Xem audit logs | Tra cứu lịch sử thay đổi: actor, action, resource, thời gian. |

**Ràng buộc bắt buộc:**
- Không gỡ `SECURITY_ADMIN` khỏi account `ACTIVE` cuối cùng còn role này → trả `409 Conflict`.
- Không khóa Security Administrator `ACTIVE` cuối cùng → trả `409 Conflict`.
- Khi role thay đổi: hệ thống revoke mọi session của account mục tiêu.
- Mọi thao tác SA-02 đến SA-09 đều ghi Audit Log.

**Giới hạn:** Security Administrator không trực tiếp xử lý alerts (đó là việc của SOC Analyst).

---

### 2.3 Phân tích viên SOC (SOC Analyst) — Role: `SOC_ANALYST`

| Mã | Chức năng | Mô tả |
|---|---|---|
| SC-01 | Xem danh sách alerts | Xem alerts, lọc theo status (open/acknowledged/resolved/false_positive) và risk_level (low/medium/high/critical), phân trang. |
| SC-02 | Xem chi tiết alert | Xem toàn bộ thông tin: login attempt, risk scores, rule hit, IP, user-agent, thời gian. |
| SC-03 | Acknowledge alert | Ghi nhận đã xem xét alert, chuyển từ `open` → `acknowledged`, ghi assigned_to và notes. |
| SC-04 | Resolve alert | Kết thúc xử lý: chuyển `acknowledged` → `resolved` hoặc `false_positive`, ghi resolved_by, resolved_at. |

**Giới hạn:** SOC Analyst không có quyền quản lý account, không tạo/sửa rule, không xem audit logs.

---

## 3. Ma trận chức năng theo đối tượng

| Chức năng | User | Security Admin | SOC Analyst |
|---|---|---:|---:|
| Đăng ký account | ✅ | ✅ (với tư cách User) | ✅ (với tư cách User) |
| Đăng nhập và nhận JWT/session | ✅ | ✅ | ✅ |
| Xác minh Email OTP khi bị yêu cầu | ✅ | ✅ | ✅ |
| Logout, xem/revoke session của mình | ✅ | ✅ | ✅ |
| Refresh token | ✅ | ✅ | ✅ |
| Xem danh sách account | ❌ | ✅ | ❌ |
| Gán/thu hồi role đặc biệt | ❌ | ✅ | ❌ |
| Khóa/mở khóa account | ❌ | ✅ | ❌ |
| Bật/tắt MFA persistent cho User | ❌ | ✅ | ❌ |
| Xem/tạo/activate rule versions | ❌ | ✅ | ❌ |
| Xem audit logs | ❌ | ✅ | ❌ |
| Xem danh sách alerts | ❌ | ❌ | ✅ |
| Acknowledge alert | ❌ | ❌ | ✅ |
| Resolve alert | ❌ | ❌ | ✅ |
| Xem/revoke session người khác | ❌ | ❌ | ❌ |
| Gọi internal endpoints | ❌ | ❌ | ❌ |

---

## 4. Role hierarchy và RBAC

### 4.1 Role definitions

| Role | Mô tả | Được gán khi |
|---|---|---|
| `USER` | Role nền, mặc định. Ai cũng có. Không bị gỡ trong v1. | Đăng ký |
| `SECURITY_ADMIN` | Quản trị cao nhất. Quản lý account, rule, audit. | Security Administrator gán |
| `SECURITY_MANAGER` | Quản lý bảo mật. Có quyền quản lý account + rule. Không xem audit logs. | Security Administrator gán |
| `SOC_ANALYST` | Phân tích SOC. Xử lý alerts. Không có quyền admin. | Security Administrator gán |

### 4.2 RBAC rules

- JWT mang claim `roles` dạng mảng: `["USER", "SOC_ANALYST"]`
- Endpoint cho phép khi account có **ít nhất 1 role** trong danh sách roles được yêu cầu.
- Không tự động include role nền `USER` khi gán special roles.
- Khi role bị thu hồi → tất cả session bị revoke.

---

## 5. Quan hệ giữa các đối tượng

### 5.1 User ↔ Security Administrator

- User bị Admin tác động (khóa, revoke session, bật MFA) → User nhận thông báo (OTP challenge, login fail).
- User có thể báo cáo hoạt động bất thường cho Admin (ngoài phạm vi v1).

### 5.2 User ↔ SOC Analyst

- SOC Analyst theo dõi login attempt của User qua alerts.
- User không tương tác trực tiếp với SOC Analyst trong v1.

### 5.3 Security Administrator ↔ SOC Analyst

- Admin gán role `SOC_ANALYST` cho analyst.
- Không có quan hệ trực tiếp khác.

### 5.4 Detection Engine (Internal)

- Không phải actor con người.
- Hoạt động tự động: sau mỗi login attempt, inline detection đánh giá risk.
- Khi risk cao → tạo alert (SOC xử lý).
- Khi risk vừa → enforce action (REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER) → tác động lên User.

---

## 6. Luồng dữ liệu giữa actors

```
User ──login──▶ FastAPI (inline detection)
                   │
                   ├── rule_score + ml_score ──▶ Risk Level
                   │                                 │
                   │                    ┌─────────────┼─────────────┐
                   │                    ▼             ▼             ▼
                   │               allow         challenge       block
                   │               (token)       (OTP req)    (403 + alert)
                   │                                 │
                   │                    ┌─────────────┴─────────────┐
                   │                    ▼                           ▼
                   │              MFA verify                  Alert created
                   │              (SC-03)                     (SOC handles)
                   │                    │
                   │         ┌───────────┼───────────┐
                   │         ▼                       ▼
                   │    token granted            SOC Analyst
                   │                              acknowledges
                   │                              or resolves
                   │
                   ├── Admin (SA-*) ◄─── manages ──► User account
                   │
                   └── Audit Log (SA-10) ◄── all actions
```

---

## 7. Phân biệt actors gần gũi

| So sánh | Security Administrator | SOC Analyst |
|---|---|---|
| Mục tiêu | Quản lý account & security config | Xử lý alerts từ detection |
| Quản lý account | ✅ Full | ❌ Không |
| Rule versioning | ✅ | ❌ Không |
| Xem audit logs | ✅ | ❌ Không |
| Xem alerts | ❌ Không (có thể mở rộng v2) | ✅ Full |
| Resolve alerts | ❌ Không | ✅ |
| Multi-role | Có thể đồng thời là `SOC_ANALYST` | Có thể đồng thời là `USER` |
