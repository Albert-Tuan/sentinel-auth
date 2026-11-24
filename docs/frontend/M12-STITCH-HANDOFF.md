# M12.0 — Stitch Handoff (Sentinel Auth v3.3)

**Baseline:** `origin/dev` @ `c89bff5`
**Mục đích:** Hướng dẫn chính xác cách dùng Stitch (Google Stitch, qua MCP `user-stitch`) để thiết kế 24 màn hình của Sentinel Auth, sao cho output của Stitch **map thẳng** vào Tailwind/React của [M12-ARCHITECTURE.md](./M12-ARCHITECTURE.md).

---

## 1. Vai trò của Stitch trong dự án

| Stitch **CÓ** | Stitch **KHÔNG CÓ** |
|---|---|
| Thiết kế bố cục, hệ màu, typography | Viết logic React/TypeScript |
| Sinh `html_code` + `screenshot` cho từng screen | Sinh API client / hooks / TanStack Query |
| Sinh **design system** (tokens) | Hiểu contract backend (409 policy, 502 action, 503 manager) |
| Tạo **variants** để chọn phương án | Tự sinh endpoint không tồn tại |

> **Nguyên tắc bất di bất dịch:** Stitch là nguồn **style**, không phải nguồn **component**. Không copy-paste HTML từ Stitch vào `shared/components/`. Lấy **tokens** + **bố cục** từ Stitch, còn component thật do `src/shared/components/` cung cấp.

---

## 2. Tool MCP `user-stitch` — bảng tra cứu

Các tool hiện có (đọc từ descriptor `mcps/user-stitch/tools/*.json`):

| Tool | Mục đích | Tham số chính |
|---|---|---|
| `create_project` | Tạo project Stitch | `title` |
| `list_projects` | Liệt kê project | `filter` (AIP-160) |
| `get_project` | Chi tiết project (chứa **screen instances**) | `name` = `projects/{id}` |
| `delete_project` | Xoá project (**không hoàn tác được**) | `name` = `projects/{id}` |
| `generate_screen_from_text` | Sinh **screen mới** từ prompt | `projectId`, `prompt`, `designSystem?`, `deviceType?`, `modelId?` |
| `edit_screens` | Sửa screen **đã có** bằng prompt | `projectId`, `prompt`, `selectedScreenIds[]`, `deviceType?`, `modelId?` |
| `generate_variants` | Sinh **nhiều phương án** cho 1 screen | `projectId`, `prompt`, `selectedScreenIds[]`, `variantOptions` |
| `list_screens` | Liệt kê screen trong project | `projectId` |
| `get_screen` | Chi tiết 1 screen | `name` = `projects/{p}/screens/{s}` |
| `download_file` | Tải `html_code` hoặc `screenshot` của screen | `name` = resource name từ `html_code.name` / `screenshot.name` |
| `create_design_system` | Tạo design system (tokens) | `designSystem`, `projectId?` |
| `update_design_system` | Cập nhật design system | `name` = `assets/{id}`, `designSystem`, `projectId` |
| `list_design_systems` | Liệt kê design system | `projectId?` |
| `apply_design_system` | Áp design system lên các screen đã chọn | `assetId`, `projectId`, `selectedScreenInstances[]` |
| `upload_design_md` | Upload `DESIGN.md` (base64) | `projectId`, `designMdBase64` |
| `create_design_system_from_design_md` | Tạo design system từ `DESIGN.md` | `projectId`, `selectedScreenInstance` |

### 2.1 Lưu ý vận hành (từ chính description của tool)

| Tool | Cảnh báo |
|---|---|
| `generate_screen_from_text` | *"This action can take a few minutes… DO NOT RETRY."* Nếu timeout → `get_screen` mỗi 30s, tối đa 10 lần. Nếu connection error → generation vẫn có thể thành công, thử `get_screen` sau. |
| `edit_screens` | Tương tự — không retry ngay. |
| `generate_variants` | Nếu timeout → **không** retry; dùng `get_screen` để kiểm tra. |
| `upload_design_md` | Phải gọi `create_design_system_from_design_md` **ngay sau** để tạo design system. |
| `delete_project` | *"cannot be undone"* → phải xác nhận với user trước khi gọi. |

