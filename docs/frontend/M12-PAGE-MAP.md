# M12.0 — Page Map & Permission Mapping (Sentinel Auth v3.3)

**Baseline:** `origin/dev` @ `c89bff5`

> **Nguyên tắc:** Role gating ở frontend là **UX-only**. Backend (`require_roles`) là nơi duy nhất thực thi authorization. Frontend chỉ ẩn/hiện menu và disable button — không phải hàng rào bảo mật.

---

## 1. Tổng quan: 24 screens

| Nhóm | Số | Screens |
|---|---|---|
| Public / Auth | 5 | S-01 … S-05 |
| Self-service (mọi role) | 3 | S-06 … S-08 |
| SOC Analyst | 3 | S-20 … S-22 |
| Security Admin | 2 | S-10 … S-11 |
| Policy (Admin + Manager) | 3 | S-30 … S-32 |
| Security Manager | 5 | S-40 … S-44 |
| Hệ thống | 3 | S-90 … S-92 |

**Tổng: 24 screens.**

---

## 2. Ma trận role → screen

| Screen | Route | `USER` | `SOC_ANALYST` | `SECURITY_ADMIN` | `SECURITY_MANAGER` |
|---|---|:---:|:---:|:---:|:---:|
| S-01 Register | `/register` | ✓ | ✓ | ✓ | ✓ |
| S-02 Login | `/login` | ✓ | ✓ | ✓ | ✓ |
| S-03 MFA Verify | `/mfa` | ✓ | ✓ | ✓ | ✓ |
| S-04 Trusted-device Login | `/trusted-device` | ✓ | ✓ | ✓ | ✓ |
| S-05 Sessions | `/sessions` | ✓ | ✓ | ✓ | ✓ |
| S-06 Trusted Devices | `/devices` | ✓ | ✓ | ✓ | ✓ |
| S-07 Profile | `/profile` | ✓ | ✓ | ✓ | ✓ |
| S-08 Forbidden | `/403` | ✓ | ✓ | ✓ | ✓ |
| S-10 User Management | `/admin/users` | — | — | ✓ | — |
| S-11 Audit Logs | `/admin/audit-logs` | — | — | ✓ | — |
| S-20 Alert Queue | `/alerts` | — | ✓ | — | ✓ |
| S-21 Alert Detail | `/alerts/:id` | — | ✓ | — | ✓ |
| S-22 Login History | `/login-history` | — | ✓ | — | ✓ |
| S-30 Policy List | `/policies` | — | — | ✓ | ✓ |
| S-31 Policy Detail | `/policies/:id` | — | — | ✓ | ✓ |
| S-32 Policy Editor | `/policies/new`, `/policies/:id/edit` | — | — | ✓ | — |
| S-40 Manager Dashboard | `/manager` | — | — | — | ✓ |
| S-41 Trends | `/manager/trends` | — | — | — | ✓ |
| S-42 Alert Analytics | `/manager/alerts` | — | — | — | ✓ |
| S-43 SOC KPI | `/manager/soc-kpi` | — | — | — | ✓ |
| S-44 ML Stats | `/manager/ml-stats` | — | — | — | ✓ |
| S-90 Not Found | `/*` | ✓ | ✓ | ✓ | ✓ |
| S-91 Global Error | — | ✓ | ✓ | ✓ | ✓ |
| S-92 Service Status | `/status` | ✓ | ✓ | ✓ | ✓ |

**Điểm đáng chú ý:**
- `SECURITY_MANAGER` **không** có `/admin/*` (IAM) và **không** có `/alerts` write (trừ khi cũng có `SOC_ANALYST`).
- `SECURITY_ADMIN` **không** có `/alerts` và **không** có `/manager/*`.
- `SECURITY_MANAGER` **được** xem `/alerts` (read + write theo backend) — role allow-list của alerts là `SOC_ANALYST` **hoặc** `SECURITY_MANAGER`.
- `SECURITY_ADMIN` **được** xem `/policies` nhưng **không** sửa được policy đã từng active (409 immutable).

---

## 3. Điều hướng (navigation) theo vai trò

### 3.1 `USER`

```
┌─ Sentinel Auth ─────────────── [👤 alice ▾] ─┐
│                                                │
│  🏠 Trang chủ        → /sessions               │
│  🔒 Phiên đăng nhập  → /sessions               │
│  💻 Thiết bị tin cậy → /devices                │
│  👤 Hồ sơ cá nhân   → /profile                 │
│  ─────────────────────────────────────────     │
│  🚪 Đăng xuất                                   │
└────────────────────────────────────────────────┘
```

> `USER` không có màn hình "dashboard" riêng — `/sessions` là landing page.

### 3.2 `SOC_ANALYST`

