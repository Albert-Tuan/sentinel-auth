# M12 Stage 3 — Trusted Devices, Sessions & Profile

**Nhánh:** `feature/m12-frontend-foundation`
**Phạm vi:** Stage 3 của `docs/frontend/M12-INTEGRATION-PLAN.md` — S-04, S-05, S-06, S-07.
**Trạng thái:** hoàn tất. Đã commit trong `feat(frontend): implement authentication and user self-service flows`.

> **Cập nhật sau final review (Stage 0–3):** báo cáo này mô tả trạng thái
> *tại thời điểm Stage 3*. Các mục đã thay đổi trong final review được ghi
> rõ tại §11.

---

## 1. Tóm tắt

| Hạng mục | Kết quả |
|---|---|
| Types | `TrustedDeviceItem`, `TrustedDeviceList`, `TrustDeviceRequest/Response`, `PendingTrustedDeviceRequest/Response`, `TrustedDeviceApprovalResponse`, `DeviceTrustCheckResponse` |
| API layer | `src/lib/api/devices.api.ts` (7 endpoint), `revokeSession()` bổ sung vào `auth.api.ts` |
| Shared components | `Badge`, `DataTable`, `ConfirmDialog`, `Pagination` (mới); `Button` chuyển sang `forwardRef` |
| Screens | S-04 `/trusted-device`, S-05 `/sessions`, S-06 `/devices`, S-07 `/profile` |
| Router | `HomeRedirect`, `policy.ts` (nguồn quyền duy nhất), `paths.ts` + 2 route mới |
| Auth | `loginWithTokens()` — cài session nhận được từ luồng trusted-device ngoài handshake login |
| Unit/component tests | **82 passed** tại Stage 3 (9 file) — Stage 0–2 có 46, Stage 3 bổ sung **36** |
| Integration tests | **23 passed** (2 file) — 10 của Stage 0–2 + **13** mới cho Stage 3 |
| Backend regression | **729 passed, 60 skipped** — không đổi |

---

## 2. Vì sao `loginWithTokens()` là cần thiết

Luồng trusted-device hoàn toàn khác luồng login thường:

```
POST /devices/pending              → 202 { request_id }        (chưa có token)
POST /devices/pending/{id}/approve → 200 (thiết bị cũ đã đăng nhập)
POST /devices/pending/{id}/complete→ 200 { access_token, refresh_token, session_id }
```

Bước cuối trả về **token thật** — không có bước login/MFA nào ở giữa. Nếu tái sử dụng `login()` thì sẽ phải gửi lại username/password, hoàn toàn không cần thiết.

`loginWithTokens(access, refresh, sessionId)`:

1. Kiểm tra token không rỗng → nếu rỗng, `LOGIN_FAILURE` (không cài session).
2. `setSession(...)` — ghi vào token store **in-memory**.
3. `fetchCurrentUser()` — role **luôn** lấy từ `/auth/me`, không bao giờ đọc từ token.
4. Nếu `/auth/me` lỗi → `clearSession()` + `LOGIN_FAILURE`, không để lại session nửa vời.

---

## 3. Ba điểm dễ sai trong luồng pending, và cách xử lý

### 3.1 `409 still pending` KHÔNG phải lỗi

Đây là câu trả lời bình thường của backend khi yêu cầu chưa được duyệt. Nếu hiển thị như lỗi, người dùng sẽ tưởng đăng nhập thất bại trong khi thiết bị cũ chưa kịp bấm duyệt.

`TrustedDeviceLoginPage` phân biệt:

| Phản hồi | Hành vi |
|---|---|
| `200` + token thật | Cài session, đăng nhập |
| `409` chứa `still pending` | **Tiếp tục poll** sau 3s, không hiển thị lỗi |
| `409` khác (`Detection requires MFA`, `MFA is required`) | Dừng, hướng dẫn dùng luồng đăng nhập thường |
| `403` | "Yêu cầu bị từ chối" (IP/fingerprint không khớp) |
| `410` | Yê cầu hết hạn → thử lại |
| `200` nhưng token rỗng | **Không cài session**, báo lỗi rõ ràng |

Điểm nguy hiểm nhất là trường hợp cuối: một response 200 "thành công" nhưng token rỗng sẽ khiến app coi là đã đăng nhập. Test `never installs a session when the completion returns an empty token` khoá lại hành vi này.