### 2.2 `SelectedScreenInstance` (khi apply design system)

```json
{
  "id": "<screen INSTANCE id, không phải source screen id>",
  "sourceScreen": "projects/{project}/screens/{screen}"
}
```

`id` lấy từ **`get_project`** (mảng screen instances), **không** phải từ `list_screens`.

---

## 3. Design system — đề xuất cho Sentinel Auth

### 3.1 Cấu hình `create_design_system`

`DesignSystem` = `{ displayName, theme }`, `DesignTheme` có các field bắt buộc:

| Field | Giá trị đề xuất | Ghi chú |
|---|---|---|
| `displayName` | `Sentinel Auth` | — |
| `theme.bodyFont` | `INTER` | Bảng chữ rõ ràng, phù hợp dashboard |
| `theme.headlineFont` | `INTER` | Hoặc `SPACE_GROTESK` cho phần tiêu đề |
| `theme.labelFont` | `INTER` | — |
| `theme.colorMode` | `DARK` | SOC/console thường chạy dark; nếu demo sáng thì `LIGHT` |
| `theme.colorVariant` | `NEUTRAL` hoặc `TONAL_SPOT` | `TONAL_SPOT` cho sắc xanh dịu vừa an toàn vừa khác biệt |
| `theme.customColor` | `#3B82F6` | Seed color (xanh) |
| `theme.overridePrimaryColor` | `#3B82F6` | Hành động chính |
| `theme.overrideSecondaryColor` | `#22C55E` | Thành công |
| `theme.overrideTertiaryColor` | `#F59E0B` | Cảnh báo |
| `theme.overrideNeutralColor` | `#94A3B8` | Text phụ / border |
| `theme.roundness` | `ROUND_EIGHT` | Card 8px, control 8px — dễ map sang Tailwind `rounded-card` |
| `theme.spacing` | object | Xem §3.3 |
| `theme.typography` | object | Xem §3.3 |

> ⚠️ **Stitch không có token riêng cho "danger".** Màu nguy hiểm phải do frontend định nghĩa (`--color-danger: #EF4444`) và **không** lấy từ Stitch. Tương tự `muted`/`surface`/`border` — Stitch cho `colorVariant` nhưng không map 1-1 sang các token Tailwind của ta.

### 3.2 Vì sao **không** dùng `upload_design_md`

`upload_design_md` + `create_design_system_from_design_md` là đường ưu tiên khi đã có sẵn `DESIGN.md`. Ở đây ta **chưa có** file thiết kế hoàn chỉnh, nên dùng `create_design_system` với config tường minh ở §3.1 — nhanh hơn và kiểm soát chắc hơn.

> Nếu sau này muốn mở rộng hệ thống thiết kế, có thể viết `DESIGN.md` rồi chuyển sang đường `upload_design_md`.

### 3.3 Token bridge Stitch → Tailwind

Lấy tokens từ Stitch (qua `list_design_systems` / `get_screen`), rồi map sang `@theme` trong `src/styles/index.css`:

```css
@import "tailwindcss";

@theme {
  /* --- Stitch → Tailwind --- */
  --color-primary:      #3B82F6;   /* theme.customColor / overridePrimaryColor */
  --color-secondary:    #22C55E;   /* overrideSecondaryColor */
  --color-tertiary:     #F59E0B;   /* overrideTertiaryColor */
  --color-muted:        #94A3B8;   /* overrideNeutralColor */

  /* --- Frontend-owned (KHÔNG lấy từ Stitch) --- */
  --color-surface:        #0B1220;
  --color-surface-raised: #131C2E;
  --color-border:         #1F2A3D;
  --color-danger:         #EF4444;
  --color-text:           #E2E8F0;

  /* --- Semantic aliases --- */
  --color-success: var(--color-secondary);
  --color-warning: var(--color-tertiary);

  --radius-card:   8px;   /* theme.roundness = ROUND_EIGHT */
  --radius-control: 8px;
}
```

**Quy tắc ánh xạ màu ngữ nghĩa (bắt buộc):**

