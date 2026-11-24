# M12 Stage 0–3 — Ghi chú bảo mật Frontend

Tài liệu này mô tả **hành vi đã hiện thực** của luồng xác thực trong
`feature/m12-frontend-foundation` (Stage 0–3), và ghi lại các **known risk**
còn tồn tại sau khi review.

> Tài liệu lập kế hoạch của M12 nằm ở `docs/frontend/M12-*.md` và thuộc PR #18
> (M12.0 Planning). File này thuộc **deliverable frontend Stage 0–3**.

---

## 1. Nguồn dữ liệu chuẩn cho phân quyền

Trước Stage 0–3 có **hai** danh sách quyền song song:

- `app/router/routes.tsx` — guard `<RequireRole allow={[...]}>` cho từng branch
- `app/router/access.ts` — `canAccessPath()` dùng cho navigation và redirect

Hai danh sách đó **drift**: `/alerts` được mount **không có guard** trong
`routes.tsx` (mọi user đã đăng nhập đều thấy menu Alerts), trong khi
`access.ts` chỉ cho phép `SOC_ANALYST` / `SECURITY_MANAGER`.

### Cách sửa

Nguồn duy nhất: **`src/app/router/policy.ts`** — bảng `SECTIONS`:

| Trường | Ý nghĩa |
|---|---|
| `id` | Khoá section, dùng cho `RequireRole section="..."` |
| `prefixes` | Prefix dùng để map `location.pathname` → section (deep link) |
| `routes` | Bảng route cụ thể → page factory |
| `access` | `'roles'` (cần role) hoặc `'any-session'` (mọi user đã đăng nhập) |
| `roles` | Role được backend cho phép |
| `nav` | Entry hiển thị trên Sidebar / MobileNav |
| `landing` / `landingPriority` | Trang đích sau login, theo thứ tự ưu tiên |

Bốn nơi tiêu thụ chính đều đọc từ `policy.ts`:

| Nơi dùng | Hàm |
|---|---|
| `app/router/guards.tsx` → `RequireRole` | `sectionRoles(section)` |
| `app/router/HomeRedirect.tsx` | `landingPathFor(roles)` |
| `features/auth/pages/LoginPage.tsx` | `resolvePostLoginPath(from, roles)` |
| `app/layout/Sidebar.tsx`, `app/layout/MobileNav.tsx` | `navigationFor(roles)` |

File `app/router/access.ts` và `app/layout/navigation.ts` **đã bị xoá** — không
còn danh sách allowlist thứ hai.

### Bảng quyền (không đổi so với backend)

| Route | Role backend yêu cầu |
|---|---|
| `/alerts`, `/alerts/:id`, `/login-history` | `SOC_ANALYST`, `SECURITY_MANAGER` |
| `/policies` | `SECURITY_ADMIN`, `SECURITY_MANAGER` |
| `/admin/*` | `SECURITY_ADMIN` |
| `/manager/*` | `SECURITY_MANAGER` |
| `/sessions`, `/devices`, `/profile` | mọi user đã đăng nhập |

### Landing page sau login

| Role | Landing | Priority |
|---|---|---|
| `SECURITY_MANAGER` | `/manager/dashboard` | 40 |
| `SECURITY_ADMIN` | `/admin/users` | 30 |
| `SECURITY_ADMIN` \| `SECURITY_MANAGER` | `/policies` | 25 |
| `SOC_ANALYST` \| `SECURITY_MANAGER` | `/alerts` | 20 |
| `USER` | `/sessions` | 10 |

> **`USER` → `/sessions`** (không phải `/`). Trước đây `USER` resolve về `/`,
> trong khi `HomeRedirect` lại redirect khỏi `/` ⇒ **redirect loop / trang
> trắng**. Sửa theo M12-PAGE-MAP §3.1.

### Remembered destination

`resolvePostLoginPath(from, roles)` chỉ khôi phục đường dẫn khi:

1. `isKnownPath(from)` — đường dẫn có thật trong bảng route, **và**
2. `from` không phải public auth route (`/login`, `/mfa`, `/trusted-device`,
   `/forbidden`) và không phải `/`, **và**
3. `canAccessPath(from, roles)` — user hiện tại được phép vào.

Nếu không thỏa → fallback `landingPathFor(roles)`. Không có đường dẫn nào dẫn
tới `/forbidden` khi deep link hợp lệ; `/forbidden` chỉ hiện khi user cố mở
route mà **không** có role cần thiết.

---

## 2. Ranh giới refresh-token ở luồng trusted-device