### 3.2 Endpoint public không được đi qua refresh path

`POST /devices/pending` và `POST /devices/pending/{id}/complete` là endpoint **public** — người gọi chưa có session. Một 401 từ chúng có nghĩa là "sai mật khẩu" hoặc "chưa được duyệt", **không** phải "token hết hạn".

Nếu interceptor refresh được, nó sẽ gọi `/auth/refresh` với refresh token rỗng, nhận 401, xoá session, và báo "phiên đăng nhập không hợp lệ" — che mất nguyên nhân thật.

Cơ chế chặn (`src/lib/api/client.ts`):

```ts
const NO_REFRESH_PATHS = new Set<string>([
  ENDPOINTS.auth.login,
  ENDPOINTS.auth.mfaVerify,
  ENDPOINTS.auth.refresh,
  ENDPOINTS.auth.register,
  ENDPOINTS.devices.pending,
])

// Endpoint complete chứa request_id trong URL → không thể so khớp chính xác,
// nên so khớp theo prefix.
const NO_REFRESH_PREFIXES = ['/devices/pending/']
```

Ngoài ra các call public dùng cờ `_skipRefresh` để ý định rõ ràng tại call site.

### 3.3 Fingerprint phải khớp giữa `pending` và `complete`

Backend sinh fingerprint từ header (`User-Agent`, `Accept-Language`, `Accept-Encoding`) rồi hash. `complete` chỉ thành công khi fingerprint của request đó **giống hệt** request `pending`.

→ Khi test bằng `fetch` thô, phải gửi **cùng một bộ header** cho cả hai lệnh gọi. Test dùng `Accept-Language` khác nhau để mô phỏng thiết bị khác, và một test riêng khẳng định fingerprint lệch bị **403**.

---

## 4. Quyền theo path — sửa lỗi người dùng bị đưa tới 403 sau khi đăng nhập

> **Ghi chú (final review Stage 0–3):** Ở Stage 3, quyền theo path nằm trong
> `src/app/router/access.ts`. Ở final review, module đó **đã bị thay thế** bằng
> `src/app/router/policy.ts` — một bảng duy nhất làm nguồn quyền cho route
> guard, landing page, post-login redirect và navigation. Xem §11.1.

### Triệu chứng

Khi `RequireAuth` đuổi một người dùng ẩn danh ra khỏi một route bị chặn, nó ghi lại ý định đó vào `location.state.from`. Sau khi đăng nhập, `LoginPage` khôi phục đích đến đó.

Nếu tài khoản đăng nhập **không có role** cần thiết, người dùng bị đưa tới trang 403 — dù họ vừa đăng nhập thành công.

Quan sát thực tế trên trình duyệt: đăng nhập `m12analyst` (SOC_ANALYST) → rơi vào `/forbidden`.

### Nguyên nhân

Hai vấn đề riêng biệt:

**(a)** Không kiểm tra quyền trước khi khôi phục đích đến.

**(b)** Race giữa hai lần điều hướng. `LoginPage` gọi `navigate()` trong submit handler (đóng trên `auth` object **cũ**, roles rỗng → `landingPath` = `/`), đồng thời render `<Navigate>` khi context đã cập nhật (roles thật). Hai lần điều hướng cạnh tranh, kẻ thua có thể đưa người dùng tới sai trang.

### Cách sửa

**Sửa (a)** — `src/app/router/access.ts` (nay là `policy.ts`) trả lời "user này có được đưa tới path này không?":

```ts
const ACCESS_RULES: AccessRule[] = [
  { prefix: '/alerts',   roles: [SOC_ANALYST, SECURITY_MANAGER] },
  { prefix: '/policies', roles: [SECURITY_ADMIN, SECURITY_MANAGER] },
  { prefix: '/admin',    roles: [SECURITY_ADMIN] },
  { prefix: '/manager',  roles: [SECURITY_MANAGER] },
]
```

`resolvePostLoginPath(remembered, roles, landingPath)` giữ đích đến cũ **chỉ khi** role cho phép, nếu không thì rơi về landing page theo role.

So khớp dùng prefix có ranh giới (`/alerts` không khớp `/alertsomething`) và bỏ qua query string + hash.