| Ngữ nghĩa | Token Tailwind | Stitch source |
|---|---|---|
| Hành động chính | `--color-primary` | `overridePrimaryColor` |
| Thành công | `--color-success` | `overrideSecondaryColor` |
| Cảnh báo | `--color-warning` | `overrideTertiaryColor` |
| Nguy hiểm | `--color-danger` | **frontend-owned** |
| Text phụ | `--color-muted` | `overrideNeutralColor` |
| Nền | `--color-surface*` | **frontend-owned** |

> Component dùng **tên ngữ nghĩa** (`bg-danger`, `text-muted`), **không** dùng tên màu Stitch (`bg-tertiary`). Đổi theme Stitch sau này không làm vỡ UI.

---

## 4. Danh sách 24 screen cần thiết kế

Nhóm theo thứ tự ưu tiên. Xem [M12-PAGE-MAP.md](./M12-PAGE-MAP.md) để biết endpoint và component chi tiết của từng screen.

### Batch 1 — Nền tảng & Auth (5 screen)

| ID | Screen | Route | Ghi chú thiết kế |
|---|---|---|---|
| S-02 | Login | `/login` | Card giữa trang, gradient nền tối, nút full-width |
| S-03 | MFA Verify | `/mfa` | 6 ô OTP, auto-advance, trạng thái lỗi viền đỏ |
| S-01 | Register | `/register` | Form 1 cột, meter độ mạnh mật khẩu |
| S-04 | Trusted-device Login | `/trusted-device` | Trạng thái "chờ thiết bị khác duyệt" + polling |
| S-08 | Forbidden (403) | `/403` | Icon + lý do + CTA quay lại |

### Batch 2 — Self-service (3 screen)

| ID | Screen | Route | Ghi chú |
|---|---|---|---|
| S-05 | Sessions | `/sessions` | Bảng + badge "phiên hiện tại" + nút "Đăng xuất mọi nơi" |
| S-06 | Trusted Devices | `/devices` | Bảng thiết bị + dialog thêm + nút nguy hiểm "Bỏ tin cậy tất cả" |
| S-07 | Profile | `/profile` | Card thông tin read-only + badge vai trò |

### Batch 3 — SOC (3 screen)

| ID | Screen | Route | Ghi chú |
|---|---|---|---|
| S-20 | Alert Queue | `/alerts` | Bảng dữ liệu dày, badge risk màu, filter bar, phân trang |
| S-21 | Alert Detail | `/alerts/:id` | **Màn hình phức tạp nhất**: header + action bar + 3 tab (Tổng quan / Bằng chứng / Timeline) |
| S-22 | Login History | `/login-history` | Bảng + date range picker + filter nâng cao |

### Batch 4 — Admin (2 screen)

| ID | Screen | Route | Ghi chú |
|---|---|---|---|
| S-10 | User Management | `/admin/users` | Bảng user + menu hành động + 4 dialog (role/lock/mfa) |
| S-11 | Audit Logs | `/admin/audit-logs` | Bảng + drawer xem JSON `before_state`/`after_state` |

### Batch 5 — Policies (3 screen)

| ID | Screen | Route | Ghi chú |
|---|---|---|---|
| S-30 | Policy List | `/policies` | Bảng + badge "Active" + confirm dialog activate |
| S-31 | Policy Detail | `/policies/:id` | Meta + bảng rules + config viewer + banner "immutable" |
| S-32 | Policy Editor | `/policies/new`, `/policies/:id/edit` | **Form phức tạp nhất**: rule builder dạng lặp, weights + thresholds |

### Batch 6 — Manager (5 screen)

| ID | Screen | Route | Ghi chú |
|---|---|---|---|
| S-40 | Dashboard | `/manager` | Lưới KPI + 3 section card (Core/Detection/ML) + biểu đồ |
| S-41 | Trends | `/manager/trends` | 3 biệt đồ + chọn bucket + chọn khoảng thời gian |
| S-42 | Alert Analytics | `/manager/alerts` | KPI + donut + bar + bảng backlog |
| S-43 | SOC KPI | `/manager/soc-kpi` | Lưới KPI card, cần style riêng cho giá trị "—" |
| S-44 | ML Stats | `/manager/ml-stats` | Model info + bảng versions + biểu đồ feature |

### Batch 7 — Hệ thống (3 screen)

