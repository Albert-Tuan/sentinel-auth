# M12.0 — Frontend Architecture (Sentinel Auth v3.3)

**Baseline:** `origin/dev` @ `c89bff5`
**Phạm vi:** Đề xuất kiến trúc frontend React để tích hợp ngay với backend FastAPI hiện tại. **Tài liệu này KHÔNG triển khai code frontend.**

---

## 1. Tổng quan stack

| Lớp | Lựa chọn | Phiên bản đề xuất | Lý do |
|---|---|---|---|
| Build | **Vite** | 7.x | Dev server nhanh, HMR, config TypeScript native. Không dùng CRA (đã deprecated). |
| UI runtime | **React** | 19.x | Ecosystem lớn nhất, tương thích React Router 7 + TanStack Query 5. |
| Ngôn ngữ | **TypeScript** | 5.x | Bắt buộc: có nhiều enum đóng (`SecurityAction`, `AlertStatus`, `RiskLevel`, `UserRole`, reason codes) và contract `extra="forbid"` — TS bắt lỗi compile-time. |
| Routing | **React Router** | 7.x (declarative / `createBrowserRouter`) | Route guard theo vai trò, nested layout. |
| Server state | **TanStack Query** | 5.x | Cache, retry, invalidation, `staleTime`. Không tự viết lại. |
| HTTP client | **Axios** | 1.x | Cần `interceptor` cho refresh-token rotation và xử lý lỗi tập trung. `fetch` cũng dùng được nhưng phải tự bọc nhiều hơn. |
| Styling | **Tailwind CSS** | 4.x | Token dễ map sang Stitch design tokens. |
| Charts | **Recharts** | 2.x | SVG, tương thích React 19, không cần canvas adapter. |
| Form | **React Hook Form** + **Zod** | 7.x / 3.x | Validate client trước khi gửi (backend vẫn là nơi enforce). |
| State server | **Không dùng Redux** | — | TanStack Query đủ. Chỉ thêm Zustand nếu cần state UI phức tạp. |

> **Backend giữ nguyên FastAPI.** Không có thay đổi nào cho server trong task này.

---

## 2. Cấu trúc thư mục (feature-based)