```
┌─ Sentinel Auth ─────────────── [👤 bob ▾] ─┐
│  🏠 Trang chủ         → /alerts              │
│  🚨 Cảnh báo          → /alerts              │
│  🔍 Lịch sử đăng nhập → /login-history       │
│  ─────────────────────────────────────────   │
│  🔒 Phiên đăng nhập  → /sessions             │
│  💻 Thiết bị tin cậy → /devices              │
│  👤 Hồ sơ cá nhân   → /profile               │
│  ─────────────────────────────────────────   │
│  🚪 Đăng xuất                                  │
└───────────────────────────────────────────────┘
```

### 3.3 `SECURITY_ADMIN`

```
┌─ Sentinel Auth ─────────────── [👤 carol ▾] ─┐
│  🏠 Trang chủ         → /admin/users         │
│  👥 Quản lý người dùng → /admin/users        │
│  📜 Nhật ký kiểm toán → /admin/audit-logs    │
│  🛡️ Chính sách phát hiện → /policies          │
│  ─────────────────────────────────────────    │
│  🔒 Phiên đăng nhập  → /sessions              │
│  💻 Thiết bị tin cậy → /devices               │
│  👤 Hồ sơ cá nhân   → /profile                │
│  ─────────────────────────────────────────    │
│  🚪 Đăng xuất                                  │
└────────────────────────────────────────────────┘
```

### 3.4 `SECURITY_MANAGER`

```
┌─ Sentinel Auth ─────────────── [👤 dave ▾] ─┐
│  🏠 Tổng quan         → /manager              │
│  📈 Xu hướng          → /manager/trends       │
│  🚨 Phân tích cảnh báo → /manager/alerts      │
│  🎯 SOC KPI           → /manager/soc-kpi      │
│  🧠 ML Stats          → /manager/ml-stats     │
│  🛡️ Chính sách phát hiện → /policies          │
│  🚨 Cảnh báo          → /alerts               │
│  ─────────────────────────────────────────    │
│  🔒 Phiên đăng nhập  → /sessions              │
│  💻 Thiết bị tin cậy → /devices               │
│  👤 Hồ sơ cá nhân   → /profile                │
│  ─────────────────────────────────────────    │
│  🚪 Đăng xuất                                  │
└────────────────────────────────────────────────┘
```

### 3.5 Quy tắc menu

- Menu được dựng **động** từ `roles` của `GET /auth/me`.
- Mục đang active được highlight dựa trên `useLocation()`.
- Item menu chỉ hiển thị nếu user có **ít nhất một** role được phép truy cập màn hình đó.
- Multi-role → hợp nhất các menu của tất cả role (không trùng lặp).

---

## 4. Chi tiết từng screen

### 4.1 S-01 — Register (`/register`)

| | |
|---|---|
| Roles | Public |
| Endpoints | `POST /api/v1/auth/register` |
| Components | `RegisterForm`, `TextInput`, `PasswordInput`, `PasswordStrengthMeter` |
| Form fields | `username` (3-50, `^[a-zA-Z0-9_]+$`), `email` (optional), `password` (≥8) |
| Behavior | 201 → toast + chuyển `/login` (prefill username). 409 → inline error dưới field (username hoặc email). 422 → map `detail[]` vào field tương ứng. |
| Notes | User tự động có role `USER`. |

### 4.2 S-02 — Login (`/login`)

| | |
|---|---|
| Roles | Public |
| Endpoints | `POST /api/v1/auth/login` |
| Components | `LoginForm`, `TextInput`, `PasswordInput`, `MfaChallengeBanner` |
| Behavior | 200 + `mfa_required:false` → lưu token → `GET /auth/me` → redirect theo role. 200 + `mfa_required:true` → **token rỗng**, chuyển `/mfa` với `mfaSessionId = session_id`. 401 → "Sai tài khoản hoặc mật khẩu". 423 → "Tài khoản đã bị khoá". 429 → "Quá nhiều lần thử, vui lòng thử lại sau". |
| Notes | Không bao giờ coi `access_token: ""` là đăng nhập thành công. |

### 4.3 S-03 — MFA Verify (`/mfa`)

| | |
|---|---|
| Roles | Public (yêu cầu `mfaSessionId` trong state) |
| Endpoints | `POST /api/v1/auth/mfa/verify` |
| Components | `MfaCodeInput` (6 ô, auto-advance), `ResendHint`, `CountdownTimer` |
| Form fields | `mfa_code` (`^\d{6}$`), `session_id` (UUID, ẩn) |
| Behavior | 200 → lưu token → `GET /auth/me` → redirect. 401 `Invalid MFA code` → xóa ô nhập, đếm số lần sai (3 lần → hết transaction). 401 `MFA code has expired` → "Mã đã hết hạn, đăng nhập lại". 409 `already completed` → "Mã đã được sử dụng, đăng nhập lại". 403 `IP mismatch` → "Bạn phải xác thực từ cùng địa chỉ IP". |
| Notes | **Không có endpoint resend** → CTA là "Quay lại đăng nhập". |