`src/lib/api/client.ts` không refresh khi gặp 401 ở các endpoint **public**:

| Endpoint | Backend | Refresh? |
|---|---|---|
| `POST /auth/login` | public | ❌ |
| `POST /auth/mfa/verify` | public | ❌ |
| `POST /auth/refresh` | public | ❌ |
| `POST /devices/pending` | public (`app/devices.py:307`) | ❌ |
| `POST /devices/pending/{id}/complete` | public (`app/devices.py:538`) | ❌ |
| `POST /devices/pending/{id}/approve` | **authenticated** (`app/devices.py:459`, `Depends(get_current_auth_context)`) | ✅ |

> **Bug đã sửa (Stage 0–3):** danh sách no-refresh từng dùng prefix
> `'/devices/pending/'`, nuốt luôn `/approve`. `/approve` là endpoint
> **authenticated** ⇒ 401 ở đó nghĩa là access token hết hạn, và request
> **phải** refresh + replay. Nay ranh giới được siết bằng regex
> `^/devices/pending/[^/]+/complete$` — chỉ endpoint public mới bị loại.

Hai lớp bảo vệ: (1) call site dùng `_skipRefresh: true` cho endpoint public
(`lib/api/devices.api.ts`); (2) interceptor tự chặn theo URL. Lớp (2) là lưới
an toàn khi có người gọi mới quên `_skipRefresh`.

### Vòng đời `POST /devices/pending/{id}/complete`

| Response | Hành vi frontend |
|---|---|
| `200` + token | `loginWithTokens()` → xác nhận bằng `GET /auth/me` → điều hướng landing |
| `200` nhưng token rỗng | Báo "máy chủ đã phản hồi nhưng không cấp token hợp lệ" — **không** cài session |
| `409` `still pending` | **Tiếp tục polling sau 3s** (không phải lỗi) |
| `409` `MFA is required` / `Detection requires MFA` | Dừng, yêu cầu dùng luồng đăng nhập thường |
| `403` (IP / fingerprint mismatch) | Dừng, báo "thiết bị hoặc địa chỉ IP không khớp" |
| `410` / `404` (transaction không còn hợp lệ) | Dừng, báo yêu cầu đã hết hạn |
| `401` (account không active) | Dừng, không refresh, không logout phiên hiện tại |

Polling bị **hủy** khi: component unmount (`cancelledRef` + `clearTimeout`),
user bấm "Hủy", hoặc transaction không còn hợp lệ.

---

## 3. Chống session cũ ghi đè session mới (epoch guard)

`src/lib/api/tokenStore.ts` giữ một `epoch` tăng đơn điệu. Mọi bước cài
session (`setSession`) hoặc xoá session (`clearSession`) đều bump epoch.

**Điểm yếu đã sửa (Stage 0–3):** `useAuth` cài token **rồi mới** `await
GET /auth/me`. Nếu người dùng logout hoặc đăng nhập bằng tài khoản khác trong
lúc `/auth/me` còn bay, response cũ sẽ:

- dispatch `LOGIN_SUCCESS` ⇒ UI hiện "đã đăng nhập" nhưng **không có token**;
- hoặc gọi `clearSession()` ⇒ **xoá mất session mới** của người dùng.

 Nay `useAuth.establishSession()` đọc epoch **sau** `setSession` và so sánh lại
khi response về. Nếu epoch đã đổi ⇒ response bị **discard**, không dispatch
gì, không clear session. Áp dụng cho cả `login()`, `verifyMfa()` và
`loginWithTokens()`.

Bộ đệm refresh trong `client.ts` đã có cùng cơ chế (`StaleSessionError`).

---

## 4. Token storage

`tokenStore.ts` chỉ giữ token trong **biến module-scoped**:

- ❌ `localStorage`
- ❌ `sessionStorage`
- ❌ cookie
- ❌ query string

Đánh đổi được chấp nhận: **reload trang sẽ mất phiên**, người dùng phải đăng
nhập lại. Đây là hành vi được yêu cầu bởi security review M12.

Token không bao giờ được `console.log`. Test `client.test.ts` khẳng định
`localStorage.length === 0`, `sessionStorage.length === 0`,
`document.cookie` không chứa token.

---

## 5. KNOWN RISK — fingerprint thiết bị

Backend dựng fingerprint từ **header của request**
(`app/device_fingerprint.py` → `fingerprint_material_from_headers`), rồi
SHA-256 trước khi lưu. Vậy fingerprint **không phải** mã định danh phần cứng.