| ID | Screen | Route | Ghi chú |
|---|---|---|---|
| S-90 | Not Found | `/*` | Tối giản |
| S-91 | Global Error | — | Tối giản, có chỗ hiển thị `request_id` |
| S-92 | Service Status | `/status` | Badge "sẵn sàng"/"chưa sẵn sàng" |

---

## 5. Prompt mẫu cho Stitch

Prompt phải mô tả **layout + dữ liệu giả có hình dạng đúng**, không mô tả logic.

### 5.1 S-02 — Login

```
Design a security operations console login screen for "Sentinel Auth".

Layout: centered card on a dark gradient background, max-width 400px.
Card contains: product logo and wordmark "Sentinel Auth" at top;
a heading "Đăng nhập"; a username text input with placeholder "Tên đăng nhập";
a password input with a visible show/hide toggle icon; a full-width primary
blue button labeled "Đăng nhập"; a small muted text link "Quên mật khẩu?";
and a divider "Hoặc" with a secondary outlined button "Đăng ký tài khoản".

Show an inline error state below the password field: red border and red
helper text "Sai tài khoản hoặc mật khẩu".

Below the card, centered muted text: "Hệ thống phát hiện đăng nhập bất thường
và giám sát phiên làm việc của bạn".

Style: dark mode, Inter font, 8px corner radius, subtle border, no gradients
on the card itself.
```

### 5.2 S-21 — Alert Detail (màn hình quan trọng nhất)

```
Design a security alert detail screen for a SOC analyst console named
"Sentinel Auth".

Layout: two columns, 2fr / 1fr gap 24px, on a dark background.

Left column:
- Alert header card: severity badge "CRITICAL" in red, title "Đăng nhập bất
  thường — admin@example.com", and 3 small meta rows (detection reason,
  risk score 0.87, created time "10/11/2026 14:02").
- A horizontal action bar card with 4 buttons: primary blue "Acknowledge",
  outlined "Phân công", outlined "Yêu cầu hành động bảo vệ" in red tint,
  and a ghost "Ghi chú".
- Below, a tab bar with 3 tabs: "Tổng quan", "Bằng chứng", "Dòng thời gian";
  "Tổng quan" is active.
- A "Điểm rủi ro" card with 3 score rows: Rule score 0.62, ML score 0.81,
  Tổng 0.87 — each as a horizontal progress bar with its value on the right.
- A "Quy tắc kích hoạt" table with 4 columns: Quy tắc, Trường, Toán tử,
  Điểm; 3 rows of realistic rule names.

Right column:
- A card "Thông tin đăng nhập" with key/value rows: IP 203.0.113.42,
  User Agent, Thiết bị mới, MFA Có.
- A card "Dòng thời gian" with a vertical timeline of 4 entries, each with a
  colored dot, event label, actor and time.

Style: dark mode, Inter, 8px radius, dense data tables, muted secondary text.
```

### 5.3 S-32 — Policy Editor

```
Design a detection policy editor screen for a security admin console.

Layout: single column form, max-width 900px, dark background.
- Header: back arrow, title "Sửa policy", version tag "v1.2" in a read-only
  grey chip (version is immutable), and a Save button top-right.
- A sticky banner card in amber tint: "Policy đã từng được kích hoạt nên bị
  đóng băng. Hãy tạo version mới." — with a secondary button "Tạo version mới".
- Section "Thông tin": two inputs side by side (Tên, Mô tả).
- Section "Quy tắc phát hiện": a repeatable list of 2 rule cards. Each rule
  card has inputs: Tên quy tắc, a select "Trường" (fail_count_24h), a select
  "Toán tử" (>), a number input "Giá trị" (10), two small number inputs
  "Trọng số" (0.5) and "Điểm" (0.7), an enabled toggle, and a delete icon
  button. Below the list, a dashed-outline button "+ Thêm quy tắc".
- Section "Cấu hình": two number inputs side by side for weights
  ("Rule 0.4", "ML 0.6") with a muted helper "Tổng phải bằng 1.0"; and three
  number inputs in a row for thresholds ("Low 0.25", "Medium 0.50", "High 0.75").
- A footer bar with a secondary "Huỷ" and a primary "Lưu thay đổi".

Style: dark mode, Inter, dense form, clear section separators.
```