### 4.4 S-04 — Trusted-device Login (`/trusted-device`)

| | |
|---|---|
| Roles | Public |
| Endpoints | `POST /api/v1/devices/pending` → `POST /api/v1/devices/pending/{id}/complete`; nhánh approve: `POST /api/v1/devices/pending/{id}/approve` |
| Components | `TrustedDeviceForm`, `DeviceStatusBadge`, `PollPendingApproval` |
| Behavior | 202 → hiển thị "Đang chờ thiết bị đã đăng nhập xác nhận" + polling `POST /complete`. 409 `still pending` → tiếp tục poll. 200 từ `/complete` → đăng nhập thành công. 409 `Detection requires MFA` → "Hệ thống phát hiện rủi ro, vui lòng dùng luồng đăng nhập thường". 403 (IP/fingerprint mismatch) → "Yêu cầu bị từ chối". |
| Notes | Đây là luồng **thay thế**, không phải luồng chính. |

### 4.5 S-05 — Sessions (`/sessions`)

| | |
|---|---|
| Roles | Mọi role đã đăng nhập |
| Endpoints | `GET /api/v1/auth/sessions`, `DELETE /api/v1/auth/sessions/{id}`, `POST /api/v1/auth/logout-all` |
| Components | `SessionTable`, `RevokeButton`, `LogoutAllButton`, `ConfirmDialog` |
| Table columns | `device (user_agent)`, `ip_address`, `created_at`, `last_activity_at`, `expires_at`, `is_current` (badge "Phiên hiện tại") |
| Behavior | Revoke phiên hiện tại → logout client. "Logout all" → xoá toàn bộ token client + về `/login`. |
| Permission | Tất cả role. |

### 4.6 S-06 — Trusted Devices (`/devices`)

| | |
|---|---|
| Roles | Mọi role đã đăng nhập |
| Endpoints | `GET /api/v1/devices`, `POST /api/v1/devices`, `DELETE /api/v1/devices/{id}`, `DELETE /api/v1/devices/all` |
| Components | `DeviceTable`, `TrustDeviceDialog`, `UntrustAllButton` |
| Table columns | `device_name`, `last_user_agent`, `last_ip`, `last_used_at`, `expires_at` |
| Form | `TrustDeviceDialog`: `device_name` (≤100), `remember_for_days` (1..365, default 30) |
| Behavior | "Untrust all" → ConfirmDialog mạnh (không thể hoàn tác). |
| Notes | Chỉ hiển thị thiết bị **của chính mình** (backend tự lọc). |

### 4.7 S-07 — Profile (`/profile`)

| | |
|---|---|
| Roles | Mọi role đã đăng nhập |
| Endpoints | `GET /api/v1/auth/me` (read-only) |
| Components | `ProfileCard`, `RoleBadges`, `StatusBadge` |
| Fields (read-only) | `username`, `email`, `full_name`, `status`, `roles`, `admin_mfa_required`, `last_login_at`, `failed_login_count`, `locked_at`, `created_at` |
| Notes | **Không có endpoint update profile** → form chỉ đọc. MFA bắt buộc chỉ đổi được bởi `SECURITY_ADMIN`. |

### 4.8 S-08 — Forbidden (`/403`)

| | |
|---|---|
| Roles | Authenticated |
| Endpoints | — |
| Behavior | Hiển thị lý do + nút "Về trang phù hợp với vai trò của bạn" (dựa trên menu động). |

### 4.9 S-10 — User Management (`/admin/users`)

| | |
|---|---|
| Roles | `SECURITY_ADMIN` |
| Endpoints | `GET /api/v1/admin/users`, `POST /api/v1/admin/users/{id}/roles`, `DELETE /api/v1/admin/users/{id}/roles/{rid}`, `POST /api/v1/admin/users/{id}/lock`, `DELETE /api/v1/admin/users/{id}/lock`, `PUT /api/v1/admin/users/{id}/mfa` |
| Components | `UserTable`, `UserFilters` (role, status), `AssignRoleDialog`, `LockUserDialog`, `ToggleMfaSwitch`, `Pagination` |
| Table columns | `username`, `email`, `status` (badge), `roles` (multi-badge), `admin_mfa_required`, `last_login_at`, `failed_login_count`, `created_at`, actions |
| Filters | `role`, `status` (server-side query) |
| Actions & permissions | |
| | Action | API | Quyền |
| |---|---|---|
| | Gán role | `POST /users/{id}/roles` | `SECURITY_ADMIN` |
| | Gỡ role | `DELETE /users/{id}/roles/{rid}` | `SECURITY_ADMIN` — **disable với role `USER`** (backend 400) |
| | Khoá | `POST /users/{id}/lock` | `SECURITY_ADMIN` |
| | Mở khoá | `DELETE /users/{id}/lock` | `SECURITY_ADMIN` |
| | Bắt buộc MFA | `PUT /users/{id}/mfa` | `SECURITY_ADMIN` |
| Notes | `assigned_to_id` cho SOC analyst: xem G-2/Gap — chưa có mapping. |