| # | Rủi ro | Mức | Mô tả | Giảm thiểu hiện tại |
|---|---|---|---|---|
| **R1** | **Fingerprint collision** | Trung bình | Nhiều máy/người dùng dùng cùng `User-Agent` + `Accept-Language` + `Accept-Encoding` (đặc biệt trong môi trường demo, container, hoặc cùng một hệ điều hành) ⇒ **cùng một fingerprint**. Điều đó khiến "thiết bị tin cậy" có thể bị cấp cho nhiều account khác nhau. | Backend còn ràng buộc thêm: IP phải khớp (`_same_ip`), transaction chỉ dùng được 1 lần (`consumed_at`), hết hạn sau 5 phút, và phải có một session đã đăng nhập của **cùng user** để approve. |
| **R2** | **Header do client kiểm soát** | Cao | `User-Agent`, `Accept-Language`, `Accept-Encoding` đều do client gửi và có thể bị giả mạo. Attacker có thể sao chép header để tạo cùng fingerprint. | **Chưa** có biện pháp bổ sung. Fingerprint chỉ nên được coi là *yếu tố phụ* (defense-in-depth), **không phải** yếu tố xác thực chính. Yếu tố chính vẫn là password + session của thiết bị đã đăng nhập. |
| **R3** | **Browser update đổi fingerprint** | Thấp | Trình duyệt cập nhật có thể đổi `Accept-Encoding` ⇒ thiết bị tin cậy cũ không còn khớp ⇒ người dùng bị buộc phê duyệt lại. | Chấp nhận. Flow hiển thị lỗi "thiết bị hoặc địa chỉ IP không khớp" (403) thay vì lỗi kỹ thuật mơ hồ. |
| **R4** | **Privacy mode / proxy** | Thấp | Header bị proxy hoặc extension chèn vào làm fingerprint không ổn định giữa hai lần đăng nhập. | Chấp nhận cho demo. Nếu cần ổn định hơn thì phải dùng WebAuthn / client certificate — nằm ngoài phạm vi M12. |
| **R5** | **HTTP fingerprint collision ⇒ 403 giả** | Thấp | Do R1, một thiết bị hợp lệ có thể bị backend từ chối ở bước `complete` vì fingerprint lệch với transaction. | Frontend hiển thị thông báo rõ ràng (403) thay vì lỗi chung chung. |

### Hướng khắc phục đề xuất (ngoài phạm vi M12)

1. **WebAuthn / FIDO2** thay cho fingerprint tự quản lý — fingerprint do
   authenticator sinh, không nằm trong tay client.
2. **Client certificate (mTLS)** cho thiết bị tin cậy nội bộ.
3. **Nonce / challenge** do backend cấp, browser phải ký bằng khóa lưu ở
   thiết bị → chặn được việc sao chép header từ máy khác.
4. Bổ sung thêm tín hiệu (IP subnet, TLS fingerprint của client, thời gian
   hoạt động) để tăng entropy.

> **Kết luận:** với cơ chế hiện tại, "trusted device" là **tiện ích trải
> nghiệm**, không phải cơ chế xác thực mạnh. Backend vẫn là nơi duy nhất
> enforce (password + session + IP + MFA gate), vì vậy R1–R5 **không** làm suy
> giảm biên an toàn của hệ thống — chỉ làm giảm độ tin cậy của tín hiệu
> fingerprint.

---

## 6. Checklist review Stage 0–3

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| `complete` chỉ authenticated khi có token hợp lệ + `GET /auth/me` | ✅ | `useAuth.establishSession()` + test `useAuth.test.tsx` |
| `409 still pending` polling mỗi 3s | ✅ | `trustedDeviceLogin.test.tsx` — "polls on a 3 second interval" |
| Polling hủy khi unmount / transaction không hợp lệ | ✅ | test "cancels the polling when the page unmounts", "stops polling when the transaction is no longer valid (410)" |
| `401` public endpoint không kích hoạt refresh | ✅ | `client.test.ts` — "never refreshes on the PUBLIC completion endpoint" |
| `/approve` (authenticated) **có** refresh | ✅ | `client.test.ts` — "DOES refresh on the AUTHENTICATED approval endpoint" |
| Fingerprint mismatch → 403 | ✅ | test "explains a fingerprint or IP mismatch (403)" |
| Session cũ không ghi đè session mới | ✅ | `useAuth.test.tsx` — 2 test epoch guard |
| Token không lưu storage/cookie, không lộ console | ✅ | `client.test.ts` — "token storage" |
| Fingerprint collision / header limitation | ⚠️ **known risk** | §5 (R1–R5) |
