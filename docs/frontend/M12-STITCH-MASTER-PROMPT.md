# M12.4 — Stitch Master Prompt (Sentinel Auth v3.3)

**Baseline:** `origin/dev` @ `6839be7`
**Mục đích:** Một prompt "master" duy nhất để sinh **24 màn hình** của Sentinel Auth trong Stitch, đảm bảo một design system thống nhất và một bốn vai trò nhất quán.
**Stitch project:** `projects/6351989476271203310` — *Sentinel Auth Security Operations Platform*
**Design system asset:** `assets/82164d4ec352432ba8c6232f8195c642` — *Sentinel Telemetry Operator*

> **Quy tắc:** Stitch sinh **presentation** (layout, component, form, table, chart, typography, design token, responsive). Cursor giữ **functionality** (routing, API, state, role gating, mutation, test). Không có màn hình nào của Stitch chứa logic; không có endpoint nào được bịa ra.

---

## 0. Vì sao dùng project có sẵn thay vì tạo project mới

Project Stitch `6351989476271203310` (tạo 2026-11-01) đã có:

| Hạng mục | Trạng thái |
|---|---|
| Design system | **"Sentinel Telemetry Operator"** — brutalist dark SOC console, đầy đủ `designMd` + `styleGuidelines` + token JSON |
| Screen | `SOC Alerts - Cảnh báo bảo mật` (S-20) — bản vẽ tham chiếu |
| Screen | `Manager Dashboard - Bảng điều khiển Quản lý An ninh` (S-40) — bản vẽ tham chiếu |
| Screen | `Alert Details - Chi tiết cảnh báo ALT-2025-0891` (S-21) — sinh từ prompt bên dưới |

Design system này **khớp** với `M12-STITCH-HANDOFF.md` §3 (dark, Inter→ nhưng đã đổi sang Space Grotesk/Geist, primary xanh-teal, 8px→0 radius). Vì vậy:

- **Không** tạo project mới (`6844955677292508142` đã tạo nhưng bị bỏ — rỗng, không dùng).
- **Không** `apply_design_system` lại: 3 screen đã mang đúng design system.
- Mọi screen mới sinh bằng `designSystem: "assets/82164d4ec352432ba8c6232f8195c642"`.

---

## 1. Design system — "Sentinel Telemetry Operator" (nguồn chân lý)

### 1.1 Bảng màu Stitch → token ngữ nghĩa của frontend

Stitch dùng hệ Material-ish (`primary`, `surface-container`, `on-surface`…). Frontend **KHÔNG** dùng tên đó — dùng tên ngữ nghĩa, để đổi theme Stitch sau này không phá UI.

| Ngữ nghĩa | Stitch source | Token Tailwind | Hex |
|---|---|---|---|
| Canvas | `background` / `surface` | `--color-surface` | `#0B1220` |
| Panel cấp 1 (sidebar, header) | — (Stitch: `surface-container-low` là `#151b2a`) | `--color-panel` | `#111827` |
| Card / data cell | — (Stitch: `surface-container` là `#19202e`) | `--color-surface-raised` | `#182235` |
| Viền lưới | — | `--color-border` | `#1E293B` |
| Viền focus | — | `--color-border-strong` | `#334155` |
| Hành động chính | `primary-container` / `customColor` | `--color-primary` | `#14B8A6` |
| Text trên primary | `on-primary-container` | `--color-on-primary` | `#020617` |
| Beacon phụ | `secondary` | `--color-secondary` | `#22D3EE` |
| Thành công / risk low | `tertiary-fixed-dim` | `--color-success` | `#10B981` |
| Cảnh báo / risk medium | `tertiary` | `--color-warning` | `#F59E0B` |
| Risk high | — (frontend-owned) | `--color-risk-high` | `#F97316` |
| Nguy hiểm / risk critical | `error-container` | `--color-danger` | `#EF4444` |
| Degraded / source down | — (frontend-owned) | `--color-degraded` | `#64748B` |
| Text chính | `on-surface` | `--color-text` | `#F8FAFC` |
| Text phụ | `on-surface-variant` / `outline` | `--color-text-muted` | `#94A3B8` |

> **Đường ranh giới an toàn:** `danger`, `risk-high`, `degraded`, `surface`, `panel`, `surface-raised`, `border` là **frontend-owned** — Stitch không có token tương đương 1-1. Chỉ `primary`, `secondary`, `warning`, `success`, `text`, `text-muted` lấy từ Stitch.

### 1.2 Shape & typography