### 4.10 S-11 — Audit Logs (`/admin/audit-logs`)

| | |
|---|---|
| Roles | `SECURITY_ADMIN` |
| Endpoints | `GET /api/v1/admin/audit-logs` |
| Components | `AuditLogTable`, `AuditFilters`, `AuditDetailDrawer`, `Pagination` |
| Table columns | `created_at`, `actor`, `action`, `resource`, `resource_id`, `ip_address` |
| Filters | `actor` (username hoặc actor_type), `action`, `resource`, `from`, `to` |
| Detail drawer | `before_state`, `after_state`, `change_reason`, `user_agent`, `request_id` (JSON pretty-print) |
| Notes | `before_state`/`after_state` là `dict` tự do → render JSON, không ép schema. |

### 4.11 S-20 — Alert Queue (`/alerts`)

| | |
|---|---|
| Roles | `SOC_ANALYST` \| `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/alerts` |
| Components | `AlertTable`, `AlertFilters`, `RiskBadge`, `StatusBadge`, `Pagination`, `BulkAcknowledgeButton` |
| Table columns | `risk_level` (badge màu), `status`, `detection_reason`, `username` (từ nested `login_attempt`), `ip_address`, `assigned_to_id`, `created_at` |
| Filters | `status`, `risk_level`, `assigned_to_id`, `page`, `limit` |
| Sorting | Server đã sort mới nhất trước (thứ tự backend). |
| Behavior | Click row → `/alerts/:id`. |

### 4.12 S-21 — Alert Detail (`/alerts/:id`)

| | |
|---|---|
| Roles | `SOC_ANALYST` \| `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/alerts/{id}`, `GET /api/v1/alerts/{id}/evidence`, `GET /api/v1/alerts/{id}/timeline`, `POST /api/v1/alerts/{id}/timeline`, `POST /api/v1/alerts/{id}/acknowledge`, `POST /api/v1/alerts/{id}/resolve`, `POST /api/v1/alerts/{id}/assign`, `POST /api/v1/alerts/{id}/actions` |
| Layout | 2 cột: trái = tổng quan + hành động; phải = Evidence + Timeline (tabs) |
| Components | `AlertHeader`, `AlertScorePanel`, `ActionBar`, `AcknowledgeDialog`, `ResolveDialog`, `AssignDialog`, `ProtectiveActionDialog`, `EvidencePanel`, `DetectionLogTable`, `TimelineFeed`, `AddNoteForm` |
| Tabs | **Tổng quan** · **Bằng chứng** (evidence) · **Dòng thời gian** (timeline) |
| Action bar (theo `status`) | |
| | `status` | Action được phép | API |
| |---|---|---|
| | `open` | Acknowledge, Assign, Request action | `POST /acknowledge`, `/assign`, `/actions` |
| | `acknowledged` | Resolve, Assign, Request action | `POST /resolve`, `/assign`, `/actions` |
| | `resolved` | Chỉ xem, Add note | `POST /timeline` |
| | `false_positive` | Chỉ xem, Add note | `POST /timeline` |
| Resolve form | `resolution` ∈ `true_attack \| false_positive \| benign_true_positive \| insufficient_evidence`, `notes` |
| Protective action form | `action` ∈ `REQUIRE_MFA \| REVOKE_SESSIONS \| LOCK_USER \| FORCE_LOGOUT`, `reason` (bắt buộc ≥1) |
| Assign form | `assigned_to_id` (UUID của `soc_analysts.id`) — **xem Gap G-1**: hiện dùng free-text UUID input |
| Evidence panel | `alert`, `login_attempt`, `risk_assessment` (rule_score / ml_score / combined_score / ml_status / rule_hits), `detection_logs[]` (bảng: stage, rule_name, triggered, score_contribution, decision, reason) |
| Timeline | `event_type` badge + `old_value → new_value` + `comment` + `actor_id` + `created_at` |
| **Quan trọng** | Protective action trả **502** → hiển thị rõ "**Hành động KHÔNG được áp dụng**" + lý do. Không hiển thị success. Timeline sẽ có thêm event `note_added` ghi nhận việc thất bại. |

### 4.13 S-22 — Login History (`/login-history`)