**Sửa (b)** — chuyển toàn bộ logic redirect về **một chỗ duy nhất**: `<Navigate>` render khi context đã xác nhận `isAuthenticated`. Submit handler chỉ gọi `auth.login()` và trả kết quả.

```tsx
if (auth.isAuthenticated) {
  return (
    <Navigate
      to={resolvePostLoginPath(from, auth.roles, auth.landingPath)}
      replace
    />
  )
}
```

**Sửa (c)** — route `/` giờ dùng `HomeRedirect` thay vì `<Navigate to={PATHS.alerts}>` hard-code. `/` phải đưa người dùng tới trang khớp role của họ (analyst → `/alerts`, admin → `/admin/users`, manager → `/manager/dashboard`), không phải luôn `/alerts`.

### Kiểm chứng

- `access.test.ts` — 10 test: quyền theo path, prefix, query string, path rỗng, fallback.
  *(Ở final review, các test này được hợp nhất và mở rộng thành
  `policy.test.ts` — 35 test — xem §11.1.)*
- `homeRedirect.test.tsx` — 4 test: analyst → `/alerts`, admin → `/admin/users`, user thường không rơi vào 403, đích đến không thuộc quyền không được khôi phục.
  *(Ở final review: 12 test — xem §11.1.)*
- Trình duyệt: đăng nhập `m12analyst` → `/alerts`. Đăng nhập lại sau khi logout → `/alerts`. Không còn `/forbidden`.

---

## 5. Component dùng chung mới

### `ConfirmDialog`
Modal xác nhận cho hành động không thể hoàn tác. Focus chuyển vào nút xác nhận khi mở, Escape huỷ, nút bị disable khi mutation đang chạy (chặn double-click). `Button` phải chuyển sang `forwardRef` để làm được điều này.

### `DataTable`
Bảng cuộn ngang trên màn hình nhỏ thay vì xếp chồng thành card — các cột là một hợp đồng cố định do backend quy định, xếp chồng sẽ giấu mất header.

### `Badge` / `Pagination`
`Badge` mang ý nghĩa qua màu nhưng label luôn có chữ, không bao giờ chỉ dựa vào màu. `Pagination` chỉ đổi trang, không đổi `limit` (backend sở hữu page size).

---

## 6. Kiểm thử

### 6.1 Unit / component — 82 test

| File | Số test | Phủ |
|---|---|---|
| `features/devices/devices.test.tsx` | 12 | Liệt kê thiết bị, empty state, tin cậy thiết bị, chặn `remember_for_days` ngoài khoảng, confirm dialog, lỗi 403 từ backend, lỗi 500 không lộ chi tiết thô |
| `features/devices/trustedDeviceLogin.test.tsx` | 5 | Sai mật khẩu, MFA bắt buộc, poll 409→200, token rỗng, risk gate 409 |
| `features/profile/profile.test.tsx` | 2 | Thông tin tài khoản, cờ MFA bắt buộc |
| `app/router/access.test.ts` | 10 | Quyền theo path |
| `app/router/homeRedirect.test.tsx` | 4 | Redirect sau login |
| `features/auth/useAuth.test.tsx` | 15 | +3 cho `loginWithTokens` |
| `lib/api/client.test.ts` | 16 | Single-flight refresh, epoch guard |
| `app/router/guards.test.tsx` | 8 | RBAC, navigation theo role |
| `features/auth/pages/authPages.test.tsx` | 10 | Login, MFA, 403, 404 |

### 6.2 Integration HTTP thật — 23 test

`src/test/integration/realBackendDevices.test.ts` (13 test mới) chạy thẳng về FastAPI ở `127.0.0.1:8000`, không mock:

| Nhóm | Kết quả quan sát |
|---|---|
| Danh sách thiết bị | `total === devices.length`; backend tự lọc theo `ctx.user.id` |
| Tin cậy thiết bị | `POST /devices` → xuất hiện trong list, có `expires_at` |
| Gỡ một thiết bị | `DELETE /devices/{id}` → list rỗng |
| Gỡ tất cả | `DELETE /devices/all` → list rỗng |
| `/devices/check` không token | `{ trusted: false, reason: "No token" }` — **không** phải 401 |
| `/devices/check` token sai | 401, không làm hỏng flow |
| `remember_for_days: 400` | 422 validation từ backend |
| Danh sách phiên | Có đúng 1 `is_current: true` |
| Thu hồi phiên khác | Phiên bị thu hồi không còn xác thực được |
| **Handshake 3 bước** | `pending` (202) → `complete` (409 chưa duyệt) → `approve` (200) → `complete` (200) → token thật, `GET /auth/me` với token đó trả 200 |
| Handshake qua typed module | `requestTrustedDeviceApproval` → `approveTrustedDevice` → `completeTrustedDeviceLogin` — dùng đúng API layer mà UI dùng |
| Fingerprint lệch | `complete` với header khác → **403** `Trusted-device fingerprint does not match the request` |
| Sai mật khẩu | `POST /devices/pending` → 401, **không** kích hoạt refresh |

### 6.3 Kiểm chứng trên trình duyệt

| Bước | Kết quả quan sát |
|---|---|
| Đăng nhập `m12analyst` | → `/alerts`; sidebar hiện `m12analyst` · `SOC_ANALYST · USER` (đọc từ `/auth/me`) |
| `localStorage` / `sessionStorage` / `document.cookie` sau login | `[]` / `[]` / `""` — **không có token nào ngoài memory** |
| `/devices` | Bảng thiết bị tin cậy với dữ liệu thật từ backend (3 thiết bị do test tạo) |
| Tin cậy thiết bị mới | Thông báo `Device trusted until 2026-12-11`; thiết bị mới xuất hiện trong bảng |
| `/profile` | `m12analyst`, `m12analyst@example.com`, `SOC_ANALYST`, `USER`, `Đang hoạt động`, số lần đăng nhập thất bại `0` — tất cả từ `/auth/me` |
| `/trusted-device` | Nhập credential → `already_trusted` → "Thiết bị này đã được tin cậy. Vui lòng dùng luồng đăng nhập thường." |
| `/sessions` | Bảng phiên, badge "Phiên hiện tại", nút "Đăng xuất khỏi mọi thiết bị" |

### 6.4 Acceptance

| Lệnh | Kết quả |
|---|---|
| `npx tsc -b --force` | sạch |
| `npx eslint .` | sạch |
| `npm run test` | 82 passed / 9 file |
| `npm run test:integration` | 23 passed / 2 file |
| `npm run build` | ✓ built, `index.js` 312.91 kB (gzip 101.03 kB) |
| `pytest -q` (backend) | 729 passed, 60 skipped |

---

## 7. Ghi chú về hạ tầng test

**Rate limit.** Backend giới hạn 5 lần đăng nhập/phút mỗi IP, và `POST /devices/pending` có counter riêng (`trusted_device_approval`, 5/phút). Test integration xoá các dòng `rate_limits` trước mỗi test:

```sql
DELETE FROM rate_limits WHERE action IN ('login', 'trusted_device_approval')
```

Đây là housekeeping của test harness, không thay đổi hành vi ứng dụng.

**SMTP capture sink.** Test MFA cần đọc OTP thật từ email. Sink `aiosmtpd` ở `127.0.0.1:1025` ghi vào `/tmp/m12_otp_capture.log`. **Sink phải đang chạy** thì test MFA mới pass — nếu nó chết, log giữ lại OTP cũ đã hết hạn và test fail với 401 (không phải lỗi frontend). Khởi động lại:

```bash
nohup python3 /tmp/smtp_capture.py > /tmp/smtp_capture.log 2>&1 &
```

> **Ghi chú (final review Stage 0–3):** sink `aiosmtpd` ở trên là bản dùng
> tay trong lúc phát triển. CI dùng **sink chuẩn thư viện Python** đã được
> commit vào repo: `scripts/ci_smtp_sink.py` — không cần cài thêm dependency
> nào. Lệnh khởi động trong CI:
>
> ```bash
> nohup python scripts/ci_smtp_sink.py \
>   --host 127.0.0.1 --port 1025 --log /tmp/m12_otp_capture.log &
> ```

---

## 8. Rủi ro còn lại