### 5.4 S-40 — Manager Dashboard

```
Design a security overview dashboard for a CISO console named "Sentinel Auth".

Layout: dark background, page header with title "Tổng quan an ninh" and on
the right a date-range picker chip "24 giờ gần nhất" plus a refresh icon button.
- An amber warning banner across the top: "Một số nguồn dữ liệu không khả
  dụng: core (không kết nối được tới nguồn dữ liệu)" with a "Thử lại" link.
- A 4-column KPI grid, 4 cards: "Tổng người dùng 1.284", "Phiên hoạt động 342",
  "Cảnh báo đang mở 27" (in amber), "Tỷ lệ bất thường ML 4.2%" (in green).
- Then a 2-column grid of three section cards:
  Card 1 "Core" — 6 small stat rows.
  Card 2 "Detection" — a horizontal bar chart of 4 risk levels (low/medium/
  high/critical) with the critical bar in red.
  Card 3 "Machine Learning" — a small line chart of 7 daily points, plus a
  line "Model: v3.2.1 — sẵn sàng".
- One card shows an empty state instead of data: dashed border, centered text
  "Không có dữ liệu" and muted subtext "Nguồn dữ liệu không khả dụng".

Style: dark mode, Inter, 8px radius, chart accent colors follow semantic
palette (blue primary, red danger, amber warning, green success).
```

---

## 6. Quy trình Stitch đề xuất

```
① create_project(title="Sentinel Auth")
        ↓
② create_design_system(designSystem={displayName:"Sentinel Auth", theme:{...}})
        ↓
③ generate_screen_from_text(projectId, designSystem=<id>, prompt=..., deviceType="desktop")
        ↓
④ get_screen / list_screens → review
        ↓
⑤ (tuỳ chọn) generate_variants → chọn phương án → edit_screens để tinh chỉnh
        ↓
⑥ apply_design_system(assetId, projectId, selectedScreenInstances[...])
        ↓
⑦ download_file(name=<html_code.name>) → tham khảo layout khi code Tailwind
```

### 6.1 Quy tắc thực thi

| # | Quy tắc |
|---|---|
| ST1 | **Sinh screen theo batch**, không sinh 24 screen một lúc. Mỗi batch ≤ 5 screen. |
| ST2 | **Luôn truyền `designSystem`** khi generate screen (trừ screen đầu tiên của project mới). |
| ST3 | `deviceType="desktop"` cho toàn bộ — đây là console quản trị, không phải mobile app. |
| ST4 | **Không retry** `generate_screen_from_text` khi timeout. Dùng `get_screen` mỗi 30s, tối đa 10 lần. |
| ST5 | Sau mỗi batch: **review ảnh** với `get_screen` / `download_file` (screenshot) trước khi sinh batch tiếp. |
| ST6 | Dùng `generate_variants` cho S-21 và S-32 (2 màn hình khó nhất) → chọn phương án tốt nhất → `edit_screens` để hoàn thiện. |
| ST7 | `apply_design_system` sau khi có **design system ổn định** và **nhiều screen** — dùng `selectedScreenInstances` lấy từ `get_project`. |
| ST8 | **Không** `delete_project` nếu chưa hỏi user. |
| ST9 | Mọi prompt phải mô tả **dữ liệu giả có hình dạng đúng** (số dòng bảng, số card, tên field thật) — không mô tả chung chung. |
| ST10 | **Không** yêu cầu Stitch sinh code React. Chỉ `html_code` + `screenshot` làm tham khảo. |

---

## 7. Ánh xạ Stitch → React (bước chuyển giao)

