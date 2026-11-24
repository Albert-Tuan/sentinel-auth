# M12.0 — Integration Plan & Critical Contracts (Sentinel Auth v3.3)

**Baseline:** `origin/dev` @ `c89bff5`
**Phạm vi:** Hợp đồng tích hợp quan trọng giữa frontend React và backend FastAPI. Tài liệu này là **hợp đồng** — mọi thứ ở đây phải được implement đúng ở cả hai phía.

---

## 1. Login → MFA → Session

### 1.1 Luồng chuẩn (không MFA)

```
Client                          API (FastAPI)                     DB
  │ POST /api/v1/auth/login      │                                │
  │ {username, password}        │                                │
  │────────────────────────────►│ rate limit (5/min/IP)         │
  │                             │ verify Argon2id                │
  │                             │ check user.status              │
  │                             │ _pre_token_risk()  ────────────┼──► Detection
  │                             │ create Session + 2 tokens      │
  │ 200 LoginResponse           │                                │
  │ {access_token, refresh_token,│                                │
  │  mfa_required: false,       │                                │
  │  session_id}                │                                │
  │◄────────────────────────────┤                                │
```

### 1.2 Luồng MFA

```
Client                          API                              DB
  │ POST /api/v1/auth/login      │                               │
  │────────────────────────────►│ credentials OK, mfa_required  │
  │                             │ = admin_mfa_required OR        │
  │                             │   detection_mfa_once           │
  │                             │ create MfaTransaction          │
  │                             │   (status=pending, expires     │
  │                             │    = now + 5 MINUTES)          │
  │                             │ create MfaNotification         │
  │                             │   (channel=email, mfa_code_hash)│
  │                             │ send OTP email (best-effort)   │
  │ 200 LoginResponse            │                                │
  │ {access_token: "",           │                                │
  │  refresh_token: "",          │                                │
  │  mfa_required: true,         │                                │
  │  session_id: <MfaTxn.id>}    │                                │
  │◄────────────────────────────┤                                │
  │                               │                               │
  │  [user nhận OTP qua email]    │                               │
  │                               │                               │
  │ POST /api/v1/auth/mfa/verify  │                               │
  │ {session_id, mfa_code}        │                               │
  │────────────────────────────►│ SELECT ... FOR UPDATE          │
  │                             │ status checks:                │
  │                             │  completed → 409              │
  │                             │  failed    → 409              │
  │                             │  expired   → 401              │
  │                             │ verify OTP (Argon2)           │
  │                             │  fail → fail_count++, >=3 →    │
  │                             │         status=failed → 401   │
  │                             │ IP binding check → 403        │
  │                             │ mark completed + verified_at  │
  │                             │ _create_session() → 2 tokens  │
  │ 200 MfaVerifyResponse       │                                │
  │ {access_token, refresh_token,│                                │
  │  session_id: <Session.id>}   │                                │
  │◄────────────────────────────┤                                │
```

### 1.3 Hợp đồng cho frontend

| # | Quy tắc | Lý do |
|---|---|---|
| A1 | `session_id` trong response của `login` **đổi ý nghĩa** tùy `mfa_required`. Khi `true` → đó là **`mfa_transactions.id`**, KHÔNG phải session. | Backend tái sử dụng field cho pre-auth transaction. |
| A2 | Frontend **phải** kiểm tra `mfa_required === true` **trước khi** coi là đăng nhập. | `access_token` là `""` — falsy. |
| A3 | Khi `mfa_required: true`, **không** lưu token nào (vì chúng rỗng). Lưu `mfaSessionId` riêng. | Tránh state "đã đăng nhập" giả. |
| A4 | OTP có **5 phút** hạn. UI nên hiển thị đồng hồ đếm ngược từ `expires_at` (nếu có) hoặc giả định 300s. | Trải nghiệm. |
| A5 | OTP sai **3 lần** → transaction chết → phải login lại. UI nên đếm số lần sai và cảnh báo. | `fail_count >= 3` → `status = failed`. |
| A6 | 403 `IP mismatch` → hiển thị rõ "Bạn phải xác thực từ cùng địa chỉ IP đã dùng để đăng nhập". | Không phải lỗi chung chung. |
| A7 | **Không có endpoint resend OTP.** CTA khi hết hạn: "Quay lại đăng nhập". | Xem Gap G-4. |
| A8 | `POST /api/v1/auth/mfa/verify` **không** cần bearer token. | Pre-auth. |

### 1.4 HTTP status quan trọng

| Status | `detail` | UI |
|---|---|---|
| 401 | `Invalid credentials` | "Sai tài khoản hoặc mật khẩu" (không tiết lộ user tồn tại) |
| 401 | `Invalid MFA code` | "Mã không đúng", xóa ô nhập |
| 401 | `MFA code has expired` / `MFA transaction expired` | "Mã đã hết hạn, hãy đăng nhập lại" |
| 401 | `Account is not active` | Tài khoản bị khoá/suspend |
| 403 | `MFA verification is bound to the original IP address` | "Phải xác thực từ cùng IP" |
| 404 | `Transaction not found` | "Phiên xác thực không tồn tại, hãy đăng nhập lại" |
| 409 | `MFA transaction already completed` | "Mã đã được dùng, hãy đăng nhập lại" |
| 409 | `MFA transaction failed` | "Đã quá số lần thử, hãy đăng nhập lại" |
| 423 | `Account is locked` | "Tài khoản đã bị khoá" |
| 429 | `Too many requests. Try again later.` | "Quá nhiều lần thử, thử lại sau" |
| 502 | — | — |

---

## 2. Token refresh & logout

### 2.1 Vòng đời access token

| Thuộc tính | Giá trị |
|---|---|
| Độ dài | 32 bytes random (`secrets.token_urlsafe(32)`) → ~43 ký tự |
| Lưu trữ server | SHA-256 hash trong `sessions.access_token_hash` |
| TTL | **1 giờ** (`expires_at = now + 1h`) |
| Kiểm tra | `revoked_at IS NULL AND expires_at > now()` |
| Khi hết hạn | Mọi request → **401** `Invalid or expired session` |

### 2.2 Vòng đời refresh token

| Thuộc tính | Giá trị |
|---|---|
| Lưu trữ server | SHA-256 hash trong `sessions.refresh_token_hash` |
| TTL | Cùng session (`expires_at`) |
| **Rotation** | **BẮT BUỘC** — mỗi lần refresh sinh refresh token mới và ghi đè hash cũ |

**Rotation ⇒ token cũ bị vô hiệu ngay lập tức.**

> Đây là lý do **bắt buộc** phải có mutex refresh: 3 request cùng lúc gặp 401 → nếu cả 3 đều gọi `/refresh` với cùng refresh token cũ, request thứ 2 và 3 sẽ nhận 401 (token đã bị thay) → logout oan.

### 2.3 Hợp đồng refresh

```
GET /some/protected        → 401
   ↓
interceptor: chặn 401, gọi POST /auth/refresh (mutex, 1 lần)
   ↓
200 { access_token: NEW, refresh_token: NEW2 }
   ↓
thay cả 2 token trong store
   ↓
retry request gốc với Authorization: Bearer NEW
```

| # | Quy tắc |
|---|---|
| B1 | **Phải thay cả 2** token sau mỗi refresh (`access_token` **và** `refresh_token`). |
| B2 | **Mutex**: chỉ một refresh bay. Các request còn lại chờ rồi retry. |
| B3 | Đánh dấu request đã retry (`_retried`) để tránh **vòng lặp vô hạn** (401 → refresh → 401 → refresh → …). |
| B4 | **Không** refresh trên 401 của chính `/auth/refresh` (vô ích) → clear session → về `/login`. |
| B5 | Refresh fail (401) ⇒ **xoá cả 2 token** + clear user ⇒ `window.location.assign('/login?redirect=...')`. |
| B6 | Giữ nguyên `redirect` để sau khi login lại, quay về đúng trang user đang cố vào. |
| B7 | **Không** retry tự động các lỗi khác (403, 404, 409, 502) — chỉ 401 mới refresh. |