| | |
|---|---|
| Roles | `SOC_ANALYST` \| `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/login-attempts` |
| Components | `LoginAttemptTable`, `LoginAttemptFilters`, `DateRangePicker`, `Pagination` |
| Table columns | `timestamp`, `username_attempted`, `outcome` (badge), `risk_level`, `detection_decision`, `ip_address`, `mfa_used`, `policy_id`, `primary_alert_id` |
| Filters | `username`, `user_id`, `ip_address`, `outcome` (`success`/`failure`), `risk_level`, `from_date` (inclusive), `to_date` (exclusive) |
| Behavior | 400 filter sai → toast inline. Click `primary_alert_id` → `/alerts/:id`. |
| Notes | `from_date`/`to_date` là **datetime đầy đủ**, gửi ISO-8601. |

### 4.14 S-30 — Policy List (`/policies`)

| | |
|---|---|
| Roles | `SECURITY_ADMIN` \| `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/policies`, `POST /api/v1/policies/{id}/activate` (chỉ ADMIN) |
| Components | `PolicyTable`, `ActivePolicyBadge`, `ActivateButton`, `ConfirmDialog` |
| Table columns | `version`, `name`, `rule_count`, `is_active` (badge "Active"), `created_at`, `activated_at`, actions |
| Actions | Activate (chỉ `SECURITY_ADMIN`) → ConfirmDialog → `POST /policies/{policy_id}/activate` → invalidate list. |
| Notes | Response là **mảng thô** (`array`), không có `total` → không hiển thị phân trang. `SECURITY_MANAGER` xem read-only, không thấy nút Activate. |

### 4.15 S-31 — Policy Detail (`/policies/:id`)

| | |
|---|---|
| Roles | `SECURITY_ADMIN` \| `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/policies/{id}`, `POST /api/v1/policies/{id}/activate` (chỉ ADMIN) |
| Components | `PolicyHeader`, `PolicyMeta`, `RuleViewer`, `ConfigViewer`, `ActivateButton`, `EditButton`, `ImmutabilityBanner` |
| Sections | Meta (`version`, `name`, `description`, `is_active`, `created_at`, `updated_at`, `activated_at`, `deactivated_at`, `created_by`) · Rules (bảng: name, field, operator, value, weight, score, enabled) · Config (weights + thresholds) |
| Behavior | Nếu `is_active` hoặc `activated_at != null` → hiển thị `ImmutabilityBanner` "Policy đã từng được kích hoạt — không thể sửa" + ẩn nút Edit (chỉ ADMIN). |
| Notes | **Đây là màn hình duy nhất lấy `updated_at` để chuẩn bị cho Edit.** |

### 4.16 S-32 — Policy Editor (`/policies/new`, `/policies/:id/edit`)

| | |
|---|---|
| Roles | `SECURITY_ADMIN` (chỉ) |
| Endpoints | Create: `POST /api/v1/policies` · Edit: `GET /api/v1/policies/{id}` → `PUT /api/v1/policies/{id}` |
| Components | `PolicyForm`, `RuleBuilder`, `RuleRow`, `FieldSelector`, `OperatorSelector`, `ValueEditor`, `WeightsEditor`, `ThresholdsEditor`, `VersionField`, `ConflictDialog` |
| Create form | `version` (pattern `^v\d+(\.\d+)*$`, ví dụ `v1.0`), `name?` (≤255), `description?`, `rules[]` (≥1), `config` (default `{ weights: {rule:0.4, ml:0.6}, thresholds: {low:0.25, medium:0.5, high:0.75} }`) |
| Edit form | `name?`, `description?`, `rules?`, `config?`, `expected_updated_at` (**bắt buộc, lấy từ `GET /detail`**) |
| Rule field | `name` (1-100), `field` ∈ 6 features (`hour_of_day`, `fail_count_24h`, `ip_change_rate_7d`, `new_device`, `average_login_interval_seconds`, `deviation_score`), `operator` ∈ 9 toán tử, `value`, `weight` (0..1), `score` (0..1), `enabled`, `description?` |
| Value editor theo operator | `between`/`not_between` → **2 số** `[min,max]`; `in` → **mảng không rỗng**; còn lại → **1 giá trị đơn** (mảng bị từ chối) |
| Client validation | `weights.rule + weights.ml` phải = 1.0 (nếu cả hai > 0) · `thresholds.low ≤ medium ≤ high` · `rules` không trùng tên |
| **Create behavior** | 201 → toast + chuyển `/policies/:id` · 400 → hiển thị **danh sách** `problems[]` ngay trên form · 409 `version already exists` → highlight field `version` · 422 → map vào field |
| **Edit behavior** | 200 → toast + chuyển detail · 400 `problems[]` → inline · 409 `Policy is immutable` → `ImmutabilityBanner`, ẩn nút lưu, CTA "Tạo version mới" · 409 `modified by someone else` → **REFETCH** + thông báo "đã bị sửa bởi người khác" · **KHÔNG auto-overwrite** |
| Notes | `version` **immutable** → không cho sửa ở chế độ edit, chỉ hiển thị readonly. `is_active`/`created_by`/timestamps **không** gửi lên (server 400 nếu gửi). |