```
sentinel-auth-web/
├── public/
│   └── favicon.svg
├── src/
│   ├── main.tsx                     # ReactDOM.createRoot + QueryClientProvider + RouterProvider
│   ├── App.tsx                      # Router config (createBrowserRouter) — KHÔNG chứa logic
│   │
│   ├── app/                         # Hạ tầng dùng chung
│   │   ├── router/
│   │   │   ├── routes.tsx            # Route table + lazy imports
│   │   │   ├── guards.tsx            # <RequireAuth>, <RequireRole>
│   │   │   └── paths.ts              # Hằng số đường dẫn
│   │   ├── providers/
│   │   │   ├── AuthProvider.tsx      # SessionProvider (context) — token + user + roles
│   │   │   ├── QueryProvider.tsx     # QueryClient config
│   │   │   └── ToastProvider.tsx     # thông báo lỗi/success toàn cục
│   │   └── layout/
│   │       ├── AppShell.tsx          # Sidebar + Header + Outlet
│   │       ├── Sidebar.tsx           # menu lọc theo role
│   │       ├── Topbar.tsx            # user menu, logout, theme
│   │       └── RouteErrorBoundary.tsx
│   │
│   ├── lib/                         # Hạ tầng thuần, không phụ thuộc React
│   │   ├── api/
│   │   │   ├── client.ts            # axios instance + interceptors (token, refresh, error)
│   │   │   ├── endpoints.ts          # hằng số URL, KHÔNG có logic
│   │   │   ├── auth.api.ts
│   │   │   ├── admin.api.ts
│   │   │   ├── alerts.api.ts
│   │   │   ├── policies.api.ts
│   │   │   ├── devices.api.ts
│   │   │   ├── loginHistory.api.ts
│   │   │   └── manager.api.ts
│   │   ├── queryKeys.ts             # factory cho query key
│   │   ├── errors.ts                # ApiError class + parseErrorBody
│   │   ├── datetime.ts              # HÀM XỬ LÝ TIMESTAMP (giữ microsecond)
│   │   ├── enums.ts                 # SecurityAction, AlertStatus, RiskLevel, UserRole, ReasonCode
│   │   └── format.ts                # formatDate, formatBytes, ...
│   │
│   ├── features/
│   │   ├── auth/
│   │   │   ├── api/                 # hooks: useLogin, useMfaVerify, useLogout, useMe
│   │   │   ├── components/          # LoginForm, MfaCodeInput, PasswordField
│   │   │   ├── pages/               # LoginPage, MfaVerifyPage, RegisterPage, NotFoundPage
│   │   │   └── types.ts
│   │   ├── sessions/
│   │   │   ├── api/  components/  pages/  types.ts
│   │   ├── devices/
│   │   │   ├── api/  components/  pages/  types.ts
│   │   ├── admin-users/
│   │   │   ├── api/  components/  pages/  types.ts
│   │   ├── audit-logs/
│   │   │   ├── api/  components/  pages/  types.ts
│   │   ├── alerts/
│   │   │   ├── api/
│   │   │   ├── components/          # AlertTable, AlertFilters, AlertTimeline, EvidencePanel,
│   │   │   │                        # ActionDialog, AssignDialog, ResolveDialog
│   │   │   ├── pages/               # AlertQueuePage, AlertDetailPage
│   │   │   └── types.ts
│   │   ├── login-history/
│   │   │   ├── api/  components/  pages/  types.ts
│   │   ├── policies/
│   │   │   ├── api/
│   │   │   ├── components/          # PolicyTable, PolicyForm, RuleBuilder, ConfigForm, ActivateDialog
│   │   │   ├── pages/               # PolicyListPage, PolicyDetailPage, PolicyEditorPage
│   │   │   └── types.ts
│   │   └── manager/
│   │       ├── api/
│   │       ├── components/          # SourceStatusBanner, KpiCard, TrendChart, DegradedNotice
│   │       ├── pages/               # DashboardPage, TrendsPage, AlertAnalyticsPage, SocKpiPage, MlStatsPage
│   │       └── types.ts
│   │
│   ├── shared/
│   │   ├── components/              # Button, Input, Select, Dialog, Table, Badge, Spinner,
│   │   │                            # EmptyState, ErrorState, Pagination, DateRangePicker, Tabs, Toast
│   │   ├── hooks/                   # useDebounce, usePagination, useRole, useIsManager
│   │   ├── utils/                   # cn(), formatters
│   │   └── constants/
│   │
│   ├── types/                       # types dùng chung (ApiError, Paginated, WindowQuery)
│   └── styles/
│       ├── index.css                # @import "tailwindcss" + @theme tokens
│       └── tokens.ts                # cầu nối Stitch design tokens → Tailwind
│
├── .env.example                     # VITE_API_BASE_URL=http://localhost:8000
├── vite.config.ts
├── tailwind.config.ts (nếu dùng Tailwind 3) hoặc CSS-first config (Tailwind 4)
├── tsconfig.json
├── package.json
└── index.html
```

**Quy tắc import (để tránh cycle):**

```
shared/  ←  lib/  ←  features/*/api  ←  features/*/components  ←  features/*/pages  ←  app/
```

`lib/` **không** import từ `features/` hay `app/`. `shared/` không import React hooks nặng.

---

## 3. Quản lý token & phiên (SessionProvider)

### 3.1 Mô hình: token trong memory, không persist

```
┌─────────────────────────────────────────────────────────┐
│  Module-level store (KHÔNG React state)                  │
│                                                          │
│  let accessToken: string | null = null                   │
│  let refreshToken: string | null = null                  │
│  let mfaSessionId: string | null = null  // pre-auth txn  │
└─────────────────────────────────────────────────────────┘
        ▲                    │
        │ set/get            │ đọc trong axios interceptor
        ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│  <AuthProvider>                                          │
│   - user: UserItem | null                                │
│   - roles: Set<string>                                   │
│   - status: 'anonymous' | 'authenticating' | 'authenticated'│
│   - login(), verifyMfa(), logout(), refreshUser()        │
└─────────────────────────────────────────────────────────┘
```

**Vì sao token trong module-level store chứ không phải `useState`?**
Vì `axios` interceptor là code không thuộc React — nó cần đọc token **đồng bộ** ở thời điểm request. `useState` trong component sẽ tạo closure cũ trong interceptor (stale value). Store module-level giải quyết đúng vấn đề đó.

### 3.2 Quy tắc bất di bất dịch