### 2.4 Logout

| Endpoint | Phạm vi | Hiệu lực |
|---|---|---|
| `POST /api/v1/auth/logout` | Session hiện tại | `revoked_at` set → token đó 401 ngay. **Refresh token của session đó cũng chết** (vì `refresh_token_hash` trỏ về session đã revoked → `refresh_token IS NULL` khi query revoked). |
| `POST /api/v1/auth/logout-all` | Tất cả session của user | Tất cả token của user 401. |

| # | Quy tắc |
|---|---|
| C1 | Logout **luôn** clear client store (access + refresh + user), kể cả khi API lỗi. |
| C2 | Sau `logout-all`, **không** thử refresh (refresh token đã chết). |
| C3 | Redirect về `/login` **kèm** thông báo "Bạn đã đăng xuất khỏi tất cả thiết bị". |

### 2.5 Hậu quả của việc reload

Do token nằm **trong memory** (T3/T4 trong [M12-ARCHITECTURE.md §3.2](./M12-ARCHITECTURE.md)):

> **Reload trang ⇒ mất session ⇒ phải đăng nhập lại.**

**UX bắt buộc:**
- Không dùng `401` thô từ axios khi user chưa từng đăng nhập → hiển thị `/login` bình thường.
- Nếu user **đã** đăng nhập rồi reload → hiển thị `/login` kèm thông báo nhẹ: "Phiên đăng nhập đã hết do tải lại trang. Vui lòng đăng nhập lại." (không phải error đỏ).
- Cân nhắc `sessionStorage` chỉ cho **refresh token** + `HttpOnly`-style? **Không** — backend không hỗ trợ cookie, và đây là bản demo. Ghi rõ giới hạn này trong README của frontend.

---

## 3. SOC alert lifecycle

### 3.1 Máy trạng thái

```
                ┌──────────────┐
                │     open     │ ◄──── (tạo tự động bởi Detection khi risk ≥ threshold)
                └──────┬───────┘
                       │ POST /alerts/{id}/acknowledge
                       │ (chỉ khi status == open)
                       ▼
                ┌──────────────────┐
                │  acknowledged    │
                └──────┬───────────┘
                       │ POST /alerts/{id}/resolve
                       │   resolution = "false_positive" → FALSE_POSITIVE
                       │   resolution = khác           → RESOLVED
                       ▼
        ┌───────────────────┐   ┌─────────────────────┐
        │     resolved      │   │  false_positive     │
        └───────────────────┘   └─────────────────────┘
                (terminal)            (terminal)
```

| Từ | Đến | Endpoint | Điều kiện |
|---|---|---|---|
| — | `open` | (Detection tự tạo) | — |
| `open` | `acknowledged` | `POST /alerts/{id}/acknowledge` | status phải là `open` |
| `open` | `resolved`/`false_positive` | `POST /alerts/{id}/resolve` | status ∈ {open, acknowledged} |
| `acknowledged` | `resolved`/`false_positive` | `POST /alerts/{id}/resolve` | status ∈ {open, acknowledged} |
| `resolved` | — | — | **terminal** |
| `false_positive` | — | — | **terminal** |

### 3.2 Các transition **không** hợp lệ

| Gọi endpoint | Trạng thái hiện tại | Response |
|---|---|---|
| `/acknowledge` | `acknowledged` | **400** `Alert is acknowledged, only open alerts can be acknowledged` |
| `/acknowledge` | `resolved` | **400** `Alert is resolved, only open alerts can be acknowledged` |
| `/resolve` | `resolved` | **400** `Cannot resolve alert from status: resolved` |
| `/resolve` | `false_positive` | **400** `Cannot resolve alert from status: false_positive` |

**Hợp đồng cho frontend:**

| # | Quy tắc |
|---|---|
| D1 | Disable nút **Acknowledge** khi `status !== 'open'` (UI chặn trước). Backend vẫn là nơi enforce. |
| D2 | Disable nút **Resolve** khi `status` ∈ {`resolved`, `false_positive`}. |
| D3 | Khi gặp 400 transition → hiển thị message backend **nguyên văn** + refetch alert (trạng thái có thể đã đổi). |
| D4 | Sau mọi mutation → invalidate `detail`, `list`, `timeline`. |
| D5 | Timeline được append tự động bởi backend cho mỗi hành động — **không** tự thêm event ở frontend. |

### 3.3 Timeline event types

`created` · `assigned` · `unassigned` · `acknowledged` · `escalated` · `note_added` · `status_changed` · `resolved` · `false_positive`

> `escalated` tồn tại trong enum **nhưng backend không có endpoint escalate** — không được render nút "Escalate".

### 3.4 Ghi chú (notes)

`POST /alerts/{id}/timeline` với `{ event_type, comment? }` — dùng `event_type: "note_added"`.

| # | Quy tắc |
|---|---|
| D6 | `event_type` phải thuộc enum 9 giá trị → dùng dropdown, không free-text. |
| D7 | Endpoint `POST /alerts/{id}/timeline` nhận `TimelineEventCreate { event_type, comment? }` — **`comment` KHÔNG có giới hạn độ dài ở server** (schema `AlertNoteRequest` có `max_length=2000` nhưng là schema chết, không route nào dùng). UI vẫn nên tự giới hạn ở 2000 ký tự. |

### 3.5 Phân công (assign)

```
POST /api/v1/alerts/{id}/assign
{ "assigned_to_id": "<UUID của soc_analysts.id>", "notes": "..." }
```

| Lỗi | Ý nghĩa |
|---|---|
| 400 `assigned_to_id must be a valid UUID` | Không phải UUID hợp lệ |
| 400 `assigned_to_id must reference an existing active SOC analyst` | UUID hợp lệ nhưng không có analyst active tương ứng |

> **Gap G-1**: không có endpoint list `soc_analysts` ⇒ UI dùng **free-text UUID input** (validate UUID ở client) + helper text "UUID của hồ sơ SOC analyst (bảng `soc_analysts`)". Đây là **workaround tạm**, cần thay khi backend bổ sung `GET /api/v1/soc/analysts`.

---

## 4. Protective actions

### 4.1 Luồng thực thi

```
SOC Analyst                Detection API                Core API
     │ POST /alerts/{id}/actions                            │
     │ {action, reason}                                    │
     │────────────────►│                                    │
     │                 │ validate action enum (4 giá trị)   │
     │                 │ idempotency_key =                  │
     │                 │   "alert:{alert_id}:{action}"       │
     │                 │──────────────────────────────────►│
     │                 │   POST /api/v1/internal/actions     │
     │                 │   X-Internal-Secret: ...            │
     │                 │                                     │ enforce:
     │                 │                                     │  REQUIRE_MFA     → set detection_mfa_once
     │                 │                                     │  REVOKE_SESSIONS → revoke sessions
     │                 │                                     │  LOCK_USER       → status=locked
     │                 │                                     │  FORCE_LOGOUT    → revoke sessions
     │                 │◄──────────────────────────────────┤
     │                 │  outcome.enforced == true?          │
     │                 ├── yes ─► timeline note "applied"     │
     │                 │         200 AlertActionResponse      │
     │                 ├── no  ─► timeline note "NOT enforced"│
     │                 │         502 Bad Gateway             │
     │◄────────────────┤                                      │
```

### 4.2 Action enum

| `action` | Tác động lên core-db |
|---|---|
| `REQUIRE_MFA` | Set `users.detection_mfa_once = true` → login kế tiếp bắt MFA |
| `REVOKE_SESSIONS` | Revoke session của user đó |
| `LOCK_USER` | Set `users.status = 'locked'` |
| `FORCE_LOGOUT` | Revoke session của user đó |