### 4.17 S-40 — Manager Dashboard (`/manager`)

| | |
|---|---|
| Roles | `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/manager/dashboard` |
| Components | `SourceStatusBanner`, `WindowPicker`, `KpiGrid`, `CoreSection`, `DetectionSection`, `MlSection`, `CriticalIncidentTable`, `EnforcementCard` |
| Layout | 3 block: Core · Detection · ML — mỗi block là một section card |
| KPIs Core | `total_users`, `active_sessions`, `users_with_mfa_required`, `mfa_challenges/completed/failed`, `audit_events` |
| KPIs Detection | `login_attempts`, `by_outcome`, `by_risk_level`, `by_decision`, `alerts.{total,open,critical_open}` |
| KPIs ML | `model_status`, `inferences`, `anomalies`, `anomaly_rate`, `active_model_version` |
| Charts | Bar chart `by_risk_level` · Bar chart `by_outcome` · Line chart `daily` (ML) |
| **Degraded handling** | `degraded === true` → `SourceStatusBanner` ở đầu trang: "Một số nguồn dữ liệu không khả dụng: {source} ({reason_code})". Section của source đó render `<EmptyState>` + nút "Thử lại", **không** render số 0. |
| 503 handling | Endpoint trả 503 → hiển thị **toàn trang** degraded state với `sources` map + nút "Thử lại". Không phải error page chung. |
| Notes | Mỗi section có thể `null` → coi như không có dữ liệu, không phải 0. `window` mặc định 24h. |

### 4.18 S-41 — Trends (`/manager/trends`)

| | |
|---|---|
| Roles | `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/manager/trends` |
| Components | `WindowPicker`, `BucketSelector` (`auto`/`hour`/`day`), `TrendChart`, `MultiSeriesLegend`, `SourceStatusBanner` |
| Charts | 3 chart: Login attempts (stacked by `by_outcome`) · Alerts (stacked by `by_status`) · ML (`anomalies` vs `total`) |
| Bucket | `auto` mặc định (server resolve theo độ dài window). Hiển thị `bucket` **đã resolve** từ response. |
| Series null | Series `null` → chart placeholder "Không có dữ liệu". |
| Notes | Default window 14 ngày. |

### 4.19 S-42 — Alert Analytics (`/manager/alerts`)

| | |
|---|---|
| Roles | `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/manager/alerts` |
| Components | `WindowPicker`, `AlertTotalsCard`, `ByStatusChart`, `ByRiskChart`, `ByRuleTable`, `ByMlReasonTable`, `BacklogCard`, `MttA_MttRCard` |
| KPIs | `totals.{created,open,acknowledged,resolved,false_positive}`, `backlog.{open_count,unassigned,escalated,oldest_open_age_hours}`, `false_positive_rate`, `mtta_seconds`, `mttr_seconds` |
| Charts | Donut `by_status` · Bar `by_risk_level` · Bar `by_rule` · Bar `by_ml_reason` |
| Filters | `status`, `risk_level` (giống `/alerts`) |
| Degraded | Endpoint này chỉ dùng **1 source** → bất kỳ failure nào = **503**, không có degraded 200. Xử lý 503 như S-40. |

### 4.20 S-43 — SOC KPI (`/manager/soc-kpi`)

| | |
|---|---|
| Roles | `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/manager/soc-kpi` |
| Components | `KpiGrid`, `KpiCard` (nullable-aware), `SourceStatusBanner`, `DefinitionTooltip` |
| KPI groups | |
| | Nhóm | KPI |
| |---|---|
| | Response | `mtta_seconds`, `mttr_seconds`, `acknowledgement_rate`, `resolution_rate`, `false_positive_rate`, `escalation_rate` |
| | Volume | `alerts_per_analyst`, `enforcement_attempted`, `enforcement_succeeded`, `enforcement_success_rate` |
| | ML | `ml_assessments`, `ml_fallback_count`, `ml_fallback_rate` |
| | MFA | `mfa_enrollment_rate`, `forced_mfa_users` |
| | Audit | `audit_events` |
| **Nullable KPI** | `null` → hiển thị "—" **kèm tooltip** phân biệt 2 nguyên nhân: (a) population rỗng → "Không có dữ liệu trong khoảng thời gian này"; (b) source down → "Nguồn dữ liệu không khả dụng". Kiểm tra `sources[...].status === 'unavailable'` để phân biệt. |
| Notes | Default window 30 ngày. **Không** hiển thị `0` cho KPI null. |