| Token | Stitch | Tailwind |
|---|---|---|
| Radius | **0** (brutalist, vuông tuyệt đối) | `--radius-card: 0px`, `--radius-control: 0px` |
| Heading font | Space Grotesk | `--font-display` |
| Body font | Geist | `--font-sans` |
| Technical / mono | JetBrains Mono | `--font-mono` |
| Label | uppercase 10–11px, `letterSpacing 0.06–0.08em` | dùng class `label-*` |

> ⚠️ **Khác biệt với code hiện tại:** `src/styles/index.css` đang dùng token **sáng** (`--color-surface: #ffffff`, `--color-brand-500: #6366f1`, `rounded-md`). Bridge sang Stitch là **một PR riêng** (Task 2b), không trộn vào PR chức năng.

---

## 2. Sáu trạng thái bắt buộc trên MỌI màn hình

Stitch không hiểu runtime API, nên **mỗi prompt phải mô tả cả 6 trạng thái bằng ngôn ngữ thiết kế** (không dùng từ khoá API):

| # | Trạng thái | Mô tả cho Stitch (ngôn ngữ thiết kế) |
|---|---|---|
| 1 | **Loading** | "a card showing grey skeleton placeholder rows (three dashed placeholder bars) with a small spinner" |
| 2 | **Empty** | "a card with a dashed 1px border, a centred icon, the text 'Không có dữ liệu' and a muted sub-line" |
| 3 | **Error** | "a card with a red left border, a red heading 'Không thể tải dữ liệu', a muted reason line and a bordered 'Thử lại' button" |
| 4 | **Forbidden** | "a full-width amber-bordered notice 'Bạn không có quyền truy cập màn hình này' with a primary 'Về trang phù hợp với vai trò của bạn' button" |
| 5 | **Degraded** | "an amber banner across the top 'Một số nguồn dữ liệu không khả dụng: core (không kết nối được)' with a 'Thử lại' link, and the affected card replaced by an empty state reading 'Nguồn dữ liệu không khả dụng'" |
| 6 | **Confirmation** | "a modal on an opaque 85% #050811 curtain, 0 radius, 1px border, title 'Xác nhận', body text, a secondary 'Huỷ' button and a primary confirm button" |

> **Bí kíp từ `M12-STITCH-HANDOFF.md` §7.1:** luôn mô tả thêm 1 trạng thái lỗi/empty trong cùng prompt. Stitch cho layout đúng cho cả hai mà không cần sinh thêm screen.

---

## 3. Bốn vai trò — menu và landing page

Menu được dựng **động** từ `roles` của `GET /auth/me`. Stitch chỉ cần vẽ **4 biến thể sidebar**; code sinh menu từ `policy.ts`.

| Vai trò | Landing | Menu (theo thứ tự hiển thị) |
|---|---|---|
| `USER` | `/sessions` | Phiên đăng nhập · Thiết bị tin cậy · Hồ sơ |
| `SOC_ANALYST` | `/alerts` | Cảnh báo · Lịch sử đăng nhập · Phiên đăng nhập · Thiết bị tin cậy · Hồ sơ |
| `SECURITY_ADMIN` | `/admin/users` | Người dùng · Nhật ký kiểm toán · Chính sách phát hiện · Phiên đăng nhập · Thiết bị tin cậy · Hồ sơ |
| `SECURITY_MANAGER` | `/manager` | Tổng quan · Xu hướng · Phân tích cảnh báo · KPI SOC · Thống kê ML · Chính sách phát hiện · Cảnh báo · Phiên đăng nhập · Thiết bị tin cậy · Hồ sơ |

**Sidebar (chung 4 vai trò):**
- Nền `#111827`, viền phải `1px #1E293B`, rộng 240px (thu gọn 64px).
- Item active: nền `#182235`, **gạch trái 3px `#14B8A6`**, chữ `#F8FAFC`.
- Item không active: chữ `#94A3B8`.
- Nhãn uppercase 11px, `letterSpacing 0.06em`.
- Nhóm cách nhau bằng 1px `#1E293B`; cuối cột có "Đăng xuất".

---

## 4. Bản vẽ 24 màn hình