### 4.3 Hợp đồng cho frontend

| # | Quy tắc | Lý do |
|---|---|---|
| E1 | **`reason` là bắt buộc** (`min_length=1`). UI bắt buộc nhập, không cho submit rỗng. | Backend 422 nếu thiếu. |
| E2 | **502 ⇒ KHÔNG hiển thị "thành công".** Hiển thị: *"Hành động **KHÔNG** được áp dụng. Vui lòng thử lại hoặc liên hệ quản trị."* + detail lỗi. | Hành động chưa có tác dụng. |
| E3 | Sau 502, **refetch timeline** — backend đã ghi event `note_added` ghi nhận thất bại. | SOC cần thấy hành động đã được *yêu cầu* nhưng *chưa áp dụng*. |
| E4 | Disable nút submit trong lúc request đang bay (chống double-submit). | Idempotency key giúp, nhưng UX vẫn cần. |
| E5 | Action chỉ khả dụng khi alert có `login_attempt.user_id`. Nếu không → 400 `No user associated with this alert`. UI nên disable + giải thích. | Không biết target. |
| E6 | **Không** hiển thị success trước khi nhận 200. | — |
| E7 | Nút action nên hiển thị cảnh báo tác dụng ("Khóa tài khoản" → "Tài khoản sẽ bị khóa ngay"). | Hành động phá huỷ. |
| E8 | 400 `Unsupported action` — không xảy ra nếu UI dùng enum đúng. | Guard. |

### 4.4 Ranh giới internal

`POST /api/v1/internal/actions` yêu cầu `X-Internal-Secret`. **Frontend không bao giờ** gọi endpoint này — nó được Detection gọi server-side. Nếu Core không cấu hình secret ⇒ mọi protective action trả **502**.

> ⇒ **Nếu demo báo 502 mọi lần**, kiểm tra `INTERNAL_SECRET` trong `.env` backend (≥32 ký tự, không phải placeholder).

---

## 5. Policy Create / Edit / Detail / Activate

### 5.1 Mô hình dữ liệu

| Khái niệm | Nguồn |
|---|---|
| Policy **summary** (list) | `GET /api/v1/policies` → `{id, version, name, description, rule_count, is_active, created_at, activated_at}` — **KHÔNG có `rules`, `config`, `updated_at`** |
| Policy **detail** (đầy đủ) | `GET /api/v1/policies/{id}` → `PolicyDetail` — **có `rules`, `config`, `updated_at`** |

⇒ **Bắt buộc** phải gọi `GET /detail` trước khi edit. Danh sách không đủ dữ liệu để sửa.

### 5.2 Vòng đời policy

```
        POST /api/v1/policies                POST /api/v1/policies/{id}/activate
        (is_active = false)                  (deactivate policy cũ, activate cái mới)
              │                                        │
              ▼                                        ▼
        ┌───────────┐                        ┌────────────────────┐
        │  DRAFT    │────────────────────────►│   ACTIVE (frozen)  │
        │ (inactive)│                        │  đã từng active    │
        └─────┬─────┘                        └────────────────────┘
              │ PUT /api/v1/policies/{id}            ▲
              │ (được khi CHƯA từng active)           │
              │                                      │
              │  Sau khi activate ────────────────────┘
              │  → PUT bị 409 "Policy is immutable"
              ▼
        (đóng băng vĩnh viễn — phải tạo version mới)
```

| Hành động | Điều kiện | Kết quả |
|---|---|---|
| `POST /policies` | version chưa tồn tại | 201, `is_active=false` |
| `PUT /policies/{id}` | `is_active == false` **AND** `activated_at == null` | 200 |
| `PUT /policies/{id}` | `is_active == true` | **409** `Policy is immutable` (active) |
| `PUT /policies/{id}` | `activated_at != null` | **409** `Policy is immutable` (đã từng active) |
| `PUT /policies/{id}` | `expected_updated_at` lệch | **409** `Policy was modified by someone else` |
| `POST /policies/{id}/activate` | policy hợp lệ | 200 `{status:"activated", version}` |

> **Điểm quan trọng:** `POST /policies/{id}/activate` **cũng bump `updated_at`** (do `onupdate` / set trong activate). Vì vậy một policy **vừa được activate rồi bị deactivate** sẽ vẫn có `activated_at != null` ⇒ 409 immutable.

### 5.3 Optimistic concurrency — chi tiết microsecond

**Vấn đề:**

```
Server trả:  "2026-11-07T02:33:00.123456Z"
JS Date:      new Date("2026-11-07T02:33:00.123456Z").toISOString()
           →  "2026-11-07T02:33:00.123Z"        ← mất 456 µs
Server so:   _same_instant(policy.updated_at, body.expected_updated_at)
           →  False ⇒ 409 "Policy was modified by someone else"
```

⇒ **Luôn** 409, dù không ai sửa policy. Đây là lỗi phổ biến nhất khi tích hợp.

**Giải pháp bắt buộc:**

```
GET /api/v1/policies/{id}
  → policy.updated_at  (string, giữ nguyên µs)     ← giữ NGUYÊN VĂN
  → policy.rules, policy.config                     ← vào form

PUT /api/v1/policies/{id}
  { ..., expected_updated_at: "<đúng chuỗi ở trên>" }   ← gửi lại nguyên văn
```

| # | Quy tắc |
|---|---|
| F1 | Kiểu TS của `updated_at` là `string`. **Không** phải `Date`. |
| F2 | **Không** gọi `new Date()`, `Date.parse()`, `toISOString()`, `date-fns` `format()` trên `updated_at` trước khi gửi. |
| F3 | **Không** dùng `JSON.stringify` lên object chứa `Date` — `Date` sẽ tự serialize thành `ISO` (mất µs). Giữ string. |
| F4 | Sau khi `GET /detail`, lưu `updated_at` vào một biến **string** riêng (`useRef` hoặc state). Cập nhật biến này **chỉ** khi refetch. |
| F5 | Mọi hàm format (`formatTimestamp`) chỉ dùng cho **hiển thị**, tuyệt đối không dùng lại output cho request. |
| F6 | Response của `PUT` trả `PolicyDetail` mới với `updated_at` mới ⇒ **cập nhật** biến string bằng `response.updated_at`. |

### 5.4 Xử lý 409 — không auto-overwrite

**Ba biến thể 409 phải phân biệt bằng `detail.message`:**

```ts
type PolicyProblem = { message: string; problems?: string[] };

function asPolicyProblem(detail: unknown): PolicyProblem | null {
  if (detail && typeof detail === "object" && "message" in detail) {
    return detail as PolicyProblem;
  }
  return null;
}
```

| `detail.message` | Hành động UI | Vì sao |
|---|---|---|
| `"Policy is immutable"` | Hiển thị banner "Policy đã từng được kích hoạt nên bị đóng băng. Hãy tạo version mới." + ẩn nút Lưu + CTA "Tạo version mới" (prefill `version` = `v{major}.{minor+1}`) | Không có cách nào sửa; phải tạo mới |
| `"Policy was modified by someone else"` | **REFETCH** `GET /policies/{id}`. Hiển thị "Policy đã bị sửa bởi người khác. Dữ liệu đã được tải lại — hãy kiểm tra và gửi lại." Giữ nguyên input của user để họ so sánh. **KHÔNG** tự gửi lại. | Blind retry sẽ ghi đè thay đổi của người khác |
| `"Policy version already exists"` (chỉ ở Create) | Highlight field `version`, giải thích version đã tồn tại | Cần version mới |

**Quy trình 409 (edit) chuẩn:**

```
PUT → 409 "Policy was modified by someone else"
  ↓
showConflictDialog()
  ├─ [Giữ thay đổi của tôi & tải lại]  → refetch() → user tự merge & gửi lại
  └─ [Huỷ]                          → đóng dialog, giữ input
  ↓
TUYỆT ĐỐI KHÔNG: tự động lấy updated_at mới rồi PUT lại
```