| # | Quy tắc | Lý do |
|---|---|---|
| T1 | **Không decode token.** Không `jwtDecode`, không `atob`, không parse payload. | Token là opaque random; không có payload. Mọi thông tin đọc từ `/auth/me`. |
| T2 | **`INTERNAL_SECRET` không bao giờ vào browser.** Không đặt trong `.env` Vite, không đặt trong `VITE_*`. | `VITE_*` được bundle vào JS, ai cũng đọc được. Internal secret là service-to-service trust boundary. |
| T3 | **Không dùng `localStorage`/`sessionStorage`/`document.cookie` cho token.** | Demo bản demo không có cơ chế refresh-token an toàn (không có cookie `HttpOnly`, không có rotating refresh trên server-side storage). Lưu token vào storage ⇒ XSS ⇒ chiếm session. |
| T4 | **Sau reload → yêu cầu đăng nhập lại.** Đây là hành vi **được chấp nhận** cho bản demo theo yêu cầu đặc biệt. UI phải hiển thị thông báo thân thiện thay vì lỗi trống. | Token không còn trong memory ⇒ không còn phiên. |
| T5 | **Refresh token phải được thay thế sau mỗi lần refresh.** Backend rotate refresh token; token cũ không dùng lại được (→ 401). | Token rotation chống replay. |
| T6 | **Chỉ gọi `/internal/*` từ server-side.** Frontend **không** có endpoint nào gọi internal. | Ranh giới bảo mật. |

### 3.3 Vòng đời phiên (state machine)

```
                 POST /auth/login
                        │
                        ▼
              ┌─────────────────┐
              │  mfa_required?  │
              └──┬───────────┬──┘
              false│       true│
                 │           │
                 │           ▼
                 │   ┌───────────────────────┐
                 │   │ POST /auth/mfa/verify │  (mfaSessionId, code)
                 │   └──┬────────────────┬──┘
                 │  200 │             4xx│
                 └──────┴────────────────┤
                 │                       │
                 ▼                       ▼
        ┌────────────────┐      ┌──────────────────────┐
        │  AUTHENTICATED │      │  MFA_CHALLENGE       │
        │  tokens + user │      │  (không có token)    │
        └───────┬────────┘      └──────────────────────┘
                │
   access hết hạn / 401
                ▼
        ┌────────────────┐
        │  REFRESHING    │  POST /auth/refresh (1 lần, có mutex)
        └───┬────────┬───┘
          200│      401│
             │         ▼
             │    ┌──────────────┐
             │    │  ANONYMOUS   │ → về /login
             │    └──────────────┘
             ▼
        AUTHENTICATED (token mới)
```

**Mutex refresh:** nhiều request đồng thời gặp 401 → chỉ **một** request refresh chạy; các request còn lại **chờ** (promise queue) rồi retry bằng token mới. Không có mutex ⇒ refresh token rotation làm hỏng request song song (request thứ 2 dùng refresh token đã bị thay ⇒ 401 ⇒ logout oan).

---

## 4. HTTP client

### 4.1 Instance

```ts
// src/lib/api/client.ts
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});
```

**Không** set `withCredentials: true` — API dùng header `Authorization: Bearer`, không dùng cookie. `allow_credentials=True` trong CORS là phòng thủ của server, không phải yêu cầu của client.

### 4.2 Request interceptor

```ts
api.interceptors.request.use((config) => {
  const token = sessionStore.getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
```

### 4.3 Response interceptor (401 → refresh → retry)

```ts
let refreshing: Promise<string> | null = null;

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig | undefined;
    const status = error.response?.status;

    // Bỏ qua các endpoint public — refresh sẽ thất bại vô ích
    const isAuthEndpoint = original?.url?.includes("/api/v1/auth/refresh");
    if (status !== 401 || !original || isAuthEndpoint || original._retried) {
      return Promise.reject(toApiError(error));
    }

    original._retried = true;

    try {
      refreshing ??= doRefresh().finally(() => { refreshing = null; });
      const newToken = await refreshing;
      original.headers.Authorization = `Bearer ${newToken}`;
      return api(original);
    } catch {
      sessionStore.clear();
      window.location.assign(`/login?redirect=${encodeURIComponent(location.pathname)}`);
      return Promise.reject(toApiError(error));
    }
  },
);
```

### 4.4 `ApiError` — chuẩn hoá lỗi

Backend trả **hai hình dạng** `detail` khác nhau:

| Hình dạng | Ví dụ | Endpoint nào |
|---|---|---|
| **String** | `{"detail": "Alert not found"}` | Hầu hết 400/401/403/404/429/502 |
| **Object** | `{"detail": {"message": "Policy is invalid", "problems": ["rule 0: ..."]}}` | Policy create/edit/activate |
| **String (FastAPI)** | `{"detail": "..."}` | 422 validation — `detail` là **mảng** các object |
| **Object (Manager 503)** | `{"detail": "analytics sources unavailable", "sources": {...}}` | Manager 503 |

```ts
export type ApiErrorDetail =
  | string
  | { message: string; problems?: string[] }
  | Array<{ loc: (string | number)[]; msg: string; type: string }>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: ApiErrorDetail,
    readonly sources?: Record<string, { status: string; detail: string | null }>,
  ) { super(ApiError.messageOf(detail, status)); }
}
```

**Frontend phải phân biệt 2 dạng `detail`** để hiển thị lỗi đúng:
- Object có `problems` → hiển thị **danh sách** lỗi (policy).
- Array (422) → map `loc` → tên field, hiển thị lỗi **inline** dưới input.

### 4.5 CORS cho Vite dev

Backend đọc `CORS_ALLOWED_ORIGINS` (`.env.example` dòng 147, mặc định `http://localhost:8000,http://127.0.0.1:8000`).

**Bắt buộc thêm origin của Vite:**

```bash
# .env ở root backend
CORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173
```

| Quy tắc CORS backend | Hệ quả cho dev |
|---|---|
| Wildcard `*` bị **từ chối lúc startup** | Không dùng `*` |
| Mỗi entry phải là **origin đầy đủ** (`scheme://host[:port]`), không có path/query/fragment/trailing slash | `http://localhost:5173` OK; `http://localhost:5173/` được strip; `localhost:5173` (thiếu scheme) → **startup error** |
| `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]` | Header `Authorization` và `Content-Type` đều được phép |

**Hai cách chạy dev:**

| Cách | Cách làm | Khi nào dùng |
|---|---|---|
| **A. Vite proxy** (khuyến nghị) | `vite.config.ts` khai báo `server.proxy` cho `/api` → `http://localhost:8000`; `baseURL = "/api"` | Mọi lúc. Tránh CORS hoàn toàn, cùng origin với proxy. |
| **B. CORS trực tiếp** | `baseURL = "http://localhost:8000"` + thêm origin Vite vào `CORS_ALLOWED_ORIGINS` | Khi muốn test đúng hành vi CORS thật (vd. deploy tách domain) |

> Với cách A, `VITE_API_BASE_URL` để trống ⇒ `baseURL = "/api"`.
> Với cách B, **phải** thêm origin vào allow-list, nếu không trình duyệt chặn response trước khi JS đọc được.

### 4.6 Retry policy của TanStack Query

| Loại query | `retry` | `staleTime` | `refetchOnWindowFocus` |
|---|---|---|---|
| `GET /auth/me` | 0 (401 → refresh, không phải retry) | 60s | false |
| `GET /policies`, `/policies/{id}` | 1 | 30s | true |
| `GET /alerts` | 1 | 15s | true |
| `GET /manager/*` | 0 (503 là trạng thái nghiệp vụ, không retry) | 60s | false |
| `GET /login-attempts` | 1 | 15s | true |

---

## 5. Xử lý timestamp — điểm dễ sai nhất

### 5.1 Vấn đề

Backend trả `updated_at` với **full microsecond precision**:

```
2026-11-07T02:33:00.123456Z
```

JavaScript `Date` chỉ giữ **millisecond**:

```ts
new Date("2026-11-07T02:33:00.123456Z").toISOString()
// → "2026-11-07T02:33:00.123Z"   ← mất .000456
```

Nếu gửi token đã cắt ngắn ⇒ **luôn** 409, dù không có ai sửa policy.

### 5.2 Giải pháp: timestamp là **chuỗi opaque**

```ts
// src/lib/datetime.ts

/** ISO-8601 string, giữ nguyên microsecond từ server. KHÔNG parse. */
export type IsoTimestamp = string;

/** Chỉ dùng để hiển thị. Không dùng kết quả để gửi lại server. */
export function formatTimestamp(ts: IsoTimestamp | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;          // fallback: hiện raw
  return d.toLocaleString(undefined, {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

/**
 * So sánh hai timestamp server trả về.
 * Parse ra epoch millisecond chỉ để so sánh — không dùng để gửi lại.
 */
export function isSameTimestamp(a: IsoTimestamp, b: IsoTimestamp): boolean {
  return Date.parse(a) === Date.parse(b);
}

/**
 * Cắt microsecond thành millisecond — CHỈ dùng để hiển thị log/debug.
 * TUYỆT ĐỐI KHÔNG dùng kết quả này làm expected_updated_at.
 */
export function toMillis(ts: IsoTimestamp): string {
  return new Date(ts).toISOString();
}
```

