# Yêu cầu thiết kế chi tiết — Core App

**Người nhận:** Thành viên phụ trách Core App
**Deadline:** [Tuỳ bạn quy định]
**Branch:** `dev` (hoặc feature branch `core-app-design`)

---

## 1. Phạm vi bạn phải thiết kế chi tiết (Core App)

### 1.1 Entities & Schema (SQL)

Thiết kế chi tiết **tất cả** bảng thuộc phạm vi Core App:

| Bảng | Phụ trách | Chi tiết cần có |
|---|---|---|
| `users` | ✅ Core App | Thêm: `username`, `email`, `password_hash`, `status` (`active`/`locked`/`suspended`), `admin_mfa_required`, `detection_mfa_once`, `created_at`, `updated_at`. Ràng buộc: username UNIQUE. |
| `roles` | ✅ Core App | 4 role: `USER`, `SECURITY_ADMIN`, `SOC_ANALYST`, `SECURITY_MANAGER`. |
| `user_roles` | ✅ Core App | Many-to-many: `user_id` + `role_id`, `assigned_at`. |
| `sessions` | ✅ Core App | `user_id`, `access_token_hash`, `refresh_token_hash`, `expires_at`, `revoked_at`, `ip_address`, `user_agent`, `created_at`. |
| `pre_auth_transactions` | ✅ Core App | MFA: `user_id`, `mfa_code_hash` (Argon2id), `expires_at` (5 phút), `status` (`pending`/`completed`/`expired`/`failed`), `fail_count`, `bound_ip_hash`, `created_at`. |
| `rate_limits` | ✅ Core App | `ip_address`, `action`, `count`, `window_start`. UNIQUE(ip_address, action). Max 5 login/phút/IP. |
| `audit_logs` | ✅ Core App | `actor` (user_id hoặc `system:detection-engine`), `action`, `resource`, `resource_id`, `before_state` (JSONB), `after_state` (JSONB), `reason`, `ip_address`, `user_agent`, `created_at`. |

> ⚠️ **Không lưu**: password plaintext, OTP plaintext, JWT payload, email body.

---

### 1.2 Authentication & Session Endpoints

Thiết kế chi tiết **tất cả** endpoint:

```
POST   /api/v1/auth/register       — Đăng ký, Argon2id hash
POST   /api/v1/auth/login         — Login, rate limit, inline detection hook
POST   /api/v1/auth/mfa/verify    — Verify OTP 6 số
POST   /api/v1/auth/refresh       — Refresh JWT
POST   /api/v1/auth/logout        — Revoke session hiện tại
GET    /api/v1/auth/sessions      — Xem session của mình
DELETE /api/v1/auth/sessions/{id} — Revoke session lạ (chỉ của mình)
```

**Với mỗi endpoint, cần trình bày:**

- [ ] HTTP method + path + content-type
- [ ] Authentication: JWT hay không?
- [ ] Authorization (roles nào được phép)?
- [ ] Request body schema (JSON example)
- [ ] Success response (status code + body example)
- [ ] Error responses (status code + body example)
- [ ] Validation rules chi tiết (e.g. username 3-50 chars, alphanumeric + `_`)
- [ ] Edge cases xử lý như thế nào (VD: sai OTP 3 lần → thế nào?)

---

### 1.3 Security Admin Endpoints

```
GET    /api/v1/admin/users              — Danh sách account, lọc role/status
POST   /api/v1/admin/users/{id}/roles   — Gán role
DELETE /api/v1/admin/users/{id}/roles/{role} — Thu hồi role
POST   /api/v1/admin/users/{id}/lock    — Khóa account
DELETE /api/v1/admin/users/{id}/lock     — Mở khóa
PUT    /api/v1/admin/users/{id}/mfa     — Bật/tắt MFA persistent
GET    /api/v1/admin/audit-logs         — Xem audit trail
```

**Với mỗi endpoint, cần trình bày** (cùng format với Auth endpoints):

- [ ] Request/response schema
- [ ] RBAC validation (chỉ `SECURITY_ADMIN` được gọi)
- [ ] Ràng buộc: không gỡ `SECURITY_ADMIN` cuối cùng còn ACTIVE, không khóa Security Admin cuối cùng
- [ ] Audit log ghi nhận gì (`before_state` → `after_state`)
- [ ] Session revoke khi nào (khi gán/revoke role, khóa account)

---

### 1.4 Rule Versioning Endpoints

```
GET    /api/v1/admin/rules              — Danh sách rule versions
POST   /api/v1/admin/rules              — Tạo rule version mới (chưa activate)
PUT    /api/v1/admin/rules/{id}/activate — Activate rule version
```

