# M12.0 — API Inventory (Sentinel Auth v3.3)

**Baseline:** `origin/dev` @ `c89bff5`
**Nguồn:** OpenAPI sinh từ ứng dụng FastAPI thật (`app.main:app`), `openapi: 3.1.0`, `title: Sentinel Auth`, `version: 3.3.0`.
**Ngày lập:** 2026-11-10.

> **Quy tắc:** Tài liệu này chỉ mô tả endpoint **đang tồn tại** trong source code. Không có endpoint nào được "tự tạo" để phục vụ UI. Mọi nhu cầu UI chưa có API được ghi ở mục [§7 — Gap](#7-gap-các-api-backend-còn-thiếu).

---

## 1. Tổng quan

| Hạng mục | Số lượng |
|---|---|
| Tổng số path | 52 |
| Tổng số operation (method + path) | **57** |
| Operation public (không cần auth) | 7 |
| Operation cần Bearer token, bất kỳ user đã đăng nhập | 10 |
| Operation có RBAC (role cụ thể) | 27 |
| Operation internal-only (`X-Internal-Secret`) | 8 (secret) + 3 (probe công khai) = 11 |
| Operation health / readiness | 2 |

> Tổng: 7 + 10 + 27 + 11 + 2 = **57**. Trong đó **44** operation nằm dưới `/api/v1` và có thể gọi từ browser; cộng thêm `/health` + `/ready` ⇒ **46** operation browser-callable.
> `app/detection.py` đóng góp **4** operation internal (`login-events`, `login-attempts/{id}`, `pre-token-check`, `health`); tag `detection-internal` có 5 vì `detection_analytics.py` đóng góp thêm 1.
> Trong 11 operation internal: **8** bắt buộc `X-Internal-Secret`; **3** là probe/contract công khai (`/internal/health`, `/internal/ml/health`, `/internal/ml/features`) — xem §10.

Phân theo router (prefix + tag):

| File | Prefix | Tag | Ops |
|---|---|---|---|
| `app/auth.py` | `/api/v1/auth` | `auth` | 9 |
| `app/iam.py` | `/api/v1/admin` | `iam-admin` | 7 |
| `app/alerts.py` | `/api/v1` | `soc` | 9 |
| `app/detection.py` (policy_router) | `/api/v1/policies` | `policies` | 5 |
| `app/detection.py` (router) | `/api/v1/internal` | `detection-internal` | 4 |
| `app/devices.py` | `/api/v1/devices` | `devices` | 8 |
| `app/login_history.py` | `/api/v1` | `detection-investigation` | 1 |
| `app/manager.py` | `/api/v1` | `manager` | 5 |
| `app/internal_actions.py` | `/api/v1/internal` | `core-internal` | 2 |
| `app/core_analytics.py` | `/api/v1/internal` | `core-internal` | 1 |
| `app/detection_analytics.py` | `/api/v1/internal` | `detection-internal` | 1 |
| `app/ml.py` | `/api/v1/internal` | `ml-internal` | 3 |
| `app/main.py` | `/`, `/ready` | — | 2 |

---

## 2. Mô hình xác thực (đọc trước mọi endpoint)

Backend **không** dùng JWT. Token là **opaque random 32 ký tự** (`secrets.token_urlsafe(32)`), lưu dạng **SHA-256 hash** trong bảng `sessions` (core-db).

```python
# app/authz.py
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)
```

**Hệ quả bắt buộc cho frontend:**

1. **KHÔNG decode token.** Không có `jwtDecode`, không có `atob` + parse payload. Token không chứa `sub`/`exp`/`roles`.
2. **Vai trò lấy từ server**, không từ token. Nguồn duy nhất: `GET /api/v1/auth/me` → `UserItem.roles: string[]`.
3. Roles được đọc **real-time từ DB** mỗi request (`app/authz.py` → `get_current_auth_context`), nên thu hồi quyền có hiệu lực ngay lập tức — frontend không cần cache role lâu dài.
4. Header bắt buộc: `Authorization: Bearer <access_token>`.
5. `POST /api/v1/auth/refresh` **xoay vòng refresh token** (token rotation): response luôn trả `refresh_token` mới, token cũ không dùng lại được.

### 2.1 Ma trận xác thực

| Loại | Header | Khi nào dùng |
|---|---|---|
| **Public** | không | login, register, mfa/verify, refresh, trusted-device pending/complete/check |
| **Bearer** | `Authorization: Bearer <token>` | mọi endpoint của user đã đăng nhập (self-service) |
| **Internal** | `X-Internal-Secret: <secret>` | chỉ service-to-service; **browser KHÔNG BAO GIỜ được giữ secret này** |

> `X-Internal-Secret` phải dài ≥ 32 ký tự, không được là `changeme-in-production` và không được bắt đầu bằng các prefix mẫu (`change-me`, `secret`, `password`, `placeholder`, `your-`…). Xem `app/internal_auth.py`.
> Ứng dụng **từ chối khởi động** nếu `INTERNAL_SECRET` không hợp lệ.

### 2.2 Mã lỗi xác thực

| Code | Body `detail` | Nguyên nhân |
|---|---|---|
| 401 | `"Missing Authorization header"` | thiếu header |
| 401 | `"Invalid Authorization header format"` | không phải `Bearer <token>` |
| 401 | `"Token is empty"` | token rỗng |
| 401 | `"Invalid or expired session"` | hash không khớp / session revoked / hết hạn |
| 401 | `"User not found"` | user đã bị xoá |
| 401 | `"Account is not active"` | `user.status != 'active'` (locked/suspended) |
| 403 | `"Insufficient permissions"` | role không thuộc allow-list (`require_roles`) |

---

## 3. NHÓM 1 — Authentication (`tag: auth`, prefix `/api/v1/auth`)

### 3.1 `POST /api/v1/auth/register` — Public

| | |
|---|---|
| Auth | Không |
| Roles | — |
| Request | `UserRegisterRequest { username: string (3-50, `^[a-zA-Z0-9_]+$`), email?: string, password: string (≥8) }` |
| Response | **201** `UserRegisterResponse { id, username, email?, created_at }` |
| Errors | 409 `Username already exists` / `Email already exists`; 422 validation |

User mới tự động có role `USER`. Không tự assign role đặc biệt.

### 3.2 `POST /api/v1/auth/login` — Public

| | |
|---|---|
| Auth | Không |
| Roles | — |
| Request | `LoginRequest { username, password }` — IP lấy server-side từ `request.client.host` (app **không** đọc `X-Forwarded-For` trực tiếp) |
| Response | **200** `LoginResponse { access_token: string, refresh_token: string, mfa_required: boolean, session_id: UUID }` |
| Errors | **401** `Invalid credentials`; **423** `Account is locked`; **429** `Too many requests. Try again later.` (rate limit 5 req/phút/IP) |

**Hai nhánh trả về (rất quan trọng cho UI):**

- **Không cần MFA** → `mfa_required: false`, `access_token`/`refresh_token` có giá trị, `session_id` = session ID thật.
- **Cần MFA** → `mfa_required: true`, `access_token: ""`, `refresh_token: ""`, `session_id` = **ID của `MfaTransaction` (pre-auth transaction), KHÔNG phải session ID**. UI phải dùng giá trị này làm `session_id` cho bước verify.

Trạng thái MFA phát sinh từ 3 nguồn: `user.admin_mfa_required` (admin bắt buộc, tĩnh), `user.detection_mfa_once` (Detection yêu cầu 1 lần, set qua `_pre_token_risk`), hoặc cả hai.

### 3.3 `POST /api/v1/auth/mfa/verify` — Public

| | |
|---|---|
| Auth | Không |
| Roles | — |
| Request | `MfaVerifyRequest { session_id: UUID, mfa_code: string (^\d{6}$) }` |
| Response | **200** `MfaVerifyResponse { access_token, refresh_token, session_id }` (`session_id` giờ là session thật) |
| Errors | 404 `Transaction not found` / `User not found` / `MFA notification not found`; **409** `MFA transaction already completed` / `MFA transaction failed` / `MFA code already used` / `Trusted-device approvals must be completed by the approving device`; **401** `MFA transaction expired` / `MFA code has expired` / `Invalid MFA code`; **403** `MFA verification is bound to the original IP address` |

Đặc điểm:
- OTP 6 chữ số, hết hạn sau **5 phút** (`expires_at = now + 5min`).
- **Atomic consumption** bằng `SELECT ... FOR UPDATE` — chỉ 1 request thành công.
- Sau **3 lần sai** → transaction `failed`, không thử lại được (phải login lại).
- **IP binding**: transaction ghi `bound_ip`; verify từ IP khác → 403.
- Đây là **pre-auth transaction**, không cần token.

### 3.4 `POST /api/v1/auth/refresh` — Public (dùng refresh token)

| | |
|---|---|
| Auth | Không (dùng `refresh_token` trong body) |
| Roles | — |
| Request | `RefreshRequest { refresh_token: string }` |
| Response | **200** `RefreshResponse { access_token: string, refresh_token?: string }` |
| Errors | 401 `Invalid refresh token` / `Session expired` |

**Token rotation**: server luôn phát hành refresh token mới và ghi đè `refresh_token_hash` của session. Client **phải** thay thế refresh token trong bộ nhớ sau mỗi lần refresh; dùng lại token cũ sẽ nhận 401.

### 3.5 `GET /api/v1/auth/me` — Bearer, mọi role

| | |
|---|---|
| Auth | Bearer token |
| Roles | Bất kỳ (chỉ cần đăng nhập) |
| Response | **200** `UserItem { id, username, email?, full_name?, status, admin_mfa_required, roles: string[], last_login_at?, failed_login_count, locked_at?, created_at }` |

**Đây là nguồn duy nhất của `roles` cho frontend.** Gọi lại sau mỗi login / refresh / rồi điều hướng tới app.

### 3.6 `POST /api/v1/auth/logout` — Bearer

| | |
|---|---|
| Auth | Bearer |
| Roles | Bất kỳ |
| Response | **200** `LogoutResponse { status: "ok" }` |
| Effects | Set `revoked_at` cho **session hiện tại**. Token đó → 401 ngay lập tức ở mọi endpoint khác. |

### 3.7 `POST /api/v1/auth/logout-all` — Bearer

| | |
|---|---|
| Auth | Bearer |
| Roles | Bất kỳ |
| Response | **200** `LogoutResponse { status: "ok" }` |
| Effects | Revoke **tất cả** session đang hoạt động của user. |

### 3.8 `GET /api/v1/auth/sessions` — Bearer

| | |
|---|---|
| Auth | Bearer |
| Roles | Bất kỳ (chỉ session của chính mình) |
| Response | **200** `SessionList { sessions: SessionItem[], total }` |
| `SessionItem` | `{ id, ip_address?, user_agent?, expires_at, last_activity_at?, created_at, is_current }` |

### 3.9 `DELETE /api/v1/auth/sessions/{session_id}` — Bearer

| | |
|---|---|
| Auth | Bearer |
| Roles | Bất kỳ (chỉ session của chính mình) |
| Response | **204 No Content** |

---

## 4. NHÓM 2 — IAM / Admin (`tag: iam-admin`, prefix `/api/v1/admin`)

**Tất cả 7 endpoint yêu cầu role `SECURITY_ADMIN`.** Không endpoint nào cho `SECURITY_MANAGER` hay `SOC_ANALYST`.

### 4.1 `GET /api/v1/admin/users` — `SECURITY_ADMIN`

| | |
|---|---|
| Query | `page` (≥1, default 1), `limit` (1..100, default 20), `role?: UserRole`, `status?: UserStatus` (alias `status`) |
| Response | **200** `UserList { users: UserItem[], total, page, limit }` |
| Errors | 422 (query) |

`UserStatus` ∈ `active | suspended | locked`. `UserRole` ∈ `USER | SECURITY_ADMIN | SOC_ANALYST | SECURITY_MANAGER`.

### 4.2 `POST /api/v1/admin/users/{user_id}/roles` — `SECURITY_ADMIN`

| | |
|---|---|
| Body | `RoleAssignRequest { role: UserRole }` |
| Response | **200** `UserItem` |
| Errors | **404** `Role assignment not found`; **422** `Role is not configured`; **409** `Cannot remove or lock the last active SECURITY_ADMIN` |

> Gán role cũng **thu hồi session** của user đó (`sessions_revoked` trong `after_state` của audit log).

### 4.3 `DELETE /api/v1/admin/users/{user_id}/roles/{role_id}` — `SECURITY_ADMIN`

| | |
|---|---|
| Path | `role_id` là **string tự do** (không phải enum), ví dụ `"SOC_ANALYST"` |
| Response | **200** `UserItem` |
| Errors | **422** `The USER base role cannot be removed` / `Unsupported role`; **404** `User not found` / `Role assignment not found`; **409** `Cannot remove or lock the last active SECURITY_ADMIN` |

> **Lưu ý UI:**
> - Role cơ bản `USER` không thể bị gỡ → server trả **422** (không phải 400). UI nên disable nút gỡ cho role `USER`.
> - Gỡ `SECURITY_ADMIN` của user active cuối cùng → **409**. UI nên hiển thị message này.

### 4.4 `POST /api/v1/admin/users/{user_id}/lock` — `SECURITY_ADMIN`

| | |
|---|---|
| Body | không có |
| Response | **200** `UserItem` (`status` → `locked`, `locked_at` set) |
| Errors | **404** `User not found`; **409** `Cannot remove or lock the last active SECURITY_ADMIN` |

### 4.5 `DELETE /api/v1/admin/users/{user_id}/lock` — `SECURITY_ADMIN`

| | |
|---|---|
| Response | **200** `UserItem` (unlock) |

### 4.6 `PUT /api/v1/admin/users/{user_id}/mfa` — `SECURITY_ADMIN`

| | |
|---|---|
| Body | `MfaToggleRequest { mfa_required: boolean }` |
| Response | **200** `UserItem` (cập nhật `admin_mfa_required`) |

### 4.7 `GET /api/v1/admin/audit-logs` — `SECURITY_ADMIN`

| | |
|---|---|
| Query | `page`, `limit`, `actor?` (username **hoặc** `actor_type`), `action?`, `resource?`, `from?` (alias của `from_time`), `to?` (alias của `to_time`) |
| Response | **200** `AuditLogList { logs: AuditLogItem[], total, page, limit }` |
| `AuditLogItem` | `{ id, request_id?, actor, action, resource, resource_id?, before_state?, after_state?, change_reason?, ip_address?, user_agent?, created_at }` |

---

## 5. NHÓM 3 — SOC Alerts (`tag: soc`, prefix `/api/v1`)

**Tất cả 9 endpoint yêu cầu `SOC_ANALYST` **hoặc** `SECURITY_MANAGER`.**

### 5.1 `GET /api/v1/alerts` — `SOC_ANALYST` | `SECURITY_MANAGER`

| | |
|---|---|
| Query | `status?`, `risk_level?`, `assigned_to_id?`, `page` (default 1), `limit` (1..100, default 20) |
| Response | **200** `AlertListResponse { alerts: AlertItem[], total, page, limit }` |
| `AlertItem` | `{ id, login_attempt_id, policy_id?, status, risk_level?, detection_reason?, detection_scores?, assigned_to_id?, resolved_by_id?, resolved_at?, resolution?, notes?, created_at, updated_at }` |
| `status` | `open | acknowledged | resolved | false_positive` |
| `risk_level` | `low | medium | high | critical` |

### 5.2 `GET /api/v1/alerts/{alert_id}` — `SOC_ANALYST` | `SECURITY_MANAGER`

**200** `AlertItem` · **404** `Alert not found`

### 5.3 `GET /api/v1/alerts/{alert_id}/evidence` — `SOC_ANALYST` | `SECURITY_MANAGER`

**200** `AlertEvidence { alert: AlertItem, login_attempt?: LoginAttemptSummary, risk_assessment?: RiskAssessmentSummary, detection_logs: DetectionLogSummary[], timeline: TimelineEvent[] }`

`DetectionLogSummary` = `{ id, stage, stage_detail?, rule_name?, triggered?, score_contribution?, decision?, reason?, details?, created_at }`.

### 5.4 `GET /api/v1/alerts/{alert_id}/timeline` — `SOC_ANALYST` | `SECURITY_MANAGER`

**200** `TimelineEvent[]` — `{ id, alert_id, event_type, actor_id?, actor_type, old_value?, new_value?, comment?, ip_address?, created_at }`

`event_type` ∈ `created | assigned | unassigned | acknowledged | escalated | note_added | status_changed | resolved | false_positive`.

### 5.5 `POST /api/v1/alerts/{alert_id}/timeline` — `SOC_ANALYST` | `SECURITY_MANAGER`

| | |
|---|---|
| Body | `TimelineEventCreate { event_type: string, comment?: string }` |
| Response | **200** `TimelineEvent` |
| Errors | 400 (`event_type` không hợp lệ); 404 |

### 5.6 `POST /api/v1/alerts/{alert_id}/acknowledge` — `SOC_ANALYST` | `SECURITY_MANAGER`

| | |
|---|---|
| Body | `AlertAcknowledgeRequest { notes?: string }` |
| Response | **200** `AlertItem` |
| Errors | **400** `Alert is {status}, only open alerts can be acknowledged`; 404 |

Chỉ chuyển được từ `open` → `acknowledged`.

### 5.7 `POST /api/v1/alerts/{alert_id}/resolve` — `SOC_ANALYST` | `SECURITY_MANAGER`

| | |
|---|---|
| Body | `AlertResolveRequest { resolution: 'true_attack'\|'false_positive'\|'benign_true_positive'\|'insufficient_evidence', notes?: string }` |
| Response | **200** `AlertItem` |
| Errors | **400** `Cannot resolve alert from status: {status}`; 404 |

Nguồn trạng thái hợp lệ: `open` hoặc `acknowledged`. `resolution == "false_positive"` → status `false_positive`; còn lại → `resolved`.

### 5.8 `POST /api/v1/alerts/{alert_id}/assign` — `SOC_ANALYST` | `SECURITY_MANAGER`

| | |
|---|---|
| Body | `AlertAssignRequest { assigned_to_id: string (UUID của `soc_analysts.id`), notes?: string }` |
| Response | **200** `AlertItem` |
| Errors | **400** `assigned_to_id must be a valid UUID` / `assigned_to_id must reference an existing active SOC analyst`; 404 |

> **Lưu ý quan trọng:** `assigned_to_id` trỏ tới bảng **`soc_analysts`** (detection-db), **KHÔNG** phải `users.id`. Backend **không có endpoint list `soc_analysts`**. Xem [§7 Gap](#7-gap-các-api-backend-còn-thiếu) — G-2.

### 5.9 `POST /api/v1/alerts/{alert_id}/actions` — `SOC_ANALYST` | `SECURITY_MANAGER`

| | |
|---|---|
| Body | `AlertActionRequest { action: SecurityAction, reason: string (≥1) }` |
| Response | **200** `AlertActionResponse { status: string, action: string, details: dict }` |
| `action` | `REQUIRE_MFA | REVOKE_SESSIONS | LOCK_USER | FORCE_LOGOUT` |
| Errors | **400** `No user associated with this alert` / `Unsupported action: ...`; **404** `Alert not found`; **502** `Core did not apply the {action} action. The protective action was NOT enforced.` |

**Hành vi:** Detection **không** tự mutate core-db. Nó gọi `POST /api/v1/internal/actions` với `idempotency_key = "alert:{alert_id}:{action}"`. Nếu Core không enforce được (unreachable / thiếu secret), backend trả **502** và ghi thêm một timeline event (`note_added`) ghi rõ hành động **chưa** được áp dụng.

---

## 6. NHÓM 4 — Detection Policies (`tag: policies`, prefix `/api/v1/policies`)

### 6.1 `GET /api/v1/policies` — `SECURITY_ADMIN` | `SECURITY_MANAGER`

| | |
|---|---|
| Response | **200** `array` (không phải object có wrapper!) |
| Item shape | `{ id, version, name?, description?, rule_count: number, is_active, created_at, activated_at? }` |

Đây là **danh sách rút gọn** — không có `rules`, không có `config`, **không có `updated_at`**. Muốn sửa thì bắt buộc gọi `GET /api/v1/policies/{id}`.

### 6.2 `GET /api/v1/policies/{policy_id}` — `SECURITY_ADMIN` | `SECURITY_MANAGER`

| | |
|---|---|
| Response | **200** `PolicyDetail { id, version, name?, description?, rules: object[], config: object, is_active, created_by?, created_at, updated_at, activated_at?, deactivated_at? }` |
| Errors | 404 `Policy not found` |

**Đây là endpoint bắt buộc cho luồng Edit** (xem [M12-INTEGRATION-PLAN.md §5](./M12-INTEGRATION-PLAN.md)). `updated_at` trả về **full microsecond precision** để làm `expected_updated_at`.

### 6.3 `POST /api/v1/policies` — `SECURITY_ADMIN` (chỉ)

| | |
|---|---|
| Body | `PolicyCreateRequest { version, name?, description?, rules: object[], config: object }` + `extra="forbid"` |
| `version` | Pattern `^v\d+(\.\d+)*$` (ví dụ `v1.0`) |
| `rules` | `min_length=1`; raw JSON, server validate bằng validator canonical |
| Response | **201** `PolicyDetail` |
| Errors | **400** `{ message: "Policy is invalid", problems: string[] }`; **409** `{ message: "Policy version already exists", problems: [...] }`; 422 |

Policy **luôn được tạo ở trạng thái INACTIVE**. Kích hoạt là bước riêng.

**Gửi field server-owned sẽ bị 400** với tên field cụ thể: `is_active`, `created_by`, `created_at`, `updated_at`, `activated_at`, `deactivated_at` (khai báo tường minh trong `ServerOwnedPolicyFields` để lỗi nói rõ field nào sai, thay vì 422 "unexpected key").

### 6.4 `PUT /api/v1/policies/{policy_id}` — `SECURITY_ADMIN` (chỉ)

| | |
|---|---|
| Body | `PolicyUpdateRequest { name?, description?, rules?, config?, expected_updated_at: datetime (BẮT BUỘC) }` + `extra="forbid"` |
| Response | **200** `PolicyDetail` |
| Errors | **400** `Policy is invalid` / field server-owned; **404** `Policy not found`; **409** × 3 biến thể |

**Ba loại 409** (phân biệt bằng `detail.message`):

| `detail.message` | `detail.problems` | Nguyên nhân |
|---|---|---|
| `"Policy is immutable"` | `an active policy cannot be edited; create a new version and activate it instead` | policy đang active |
| `"Policy is immutable"` | `this policy has already been activated and its historical risk assessments reference it; create a new version instead` | `activated_at != null` |
| `"Policy was modified by someone else"` | `expected_updated_at does not match the current policy; re-read the policy and retry` | concurrency token lệch |

**Semantics:**
- `version` **không sửa được** (bất biến sau khi tạo).
- Field **bị omit giữ nguyên giá trị cũ** (partial update).
- Policy đã từng active thì **đóng băng vĩnh viễn** → phải tạo version mới.

### 6.5 `POST /api/v1/policies/{policy_id}/activate` — `SECURITY_ADMIN` (chỉ)

| | |
|---|---|
| Body | không có |
| Response | **200** `{ status: "activated", version: string }` |
| Errors | **400** `{ message: "Policy is invalid", problems: [...] }`; 404 |

Chỉ **một** policy active tại một thời điểm (partial unique index `idx_policies_single_active`). Policy cũ bị set `deactivated_at`.

---

## 7. NHÓM 5 — Trusted Devices (`tag: devices`, prefix `/api/v1/devices`)

### 7.1 `GET /api/v1/devices` — Bearer (self)

**200** `TrustedDeviceList { devices: TrustedDeviceItem[], total }` — `TrustedDeviceItem` = `{ id, device_name?, device_fingerprint, last_ip?, last_user_agent?, last_used_at, expires_at?, created_at }`

### 7.2 `POST /api/v1/devices` — Bearer (self)

| | |
|---|---|
| Body | `TrustDeviceRequest { device_name?: string (≤100), remember_for_days?: number (1..365, default 30) }` |
| Response | **200** `TrustDeviceResponse { id, device_name?, message }` |

### 7.3 `DELETE /api/v1/devices/{device_id}` — Bearer (self)

**204 No Content**

### 7.4 `DELETE /api/v1/devices/all` — Bearer (self)

**204 No Content** — thu hồi mọi thiết bị (tính năng bảo mật).

### 7.5 `POST /api/v1/devices/check` — **Optional auth** (public)

| | |
|---|---|
| Header | `Authorization` **optional** |
| Response | **200** `{ trusted: boolean, reason: string }` |

Contract: không token → `{ trusted: false, reason: "No token" }`; token sai → `trusted: false` (**không** trả 401). Lý do có thể: `"No token"`, `"Device not registered"`, `"Device used from an unfamiliar IP"`, `"Device expired"`.

### 7.6 `POST /api/v1/devices/pending` — **Public** (verify password)

| | |
|---|---|
| Body | `PendingTrustedDeviceRequest { username, password, device_name? }` |
| Response | **202** `PendingTrustedDeviceResponse { request_id: UUID, status: string, expires_at, message }` |
| `status` | `pending` \| `already_trusted` |
| Errors | **400** `A valid client IP is required`; **401** `Invalid credentials`; **409** `Complete the required MFA through the normal login flow before trusting a device` / `Detection requires MFA; trusted-device approval cannot bypass it`; **423** `Account is locked`; **429** `Too many device approval requests` |

### 7.7 `POST /api/v1/devices/pending/{request_id}/approve` — Bearer (self)

| | |
|---|---|
| Response | **200** `TrustedDeviceApprovalResponse { request_id, device_id, status: "approved", expires_at }` |
| Errors | **403** `Approval must come from the current session's familiar IP`; **404**; **410** `Trusted-device request expired` / `... is no longer valid` |

### 7.8 `POST /api/v1/devices/pending/{request_id}/complete` — **Public**

| | |
|---|---|
| Response | **200** `LoginResponse` — trả token thật, `mfa_required: false` |
| Errors | **403** `Trusted-device IP does not match the request` / `Trusted-device fingerprint does not match the request`; **404**; **409** `Trusted-device approval is still pending` / `Trusted-device request already completed`; **410** |

> Luồng đầy đủ 3 bước: `POST /devices/pending` (thiết bị mới, có password) → `POST /devices/pending/{id}/approve` (thiết bị cũ đã đăng nhập) → `POST /devices/pending/{id}/complete` (thiết bị mới nhận token).

---

## 8. NHÓM 6 — Detection Investigation (`tag: detection-investigation`)

### 8.1 `GET /api/v1/login-attempts` — `SOC_ANALYST` | `SECURITY_MANAGER`

| | |
|---|---|
| Query | `user_id?: UUID`, `username?`, `from_date?: datetime` (**inclusive**), `to_date?: datetime` (**exclusive**), `ip_address?`, `outcome?: 'success'\|'failure'`, `risk_level?`, `page`, `limit` |
| Response | **200** `LoginAttemptListResponse { attempts: LoginAttemptItem[], total, page, limit }` |
| `LoginAttemptItem` | `{ id, event_id, user_id?, username_attempted?, outcome, mfa_used, ip_address?, user_agent?, device_fingerprint?, timestamp, status, risk_level?, detection_decision?, policy_id?, primary_alert_id?, request_id? }` |
| Errors | **400** `outcome must be one of [...]` / `risk_level must be one of [...]` / `from_date must be earlier than to_date`; 422 |

Đây là endpoint **read-only duy nhất** của nhóm Detection mà user thường có thể gọi. `GET /api/v1/internal/login-attempts/{id}` là internal-only (xem §10).

---

## 9. NHÓM 7 — Manager Analytics (`tag: manager`, prefix `/api/v1`)

**Tất cả 5 endpoint yêu cầu role `SECURITY_MANAGER`.**

### 9.1 Hợp đồng 5-shape (giống nhau cho cả 5 endpoint)

| Code | Khi nào | Body |
|---|---|---|
| **200** | OK | response model riêng của endpoint |
| **400** | Window/bucket/filter không hợp lệ | `{ detail: "'from' must be strictly earlier than 'to'" }` |
| **401** | Thiếu/sai bearer token | `{ detail: "Missing Authorization header" }` |
| **403** | Không phải `SECURITY_MANAGER` | `{ detail: "Insufficient permissions" }` |
| **503** | **Tất cả** source mà endpoint tiêu thụ đều fail | `{ detail: "analytics sources unavailable", sources: { "<name>": { status: "unavailable", detail: "<reason_code>" } } }` |

> **503 KHÔNG có `response_model`** — body lệch khỏi envelope chuẩn. Frontend phải parse riêng.

### 9.2 Envelope chung của mọi response 200

```ts
{
  generated_at: string;          // ISO-8601 UTC
  window: { from: string; to: string };
  degraded: boolean;             // true nếu ≥1 source unavailable
  sources: Record<string, { status: "ok" | "unavailable"; detail: string | null }>;
}
```

### 9.3 Source và reason code

| Source | Thuộc endpoint | Nguồn dữ liệu |
|---|---|---|
| `core` | dashboard | HTTP → `GET /api/v1/internal/analytics/core` |
| `detection` | dashboard, trends, alerts | HTTP → `GET /api/v1/internal/analytics/detection` |
| `ml` | dashboard, trends, ml-stats | đọc DB trực tiếp (worker thread) |

**Reason code đóng (closed vocabulary)** — `app/manager_client.py`:

`not_configured` · `timeout` · `unreachable` · `invalid_payload` · `database_error` · `internal_error`

Frontend **không** được hard-code string tự do; nên map sang nhãn tiếng Việt/Anh qua một bảng tra cứu.

### 9.4 `GET /api/v1/manager/dashboard` — `SECURITY_MANAGER`

| | |
|---|---|
| Query | `from?`, `to?` |
| Response | **200** `ManagerDashboardResponse` |
| Default window | 24 giờ |

`core?: DashboardCore` — `{ total_users, users_by_status: Record<string,number>, users_with_mfa_required, users_under_forced_mfa, new_users, users_with_failed_logins, active_sessions, sessions_created, sessions_revoked, mfa_challenges, mfa_completed, mfa_failed, audit_events, audit_activity?: { by_action, by_actor_type, recent: AuditActivityRow[] } }`

`detection?: DashboardDetection` — `{ login_attempts, by_outcome, by_risk_level, by_decision, avg_combined_score?, alerts: { total, open, acknowledged, resolved, false_positive, critical_open }, critical_incidents: CriticalIncident[], enforcement?: { attempted, succeeded, success_rate? }, ml_fallback?: { assessments, fallback, fallback_rate? }, policy?: { active_version?, active_policy_id? } }`

`ml?: DashboardMl` — `{ active_model_version?, model_status, inferences, anomalies, anomaly_rate?, avg_processing_ms?, daily: MlDailyPoint[] }`

> **Mỗi section có thể `null`.** Section `null` = nguồn của nó unavailable (kể cả khi tổng `degraded: false` không xảy ra). UI phải render "không có dữ liệu" chứ không render `0`.

### 9.5 `GET /api/v1/manager/trends` — `SECURITY_MANAGER`

| | |
|---|---|
| Query | `from?`, `to?`, `bucket?` (`hour` \| `day` \| `auto`) |
| Response | **200** `ManagerTrendsResponse { bucket, series: ManagerTrendSeries }` |
| Default | 14 ngày, `bucket=auto` (auto-resolve theo độ dài window) |

`series` = `{ login_attempts?: ManagerTrendPoint[], alerts?: ManagerTrendAlertsPoint[], ml?: ManagerTrendMlPoint[] }` — mỗi series **có thể null**.

### 9.6 `GET /api/v1/manager/alerts` — `SECURITY_MANAGER`

| | |
|---|---|
| Query | `from?`, `to?`, `status?`, `risk_level?` |
| Response | **200** `ManagerAlertsResponse` |
| Default | 30 ngày |

`totals: { created, open, acknowledged, resolved, false_positive }` · `by_status` · `by_risk_level` · `by_rule: object[]` · `by_ml_reason: object[]` · `backlog: { open_count, oldest_open_age_hours?, unassigned, escalated }` · `false_positive_rate?` · `mtta_seconds?` · `mttr_seconds?` · `acknowledged_count` · `resolved_count`

> Endpoint này chỉ tiêu thụ **một** source (`detection`), nên **bất kỳ** failure nào cũng → **503** (không phải degraded 200).

### 9.7 `GET /api/v1/manager/soc-kpi` — `SECURITY_MANAGER`

**200** `ManagerSocKpiResponse { kpis: ManagerSocKpis }`

**Mọi KPI đều nullable.** `null` = hoặc population rỗng, hoặc source down — hai nguyên nhân **khác nhau** nhưng cùng biểu hiện. `ManagerSocKpis` = `{ mtta_seconds?, mttr_seconds?, acknowledgement_rate?, resolution_rate?, false_positive_rate?, escalation_rate?, alerts_per_analyst?, enforcement_attempted?, enforcement_succeeded?, enforcement_success_rate?, ml_assessments?, ml_fallback_count?, ml_fallback_rate?, mfa_enrollment_rate?, forced_mfa_users?, audit_events? }`

### 9.8 `GET /api/v1/manager/ml-stats` — `SECURITY_MANAGER`

**200** `ManagerMlStatsResponse { model?: MlModelInfo, versions: MlVersionInfo[], inference: MlInferenceStats, by_status, reason_codes: object[], daily: MlDailyPoint[], features: MlFeaturePoint[] }`

---

## 10. NHÓM 8 — Internal / Service-to-Service (`/api/v1/internal/*`) — **KHÔNG dùng từ browser**

> **Ranh giới bảo mật.** Toàn bộ **11 operation** dưới đây yêu cầu header `X-Internal-Secret`. Secret là **service-to-service trust boundary**, không phải user auth. Browser **không bao giờ** được giữ hoặc gửi `INTERNAL_SECRET` — không đặt trong `.env` của Vite, không đặt trong `VITE_*` (biến `VITE_*` được bundle vào JS và ai cũng đọc được).
>
> (3 operation trong nhóm này — `/internal/health`, `/internal/ml/health`, `/internal/ml/features` — là **probe/contract công khai**, không yêu cầu secret. Xem bảng bên dưới.)

### 10.1 Detection-internal (5)

| Method | Path | Request | Response | Ghi chú |
|---|---|---|---|---|
| POST | `/api/v1/internal/login-events` | `LoginEventRequest` (strict `extra="forbid"`) | **202** `LoginEventResponse { status, event_id, login_attempt_id, processing }` | Idempotent theo `event_id` |
| GET | `/api/v1/internal/login-attempts/{login_attempt_id}` | — | **200** `LoginAttemptStatusResponse { login_attempt_id, status, risk_level?, decision?, alert_id? }` | Poll trạng thái xử lý |
| POST | `/api/v1/internal/pre-token-check` | `PreTokenCheckRequest` | **200** `PreTokenCheckResponse { risk_level, decision, require_mfa, degraded, reason }` | Verdict trước khi phát token |
| GET | `/api/v1/internal/health` | — | **200** `InternalHealthResponse { status, active_policy }` | **KHÔNG cần secret** |
| GET | `/api/v1/internal/analytics/detection` | query `from,to,bucket,status,risk_level` | **200** `object` | Provider cho Manager facade |

### 10.2 Core-internal (3)

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/v1/internal/actions` | `ActionRequest { action, target_user_id, reason, alert_id?, severity?, idempotency_key?, detected_at? }` | **200** `ActionResponse { status, action, target_user_id, details? }` |
| GET | `/api/v1/internal/users/{user_id}` | — | **200** `InternalUserResponse { user_id, username, status, roles, role_ids }` |
| GET | `/api/v1/internal/analytics/core` | query `from,to,bucket` | **200** `object` |

### 10.3 ML-internal (3)

| Method | Path | Response |
|---|---|---|
| POST | `/api/v1/internal/ml/score` | **200** `MlScoreResponse { request_id, normalized_anomaly_score, is_anomaly, model_version?, reason_codes[], model_status, processing_time_ms }` |
| GET | `/api/v1/internal/ml/health` | **200** `object` (free-form) — **KHÔNG cần secret** |
| GET | `/api/v1/internal/ml/features` | **200** `object` — feature contract (6 features) — **KHÔNG cần secret** |

### 10.4 Health / Readiness (`app/main.py`)

| Method | Path | Response |
|---|---|---|
| GET | `/health` | **200** `{ status: "ok" }` — liveness, không query DB |
| GET | `/ready` | **200** hoặc **503** — readiness, probe cả 3 DB (read-only `SELECT 1`) |

---

## 11. Bảng tra cứu nhanh

Endpoint → Frontend Screen (chỉ 46 operation browser-callable)

| # | Method + Path | Roles | Screen |
|---|---|---|---|
| 1 | POST `/api/v1/admin/users/{user_id}/lock` | SECURITY_ADMIN | S-10 |
| 2 | POST `/api/v1/admin/users/{user_id}/roles` | SECURITY_ADMIN | S-10 |
| 3 | POST `/api/v1/alerts/{alert_id}/acknowledge` | SOC_ANALYST / SECURITY_MANAGER | S-21 |
| 4 | POST `/api/v1/alerts/{alert_id}/actions` | SOC_ANALYST / SECURITY_MANAGER | S-21 |
| 5 | POST `/api/v1/alerts/{alert_id}/assign` | SOC_ANALYST / SECURITY_MANAGER | S-21 |
| 6 | POST `/api/v1/alerts/{alert_id}/resolve` | SOC_ANALYST / SECURITY_MANAGER | S-21 |
| 7 | POST `/api/v1/alerts/{alert_id}/timeline` | SOC_ANALYST / SECURITY_MANAGER | S-21 |
| 8 | POST `/api/v1/auth/login` | public | S-02 Login |
| 9 | POST `/api/v1/auth/logout` | bất kỳ (đã đăng nhập) | Global (user menu) |
| 10 | POST `/api/v1/auth/logout-all` | bất kỳ (đã đăng nhập) | S-05 Sessions |
| 11 | POST `/api/v1/auth/mfa/verify` | public | S-03 MFA Verify |
| 12 | POST `/api/v1/auth/refresh` | public | Global (axios interceptor) |
| 13 | POST `/api/v1/auth/register` | public | S-01 Register |
| 14 | POST `/api/v1/devices` | bất kỳ (đã đăng nhập) | S-06 Trusted Devices |
| 15 | POST `/api/v1/devices/check` | public (token optional) | S-04 Trusted-device Login |
| 16 | POST `/api/v1/devices/pending` | public (verify password) | S-04 Trusted-device Login |
| 17 | POST `/api/v1/devices/pending/{request_id}/approve` | bất kỳ (đã đăng nhập) | S-04 (nhánh approve) |
| 18 | POST `/api/v1/devices/pending/{request_id}/complete` | public | S-04 Trusted-device Login |
| 19 | POST `/api/v1/policies` | SECURITY_ADMIN | S-32 Policy Editor (chế độ create) |
| 20 | POST `/api/v1/policies/{policy_id}/activate` | SECURITY_ADMIN | S-30 / S-31 |
| 21 | GET `/api/v1/admin/audit-logs` | SECURITY_ADMIN | S-11 Audit Logs |
| 22 | GET `/api/v1/admin/users` | SECURITY_ADMIN | S-10 User Management |
| 23 | GET `/api/v1/alerts` | SOC_ANALYST / SECURITY_MANAGER | S-20 Alert Queue |
| 24 | GET `/api/v1/alerts/{alert_id}` | SOC_ANALYST / SECURITY_MANAGER | S-21 Alert Detail |
| 25 | GET `/api/v1/alerts/{alert_id}/evidence` | SOC_ANALYST / SECURITY_MANAGER | S-21 |
| 26 | GET `/api/v1/alerts/{alert_id}/timeline` | SOC_ANALYST / SECURITY_MANAGER | S-21 |
| 27 | GET `/api/v1/auth/me` | bất kỳ (đã đăng nhập) | Global (AppShell / user menu) |
| 28 | GET `/api/v1/auth/sessions` | bất kỳ (đã đăng nhập) | S-05 Sessions |
| 29 | GET `/api/v1/devices` | bất kỳ (đã đăng nhập) | S-06 Trusted Devices |
| 30 | GET `/api/v1/login-attempts` | SOC_ANALYST / SECURITY_MANAGER | S-22 Login History |
| 31 | GET `/api/v1/manager/alerts` | SECURITY_MANAGER | S-42 Alert Analytics |
| 32 | GET `/api/v1/manager/dashboard` | SECURITY_MANAGER | S-40 Manager Dashboard |
| 33 | GET `/api/v1/manager/ml-stats` | SECURITY_MANAGER | S-44 ML Stats |
| 34 | GET `/api/v1/manager/soc-kpi` | SECURITY_MANAGER | S-43 SOC KPI |
| 35 | GET `/api/v1/manager/trends` | SECURITY_MANAGER | S-41 Trends |
| 36 | GET `/api/v1/policies` | SECURITY_ADMIN / SECURITY_MANAGER | S-30 Policy List |
| 37 | GET `/api/v1/policies/{policy_id}` | SECURITY_ADMIN / SECURITY_MANAGER | S-31 Policy Detail / S-32 Policy Edit |
| 38 | GET `/health` | public | S-92 Service Status |
| 39 | GET `/ready` | public | S-92 Service Status |
| 40 | PUT `/api/v1/admin/users/{user_id}/mfa` | SECURITY_ADMIN | S-10 |
| 41 | PUT `/api/v1/policies/{policy_id}` | SECURITY_ADMIN | S-32 Policy Editor (chế độ edit) |
| 42 | DELETE `/api/v1/admin/users/{user_id}/lock` | SECURITY_ADMIN | S-10 |
| 43 | DELETE `/api/v1/admin/users/{user_id}/roles/{role_id}` | SECURITY_ADMIN | S-10 |
| 44 | DELETE `/api/v1/auth/sessions/{session_id}` | bất kỳ (đã đăng nhập) | S-05 Sessions |
| 45 | DELETE `/api/v1/devices/all` | bất kỳ (đã đăng nhập) | S-06 Trusted Devices |
| 46 | DELETE `/api/v1/devices/{device_id}` | bất kỳ (đã đăng nhập) | S-06 Trusted Devices |

**46 operation có thể gọi từ browser** (44 dưới `/api/v1` + `/health` + `/ready`). 11 operation internal-only nằm ngoài danh sách này — xem §10.

---

## 12. Gap — Các API backend còn thiếu

| ID | Mức | Thiếu gì | Ảnh hưởng UI | Đề xuất |
|---|---|---|---|---|
| **G-1** | Cao | **Không có endpoint đọc danh sách `soc_analysts`** | `POST /alerts/{id}/assign` cần `assigned_to_id` = `soc_analysts.id`, nhưng frontend không có cách lấy danh sách này. Hiện tại UI buộc phải nhập UUID thủ công. | Thêm `GET /api/v1/soc/analysts` (roles: `SOC_ANALYST`, `SECURITY_MANAGER`) trả `{ analysts: [{ id, user_id, display_name, is_active, max_alerts }] }`. Cho tới khi có, UI dùng **free-text UUID input** có validate UUID + hướng dẫn "copy từ DB". |
| **G-2** | Trung bình | **`GET /api/v1/admin/users` không trả `soc_analysts.id`** | Người dùng có role `SOC_ANALYST` không map được sang `assigned_to_id`. | Bổ sung `soc_analyst_id` vào `UserItem` (chỉ khi user có role SOC_ANALYST). |
| **G-3** | Trung bình | **Không có endpoint đọc audit log của chính mình** | `GET /api/v1/admin/audit-logs` chỉ `SECURITY_ADMIN`. User thường không xem được lịch sử đăng nhập chi tiết ngoài `GET /api/v1/login-attempts` (SOC-only). | Chấp nhận: `GET /api/v1/auth/sessions` + `GET /api/v1/devices` là đủ cho USER. Hoặc thêm `GET /api/v1/auth/me/activity`. |
| **G-4** | Thấp | **Không có endpoint list notification / OTP delivery** | `POST /auth/mfa/verify` cần mã OTP 6 số gửi qua email. Trong môi trường demo không có email → người dùng không lấy được OTP. | Cho demo: hiển thị mã OTP trong log server / seed script, hoặc thêm endpoint `POST /api/v1/auth/mfa/resend`. |
| **G-5** | Thấp | **Không có endpoint list role đầy đủ** | `UserRole` enum là cố định 4 giá trị — frontend có thể hard-code. Không cần API. | Hard-code enum trong frontend. |
| **G-6** | Thấp | **`GET /api/v1/policies` trả `array` thay vì envelope** | Không có `total` → không biết tổng số policy, không có phân trang. | Chấp nhận cho demo (danh sách policy nhỏ). Nếu cần phân trang, đổi sang `PolicyList` — nhưng contract hiện tại cố ý giữ nguyên. |
| **G-7** | Thấp | **Không có endpoint đọc `risk_assessments` / `detection_logs` độc lập** | Chỉ xem được qua `/alerts/{id}/evidence`. | Chấp nhận — evidence bundle là đủ cho UI điều tra. |
| **G-8** | Thấp | **Không có endpoint escalate alert** | `AlertEscalateRequest` tồn tại trong `app/schemas.py` nhưng **không có route** (`app/alerts.py` không dùng), nên **không** xuất hiện trong OpenAPI. `event_type: "escalated"` tồn tại trong enum timeline. | **Không** dùng. Ghi chú để tránh dev tưởng có API. |
| **G-9** | Thấp | **Không có endpoint ghi note riêng** | `AlertNoteRequest` (`comment` 1..2000) tồn tại trong `app/schemas.py` nhưng **không có route**. Route ghi timeline dùng `TimelineEventCreate` với `comment` **không giới hạn độ dài**. | Ghi note qua `POST /alerts/{id}/timeline` với `event_type: "note_added"`. UI tự giới hạn 2000 ký tự. |

### 12.1 Kết luận Gap

> **Backend KHÔNG thiếu API bắt buộc nào để dựng một UI hoàn chỉnh cho demo.**
>
> - Toàn bộ 4 vai trò đều có đủ màn hình cốt lõi.
> - G-1 (danh sách SOC analyst) là gap **thực sự duy nhất** ảnh hưởng chức năng, nhưng có workaround bằng UUID input.
> - G-6 chỉ là thiếu tiện ích phân trang, không chặn.
> - G-8 **không phải gap** — đó là schema tồn đọng, không phải endpoint thiếu.

---

## 13. Phụ lục — Sinh lại OpenAPI

```bash
cd sentinel-auth
python - <<'PY'
import json, os
os.environ.setdefault("INTERNAL_SECRET", "planning-only-internal-secret-0123456789abcdef")
from app.main import app
spec = app.openapi()
json.dump(spec, open("/tmp/openapi.json", "w"), indent=2, ensure_ascii=False)
print(len(spec["paths"]), "paths")
PY
```

> `INTERNAL_SECRET` chỉ cần set để app **import** được (module-level `get_internal_secret()` check trong `lifespan`, không chạy lúc import — nhưng set cho an toàn). Giá trị trên **không** dùng được ở production.
>
> Lưu ý: OpenAPI **không khai báo `securitySchemes`** — auth dùng custom dependency (`get_current_auth_context` / `require_roles`), FastAPI không sinh được security scheme cho dependency đó. Vì vậy bảng "roles" trong tài liệu này được trích **từ source code**, không từ OpenAPI. Đây là lý do không thể dùng `openapi-typescript` để sinh client tự động một cách tin cậy → xem [M12-ARCHITECTURE.md](./M12-ARCHITECTURE.md) §6.