### 5.3 Luật áp dụng

| Quy tắc | Chi tiết |
|---|---|
| **L1** | Type `PolicyDetail.updated_at` phải là `string`, **không** phải `Date`. Không có `new Date()` nào chạm vào nó trước khi gửi. |
| **L2** | Form edit giữ `expected_updated_at` trong một `useRef<string>` / biến state **string**, cập nhật **chỉ** khi refetch. |
| **L3** | Khi nhận 409 `"Policy was modified by someone else"` → **refetch** `GET /policies/{id}`, hiển thị diff/thông báo "policy đã bị sửa bởi người khác", **không** tự động ghi đè. |
| **L4** | **Không** dùng `date-fns`/`dayjs`/`luxon` để "chuẩn hoá" timestamp trước khi gửi. Mọi thao tác format đều chỉ phục vụ hiển thị. |
| **L5** | Nếu cần hiển thị "cập nhật 3 giây trước", dùng `Date.now() - Date.parse(updated_at)` — sai số tối đa 1ms, chấp nhận được cho UX. |

### 5.4 Code mẫu — Policy Edit

```ts
// features/policies/api/useEditPolicy.ts
export function useEditPolicy(policyId: string) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      name?: string;
      description?: string;
      rules?: RuleDefinition[];
      config?: PolicyConfig;
      expected_updated_at: string;   // ← chuỗi raw từ server, KHÔNG qua Date
    }) => {
      const { data } = await api.put<PolicyDetail>(
        `/api/v1/policies/${policyId}`,
        input,
      );
      return data;
    },
    onSuccess: (detail) => {
      qc.setQueryData(policyKeys.detail(policyId), detail);
      qc.invalidateQueries({ queryKey: policyKeys.list() });
    },
  });
}
```

```tsx
// features/policies/pages/PolicyEditorPage.tsx  (rút gọn)
const { data: policy } = usePolicyDetail(id);
// ↑ `policy.updated_at` là string nguyên vẹn từ server

const editPolicy = useEditPolicy(id);

async function onSubmit(values: PolicyFormValues) {
  try {
    await editPolicy.mutateAsync({
      ...values,
      expected_updated_at: policy!.updated_at,   // ← raw string, không format
    });
    toast.success("Policy updated");
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const problem = asPolicyProblem(e.detail);   // { message, problems[] }
      if (problem?.message === "Policy was modified by someone else") {
        // REFETCH, KHÔNG auto-overwrite
        await refetch();
        toast.error("Policy đã bị sửa bởi người khác. Dữ liệu đã được tải lại, hãy kiểm tra và gửi lại.");
        return;
      }
      if (problem?.message === "Policy is immutable") {
        toast.error("Policy đã từng được kích hoạt nên bị đóng băng. Hãy tạo version mới.");
        return;
      }
    }
    throw e;
  }
}
```

---

## 6. Types — sinh thủ công, không dùng `openapi-typescript`

**Vì sao không auto-generate?**
Backend **không khai báo `securitySchemes`** trong OpenAPI (auth dùng custom FastAPI dependency `get_current_auth_context` / `require_roles` — FastAPI không sinh security scheme cho dạng đó). Hệ quả:
- Client sinh ra **không biết** endpoint nào cần token, endpoint nào cần role nào.
- `response_model=list` của `GET /policies` → schema `array[any]`, mất toàn bộ thông tin.

→ **Type phải viết tay**, dựa trên `app/schemas.py` + `app/manager.py` + `app/alerts.py`. Đây là lý do tài liệu API inventory là bắt buộc, không phải tuỳ chọn.

### 6.1 Kiểu enum đóng (bắt buộc dùng `as const`)