### 5.5 400 — Policy không hợp lệ

```json
{
  "detail": {
    "message": "Policy is invalid",
    "problems": [
      "rule 0: field must be one of ['average_login_interval_seconds', ...]",
      "weights.rule + weights.ml must equal 1.0"
    ]
  }
}
```

⇒ UI hiển thị **danh sách** `problems[]`, không phải một chuỗi. Validate client trước để bắt lỗi sớm, nhưng **backend vẫn là nguồn chân lý**.

### 5.6 Field server-owned — không được gửi

`extra="forbid"` + khai báo tường minh ⇒ gửi field này sẽ nhận **400** với tên field cụ thể:

`is_active` · `created_by` · `created_at` · `updated_at` · `activated_at` · `deactivated_at`

⇒ **Frontend không bao giờ** gửi các field này trong body create/edit. Form state phải tách rõ: `formValues` (gửi đi) vs `policy` (metadata server, chỉ đọc).

### 5.7 Validate client (bắt lỗi trước khi gửi)

| Quy tắc | Nguồn (`app/schemas.py`) |
|---|---|
| `version` pattern `^v\d+(\.\d+)*$` | `PolicyCreateRequest.version` |
| `rules` ≥ 1 | `Field(..., min_length=1)` |
| `name` ≤ 255 | `Field(..., max_length=255)` |
| `rule.name` 1..100 | `RuleDefinition.name` |
| `rule.field` ∈ 6 features | `ALLOWED_FEATURE_FIELDS` |
| `rule.operator` ∈ 9 toán tử | `ALLOWED_OPERATORS` |
| `rule.weight`, `rule.score` ∈ [0,1] | `ge=0.0, le=1.0` |
| `between`/`not_between` ⇒ value là mảng **2 số** | `RANGE_OPERATORS` |
| `in` ⇒ value là mảng **không rỗng** | validator `operator == "in"` |
| toán tử khác ⇒ value là **đơn** (mảng bị từ chối) | validator `isinstance(value, list)` |
| `weights.rule + weights.ml == 1.0` (nếu cả hai > 0) | `PolicyWeights.check_sum` |
| `thresholds.low ≤ medium ≤ high`, mỗi cái ∈ [0,1] | `PolicyThresholds.check_order` |
| tên rule **không trùng** | `PolicyCreate.check_unique_names` |

**6 features** (`ALLOWED_FEATURE_FIELDS`):
`hour_of_day` · `fail_count_24h` · `ip_change_rate_7d` · `new_device` · `average_login_interval_seconds` · `deviation_score`

**9 toán tử** (`ALLOWED_OPERATORS`):
`==` · `!=` · `>` · `>=` · `<` · `<=` · `in` · `between` · `not_between`

---

## 6. Manager Analytics — degraded states

### 6.1 Ba khái niệm phải phân biệt

| Khái niệm | Nghĩa | HTTP | Body |
|---|---|---|---|
| **OK** | Mọi source dùng đều sẵn sàng | 200 | Envelope chuẩn, `degraded: false` |
| **Degraded** | ≥1 source unavailable, **nhưng còn source khác** | **200** | Envelope chuẩn, `degraded: true` |
| **Unavailable** | **Tất cả** source mà endpoint dùng đều unavailable | **503** | `{detail, sources}` — **không có envelope** |

> **Điểm dễ sai:** degraded trả **200**, không phải 503. Frontend không được coi `degraded: true` là lỗi HTTP.

### 6.2 Envelope

```ts
interface ManagerEnvelope {
  generated_at: string;                    // ISO-8601 UTC
  window: { from: string; to: string };
  degraded: boolean;
  sources: Record<string, {
    status: "ok" | "unavailable";
    detail: string | null;                 // reason code khi unavailable
  }>;
}
```

### 6.3 Source ↔ endpoint

| Endpoint | Sources dùng | Hành vi khi 1 source fail | Default window |
|---|---|---|---|
| `/manager/dashboard` | `core`, `detection`, `ml` | **degraded 200** (section của source đó = `null`) | 24h |
| `/manager/trends` | `detection`, `ml` | **degraded 200** (series của source đó = `null`) | 14 ngày, `bucket=auto` |
| `/manager/alerts` | `detection` | **503** (chỉ 1 source) | 30 ngày |
| `/manager/soc-kpi` | `detection` | **503** (chỉ 1 source) | 30 ngày |
| `/manager/ml-stats` | `ml` | **503** (chỉ 1 source) | 30 ngày |

### 6.4 Reason codes (closed vocabulary)

| Code | Nghĩa | Nhãn UI đề xuất |
|---|---|---|
| `not_configured` | Service chưa cấu hình secret | "Chưa cấu hình kết nối nội bộ" |
| `timeout` | Timeout | "Nguồn dữ liệu không phản hồi (timeout)" |
| `unreachable` | Không kết nối được | "Không kết nối được tới nguồn dữ liệu" |
| `invalid_payload` | Response không phải JSON hợp lệ | "Nguồn dữ liệu trả về dữ liệu không hợp lệ" |
| `database_error` | Lỗi truy vấn DB | "Lỗi cơ sở dữ liệu" |
| `internal_error` | Lỗi nội bộ | "Lỗi hệ thống" |

⇒ **Không** hard-code chuỗi tự do; dùng bảng tra cứu `REASON_LABEL: Record<SourceReasonCode, string>`.

### 6.5 Nullable — `null` ≠ `0`

Đây là **quy tắc quan trọng nhất** của Manager UI:

| Tình huống | Giá trị | UI phải hiển thị |
|---|---|---|
| Population rỗng (không có dữ liệu trong window) | `null` | "—" + tooltip "Không có dữ liệu trong khoảng thời gian này" |
| Source down | `null` + `sources[x].status === 'unavailable'` | "—" + tooltip "Nguồn dữ liệu không khả dụng: {reason}" |
| Có dữ liệu, giá trị bằng 0 | `0` | **`0`** (hiển thị bình thường) |

⇒ **Không** dùng `value ?? 0`. Phải dùng `value ?? '—'` và kiểm tra `sources` để phân biệt 2 nguyên nhân.

**Section có thể `null`:**

| Response | Field | Nguồn |
|---|---|---|
| `ManagerDashboardResponse` | `core` | `core` |
| | `detection` | `detection` |
| | `ml` | `ml` |
| `ManagerTrendsResponse` | `series.login_attempts` | `detection` |
| | `series.alerts` | `detection` |
| | `series.ml` | `ml` |
| `ManagerMlStatsResponse` | `model` | `ml` |
| `DashboardDetection` | `enforcement`, `ml_fallback`, `policy` | tuỳ chọn |
| `DashboardCore` | `audit_activity` | tuỳ chọn |

### 6.6 400 — window / filter không hợp lệ

| Case | Message | UI |
|---|---|---|
| `from` ≥ `to` | `'from' must be strictly earlier than 'to'` | Inline ở `WindowPicker` |
| `bucket` không hợp lệ | (message của backend) | Disable option không hợp lệ ở dropdown |
| `status` không hợp lệ (`/manager/alerts`) | (message của backend) | Reset filter + toast |

> `parse_window_query` là **dependency** ⇒ chạy **trước** validation của FastAPI ⇒ 400 thắng 422 cho các case window sai.

### 6.7 Chiến lược render

```tsx
// SourceStatusBanner — hiển thị khi degraded
if (data.degraded) {
  const down = Object.entries(data.sources)
    .filter(([, s]) => s.status === "unavailable")
    .map(([name, s]) => `${name} (${REASON_LABEL[s.detail ?? 'internal_error']})`);
  return <Banner tone="warning">Một số nguồn dữ liệu không khả dụng: {down.join(", ")}</Banner>;
}
```