### 4.21 S-44 — ML Stats (`/manager/ml-stats`)

| | |
|---|---|
| Roles | `SECURITY_MANAGER` |
| Endpoints | `GET /api/v1/manager/ml-stats` |
| Components | `ModelInfoCard`, `VersionTable`, `InferenceStatsCard`, `ByStatusChart`, `ReasonCodeChart`, `DailyChart`, `FeatureStatsTable` |
| Sections | Model (active version, status, is_production, algorithm, deployed_at, trained_by) · Versions (bảng) · Inference (total, anomalies, anomaly_rate, avg/p95 processing_ms, errors, degraded) · By status · Reason codes · Daily · Features (bảng: name, count, mean, std, min, max, p25/p50/p75/p95, anomaly_rate) |
| Notes | Default window 30 ngày. `reason_codes` là mảng object tự do → render bảng động. |

### 4.22 S-90 / S-91 / S-92

| Screen | Route | Roles | Endpoints | Behavior |
|---|---|---|---|---|
| S-90 Not Found | `/*` | Authenticated | — | 404 UI + link về trang chủ theo role |
| S-91 Global Error | — | — | — | ErrorBoundary bắt lỗi render; hiển thị `request_id` nếu có |
| S-92 Service Status | `/status` | Authenticated | `GET /health`, `GET /ready` | Hiển thị trạng thái API; badge "sẵn sàng"/"chưa sẵn sàng". Không phải màn hình chính, có thể ẩn khỏi menu. |

---

## 5. Ma trận endpoint → screen (đầy đủ)

| Endpoint | S-01 | S-02 | S-03 | S-04 | S-05 | S-06 | S-07 | S-10 | S-11 | S-20 | S-21 | S-22 | S-30 | S-31 | S-32 | S-40 | S-41 | S-42 | S-43 | S-44 | S-92 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `POST /auth/register` | ✓ | | | | | | | | | | | | | | | | | | | |
| `POST /auth/login` | | ✓ | | | | | | | | | | | | | | | | | |
| `POST /auth/mfa/verify` | | | ✓ | | | | | | | | | | | | | | | | |
| `GET /auth/me` | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `POST /auth/refresh` | | ✓* | ✓* | ✓* | ✓* | | | | | | | | | | | | | | | | |
| `POST /auth/logout` | | | | | ✓ | | | | | | | | | | | | | | | |
| `POST /auth/logout-all` | | | | | ✓ | | | | | | | | | | | | | | | |
| `GET /auth/sessions` | | | | | ✓ | | | | | | | | | | | | | | | |
| `DELETE /auth/sessions/{session_id}` | | | | | ✓ | | | | | | | | | | | | | | | | |
| `GET /devices` | | | | | | ✓ | | | | | | | | | | | | | |
| `POST /devices` | | | | | | ✓ | | | | | | | | | | | | | | |
| `DELETE /devices/{device_id}` | | | | | | ✓ | | | | | | | | | | | | | | |
| `DELETE /devices/all` | | | | | | ✓ | | | | | | | | | | | | | | |
| `POST /devices/check` | | | ✓ | | | | | | | | | | | | | | | | |
| `POST /devices/pending` | | | | ✓ | | | | | | | | | | | | | | |
| `POST /devices/pending/{request_id}/approve` | | | | ✓ | | | | | | | | | | | | | | | |
| `POST /devices/pending/{request_id}/complete` | | | | ✓ | | | | | | | | | | | | | | | | |
| `GET /admin/users` | | | | | | | | ✓ | | | | | | | | | | | | |
| `POST /admin/users/{user_id}/roles` | | | | | | | ✓ | | | | | | | | | | | | |
| `DELETE /admin/users/{user_id}/roles/{role_id}` | | | | | | | ✓ | | | | | | | | | | | | |
| `POST /admin/users/{user_id}/lock` | | | | | | | ✓ | | | | | | | | | | | | |
| `DELETE /admin/users/{user_id}/lock` | | | | | | | | ✓ | | | | | | | | | | | | | |
| `PUT /admin/users/{user_id}/mfa` | | | | | | | ✓ | | | | | | | | | | | | | |
| `GET /admin/audit-logs` | | | | | | | ✓ | | | | | | | | | | | |
| `GET /alerts` | | | | | | | | | | ✓ | | | | | | | | | | | |
| `GET /alerts/{alert_id}` | | | | | | | | | | ✓ | | | | | | | | | |
| `GET /alerts/{alert_id}/evidence` | | | | | | | | | | ✓ | | | | | | | | | |
| `GET /alerts/{alert_id}/timeline` | | | | | | | | | | ✓ | | | | | | | | | | |
| `POST /alerts/{alert_id}/timeline` | | | | | | | | | | ✓ | | | | | | | | | | |
| `POST /alerts/{alert_id}/acknowledge` | | | | | | | | | ✓ | | | | | | | | | |
| `POST /alerts/{alert_id}/resolve` | | | | | | | | | | | ✓ | | | | | | | | | | |
| `POST /alerts/{alert_id}/assign` | | | | | | | | | | ✓ | | | | | | | | | | |
| `POST /alerts/{alert_id}/actions` | | | | | | | | | ✓ | | | | | | | | | | |
| `GET /login-attempts` | | | | | | | | | | | ✓ | | | | | | | | | |
| `GET /policies` | | | | | | | | | | | | ✓ | | | | | | | | |
| `GET /policies/{policy_id}` | | | | | | | | | | | | ✓ | ✓ | | | | | | | | |
| `POST /policies` | | | | | | | | | | | | | ✓ | | | | | | | |
| `PUT /policies/{policy_id}` | | | | | | | | | | | | | ✓ | | | | | | | |
| `POST /policies/{policy_id}/activate` | | | | | | | | | | | ✓ | | | | | | | | |
| `GET /manager/dashboard` | | | | | | | | | | | | | | | ✓ | | | | |
| `GET /manager/trends` | | | | | | | | | | | | | | | ✓ | | | | |
| `GET /manager/alerts` | | | | | | | | | | | | | | | | ✓ | | | |
| `GET /manager/soc-kpi` | | | | | | | | | | | | | | | | | | ✓ | |
| `GET /manager/ml-stats` | | | | | | | | | | | | | | | | | | ✓ |
| `GET /health` | | | | | | | | | | | | | | | | | | | | ✓ |
| `GET /ready` | | | | | | | | | | | | | | | | | | | | | ✓ |