| ID | Screen | Route | Batch | Vai trò |
|---|---|---|---|---|
| S-01 | Register | `/register` | 1 | Public |
| S-02 | Login | `/login` | 1 | Public |
| S-03 | MFA Verify | `/mfa` | 1 | Public |
| S-04 | Trusted-device Login | `/trusted-device` | 1 | Public |
| S-08 | Forbidden | `/403` | 1 | Authenticated |
| S-05 | Sessions | `/sessions` | 2 | Mọi role |
| S-06 | Trusted Devices | `/devices` | 2 | Mọi role |
| S-07 | Profile | `/profile` | 2 | Mọi role |
| S-20 | Alert Queue | `/alerts` | 3 | SOC / Manager |
| S-21 | Alert Detail | `/alerts/:id` | 3 | SOC / Manager |
| S-22 | Login History | `/login-history` | 3 | SOC / Manager |
| S-10 | User Management | `/admin/users` | 4 | Admin |
| S-11 | Audit Logs | `/admin/audit-logs` | 4 | Admin |
| S-30 | Policy List | `/policies` | 5 | Admin / Manager |
| S-31 | Policy Detail | `/policies/:id` | 5 | Admin / Manager |
| S-32 | Policy Editor | `/policies/new`, `/policies/:id/edit` | 5 | Admin |
| S-40 | Manager Dashboard | `/manager` | 6 | Manager |
| S-41 | Trends | `/manager/trends` | 6 | Manager |
| S-42 | Alert Analytics | `/manager/alerts` | 6 | Manager |
| S-43 | SOC KPI | `/manager/soc-kpi` | 6 | Manager |
| S-44 | ML Stats | `/manager/ml-stats` | 6 | Manager |
| S-90 | Not Found | `/*` | 7 | Authenticated |
| S-91 | Global Error | — | 7 | Authenticated |
| S-92 | Service Status | `/status` | 7 | Authenticated |

**Quy tắc batch (ST1–ST10 trong `M12-STITCH-HANDOFF.md` §6.1):** mỗi batch ≤ 5 screen · luôn truyền `designSystem` · `deviceType="DESKTOP"` · **không retry** khi timeout (poll `get_screen` mỗi 30s, tối đa 10 lần) · review screenshot sau mỗi batch · `generate_variants` cho S-21 và S-32 · **không** `delete_project`.

---

## 5. Prompt mẫu — Batch 1 (Auth, 5 screen)

> Prompt dưới đây là **template**. Mỗi screen được gọi riêng với `generate_screen_from_text`, cùng `designSystem: "assets/82164d4ec352432ba8c6232f8195c642"`, `deviceType: "DESKTOP"`, `projectId: "6351989476271203310"`.

```
Design the LOGIN screen for Sentinel Auth v3.3, following the existing
"Sentinel Telemetry Operator" design system in this project.

Vietnamese UI labels. Use the SAME dark canvas #0B1220, card surface #182235,
1px #1E293B borders, ZERO border radius, Space Grotesk headings and Geist body
as the existing screens in this project.

Layout: full page, canvas #0B1220. A single centred card, max-width 400px,
surface #182235, 1px border #1E293B, radius 0.

Card content top to bottom:
1. A 24px teal #14B8A6 shield mark beside the wordmark "Sentinel Auth" in
   Space Grotesk 15px semibold #F8FAFC.
2. Heading "Đăng nhập" in Space Grotesk 22px #F8FAFC.
3. Label "TÊN ĐĂNG NHẬP" uppercase 11px #94A3B8 letterSpacing 0.08em above a
   full-width input, 40px tall, background #0B1220, 1px border #1E293B,
   radius 0, placeholder "Tên đăng nhập" in #64748B.
4. Label "MẬT KHẨU" above a full-width password input with a small eye /
   eye-off toggle icon on the right edge.
5. The password input is shown in its ERROR state: the 1px border is
   #EF4444 and a 13px #EF4444 helper line under it reads
   "Sai tài khoản hoặc mật khẩu".
6. A full-width primary button, 40px tall, background #14B8A6, radius 0,
   label "ĐĂNG NHẬP" in #020617 semibold uppercase 13px.
7. A right-aligned muted link "Quên mật khẩu?" 13px #94A3B8.
8. A 1px #1E293B horizontal divider with the centred muted word "HOẶC".
9. A full-width outlined button, transparent background, 1px #334155 border,
   label "ĐĂNG KÝ TÀI KHOẢN" in #F8FAFC.

Below the card, centred 13px #94A3B8 text on two lines: "Hệ thống phát hiện
đăng nhập bất thường" and "và giám sát phiên làm việc của bạn".

Also show, in a small area below the card, the three inline states as compact
variants so the layout is defined for them too: a grey skeleton placeholder
variant (three dashed bars) for loading, and a dashed-border card reading
"Không có dữ liệu" for the empty state.
```

### 5.1 Prompt mẫu — S-03 MFA Verify