- [ ] Schema: `version` (string), `rules_json` (JSONB), `is_active`
- [ ] Chỉ 1 version active tại một thời điểm
- [ ] Khi activate → deactivate version cũ (trong 1 transaction)
- [ ] Audit log ghi nhận

---

### 1.5 SOC Endpoints (sơ bộ — để người khác fill)

```
GET    /api/v1/soc/alerts                      — Danh sách alerts
GET    /api/v1/soc/alerts/{id}                 — Chi tiết alert
PUT    /api/v1/soc/alerts/{id}/acknowledge     — Acknowledge alert
PUT    /api/v1/soc/alerts/{id}/resolve          — Resolve hoặc false_positive
```

- [ ] Chỉ cần xác định: endpoint path, RBAC (`SOC_ANALYST`), request/response schema skeleton
- [ ] Chi tiết nghiệp vụ (status flow: `open` → `acknowledged` → `resolved`/`false_positive`) để SOC team fill thêm

---

### 1.6 Internal Endpoints (sơ bộ — để người khác fill)

```
POST   /internal/v1/detect          — Inline detection
POST   /internal/v1/ml/score        — ML scoring
POST   /internal/v1/actions         — Enforce security action
GET    /internal/v1/health          — Health check
```

- [ ] Xác định request/response schema skeleton
- [ ] Authentication: `X-Internal-Secret` header (không dùng JWT)
- [ ] Chi tiết logic detection → để detection-engine team fill

---

### 1.7 Security Requirements

Liệt kê đầy đủ:

- [ ] Argon2id hash (memory cost, parallelism)
- [ ] JWT: thuật toán, expiry, payload claims (user_id, roles[])
- [ ] OTP: 6 số, 5 phút, max 3 attempts
- [ ] Rate limit: 5 login/phút/IP
- [ ] Không log: password, OTP, JWT payload, email content
- [ ] RBAC: multi-role, endpoint-level check
- [ ] Constant-time comparison cho password/OTP verify

---

## 2. Phần sơ bộ (chỉ phác họa, người khác tự fill)

### 2.1 Detection Engine — Sơ bộ

```
POST /internal/v1/detect   ← Bạn định nghĩa request/response schema skeleton
POST /internal/v1/ml/score  ← Bạn định nghĩa features vector
```

Viết:
- [ ] Features vector cần những field nào?
- [ ] Response trả về gì (`rule_score`, `anomaly_score`, `risk_level`, `decision`)?

### 2.2 SOC Alert Management — Sơ bộ

```
GET /api/v1/soc/alerts
PUT /api/v1/soc/alerts/{id}/acknowledge
PUT /api/v1/soc/alerts/{id}/resolve
```

Viết:
- [ ] Schema của bảng `alerts` (đã có trong schema.sql)
- [ ] Status flow: `open` → `acknowledged` → `resolved`/`false_positive`
- [ ] Alert được tạo khi nào (risk_level ≥ ?)

---

## 3. Output format yêu cầu

Tạo file **`docs/core-app-design-spec.md`** với cấu trúc:

```
# Core App Design Specification

## 1. Database Schema
## 2. API Specification
   ### 2.1 Auth Endpoints
   ### 2.2 Admin Endpoints
   ### 2.3 SOC Endpoints (skeleton)
   ### 2.4 Internal Endpoints (skeleton)
## 3. Security Requirements
## 4. Detection Hooks (interface spec)
## 5. Open Questions / TBD
```

---

## 4. Checklist trước khi nộp

- [ ] Tất cả endpoint Auth có đầy đủ request/response schema
- [ ] Tất cả endpoint Admin có RBAC + audit log spec
- [ ] MFA logic rõ: 6 số, 5 phút, 3 attempts, persistent vs one-time
- [ ] Rate limit rõ: 5/phút/IP
- [ ] Không endpoint nào expose password/OTP/JWT plaintext
- [ ] Phần SOC và Detection chỉ là skeleton (placeholder)
- [ ] File `docs/core-app-design-spec.md` tồn tại và commit lên branch

---

## 5. Open Questions cần trao đổi

1. Refresh token có rotate không (sinh token mới sau mỗi refresh)?
2. JWT access token expiry bao lâu? (đề xuất: 15 phút)
3. Refresh token expiry bao lâu? (đề xuất: 7 ngày)
4. Gửi OTP qua email: dùng SMTP local (Mailpit) hay mock trong v1?
5. `X-Internal-Secret` giá trị đặt ở đâu (`config.py`, `.env`)?