```ts
// src/lib/enums.ts
export const UserRole = {
  USER: "USER",
  SECURITY_ADMIN: "SECURITY_ADMIN",
  SOC_ANALYST: "SOC_ANALYST",
  SECURITY_MANAGER: "SECURITY_MANAGER",
} as const;
export type UserRole = (typeof UserRole)[keyof typeof UserRole];

export const AlertStatus = {
  OPEN: "open",
  ACKNOWLEDGED: "acknowledged",
  RESOLVED: "resolved",
  FALSE_POSITIVE: "false_positive",
} as const;
export type AlertStatus = (typeof AlertStatus)[keyof typeof AlertStatus];

export const RiskLevel = {
  LOW: "low", MEDIUM: "medium", HIGH: "high", CRITICAL: "critical",
} as const;
export type RiskLevel = (typeof RiskLevel)[keyof typeof RiskLevel];

export const SecurityAction = {
  REQUIRE_MFA: "REQUIRE_MFA",
  REVOKE_SESSIONS: "REVOKE_SESSIONS",
  LOCK_USER: "LOCK_USER",
  FORCE_LOGOUT: "FORCE_LOGOUT",
} as const;
export type SecurityAction = (typeof SecurityAction)[keyof typeof SecurityAction];

export const AlertResolution = {
  TRUE_ATTACK: "true_attack",
  FALSE_POSITIVE: "false_positive",
  BENIGN_TRUE_POSITIVE: "benign_true_positive",
  INSUFFICIENT_EVIDENCE: "insufficient_evidence",
} as const;
export type AlertResolution = (typeof AlertResolution)[keyof typeof AlertResolution];

/** Lý do nguồn analytics không khả dụng (closed vocabulary). */
export const SourceReasonCode = {
  NOT_CONFIGURED: "not_configured",
  TIMEOUT: "timeout",
  UNREACHABLE: "unreachable",
  INVALID_PAYLOAD: "invalid_payload",
  DATABASE_ERROR: "database_error",
  INTERNAL_ERROR: "internal_error",
} as const;
export type SourceReasonCode = (typeof SourceReasonCode)[keyof typeof SourceReasonCode];
```

### 6.2 Feature flags tương lai

`alerts.py` có `AlertEscalateRequest` trong `schemas.py` nhưng **không có route**. Không tạo type cho nó — nếu tạo, dev sẽ tưởng có API.

---

## 7. Routing & role gating

### 7.1 Nguyên tắc

> **Frontend role gating chỉ phục vụ UX.** Backend là nơi duy nhất thực thi authorization (`require_roles` → 403 `"Insufficient permissions"`).
> Frontend gate chỉ để **tránh hiển thị** menu/button mà user không dùng được — **không** phải cơ chế bảo mật.

### 7.2 Guard

```tsx
// app/router/guards.tsx
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <FullPageSpinner />;
  if (status === "anonymous") {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <Outlet />;
}

export function RequireRole({ allow }: { allow: readonly UserRole[] }) {
  const { roles } = useAuth();
  const has = allow.some((r) => roles.has(r));
  if (!has) return <Navigate to="/403" replace />;
  return <Outlet />;
}
```

> `/403` nên hiển thị nút "Về trang phù hợp với vai trò của bạn" thay vì trang trắng.

### 7.3 Bảng route

| Route | Guard | Màn hình |
|---|---|---|
| `/login` | public | Login |
| `/mfa` | public (chỉ khi có `mfaSessionId`) | MFA Verify |
| `/register` | public | Register |
| `/trusted-device` | public | Trusted-device Login |
| `/403` | authenticated | Forbidden |
| `/*` | authenticated | 404 |
| `/sessions` | authenticated | Quản lý phiên |
| `/devices` | authenticated | Thiết bị tin cậy |
| `/alerts` | `SOC_ANALYST` \| `SECURITY_MANAGER` | Alert Queue |
| `/alerts/:id` | `SOC_ANALYST` \| `SECURITY_MANAGER` | Alert Detail |
| `/login-history` | `SOC_ANALYST` \| `SECURITY_MANAGER` | Lịch sử đăng nhập |
| `/admin/users` | `SECURITY_ADMIN` | Quản lý người dùng |
| `/admin/audit-logs` | `SECURITY_ADMIN` | Nhật ký kiểm toán |
| `/policies` | `SECURITY_ADMIN` \| `SECURITY_MANAGER` | Danh sách policy |
| `/policies/:id` | `SECURITY_ADMIN` \| `SECURITY_MANAGER` | Chi tiết policy |
| `/policies/new` | `SECURITY_ADMIN` | Tạo policy |
| `/policies/:id/edit` | `SECURITY_ADMIN` | Sửa policy |
| `/manager` | `SECURITY_MANAGER` | Dashboard |
| `/manager/trends` | `SECURITY_MANAGER` | Xu hướng |
| `/manager/alerts` | `SECURITY_MANAGER` | Phân tích cảnh báo |
| `/manager/soc-kpi` | `SECURITY_MANAGER` | SOC KPI |
| `/manager/ml-stats` | `SECURITY_MANAGER` | ML Stats |