| Rủi ro | Mức | Ghi chú |
|---|---|---|
| Bảng phiên không phân trang | Thấp | `GET /auth/sessions` trả mảng phẳng, không có `page`/`limit`. Backend giới hạn theo thời gian sống session; hiện tại người dùng test có ~100 phiên nên bảng rất dài. Khi backend thêm phân trang, `Pagination` đã sẵn sàng dùng. |
| Fingerprint phụ thuộc header trình duyệt | Trung bình | Backend sinh fingerprint từ `User-Agent`/`Accept-Language`/`Accept-Encoding`. Một số trình duyệt cắt bớt header có thể làm hai thiết bị khác nhau trùng fingerprint. Backend đã đây cả IP. Chưa có giải pháp client-side nào tốt hơn mà không phá hợp đồng. |
| `access.ts` phải đồng bộ với `routes.tsx` | Trung bình | Hai danh sách role đang tồn tại song song. Khi thêm nhánh role-restricted mới, **phải** thêm vào cả hai. Chưa có test chống drift. |
| *(Đã xử lý ở final review)* | — | Rủi ro "drift quyền" đã được **đóng** bằng `src/app/router/policy.ts` — một bảng quyền duy nhất, mọi consumer suy ra từ đó, kèm 35 test. Xem §11.1. |
| Endpoint `POST /devices/check` chưa dùng trong UI | Thấp | Đã có trong `devices.api.ts` và được test, nhưng chưa có màn hình nào gọi. Theo `M12-PAGE-MAP.md` nó thuộc S-02/S-03 — có thể dùng để tự động bỏ qua form login khi thiết bị đã tin cậy. |
| `S-21`/`S-31` cần `JsonViewer` | Thấp | Sẽ làm ở Stage 4+. |

---

## 9. Đề xuất bước tiếp theo

1. **Lead review** báo cáo này.
2. Commit + push `frontend/` lên `feature/m12-frontend-foundation` và mở PR vào `dev` (theo yêu cầu: không tự merge).
3. **Stage 4 — SOC Alerts (phần lõi)**: S-20 Alert Queue, S-21 Alert Detail, `GET /alerts`, `/alerts/{id}`, `/evidence`, `/timeline`.
4. **Stage 5 — SOC hành động**: acknowledge / resolve / assign / actions, S-22 Login History.
5. Cân nhắc bổ sung test chống drift giữa `access.ts` và `routes.tsx`.

---

## 10. Bản đồ file Stage 3

### Mới
```
src/lib/api/devices.api.ts                    7 endpoint trusted-device
src/lib/datetime.ts                           formatDateTime, describeUserAgent, isExpired
src/app/router/access.ts                      quyền theo path + resolvePostLoginPath
src/app/router/access.test.ts                 10 test
src/app/router/HomeRedirect.tsx               redirect `/` theo role
src/app/router/homeRedirect.test.tsx          4 test
src/shared/components/Badge.tsx
src/shared/components/ConfirmDialog.tsx
src/shared/components/DataTable.tsx
src/shared/components/Pagination.tsx
src/features/sessions/pages/SessionsPage.tsx S-05
src/features/devices/pages/TrustedDevicesPage.tsx    S-06
src/features/devices/pages/TrustedDeviceLoginPage.tsx S-04
src/features/profile/pages/ProfilePage.tsx   S-07
src/features/devices/devices.test.tsx        12 test
src/features/devices/trustedDeviceLogin.test.tsx 5 test
src/features/profile/profile.test.tsx        2 test
src/test/integration/realBackendDevices.test.ts 13 test HTTP thật
```

### Sửa
```
src/types/api.ts                    + contract TrustedDevice / PendingDevice / DeviceTrustCheck
src/lib/api/auth.api.ts             + revokeSession()
src/lib/api/client.ts               + NO_REFRESH_PREFIXES cho /devices/pending/
src/lib/api/endpoints.ts            (không đổi — đã đủ từ Stage 0)
src/app/router/paths.ts             + trustedDeviceLogin, profile
src/app/router/routes.tsx           + 4 route, HomeRedirect
src/app/layout/navigation.ts        + mục "Hồ sơ"
src/features/auth/useAuth.ts        + loginWithTokens()
src/features/auth/pages/LoginPage.tsx  redirect một nguồn + kiểm tra quyền đích đến
src/shared/components/Button.tsx    forwardRef
```

---

## 11. Final review Stage 0–3 — thay đổi so với Stage 3

Báo cáo này ban đầu mô tả trạng thái tại Stage 3. Mục §11 ghi lại
những thay đổi của đợt final review (nguồn: `docs/frontend/M12-STAGE-0-3-SECURITY-NOTES.md`).