```
Design the MFA VERIFICATION screen for Sentinel Auth v3.3, following the
"Sentinel Telemetry Operator" design system in this project.

Vietnamese UI labels. Dark canvas #0B1220, card surface #182235, 1px #1E293B
borders, ZERO border radius, Space Grotesk headings, Geist body.

A centred card, max-width 400px, surface #182235:
1. Heading "Xác thực hai yếu tố" Space Grotesk 20px #F8FAFC, and a muted
   13px line "Nhập mã 6 chữ số được gửi tới email của bạn".
2. A row of six separate 48x56 OTP boxes, 1px #1E293B border, radius 0,
   background #0B1220, centred mono digits, the third box active with a
   #14B8A6 border and a teal caret.
3. Under the boxes, a 13px #EF4444 helper line "Mã không đúng. Còn 2 lần thử."
   and the sixth box border in #EF4444.
4. A full-width primary button "XÁC NHẬN", 40px, #14B8A6 background,
   #020617 text, radius 0.
5. A ghost link "Quay lại đăng nhập" centred, 13px #94A3B8.
6. A muted footer line "Mã có hiệu lực trong 5 phút".

Include one small muted line for the loading variant: a spinner beside the
button and the button label "ĐANG XÁC NHẬN" in #64748B.
```

### 5.2 Prompt mẫu — S-32 Policy Editor (màn hình form khó nhất)

```
Design the DETECTION POLICY EDITOR screen for Sentinel Auth v3.3, following
the "Sentinel Telemetry Operator" design system in this project.

Vietnamese UI labels. Dark canvas #0B1220, card surface #182235, 1px #1E293B
borders, ZERO border radius, Space Grotesk headings, Geist body, JetBrains Mono
for version tags and numeric values.

Layout: a full-width form, max-width 960px, centred.
- Header row: a back chevron, title "Sửa chính sách" Space Grotesk 18px
  #F8FAFC, a read-only mono chip "v1.2" in #64748B on a #0B1220 background
  with a 1px #1E293B border, and a primary button "LƯU THAY ĐỔI" on the right.
- An amber notice banner spanning the form: 1px #F59E0B border, #F59E0B at
  10% background, text "Chính sách đã từng được kích hoạt nên bị đóng băng.
  Hãy tạo phiên bản mới." in #F59E0B, with a secondary bordered button
  "Tạo phiên bản mới".
- Section card "THÔNG TIN": two inputs side by side — "Tên" (filled
  "Phát hiện đăng nhập bất thường") and "Mô tả" (filled "Quy tắc heuristic kết
  hợp mô hình Isolation Forest").
- Section card "QUY TẮC PHÁT HIỆN": a repeatable list of two rule cards on
  #0B1220 with a 1px #1E293B border. Each rule card has, on one row: an input
  "Tên quy tắc" (filled "fail_count_24h"), a select "Trường" (showing
  "fail_count_24h"), a select "Toán tử" (showing ">"), a number input "Giá trị"
  (showing 10), a number input "Trọng số" (showing 0.5), a number input "Điểm"
  (showing 0.7), an enabled toggle in teal, and a red square delete icon
  button. Below the list a dashed-border full-width button "+ THÊM QUY TẮC".
- Section card "CẤU HÌNH": two number inputs side by side labelled "Trọng số
  rule" (0.4) and "Trọng số ML" (0.6) with a muted helper "Tổng phải bằng
  1.0"; then three number inputs in a row labelled "Ngưỡng thấp" (0.25),
  "Ngưỡng trung bình" (0.50), "Ngưỡng cao" (0.75).
- A footer bar with a secondary "HUỶ" button and a primary "LƯU THAY ĐỔI".

Also include, inside the first rule card, the invalid state of one field: a
1px #EF4444 border and a 13px #EF4444 helper "Giá trị phải là một số".
```

---

## 6. Điều Stitch **không** được thiết kế (code phải tự lo)

| Hành vi | Vì sao | Xử lý trong code |
|---|---|---|
| `degraded` / `null` của Manager | Phụ thuộc runtime API | Prompt mô tả empty-state bằng ngôn ngữ thiết kế; code quyết định `null` ≠ `0` |
| 3 biến thể 409 của policy | Phụ thuộc runtime | 1 banner cảnh báo tái sử dụng; code chọn nội dung theo `detail.message` |
| 502 protective action | Phụ thuộc runtime | Alert đỏ "HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG"; **không** hiện success |
| `assigned_to_id` free-text UUID | Gap G-1 (không có endpoint list SOC analyst) | Input UUID có validate format |
| Đồng hồ đếm lược MFA | Phụ thuộc runtime | Chỉ style ô OTP + text phụ |
| Phân trang policy | `GET /policies` trả mảng thô, không `total` | Không vẽ phân trang cho S-30 |