```tsx
// Section render — null ≠ 0
function Section({ title, value, source, children }) {
  if (value == null) {
    return (
      <Card>
        <h3>{title}</h3>
        <EmptyState
          message="Không có dữ liệu"
          hint={sourceDown ? "Nguồn dữ liệu không khả dụng" : "Không có dữ liệu trong khoảng thời gian này"}
        />
      </Card>
    );
  }
  return <Card><h3>{title}</h3>{children}</Card>;
}
```

---

## 7. CORS cho Vite development

### 7.1 Quy tắc backend (`app/cors_config.py`)

| Quy tắc | Hệ quả |
|---|---|
| Wildcard `*` bị **từ chối lúc startup** | `CORSConfigurationError` → app không khởi động |
| Entry phải là **origin đầy đủ** `scheme://host[:port]` | `localhost:5173` (thiếu scheme) → startup error |
| Không có path / query / fragment | `http://localhost:5173/app` → startup error |
| Trailing slash được **strip** | `http://localhost:5173/` → OK |
| Default khi env **vắng mặt** | `http://localhost:8000,http://127.0.0.1:8000` |
| Env rỗng (chỉ whitespace) → dùng default | `CORS_ALLOWED_ORIGINS=""` → default |
| Env set nhưng không có origin hợp lệ nào | startup error |
| `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]` | `Authorization`, `Content-Type` OK |
| `allow_origins` rỗng → **không** cài middleware | same-origin only |

> ⚠️ **Điều kiện quan trọng:** `resolve_cors_origins()` được gọi ở **module level** trong `app/main.py` (dòng ~107). Nghĩa là biến env phải được set **trước khi** import `app.main` (ví dụ trong `.env` được load, hoặc export trước khi chạy uvicorn). Đổi env sau khi app đã start **không có tác dụng**.

### 7.2 Hai cách chạy dev

| | **A. Vite proxy** (khuyến nghị) | **B. CORS trực tiếp** |
|---|---|---|
| Config | `vite.config.ts` → `server.proxy['/api']` | `VITE_API_BASE_URL=http://localhost:8000` |
| CORS | Không có (same-origin qua proxy) | Cần thêm origin Vite vào allow-list |
| `CORS_ALLOWED_ORIGINS` | Không cần đổi | **Bắt buộc** thêm `http://localhost:5173` |
| Ưu điểm | Đơn giản, không phụ thuộc config CORS, giống production sau reverse proxy | Test đúng hành vi CORS thật |
| Nhược điểm | Không test được preflight | Phải sửa `.env` backend + restart |

**Cấu hình A:**

```ts
// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
      "/ready": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
```

```ts
// src/lib/api/client.ts
baseURL: import.meta.env.VITE_API_BASE_URL ?? ""   // rỗng → dùng proxy
```

**Cấu hình B:**

```bash
# backend .env
CORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173
```

```ts
baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
```

### 7.3 Triệu chứng thường gặp

| Triệu chứng | Nguyên nhân | Khắc phục |
|---|---|---|
| Console: *"has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header"* | Thiếu origin trong allow-list | Thêm origin Vite vào `CORS_ALLOWED_ORIGINS` + restart backend |
| Console: *"Response to preflight request doesn't pass access control check"* | Preflight `OPTIONS` bị chặn | Kiểm tra `allow_methods`/`allow_headers` (đã là `*`) và origin trong allow-list |
| 401 mọi request | Header `Authorization` bị chặn | Kiểm tra origin có trong allow-list không (nếu origin không được allow thì browser **không gửi** header) |
| Backend không khởi động, log `CORSConfigurationError` | `CORS_ALLOWED_ORIGINS` sai format | Bỏ wildcard; thêm scheme; bỏ path |
| Đổi `.env` không có tác dụng | Env được đọc ở module level | **Restart** backend |

---

## 8. Xử lý HTTP error — bảng tổng hợp

### 8.1 Bảng status → hành động

| Status | Nguyên nhân chung | Hành động frontend |
|---|---|---|
| **400** | Request hợp lệ về cú pháp nhưng ngữ nghĩa sai (window sai, filter sai, transition sai, policy invalid, action không hợp lệ) | **Hiển thị message backend nguyên văn**. Với policy → hiển thị danh sách `problems[]`. Với transition → refetch entity. |
| **401** | Token thiếu / sai / hết hạn / bị revoke | Nếu là endpoint protected: thử refresh (mutex) → retry 1 lần. Nếu refresh fail: clear + về `/login`. Nếu là endpoint public (login/mfa): hiển thị message cụ thể. |
| **403** | Token hợp lệ nhưng thiếu role (`Insufficient permissions`), hoặc MFA IP mismatch, hoặc device IP/fingerprint mismatch | **403 do thiếu role** → "Bạn không có quyền thực hiện thao tác này" + link về trang phù hợp. **403 do IP mismatch** → message cụ thể (không phải "không có quyền"). Phân biệt bằng `detail`. |
| **404** | Resource không tồn tại hoặc không thuộc phạm vi user | "Không tìm thấy" + nút về trang danh sách. |
| **409** | Conflict: version trùng (create), policy immutable, policy bị sửa bởi người khác, MFA transaction đã dùng, device approval chờ | Xử lý **theo từng ngữ cảnh** (xem §5.4 và §1.4). Không có hành động chung. |
| **410** | Trusted-device request đã hết hạn / không còn hợp lệ | "Yêu cầu đã hết hạn, hãy thử lại" |
| **422** | FastAPI validation: type sai, thiếu field, pattern sai, query ngoài khoảng | Map `detail[]` (`loc` + `msg`) vào field tương ứng. Hiển thị inline. |
| **423** | Account bị khoá | "Tài khoản đã bị khoá. Liên hệ quản trị." |
| **429** | Rate limit (login 5/min/IP; device approval 5/min/IP) | "Quá nhiều lần thử. Vui lòng thử lại sau {n} giây." Disable nút submit. |
| **502** | Protective action không được Core áp dụng | **KHÔNG hiển thị success.** "Hành động KHÔNG được áp dụng." + refetch timeline. |
| **503** | Manager: tất cả source unavailable; hoặc internal secret chưa cấu hình | Manager: hiển thị degraded state đầy đủ (sources + reason). Nội bộ: thông báo "dịch vụ tạm thời không khả dụng". |
| **500** | Lỗi ngoài dự kiến | Error page + `request_id` nếu có. Log kỹ thuật ở console (dev). |

### 8.2 Phân tích `detail` — 4 dạng

```ts
export type ApiErrorDetail =
  | string                                                      // dạng phổ biến nhất
  | { message: string; problems?: string[] }                     // policy
  | Array<{ loc: (string | number)[]; msg: string; type: string }>  // 422
  | { detail: string; sources?: Record<string, {status: string; detail: string|null}> }; // manager 503
```

```ts
export function parseDetail(detail: ApiErrorDetail) {
  if (typeof detail === "string") return { message: detail, problems: [] as string[], fields: {} };
  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const e of detail) {
      const field = e.loc.filter((x) => x !== "body").join(".");
      fields[field] = e.msg;
    }
    return { message: "Dữ liệu không hợp lệ", problems: Object.values(fields), fields };
  }
  if ("message" in detail) {
    return { message: detail.message, problems: detail.problems ?? [], fields: {} };
  }
  return { message: "Dịch vụ không khả dụng", problems: [], fields: {} };
}
```

### 8.3 Ma trận status × endpoint