`*` = gọi tự động bởi axios interceptor, không phải bởi component.

---

## 6. Đối chiếu với backend (role thực tế)

| Màn hình | Role backend cho phép | Khớp với page map? |
|---|---|---|
| S-20/S-21/S-22 | `SOC_ANALYST` \| `SECURITY_MANAGER` | ✓ |
| S-30/S-31 | `SECURITY_ADMIN` \| `SECURITY_MANAGER` | ✓ |
| S-32 | `SECURITY_ADMIN` | ✓ |
| S-40…S-44 | `SECURITY_MANAGER` | ✓ |
| S-10/S-11 | `SECURITY_ADMIN` | ✓ |
| S-05…S-07 | bất kỳ role đã đăng nhập | ✓ |
| S-01…S-04 | public | ✓ |

**Không có màn hình nào yêu cầu role mà backend không cấp.** Ngược lại, mọi endpoint browser-callable đều được ánh xạ tới ít nhất một screen.

---

## 7. Bảng component dùng chung

| Component | Dùng ở screen | Ghi chú |
|---|---|---|
| `DataTable` | S-10, S-11, S-20, S-22, S-30, S-44 | Cột cấu hình, sort client-side hoặc server-side, empty state, loading skeleton |
| `Pagination` | S-10, S-11, S-20, S-22 | `page`/`limit` (limit ≤ 100). S-30 **không** có (API trả mảng thô). |
| `FiltersBar` | S-10, S-11, S-20, S-22, S-40…S-44 | Debounce 300ms, sync vào URL query (deep-link). |
| `RiskBadge` | S-20, S-21, S-22, S-40, S-42 | `low`/`medium`/`high`/`critical` → màu theo ngữ nghĩa |
| `StatusBadge` | S-05, S-06, S-10, S-20, S-21 | active/suspended/locked, open/acknowledged/resolved/false_positive |
| `SourceStatusBanner` | S-40…S-44 | Hiển thị `sources` map + reason code |
| `KpiCard` | S-40, S-42, S-43 | **Nullable-aware**: `null` → "—" + tooltip |
| `EmptyState` | tất cả | Icon + message + optional action |
| `ErrorState` | tất cả | Message + "Thử lại" + (dev) detail kỹ thuật |
| `ConfirmDialog` | S-05, S-06, S-30, S-31 | Destructive action cần xác nhận |
| `JsonViewer` | S-11, S-21 | Pretty-print `before_state`/`after_state`/`detection_scores`/`details` |
| `DateRangePicker` | S-22, S-40…S-44 | Gửi ISO-8601 |
| `WindowPicker` | S-40…S-44 | `from`/`to`; mặc định theo endpoint |
| `CopyButton` | S-21, S-31 | Copy UUID, timestamp |
| `Tabs` | S-21, S-31 | Tổng quan / Bằng chứng / Timeline |