---

## 8. Styling — tương thích Stitch

### 8.1 Nguyên tắc

1. **Stitch sinh design tokens**, không sinh component React hoàn chỉnh — Stitch là công cụ thiết kế UI, output là HTML/CSS hoặc hướng dẫn style.
2. **Tailwind là lớp thực thi**: Stitch tokens → `tokens.ts` → `@theme` trong CSS → dùng qua class Tailwind (`bg-surface`, `text-muted`, `rounded-card`).
3. **Component thực dùng `shared/components`** — không copy-paste HTML từ Stitch. Stitch là nguồn **style**, không phải nguồn **component**.
4. **Stitch mockup dùng dữ liệu giả** → khi tích hợp API thật, chỉ thay phần data, giữ nguyên layout.

### 8.2 Token bridge

```ts
// src/styles/tokens.ts
export const tokens = {
  color: {
    surface: "#0B1220",
    "surface-raised": "#131C2E",
    border: "#1F2A3D",
    primary: "#3B82F6",
    success: "#22C55E",
    warning: "#F59E0B",
    danger: "#EF4444",
    muted: "#94A3B8",
    text: "#E2E8F0",
  },
  radius: { card: "12px", control: "8px" },
  spacing: { page: "24px", section: "16px", gutter: "12px" },
} as const;
```

```css
/* src/styles/index.css */
@import "tailwindcss";

@theme {
  --color-surface: #0B1220;
  --color-surface-raised: #131C2E;
  --color-border: #1F2A3D;
  --color-primary: #3B82F6;
  --color-success: #22C55E;
  --color-warning: #F59E0B;
  --color-danger: #EF4444;
  --color-muted: #94A3B8;
  --color-text: #E2E8F0;

  --radius-card: 12px;
  --radius-control: 8px;
}
```

### 8.3 Bảng màu ngữ nghĩa — bắt buộc

Màu **không** được hard-code theo tên hiển thị; phải theo ngữ nghĩa để Stitch đổi theme không phá UI.

| Ngữ nghĩa | Token | Dùng cho |
|---|---|---|
| Thành công | `--color-success` | resolve alert, activate policy thành công |
| Cảnh báo | `--color-warning` | degraded analytics, policy đã từng active (immutable) |
| Nguy hiểm | `--color-danger` | lock user, 409, 502, alert critical |
| Trung tính | `--color-muted` | text phụ, badge neutral |
| Hành động | `--color-primary` | nút chính, focus ring |

---

## 9. TanStack Query patterns

### 9.1 Query key factory

```ts
// src/lib/queryKeys.ts
export const policyKeys = {
  all: ["policies"] as const,
  list: () => [...policyKeys.all, "list"] as const,
  detail: (id: string) => [...policyKeys.all, "detail", id] as const,
};

export const alertKeys = {
  all: ["alerts"] as const,
  list: (params: AlertListParams) => [...alertKeys.all, "list", params] as const,
  detail: (id: string) => [...alertKeys.all, "detail", id] as const,
  timeline: (id: string) => [...alertKeys.all, "timeline", id] as const,
  evidence: (id: string) => [...alertKeys.all, "evidence", id] as const,
};
```

### 9.2 Invalidation sau mutation

| Mutation | Invalidate |
|---|---|
| Acknowledge / Resolve / Assign alert | `alertKeys.detail(id)`, `alertKeys.list()`, `alertKeys.timeline(id)` |
| Request action | `alertKeys.detail(id)`, `alertKeys.timeline(id)` |
| Create policy | `policyKeys.list()` |
| Edit policy (thành công) | `policyKeys.detail(id)`, `policyKeys.list()` |
| **Edit policy (409)** | `policyKeys.detail(id)` — **chỉ refetch, không mutate** |
| Activate policy | `policyKeys.list()`, `policyKeys.detail(id)` |
| Lock/unlock user | `adminUsersKeys.list()` |
| Assign/revoke role | `adminUsersKeys.list()`, `adminUsersKeys.detail(id)` |
| Revoke session | `sessionsKeys.list()` |
| Untrust device | `devicesKeys.list()` |