| Endpoint | 400 | 401 | 403 | 404 | 409 | 410 | 422 | 423 | 429 | 502 | 503 |
|---| :-:| :-:| :-:| :-:| :-:| :-:| :-:| :-:| :-:| :-:||
| `POST /auth/login` |  | ✓ |  |  |  |  |  | ✓ | ✓ |  |  |
| `POST /auth/mfa/verify` |  | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |
| `POST /auth/refresh` |  | ✓ |  |  |  |  |  |  |  |  |  |
| `GET /auth/me` |  | ✓ |  |  |  |  |  |  |  |  |  |
| `POST /auth/logout` |  | ✓ |  |  |  |  |  |  |  |  |  |
| `POST /auth/logout-all` |  | ✓ |  |  |  |  |  |  |  |  |  |
| `GET /auth/sessions` |  | ✓ |  |  |  |  |  |  |  |  |  |
| `DELETE /auth/sessions/{session_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `POST /devices` |  | ✓ | ✓ |  |  |  |  |  |  |  |  |
| `DELETE /devices/{device_id}` |  | ✓ |  | ✓ |  |  |  |  |  |  |  |
| `DELETE /devices/all` |  | ✓ |  |  |  |  |  |  |  |  |  |
| `POST /devices/check` |  |  |  |  |  |  |  |  |  |  |  |
| `POST /devices/pending` | ✓ | ✓ |  |  | ✓ |  |  | ✓ | ✓ |  |  |
| `POST /devices/pending/{request_id}/approve` |  | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| `POST /devices/pending/{request_id}/complete` |  | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |
| `GET /admin/users` |  | ✓ | ✓ |  |  |  |  |  |  |  |  |
| `POST /admin/users/{user_id}/roles` |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |
| `DELETE /admin/users/{user_id}/roles/{role_id}` |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |
| `POST /admin/users/{user_id}/lock` |  | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |
| `DELETE /admin/users/{user_id}/lock` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `PUT /admin/users/{user_id}/mfa` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `GET /admin/audit-logs` |  | ✓ | ✓ |  |  |  |  |  |  |  |  |
| `GET /alerts` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| `GET /alerts/{alert_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `GET /alerts/{alert_id}/evidence` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `GET /alerts/{alert_id}/timeline` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `POST /alerts/{alert_id}/timeline` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `POST /alerts/{alert_id}/acknowledge` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `POST /alerts/{alert_id}/resolve` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `POST /alerts/{alert_id}/assign` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `POST /alerts/{alert_id}/actions` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |
| `GET /login-attempts` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| `GET /policies` |  | ✓ | ✓ |  |  |  |  |  |  |  |  |
| `GET /policies/{policy_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `POST /policies` | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |  |
| `PUT /policies/{policy_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |
| `POST /policies/{policy_id}/activate` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| `GET /manager/*` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |

> **Nguồn:** sinh tự động bằng `scripts/extract_route_contracts.py` (AST scan của source backend) + `require_roles` allow-list. Cột `401` = từ auth dependency (`get_current_auth_context`); cột `403` = từ `require_roles` hoặc từ body của route.
> Endpoint `POST /policies` trả **409** khi version đã tồn tại; `PUT /policies/{id}` trả **409** cho cả 3 biến thể (immutable / đã từng active / bị sửa bởi người khác).

---



## 10. Thứ tự tích hợp cho Cursor

9 giai đoạn, mỗi giai đoạn **độc lập chạy được** và **verify được**. Không nên làm song song 2 giai đoạn sau.

### Stage 0 — Nền tảng dự án (chưa cần API)

| Hạng mục | Nội dung |
|---|---|
| Scaffold | Vite + React 19 + TypeScript strict |
| Cấu hình | `vite.config.ts` (proxy `/api`), `tsconfig.json`, Tailwind config |
| Tokens | `src/styles/index.css` với `@theme` (ánh xạ từ Stitch hoặc tạm dùng giá trị mặc định §3.3) |
| Cấu trúc thư mục | Tạo toàn bộ skeleton `src/` theo [M12-ARCHITECTURE.md §2](./M12-ARCHITECTURE.md) |
| `shared/components` | `Button`, `TextInput`, `Select`, `Card`, `Badge`, `Table`, `Dialog`, `Banner`, `EmptyState`, `ErrorState`, `Spinner`, `Pagination`, `Tabs`, `Toast` |
| Router | `createBrowserRouter` với route table + `RequireAuth` / `RequireRole` (chưa nối API) |

**Verify:** `npm run dev` mở được, điều hướng giữa các route trống, Tailwind áp dụng đúng token.
**Không:** chưa gọi API nào.

---

### Stage 1 — Auth lõi (chưa có refresh)

| Hạng mục | Nội dung |
|---|---|
| Hạ tầng | `src/lib/api/client.ts` (axios instance, request interceptor gắn Bearer) · `src/lib/api/endpoints.ts` · `src/lib/errors.ts` (`ApiError`, `parseDetail`) · `src/lib/enums.ts` · `src/lib/datetime.ts` |
| Types | `UserItem`, `LoginResponse`, `MfaVerifyResponse`, `SessionList`, `UserRole` |
| Store | `src/lib/session.ts` — module-level `accessToken` / `refreshToken` / `mfaSessionId` |
| Provider | `src/app/providers/AuthProvider.tsx` — `status`, `user`, `roles`, `login()`, `verifyMfa()`, `logout()` |
| Screens | S-01 Register, S-02 Login, S-03 MFA Verify |
| Endpoints | `POST /auth/register`, `POST /auth/login`, `POST /auth/mfa/verify`, `GET /auth/me` |

**Verify:**
- Login sai → 401 hiển thị đúng message.
- Login đúng (không MFA) → vào app, `GET /auth/me` trả roles.
- Login đúng (có MFA) → `access_token` rỗng ⇒ **không** coi là đăng nhập; sang `/mfa`.
- MFA sai 3 lần → 401, báo "đã quá số lần thử".
- Reload → về `/login` với thông báo nhẹ.

---

### Stage 2 — Refresh token + session management

| Hạng mục | Nội dung |
|---|---|
| Interceptor | Response interceptor 401 → refresh (mutex) → retry 1 lần → fail thì clear + về `/login?redirect=` |
| Screens | S-05 Sessions, S-07 Profile, S-08 Forbidden |
| Endpoints | `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all`, `GET /auth/sessions`, `DELETE /auth/sessions/{id}` |

**Verify:**
- Để access token hết hạn (chờ 1h **hoặc** ép `expires_at`) → request tự refresh và thành công.
- 3 request song song cùng gặp 401 → **chỉ 1** `/refresh` bay, không logout oan.
- Logout → token cũ 401.
- Logout-all → mọi token 401.

---

### Stage 3 — Trusted Devices

| Hạng mục | Nội dung |
|---|---|
| Screens | S-04 Trusted-device Login, S-06 Trusted Devices |
| Endpoints | `GET/POST /devices`, `DELETE /devices/{id}`, `DELETE /devices/all`, `POST /devices/check`, `POST /devices/pending`, `POST /devices/pending/{id}/approve`, `POST /devices/pending/{id}/complete` |

**Verify:** trust → list hiện; untrust all → list rỗng; pending → complete nhận token thật.

---

### Stage 4 — SOC Alerts (phần lõi)

| Hạng mục | Nội dung |
|---|---|
| Screens | S-20 Alert Queue, S-21 Alert Detail |
| Components | `AlertTable`, `AlertFilters`, `RiskBadge`, `StatusBadge`, `TimelineFeed`, `EvidencePanel`, `DetectionLogTable` |
| Endpoints | `GET /alerts`, `GET /alerts/{id}`, `GET /alerts/{id}/evidence`, `GET /alerts/{id}/timeline` |

**Verify:** filter theo status/risk_level; tab evidence/timeline đổ dữ liệu đúng; phân trang đúng `total`.

---

### Stage 5 — SOC hành động (mutations)

| Hạng mục | Nội dung |
|---|---|
| Dialogs | `AcknowledgeDialog`, `ResolveDialog`, `AssignDialog`, `ProtectiveActionDialog`, `AddNoteForm` |
| Endpoints | `POST /alerts/{id}/acknowledge`, `/resolve`, `/assign`, `/actions`, `POST /alerts/{id}/timeline` |
| Screens (bổ sung) | S-22 Login History (`GET /login-attempts`) |

**Verify (quan trọng):**
- Acknowledge trên alert đã `acknowledged` → nút disabled; gọi tay → 400 hiển thị nguyên văn.
- Protective action trả **502** → hiển thị "KHÔNG được áp dụng" + timeline có event `note_added`.
- Assign với UUID không tồn tại → 400 `assigned_to_id must reference an existing active SOC analyst`.

---

### Stage 6 — Admin (IAM)

| Hạng mục | Nội dung |
|---|---|
| Screens | S-10 User Management, S-11 Audit Logs |
| Components | `UserTable`, `AssignRoleDialog`, `LockUserDialog`, `ToggleMfaSwitch`, `AuditLogTable`, `AuditDetailDrawer`, `JsonViewer` |
| Endpoints | `GET /admin/users`, `POST/DELETE /admin/users/{id}/roles`, `POST/DELETE /admin/users/{id}/lock`, `PUT /admin/users/{id}/mfa`, `GET /admin/audit-logs` |

**Verify:** gỡ role `USER` → nút disabled (backend 400 nếu gọi tay); khoá user → status badge đổi; audit drawer hiển thị JSON.

---

### Stage 7 — Policies

| Hạng mục | Nội dung |
|---|---|
| Screens | S-30 Policy List, S-31 Policy Detail, S-32 Policy Editor |
| Components | `PolicyTable`, `PolicyForm`, `RuleBuilder`, `WeightsEditor`, `ThresholdsEditor`, `ValueEditor`, `ActivateDialog`, `ImmutabilityBanner`, `ConflictDialog` |
| Endpoints | `GET /policies`, `GET /policies/{id}`, `POST /policies`, `PUT /policies/{id}`, `POST /policies/{id}/activate` |

**Verify (quan trọng nhất):**
1. Tạo policy → 201, list cập nhật.
2. Sửa policy → 200, `updated_at` mới đúng.
3. **Sửa policy từ 2 tab** → tab A lưu trước, tab B lưu sau ⇒ tab B nhận **409** "modified by someone else" ⇒ **refetch**, **không** auto-overwrite.
4. Activate policy → policy cũ mất active; `PUT` vào policy đã activate ⇒ **409** "Policy is immutable" ⇒ hiện banner + ẩn nút lưu.
5. Policy có `rules` sai ⇒ **400** với danh sách `problems[]` hiển thị đầy đủ.
6. **Timestamp:** đọc `updated_at` từ `GET /detail`, gửi lại nguyên văn ⇒ **không** 409 giả.
7. Gửi field server-owned (`is_active`) ⇒ 400 với tên field.

---

### Stage 8 — Manager Analytics

| Hạng mục | Nội dung |
|---|---|
| Screens | S-40 Dashboard, S-41 Trends, S-42 Alert Analytics, S-43 SOC KPI, S-44 ML Stats |
| Components | `SourceStatusBanner`, `KpiCard` (nullable-aware), `WindowPicker`, `BucketSelector`, `TrendChart`, `DefinitionTooltip` |
| Endpoints | `GET /manager/dashboard`, `/trends`, `/alerts`, `/soc-kpi`, `/ml-stats` |

**Verify (quan trọng nhất):**
1. `degraded: true` (200) → hiện banner, section `null` → "Không có dữ liệu" (**không** phải `0`).
2. 503 → hiện degraded state đầy đủ với `sources` + reason code, **không** phải error page chung.
3. KPI `null` → "—" + tooltip phân biệt "population rỗng" vs "source down" (kiểm tra `sources[x].status`).
4. Đổi window sai (`from ≥ to`) → 400 hiển thị message.
5. `bucket=auto` → chart dùng `bucket` đã resolve từ response.

---

### 10.1 Thứ tự ưu tiên nếu thiếu thời gian

| Ưu tiên | Stage | Lý do |
|---|---|---|
| **P0** | 0, 1, 2 | Không có auth thì không màn hình nào chạy được |
| **P0** | 7 (Policies) | F-1 là feature mới nhất, rủi ro timestamp cao nhất |
| **P1** | 4, 5 (Alerts) | Giá trị demo cao (SOC workflow) |
| **P1** | 8 (Manager) | Giá trị demo cao (nhiều biểu đồ) |
| **P2** | 3 (Devices) | Tính năng bảo mật nhưng không phải trọng tâm demo |
| **P2** | 6 (Admin) | IAM demo đơn giản |

---

## 11. Acceptance criteria cho frontend

### 11.1 Tiêu chí bắt buộc (Must) — theo vai trò

| # | Vai trò | Tiêu chí |
|---|---|---|
| AC-01 | Tất cả | Đăng nhập thành công → vào đúng landing page theo vai trò; menu hiển thị đúng mục cho vai trò |
| AC-02 | Tất cả | `GET /auth/me` là nguồn duy nhất của `roles`; **không** decode token |
| AC-03 | Tất cả | Access token hết hạn → refresh tự động, user **không** bị logout oan khi có nhiều request đồng thời |
| AC-04 | Tất cả | Reload trang → quay lại `/login` với thông báo thân thiện (không error đỏ) |
| AC-05 | Tất cả | Token **không** được ghi vào `localStorage` / `sessionStorage` / `document.cookie` |
| AC-06 | Tất cả | `INTERNAL_SECRET` **không** xuất hiện trong bất kỳ biến `VITE_*` nào, không xuất hiện trong bundle |
| AC-07 | USER | Xem được danh sách phiên, thu hồi được phiên, đăng xuất mọi nơi |
| AC-08 | USER | Xem/thêm/bỏ tin cậy thiết bị; "Bỏ tin cậy tất cả" có xác nhận |
| AC-09 | USER | Truy cập `/admin/*` hoặc `/manager/*` → bị chuyển `/403`, **không** gọi API bị cấm |
| AC-10 | SOC_ANALYST | Xem được queue cảnh báo, lọc theo status/risk_level, phân trang đúng `total` |
| AC-11 | SOC_ANALYST | Acknowledge chỉ khả dụng khi `status === 'open'`; Resolve chỉ khi `status ∈ {open, acknowledged}` |
| AC-12 | SOC_ANALYST | Protective action trả 502 ⇒ UI hiển thị "KHÔNG được áp dụng"; **không** hiển thị success |
| AC-13 | SOC_ANALYST | Mọi hành động trên alert ghi vào timeline và timeline tự refresh sau mutation |
| AC-14 | SOC_ANALYST | Xem được lịch sử đăng nhập với đủ filter (username, IP, outcome, risk_level, khoảng thời gian) |
| AC-15 | SECURITY_ADMIN | Quản lý được user: gán/gỡ role, khoá/mở khoá, bật/tắt MFA bắt buộc |
| AC-16 | SECURITY_ADMIN | Không cho gỡ role `USER` (nút disabled) |
| AC-17 | SECURITY_ADMIN | Xem được audit log, lọc theo actor/action/resource/thời gian, xem được `before_state`/`after_state` dạng JSON |
| AC-18 | SECURITY_ADMIN | Tạo được policy; `rules` ≥ 1; validate 6 features / 9 toán tử / weights sum = 1 / thresholds tăng dần |
| AC-19 | SECURITY_ADMIN | Sửa policy **không** bao giờ gặp 409 do mất microsecond (timestamp giữ nguyên văn) |
| AC-20 | SECURITY_ADMIN | 409 "modified by someone else" ⇒ refetch + thông báo; **không** tự động ghi đè |
| AC-21 | SECURITY_ADMIN | 409 "Policy is immutable" ⇒ hiện banner + ẩn nút lưu + CTA "Tạo version mới" |
| AC-22 | SECURITY_ADMIN | Activate policy ⇒ policy cũ mất trạng thái active, list cập nhật |
| AC-23 | SECURITY_ADMIN | Form **không** gửi field server-owned (`is_active`, `created_by`, timestamps) |
| AC-24 | SECURITY_MANAGER | Xem được 5 màn hình Manager; mỗi màn hình có `WindowPicker` và hiển thị window đã resolve |
| AC-25 | SECURITY_MANAGER | `degraded: true` (HTTP 200) ⇒ hiện cảnh báo theo `sources` + reason code |
| AC-26 | SECURITY_MANAGER | HTTP 503 ⇒ hiển thị degraded state đầy đủ, **không** phải error page chung |
| AC-27 | SECURITY_MANAGER | Giá trị `null` hiển thị "—", **không** bao giờ hiển thị `0` |
| AC-28 | SECURITY_MANAGER | Biểu đồ render đúng với series `null` (placeholder, không crash) |

### 11.2 Tiêu chí chất lượng kỹ thuật

| # | Tiêu chí |
|---|---|
| QC-01 | `tsc --noEmit` không lỗi; `strict: true` |
| QC-02 | ESLint + Prettier pass, không warning |
| QC-03 | Test coverage ≥ 80% cho `src/lib/` và `src/features/*/api/` |
| QC-04 | Có test cho: 3 biến thể 409 policy · 502 action · 503 manager · `mfa_required:true` · refresh song song · `null` vs `0` |
| QC-05 | Bundle gzipped ≤ 400 KB (Recharts là phần lớn) |
| QC-06 | Không có console.error khi render màn hình bình thường |
| QC-07 | Mọi màn hình có loading state (skeleton) và empty state |
| QC-08 | Không request nào tới `/api/v1/internal/*` (kiểm tra bằng test hoặc grep trong `endpoints.ts`) |
| QC-09 | Không có endpoint nào gọi tới path không tồn tại trong [M12-API-INVENTORY.md](./M12-API-INVENTORY.md) |
| QC-10 | Build production (`npm run build`) chạy qua, preview chạy được với `VITE_API_BASE_URL` đúng |

### 11.3 Tiêu chí tích hợp E2E

| # | Kịch bản E2E | Bước |
|---|---|---|
| E2E-01 | Login → dashboard → logout | 1 role bất kỳ |
| E2E-02 | Login có MFA → nhập OTP sai 3 lần → bị chặn | 1 |
| E2E-03 | Login → access hết hạn → tự refresh → vẫn ở trang | 1 |
| E2E-04 | USER mở `/admin/users` → bị chuyển `/403` | 1 |
| E2E-05 | Analyst acknowledge → resolve → timeline có 3 event | 1 |
| E2E-06 | Analyst yêu cầu protective action (Core không chạy) → thấy 502 | 1 |
| E2E-07 | Admin tạo policy → sửa → activate → sửa lại ⇒ 409 immutable | 1 |
| E2E-08 | Admin mở policy ở 2 tab, lưu tab A rồi tab B ⇒ 409 + refetch | 1 |
| E2E-09 | Manager mở dashboard khi Detection down ⇒ thấy degraded/503 | 1 |

### 11.4 Tiêu chí Stitch

| # | Tiêu chí |
|---|---|
| SC-01 | Đủ 24 screen trong project Stitch |
| SC-02 | Một design system duy nhất áp cho mọi screen |
| SC-03 | Mọi màu trong React dùng token ngữ nghĩa (`primary`/`success`/`warning`/`danger`/`muted`), không hex rời rạc |
| SC-04 | Không screen nào chứa giả lập logic API trong HTML sinh ra |

---

## 12. Câu trả lời trực tiếp cho các câu hỏi của stakeholder

| Câu hỏi | Trả lời |
|---|---|
| **Có bao nhiêu screens?** | **24** (chi tiết: [M12-PAGE-MAP.md §1](./M12-PAGE-MAP.md)) |
| **Screen nào dùng endpoint nào?** | Ma trận đầy đủ 24 screen × 46 endpoint: [M12-PAGE-MAP.md §5](./M12-PAGE-MAP.md) |
| **Backend có thiếu API bắt buộc nào không?** | **Không** thiếu API bắt buộc. 46 endpoint browser-callable đủ cho 24 screen. Gap G-1 (thiếu `GET /soc/analysts`) có workaround bằng UUID input. Chi tiết: [M12-API-INVENTORY.md §12](./M12-API-INVENTORY.md) |
| **Stitch cần thiết kế những gì?** | 24 screen + 1 design system, chia 7 batch theo ưu tiên. Chi tiết: [M12-STITCH-HANDOFF.md §4](./M12-STITCH-HANDOFF.md) |
| **Cursor nên tích hợp theo thứ tự nào?** | 9 stage (0→8), xem [M12-INTEGRATION-PLAN.md §10](./M12-INTEGRATION-PLAN.md). P0: stage 0, 1, 2, 7. |
| **Acceptance criteria?** | 28 tiêu chí chức năng (theo vai trò) + 10 tiêu chí kỹ thuật + 9 kịch bản E2E + 4 tiêu chí Stitch: [M12-INTEGRATION-PLAN.md §11](./M12-INTEGRATION-PLAN.md) |

---

## 13. Checklist hợp đồng tích hợp

### 13.1 Trước khi code

- [ ] `CORS_ALLOWED_ORIGINS` đã cấu hình (hoặc dùng Vite proxy).
- [ ] `INTERNAL_SECRET` ≥ 32 ký tự, không phải placeholder → **không** đưa vào frontend.
- [ ] Backend chạy ở `http://localhost:8000`, `GET /ready` trả `"ready"`.
- [ ] Đã seed user cho cả 4 vai trò.

### 13.2 Auth

- [ ] Không decode token.
- [ ] `mfa_required === true` → không lưu token rỗng.
- [ ] `mfaSessionId` lưu riêng, khác `session_id` của session thật.
- [ ] Refresh có mutex, thay **cả 2** token, retry tối đa 1 lần.
- [ ] Logout clear store dù API lỗi.
- [ ] Reload → yêu cầu đăng nhập lại, có thông báo thân thiện.

### 13.3 Alerts

- [ ] Acknowledge chỉ enable khi `status === 'open'`.
- [ ] Resolve chỉ enable khi `status ∈ {open, acknowledged}`.
- [ ] 502 protective action → **không** hiển thị success.
- [ ] 400 transition → refetch alert.
- [ ] Mọi mutation → invalidate `detail` + `list` + `timeline`.

### 13.4 Policies

- [ ] `updated_at` giữ dạng **string** xuyên suốt.
- [ ] **Không** `new Date()` / `toISOString()` / `date-fns` trước khi gửi.
- [ ] `expected_updated_at` lấy từ `GET /policies/{id}` **nguyên văn**.
- [ ] 409 → phân biệt 3 biến thể qua `detail.message`.
- [ ] 409 "modified by someone else" → refetch, **không** auto-overwrite.
- [ ] Không gửi field server-owned.
- [ ] Client validate: version pattern, rules ≥1, 6 features, 9 operators, weights sum = 1, thresholds tăng dần, tên rule unique.

### 13.5 Manager

- [ ] `degraded: true` vẫn là **200** — không coi là lỗi.
- [ ] 503 có body riêng `{detail, sources}` — parse riêng.
- [ ] `null` ⇒ hiển thị "—", **không** dùng `?? 0`.
- [ ] Reason code dùng bảng tra cứu đóng.
- [ ] Kiểm tra `sources[x].status` để phân biệt "population rỗng" vs "source down".

### 13.6 Chất lượng

- [ ] Test cho 409 ×3, 502, 503, `mfa_required:true`, refresh đồng thời.
- [ ] Không endpoint nào trong `endpoints.ts` gọi `/api/v1/internal/*`.
- [ ] Không biến `VITE_*` nào chứa secret.