| Từ Stitch | Sang React | Nơi đặt |
|---|---|---|
| `theme.customColor`, `override*Color` | `@theme` CSS variables | `src/styles/index.css` |
| `theme.bodyFont` / `headlineFont` | `--font-sans`, `--font-display` trong `@theme` | `src/styles/index.css` |
| `theme.roundness` | `--radius-card`, `--radius-control` | `src/styles/index.css` |
| `theme.spacing` | scale Tailwind mặc định (4px base) | không cần map |
| `theme.typography` | scale typography Tailwind | không cần map |
| Layout/bố cục của 1 screen | Layout của page component tương ứng | `src/features/*/pages/` |
| Màu cụ thể trong HTML | **KHÔNG** copy; dùng token ngữ nghĩa | `src/shared/components/` |
| Bảng | `DataTable` dùng chung | `src/shared/components/DataTable.tsx` |
| Badge màu | `RiskBadge` / `StatusBadge` | `src/shared/components/` |
| Card/panel | `Card` | `src/shared/components/` |
| Form field | `TextInput` / `Select` / `PasswordInput` | `src/shared/components/` |
| Modal | `Dialog` | `src/shared/components/` |
| Warning banner | `Banner` (tone: warning) | `src/shared/components/` |
| Empty state | `EmptyState` | `src/shared/components/` |
| Charts | `Recharts` component tương ứng | `src/features/manager/components/` |

### 7.1 Những thứ Stitch **không** thể thiết kế được

| Hành vi | Vì sao | Xử lý |
|---|---|---|
| Trạng thái `degraded` / `null` của Manager | Phụ thuộc runtime API | Thiết kế 1 screen với **2 biến thể**: có dữ liệu + empty state. Prompt mô tả cả hai. |
| 3 biến thể 409 của policy | Phụ thuộc runtime | Thiết kế 1 banner cảnh báo tái sử dụng cho cả 3. |
| 502 protective action | Phụ thuộc runtime | Toast/alert màu đỏ + text "KHÔNG được áp dụng". |
| Badge "phiên hiện tại" | Phụ thuộc dữ liệu | Có thể thiết kế — chỉ cần 1 variant badge. |
| Trạng thái disabled của nút | Phụ thuộc runtime | Thiết kế nút primary + outline + disabled + danger. |
| Đồng hồ đếm ngược MFA | Phụ thuộc runtime | Chỉ cần style ô OTP + text phụ. |

> **Bí kíp:** Khi prompt một screen, **luôn mô tả thêm 1 trạng thái lỗi/empty**. Ví dụ S-21: thêm "an inline error banner in red: 'Hành động KHÔNG được áp dụng'". Stitch sẽ cho layout đúng cho cả trạng thái lỗi mà không cần sinh thêm screen.

---

## 8. Definition of Done cho phần Stitch

- [ ] `create_project` xong, `projectId` lưu lại.
- [ ] `create_design_system` xong với config §3.1, `assetId` lưu lại.
- [ ] Đủ **24 screen** trong project (có thể một số screen gộp bản vẽ — chấp nhận nếu layout giống nhau).
- [ ] Mỗi screen có `screenshot` để review.
- [ ] Tokens đã map sang `@theme` trong `src/styles/index.css`.
- [ ] `apply_design_system` đã áp lên toàn bộ screen ⇒ **tất cả screen cùng một hệ màu**.
- [ ] Tất cả màu trong component React dùng **token ngữ nghĩa**, không dùng hex từ Stitch.
- [ ] Không có màn hình nào chứa logic/giả lập API trong HTML sinh ra.

---

## 9. Câu hỏi thường gặp

| Câu hỏi | Trả lời |
|---|---|
| Stitch có sinh được component React dùng luôn không? | Không theo cách này. Stitch sinh `html_code`; ta lấy layout làm tham khảo và dựng component Tailwind thật. |
| Có cần 24 screen riêng biệt không? | Không bắt buộc. Có thể gộp các screen gần giống (VD: 5 Manager screens dùng chung 1 shell). Nhưng **24 màn hình theo page map** là mục tiêu để đảm bảo không sót. |
| Làm sao để Stitch hiểu `degraded` state? | Mô tả bằng ngôn ngữ thiết kế: "a card showing an empty state with muted text 'Không có dữ liệu' and subtext 'Nguồn dữ liệu không khả dụng'". Không dùng từ khoá API. |
| Đổi design system sau khi đã sinh 24 screen? | `update_design_system` rồi `apply_design_system` lên toàn bộ screen instances (lấy từ `get_project`). |
| Stitch có biết về enum/contract backend không? | Không. Prompt phải mô tả **giá trị hiển thị** (VD: badge "CRITICAL", select có option `fail_count_24h`), không mô tả API. |