---

## 7. Bridge Stitch → React

### 7.1 `@theme` trong `src/styles/index.css`

```css
@import 'tailwindcss';

@theme {
  /* --- Stitch: Sentinel Telemetry Operator --- */
  --color-primary: #14b8a6;
  --color-on-primary: #020617;
  --color-secondary: #22d3ee;
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-danger: #ef4444;

  --color-text: #f8fafc;
  --color-text-muted: #94a3b8;

  /* --- Frontend-owned (KHÔNG lấy từ Stitch) --- */
  --color-surface: #0b1220;
  --color-panel: #111827;
  --color-surface-raised: #182235;
  --color-border: #1e293b;
  --color-border-strong: #334155;
  --color-risk-high: #f97316;
  --color-degraded: #64748b;

  --radius-card: 0px;
  --radius-control: 0px;

  --font-display: 'Space Grotesk', ui-sans-serif, system-ui, sans-serif;
  --font-sans: 'Geist', ui-sans-serif, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
}
```

### 7.2 Quy tắc bắt buộc

| # | Quy tắc |
|---|---|
| ST-B1 | Component dùng **tên ngữ nghĩa** (`bg-surface-raised`, `text-text-muted`), **không** dùng tên màu Stitch (`bg-primary-container`). |
| ST-B2 | **Không** copy HTML từ Stitch vào `src/shared/components/`. Stitch là nguồn *style*, không phải nguồn *component*. |
| ST-B3 | `DataTable`, `Pagination`, `Button`, `Input`, `Badge`, `ConfirmDialog`, `EmptyState`, `ErrorState` giữ nguyên API; chỉ đổi class token. |
| ST-B4 | Bảng dùng `DataTable`; badge dùng `RiskBadge` / `StatusBadge`; card dùng `Card`; form dùng `TextInput`/`Select`/`PasswordInput`; modal dùng `Dialog`. |
| ST-B5 | Chart dùng `Recharts`, palette theo token ngữ nghĩa (`--color-primary`, `--color-danger`, `--color-warning`, `--color-success`). |
| ST-B6 | Font được nạp qua `@fontsource/*` hoặc Google Fonts link trong `index.html` — **không** nhúng binary font vào repo. |

---

## 8. Definition of Done — phần Stitch

- [x] `create_project` — *dùng project có sẵn `6351989476271203310`; project rỗng `6844955677292508142` không dùng*
- [x] `create_design_system` — dùng asset có sẵn `82164d4ec352432ba8c6232f8195c642` ("Sentinel Telemetry Operator")
- [ ] Đủ **24 screen** trong project, mỗi screen có `screenshot` để review
- [ ] Screenshot mỗi batch được review trước khi sinh batch kế tiếp
- [ ] Tokens đã map sang `@theme` trong `src/styles/index.css`
- [ ] Không màn hình nào chứa logic / giả lập API trong HTML sinh ra
- [ ] Không màn hình nào chứa secret (`INTERNAL_SECRET`, `X-Internal-Secret`)

---

## 9. Gap backend được ghi nhận (không tự tạo API)

| ID | Gap | Ảnh hưởng UI | Xử lý |
|---|---|---|---|
| G-1 | Không có endpoint list `soc_analysts` | `POST /alerts/{id}/assign` cần `soc_analysts.id` | Input UUID có validate format + hướng dẫn "copy từ DB". **Đề xuất thay đổi riêng:** `GET /api/v1/soc/analysts`. |
| G-2 | `GET /admin/users` không trả `soc_analysts.id` | Không map user → analyst | Chấp nhận. |
| G-6 | `GET /policies` trả mảng thô, không `total` | Không có phân trang S-30 | Chấp nhận — không vẽ phân trang. |
| G-8 | `AlertEscalateRequest` có schema nhưng **không có route** | — | **Không** dùng `escalate`. |
| G-9 | `AlertNoteRequest` có schema nhưng **không có route** | Ghi chú | Ghi qua `POST /alerts/{id}/timeline` với `event_type: "note_added"`, tự giới hạn 2000 ký tự. |

> **Không** có endpoint nào được thêm vào backend trong phạm vi này. Hai đề xuất (G-1) được ghi riêng và **không** gộp vào PR frontend.