### 11.1 Nguồn quyền duy nhất — `src/app/router/policy.ts`

`access.ts`, `routes.tsx` và `src/app/layout/navigation.ts` từng giữ **ba**
bản sao của cùng một danh sách role. Drift đo được: route table cho phép
**bất kỳ** user đã đăng nhập mở `/alerts`, trong khi sidebar và kiểm tra
access chỉ cho `SOC_ANALYST` / `SECURITY_MANAGER`.

`policy.ts` thay thế cả ba bằng **một** bảng `SECTIONS`. Mọi consumer suy
ra từ đó:

| Consumer | Hàm dùng |
|---|---|
| `RequireRole` | `sectionRoles(id)` |
| `HomeRedirect` | `landingPathFor(roles)` |
| `resolvePostLoginPath` | `canAccessPath(path, roles)` |
| Sidebar / mobile nav | `navigationFor(roles)` |

Bảng role map 1–1 với hợp đồng backend; frontend **không** nới quyền.

| Route | Roles |
|---|---|
| `/alerts` | `SOC_ANALYST` \| `SECURITY_MANAGER` |
| `/policies` | `SECURITY_ADMIN` \| `SECURITY_MANAGER` |
| `/admin/*` | `SECURITY_ADMIN` |
| `/manager/*` | `SECURITY_MANAGER` |
| `/sessions`, `/devices`, `/profile` | mọi user đã đăng nhập |

Landing path theo role: manager → `/manager/dashboard`, admin →
`/admin/users`, analyst → `/alerts`, user thường → `/sessions` (trước đây
rơi về `/`).

**Test:** `policy.test.ts` (35 test) + `homeRedirect.test.tsx` (12 test) +
`guards.test.tsx` (11 test) — phủ 4 role, deep link, remembered destination,
logout/login lại với role khác, và trường hợp không có route hợp lệ.

### 11.2 Rà soát trusted-device authentication

| Vấn đề | Kết quả |
|---|---|
| `complete` chỉ authenticated khi token hợp lệ | Đã có sẵn — `loginWithTokens` trả `false` khi token rỗng; `GET /auth/me` xác nhận session |
| `409 still pending` polling 3s | Đã có sẵn — poll mỗi 3.000 ms |
| Polling hủy khi unmount / logout / transaction hết hạn | Đã có sẵn + test |
| `401` public endpoint không kích hoạt refresh | **Đã sửa** — `NO_REFRESH_PUBLIC_PATHS` dùng regex `/^\/devices\/pending\/[^/]+\/complete$/`; `POST /devices/pending/{id}/approve` (authenticated) **vẫn** refresh + replay |
| Fingerprint mismatch → 403 | Đã có sẵn + test |
| Session cũ không ghi đè session mới | **Đã sửa** — epoch guard trong `useAuth.establishSession` |
| Token không lưu localStorage/sessionStorage/cookie | Đã có sẵn — token store in-memory |
| Rủi ro fingerprint collision / browser header | **Đã tài liệu hoá** — `docs/frontend/M12-STAGE-0-3-SECURITY-NOTES.md` (R1–R5) |

### 11.3 CI

`.github/workflows/ci.yml` bổ sung hai job:

- `frontend` — `npm ci`, `tsc -b --force`, `eslint`, `vitest run`, `npm run build`.
- `frontend-integration` — PostgreSQL thật (service container), bootstrap
  schema, seed fixture (`scripts/ci_seed_frontend_users.py`), SMTP sink
  (`scripts/ci_smtp_sink.py`), uvicorn thật, rồi `npm run test:integration`.

Suite integration **không** dùng mock: nó gọi HTTP thật vào backend đang
chạy, đọc OTP thật từ file SMTP sink, và đọc audit log thật trong PostgreSQL.

### 11.4 Kết quả kiểm thử sau final review

| Lệnh | Kết quả |
|---|---|
| `npx tsc -b --force` | sạch |
| `npm run lint` | sạch |
| `npm run test` | **128 passed** / 9 file |
| `npm run test:integration` | **23 passed** / 2 file (HTTP thật) |
| `npm run build` | ✓ built |
| `pytest` (backend) | **1189 passed, 0 failed, 0 skipped** |
| `scripts/m10_http_smoke.py` | **79 passed, 0 failed** |