### 9.3 Selectors để tránh render lại thừa

```ts
const activeCount = useQuery({
  queryKey: policyKeys.list(),
  queryFn: fetchPolicies,
  select: (list) => list.filter((p) => p.is_active).length,
});
```

---

## 10. Xử lý trạng thái lỗi theo từng nhóm

| Nhóm endpoint | 400 | 401 | 403 | 404 | 409 | 422 | 429 | 502 | 503 |
|---|---|---|---|---|---|---|---|---|---|
| Auth | — | → refresh / về login | — | — | MFA state | form | login rate-limit | — | — |
| Admin | — | → refresh | "Bạn không có quyền ADMIN" | "Không tìm thấy user" | role trùng | form | — | — | — |
| Alerts | "Alert không ở trạng thái phù hợp" | → refresh | — | "Không tìm thấy alert" | — | form | — | **"Hành động KHÔNG được áp dụng"** | — |
| Policies | "Policy không hợp lệ" + problems | → refresh | — | "Không tìm thấy policy" | **3 biến thể** | form | — | — | — |
| Devices | — | → refresh | IP/fingerprint mismatch | — | MFA chặn | form | — | — | — |
| Manager | window/filter sai | → refresh | "Cần SECURITY_MANAGER" | — | — | — | — | — | **"Nguồn dữ liệu không khả dụng"** |
| Login history | filter sai | → refresh | — | — | — | — | — | — | — |

---

## 11. Kiểm thử

| Loại | Công cụ | Phạm vi |
|---|---|---|
| Unit | Vitest | formatters, `ApiError` parsing, enum mapping, timestamp helpers |
| Hook/component | Vitest + Testing Library | `RequireRole`, form validation, error rendering |
| Integration | Vitest + MSW | mock backend theo contract thật (đặc biệt 409 policy, 502 action, 503 manager) |
| E2E | Playwright | 4 luồng vai trò end-to-end |

**Bắt buộc có test cho các edge case backend đặc biệt:**
1. 409 policy với 3 message khác nhau → UI xử lý khác nhau.
2. 502 protective action → hiển thị "KHÔNG được áp dụng" (không phải "thành công").
3. 503 manager → hiển thị degraded state, không phải error page.
4. `mfa_required: true` → `access_token` là chuỗi rỗng → frontend **không** được coi là đã đăng nhập.
5. Refresh token rotation → refresh đồng thời nhiều request không logout oan.

---

## 12. Cấu hình môi trường

```bash
# .env.example (frontend)
# Để trống khi dùng Vite proxy; điền khi dùng CORS trực tiếp.
VITE_API_BASE_URL=http://localhost:8000
```

| Biến | Được phép trong browser? | Ghi chú |
|---|---|---|
| `VITE_API_BASE_URL` | ✅ | Chỉ URL công khai |
| `INTERNAL_SECRET` | ❌ **CẤM** | Chỉ ở backend `.env`. Biến `VITE_*` bị bundle vào JS. |
| `X-Internal-Secret` | ❌ **CẤM** | Không có endpoint nào của browser dùng nó. |

---

## 13. Những điều KHÔNG được làm

| # | Không được | Lý do |
|---|---|---|
| 1 | Decode token như JWT | Token opaque, không có payload |
| 2 | Đưa `INTERNAL_SECRET` vào bất kỳ biến `VITE_*` nào | Bị bundle vào JS, lộ |
| 3 | Lưu token vào `localStorage`/`sessionStorage`/cookie JS | XSS ⇒ chiếm phiên |
| 4 | Parse `updated_at` qua `new Date()` rồi gửi lại | Mất microsecond ⇒ 409 |
| 5 | Tự động ghi đè khi gặp 409 | Mất dữ liệu người khác |
| 6 | Gọi `/api/v1/internal/*` từ browser | Sai ranh giới trust |
| 7 | Hiển thị `0` khi Manager trả `null` | `null` = không có dữ liệu ≠ 0 |
| 8 | Hiển thị "thành công" khi protective action trả 502 | Hành động **chưa** được áp dụng |
| 9 | Dùng role gating frontend như cơ chế bảo mật | Backend mới enforce |
| 10 | Tạo endpoint giả trong `endpoints.ts` cho API chưa tồn tại | Sai lệch với backend thật |
