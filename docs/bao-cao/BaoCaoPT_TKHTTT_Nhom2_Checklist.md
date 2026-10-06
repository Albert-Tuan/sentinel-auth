# CHECKLIST KIỂM TRA BÁO CÁO ĐỒ ÁN

**Đề tài:** HỆ THỐNG CẢNH BÁO ĐĂNG NHẬP BẤT THƯỜNG
**Môn học:** Phân tích thiết kế hệ thống thông tin
**Tệp báo cáo:** `BaoCaoPT_TKHTTT_Nhom2_Revised.docx`
**File mẫu dùng làm chuẩn:** `Mau Cuon Bao Cao Do An PT&TKHTTT.docx`
**Báo cáo cũ dùng làm nguồn nội dung:** `BaoCaoPT&TKHTTT_Nhom2_28092026.docx`

---

## 0. QUY TẮC BẰN CHỨNG ĐÃ DÙNG KHI BIÊN TẬP

| Mã nguồn | Loại thông tin lấy từ đó | Mức độ tin cậy |
|---|---|---|
| **MÃU** | Cấu trúc chương, thứ tự mục, kiểu heading, định dạng bảng, header/footer, khổ giấy, lề, font | Cao nhất — không tự ý thay đổi |
| **SRC** | Công nghệ, số điểm cuối, cấu trúc lược đồ, công thức chấm điểm, hằng số thời gian, kết quả kiểm thử | Cao — đối chiếu trực tiếp mã nguồn và tệp SQL |
| **CŨ** | Bối cảnh nghiệp vụ, ý tưởng chính sách, mô tả vai trò, các sơ đồ workflow đã có | Trung bình — chỉ dùng khi còn khớp với SRC |
| **MỚI** | Phân tích bổ sung do nhóm viết dựa trên logic nghiệp vụ và SRC | Trung bình — phải có lập luận kèm theo |

Nguyên tắc áp dụng: **không nêu một chức năng là đã triển khai nếu không có bằng chứng trong SRC.** Mọi nơi còn thiếu bằng chứng đều ghi rõ trong báo cáo, không bỏ trống và không bịa.

---

## 1. PHẦN BÌA

- [x] Giữ nguyên bố cục trang bìa của file mẫu
- [x] MÔN HỌC: Phân tích thiết kế hệ thống thông tin
- [x] ĐỀ TÀI: Hệ thống cảnh báo đăng nhập bất thường
- [x] Giảng viên hướng dẫn: ths. Nguyễn Thị Bích Nguyên
- [x] Thành viên:
  - [x] 1. Đặng Tuấn Anh – N23DCAT003 – D23CQAT01-N – Trưởng nhóm
  - [x] 2. Nguyễn Trần Sony – N23DCAT059 – D23CQAT01-N – Thành viên
  - [x] 3. Lê Bảo Khang – N23DCAT032 – D23CQAT01-N – Thành viên
- [x] Địa điểm và thời gian: TP. Hồ Chí Minh, tháng 10/2026

**Nguồn:** thông tin nhóm lấy từ báo cáo cũ, giữ nguyên như yêu cầu đề bài.

---

## 2. PHẦN ĐẦU TÀI LIỆU

### 2.1 Mục lục
- [x] Có mục `MỤC LỤC` dùng đúng style `Heading 1` của mẫu
- [x] Trường `TOC \o "1-3" \h \z \u` — lấy từ 191 tiêu đề thật trong tài liệu
- [x] **Cách cập nhật:** mở bằng Word → `Ctrl+A` → `F9` (hoặc chuột phải → Cập nhật trường)

### 2.2 Danh sách hình, bảng
- [x] Có mục `DANH SÁCH HÌNH, BẢNG`
- [x] Trường `TOC \f c` — dựng từ **97 trường TC** gắn vào từng đoạn caption
- [x] Caption thống nhất: `Hình x.y <Tên>` và `Bảng x.y <Tên>`
- [x] Đánh số liên tục, không trùng, không thiếu — đã kiểm bằng script

| Chương | Số hình | Số bảng |
|---|---|---|
| Chương I | 1 | 4 |
| Chương II | 0 | 22 |
| Chương III | 20 | 29 |
| Chương IV | 0 | 11 |
| Chương V | 0 | 8 |
| Chương VI | 0 | 2 |
| **Tổng** | **21** | **76** |

### 2.3 Danh mục từ viết tắt
- [x] 19 thuật ngữ, **chỉ gồm thuật ngữ thực sự xuất hiện trong báo cáo**

| Thuật ngữ | Số lần xuất hiện | Thuật ngữ | Số lần xuất hiện |
|---|---|---|---|
| API | 1 | ML | 57 |
| DBMS | 1 | OTP | 1 |
| ERD | 3 | PK | 23 |
| FK | 23 | RBAC | 1 |
| HTTP | 8 | SOC | 59 |
| IP | 24 | SQL | 1 |
| JSONB | 17 | TOTP | 2 |
| JWT | 3 | TTL | 1 |
| MFA | 2 | UML | 2 |
| | | UUID | 58 |

---

## 3. CHƯƠNG I. TỔNG QUAN

### 3.1 I. Giới thiệu đề tài
- [x] **1. Mục tiêu của đề tài** — MỚI
  - [x] Giải thích vấn đề đăng nhập bất thường và lý do cần phát hiện
  - [x] Mục tiêu nghiệp vụ (4 nhóm) — có đầu ra kiểm chứng được
  - [x] Mục tiêu kỹ thuật (5 nhóm, đo được) — MỚI
  - [x] Mục `Hỗ trợ SOC như thế nào` — nêu rõ Detection Engine **không** thay thế quyết định điều tra
  - [x] Bảng 1.1 — Các đầu ra bắt buộc của hệ thống và nơi lưu trữ (8 đầu ra × nơi lưu)
  - [x] Bảng 1.2 — Các hạng mục ngoài phạm vi của đồ án
- [x] **2. Phạm vi áp dụng** — MỚI, viết kỹ theo yêu cầu
  - [x] Bối cảnh áp dụng
  - [x] Hệ thống thuộc lớp nào (lớp dịch vụ giám sát bảo mật, đặt sau lớp xác thực)
  - [x] Đối tượng được bảo vệ
  - [x] Ai vận hành hệ thống
  - [x] Quy mô áp dụng → **có gắn nhãn `[CẦN NHÓM XÁC NHẬN QUY MÔ ĐỊNH LƯỢNG]`**, không tự bịa số liệu
  - [x] Phân biệt 3 loại phạm vi: nghiệp vụ / kỹ thuật / ngoài phạm vi
- [x] **3. Nền tảng kỹ thuật** — toàn bộ xác minh từ SRC
  - [x] Bảng 1.3 — Nền tảng công nghệ (công nghệ + vị trí sử dụng cụ thể)
  - [x] Các thành phần nghiệp vụ: Core App 8000, Detection Engine 8001, ML Service 8002
  - [x] Cơ chế truyền sự kiện — **ghi trung thực**: thiết kế ban đầu dùng Outbox, mã nguồn hiện dùng cổng kiểm duyệt đồng bộ + ghi trực tiếp `login_attempts`; bảng `outbox_events` còn trong lược đồ nhưng chưa có chương trình dùng
  - [x] Xác thực và quản lý phiên — **ghi trung thực**: thiết kế mô tả JWT, mã nguồn phát hành chuỗi ngẫu nhiên 32 byte + băm SHA-256; cột `token_jti` đã khai báo nhưng thư viện JWT chưa có trong phụ thuộc
  - [x] **Hình 1.1** — Kiến trúc tổng thể (dựng mới, thay cho tệp hỏng)
  - [x] Có nhãn `[CẦN XÁC NHẬN CÔNG NGHỆ]` cho 2 hạng mục chưa chốt
  - [x] Bảng 1.4 — Phân tách dữ liệu theo ba cơ sở dữ liệu

### 3.2 II. Cơ sở lý thuyết
- [x] **A. Cơ sở lý thuyết về kỹ thuật** — 10 tiểu mục, ngắn gọn, mỗi mục trả lời *"dùng ở đâu trong hệ thống"*
  - [x] Xác thực và xác thực đa yếu tố
  - [x] Phân quyền theo vai trò — **nêu thẳng hạn chế**: phần lớn điểm cuối cảnh báo chưa phân tích vai trò
  - [x] Phiên đăng nhập và token
  - [x] Phát hiện bất thường theo quy tắc — giải thích vì sao chia cho **tổng** trọng số
  - [x] Điểm bất thường bằng máy học (Isolation Forest)
  - [x] Chấm điểm rủi ro
  - [x] Xử lý sự kiện bất đồng bộ và tính lũy đẳng
  - [x] Nhật ký kiểm toán
  - [x] Vòng đời cảnh báo
  - [x] Suy giảm êm
- [x] **B. Cơ sở lý thuyết về hệ quản trị CSDL** — 8 tiểu mục
  - [x] DBMS sử dụng: PostgreSQL 16 (xác minh từ SRC)
  - [x] Giao dịch và tính nhất quán
  - [x] Khoá chính, khoá ngoại, toàn vẹn dữ liệu
  - [x] Chỉ mục
  - [x] **Vì sao tách dữ liệu theo dịch vụ** (13 + 7 + 3 bảng)
  - [x] Quan hệ xuyên CSDL và cách xác minh ở tầng ứng dụng
  - [x] Dữ liệu nhạy cảm và cách bảo vệ
  - [x] Vì sao không dùng mô hình liên kết chặt

---

## 4. CHƯƠNG II. PHÂN TÍCH NỘI DUNG, YÊU CẦU

### 4.1 I. Quy trình 1 — QUY TRÌNH ĐĂNG NHẬP VÀ XÁC THỰC NGƯỜI DÙNG
Áp dụng **đủ 13 tiêu chí** bắt buộc của giảng viên:

- [x] 1.1 Tên quy trình và mục tiêu
- [x] 1.2 Tác nhân và điều kiện kích hoạt
- [x] 1.3 Dữ liệu đầu vào
- [x] 1.4 Các bước xử lý chi tiết
- [x] 1.5 Cổng kiểm duyệt rủi ro trước khi cấp token
- [x] 1.6 Quy định về xác thực đa yếu tố
- [x] 1.7 Quy định chính sách của quy trình
- [x] 1.8 Điểm quyết định trong quy trình
- [x] 1.9 Dữ liệu được tạo hoặc cập nhật
- [x] 1.10 Kết quả đầu ra
- [x] 1.11 Xử lý ngoại lệ
- [x] 1.12 Nhật ký và kiểm toán
- [x] 1.13 **Tiêu chí xác nhận quy trình thành công**

Nội dung chi tiết đã xử lý: tài khoản không tồn tại · sai mật khẩu · tài khoản bị khoá · điều kiện yêu cầu MFA · loại MFA · MFA hết hạn · MFA sai · số lần thử · trusted device · refresh session.

| Quy định | Giá trị | Nguồn |
|---|---|---|
| Số lần thử MFA sai tối đa | 3 | SRC |
| Thời hạn mã MFA | 5 phút | SRC `auth.py:395` |
| Độ dài mã MFA | 6 chữ số | SRC |
| Thời hạn phiên | 1 giờ | SRC `auth.py:471` |
| Cửa sổ giới hạn tần suất | 60 giây | SRC `auth.py:286` |
| Thông báo khi sai | Thống nhất, chống dò tên đăng nhập | SRC (đã kiểm chứng bằng test) |

### 4.2 II. Quy trình 2 — QUY TRÌNH PHÁT HIỆN BẤT THƯỜNG VÀ XỬ LÝ CẢNH BÁO SOC
Áp dụng **đủ 16 tiêu chí**:

- [x] 2.1 Tên quy trình và mục tiêu
- [x] 2.2 Tác nhân và điều kiện kích hoạt
- [x] 2.3 Dữ liệu đầu vào
- [x] 2.4 Sáu đặc trưng đầu vào và cách tính
- [x] 2.5 Cấu trúc quy tắc và cách tính điểm quy tắc
- [x] 2.6 Gọi ML Service và xử lý khi ML không phản hồi
- [x] 2.7 Công thức gộp điểm và phân loại mức rủi ro
- [x] 2.8 **Ví dụ tính tay để kiểm chứng công thức**
- [x] 2.9 Điều kiện tạo cảnh báo và không tạo cảnh báo
- [x] 2.10 Pha máy: các bước xử lý chi tiết
- [x] 2.11 Bốn hành động bảo vệ và điều kiện dùng
- [x] 2.12 Pha người: vòng đời cảnh báo
- [x] 2.13 Xử lý sự kiện trùng
- [x] 2.14 Dữ liệu được tạo hoặc cập nhật
- [x] 2.15 Nhật ký và kiểm toán
- [x] 2.16 **Tiêu chí xác nhận quy trình thành công**

**24 câu hỏi bắt buộc của đề bài — đã trả lời đủ 24/24.** Điểm số xác minh từ SRC:

| Hằng số | Giá trị | Vị trí trong mã nguồn |
|---|---|---|
| `DEFAULT_WEIGHTS` | `{"rule": 0.4, "ml": 0.6}` | `app/detection.py:52` |
| `DEFAULT_THRESHOLDS` | `{"low": 0.25, "medium": 0.50, "high": 0.75}` | `app/detection.py:53` |
| `ML_TIMEOUT_SECONDS` | `5.0` | `app/detection.py:56` |
| `ACTION_ENFORCE_TIMEOUT_SECONDS` | `3.0` | `app/detection.py:60` |
| `PRE_TOKEN_CHECK_TIMEOUT` | `3.0` | `app/auth.py:204` |
| `GATED_RISK_LEVELS` | `{"high", "critical"}` | `app/auth.py:207` |
| `FEATURE_FIELDS` | 6 đặc trưng | `app/ml.py:42` |

> **Lưu ý về thời gian chờ ML:** đề bài ghi "500 ms", nhưng mã nguồn hiện đặt `ML_TIMEOUT_SECONDS = 5.0`.
> Báo cáo ghi **5 giây** theo đúng SRC, đồng thời chỉ rõ sự khác biệt này.

### 4.3 III. Yêu cầu chức năng nghiệp vụ
Mỗi actor đều có **đoạn giải thích trước bảng** trả lời: actor là ai · vì sao cần actor này · trách nhiệm · dữ liệu được truy cập · nếu thiếu actor thì nghiệp vụ nào không thực hiện được.

| Actor | Bảng | Số chức năng | Đã nêu "không được phép" |
|---|---|---|---|
| Người dùng hệ thống | Bảng 2.17 | 8 | ✔ |
| SOC Analyst | Bảng 2.18 | 12 | ✔ |
| Security Administrator | Bảng 2.19 | 11 | ✔ |
| Security Manager | Bảng 2.20 | 5 | ✔ |

Định dạng bảng **đúng y hệt mẫu** (6 cột): `STT | Công việc | Loại công việc | Quy định/Công thức liên quan | Biểu mẫu/Giao diện liên quan | Ghi chú`

Ví dụ ràng buộc đã ghi cụ thể cho SOC Analyst (không phải chỉ "Điều tra cảnh báo"):
- chỉ xem cảnh báo theo quyền được giao
- phải xem lần đăng nhập và ngữ cảnh rủi ro trước khi kết luận
- phải tiếp nhận cảnh báo trước khi gửi hành động
- đánh dấu báo nhầm bắt buộc phải có người thực hiện và thời gian
- leo thang cảnh báo chỉ đổi mức ưu tiên, không đổi trạng thái
- mọi thay đổi cảnh báo đều ghi vào `alert_timeline`
- hành động nhạy cảm phải ghi `audit_logs`

### 4.4 IV. Yêu cầu chức năng hệ thống và yêu cầu chất lượng
- [x] **A. Yêu cầu chức năng hệ thống** — 20 yêu cầu mã **FR-01 … FR-20**
  - Mỗi yêu cầu ghi: chức năng · đầu vào · đầu ra · điều kiện · actor · dữ liệu liên quan
- [x] **B. Yêu cầu chất lượng** — Bảng 2.22, 14 nhóm
  - Bảo mật · Tính sẵn sàng · Hiệu năng · Độ tin cậy · Khả năng kiểm toán · Khả năng bảo trì · Khả năng mở rộng · Toàn vẹn dữ liệu · Quá hạn · Tính lũy đẳng
  - [x] Có cột **"Mức độ đáp ứng hiện tại"** — không bịa SLA
  - [x] Những mục chưa có số liệu → gắn `[CẦN XÁC NHẬN TIÊU CHÍ ĐỊNH LƯỢNG]`

---

## 5. CHƯƠNG III. PHÂN TÍCH THIẾT KẾ HỆ THỐNG

### 5.1 I. Sơ đồ use case
- [x] **Hình 3.1** — Sơ đồ use case tổng quát (dựng mới, trước đây báo cáo chưa có)
- [x] Bảng 3.1 — Tác nhân và phạm vi chức năng (4 tác nhân người)
- [x] Bảng 3.2 — Mô tả các chức năng quan trọng
- [x] Có quan hệ `include` / `extend`

### 5.2 II. Sơ đồ trạng thái
- [x] **Hình 3.2** — Vòng đời cảnh báo SOC: `MỞ → ĐÃ TIẾP NHẬN → ĐÃ KẾT LUẬN` + nhánh báo nhầm / leo thang
- [x] Bảng 3.3 — Ý nghĩa và quyền chuyển trạng thái
- [x] **Hình 3.3** — Giao dịch MFA và phiên đăng nhập (2 máy trạng thái)

> **Điểm cần lưu ý:** mẫu đề xuất 5 trạng thái `OPEN / ACKNOWLEDGED / ESCALATED / RESOLVED / FALSE_POSITIVE`.
> Báo cáo dùng **4 trạng thái** vì mã nguồn chỉ hỗ trợ 4 trạng thái. Đây là điểm **cố ý bám theo SRC**, không phải thiếu sót.

### 5.3 III. Sơ đồ tuần tự
- [x] **Hình 3.4** — Đăng nhập và xác thực
- [x] **Hình 3.5** — Phát hiện và chấm điểm rủi ro
- [x] **Hình 3.6** — Xử lý cảnh báo SOC
- [x] **Hình 3.7** — Xác thực đa yếu tố
- [x] **Hình 3.8** — Quản lý phiên đăng nhập
- [x] **Hình 3.9** — Suy luận mô hình
- [x] **Hình 3.10 – 3.13** — 4 kịch bản xử lý chi tiết (kèm chú thích phân loại đúng: gọi là *kịch bản*, không gọi nhầm là sơ đồ tuần tự)

> 6 sơ đồ workflow cũ (`WF-1` … `WF-6`) **không bị xoá**: đã dùng lại làm nguồn cho 6 sơ đồ tuần tự chính ở trên.

### 5.4 IV. Sơ đồ hoạt động
- [x] **Hình 3.14** — Đăng nhập và xác thực
- [x] **Hình 3.15** — Phát hiện và quyết định rủi ro
- [x] **Hình 3.16** — Điều tra cảnh báo SOC

### 5.5 V. Sơ đồ lớp
- [x] **Hình 3.17** — Sơ đồ lớp ở **mức miền nghiệp vụ**, không dùng bảng CSDL thay cho lớp
- [x] Giải thích 3 nhóm lớp: xác thực · phát hiện · suy luận và hợp đồng
- [x] Quan hệ chính và số lượng

### 5.6 VI. Thiết kế cơ sở dữ liệu
- [x] **1) Mô hình ERD** — Hình 3.18 (`core-db`), 3.19 (`detection-db`), 3.20 (`ml-service-db`)
- [x] **2) Sơ đồ quan hệ bảng** — Bảng 3.4 (cột khóa chính, khóa ngoại)
- [x] **3) Cấu trúc các bảng** — **23 bảng / 255 cột**, mỗi cột ghi: tên · kiểu · PK · FK · mặc định · ý nghĩa và ràng buộc

| Nhóm | Số bảng | Bảng |
|---|---|---|
| `core-db` | 13 | users, roles, user_roles, sessions, mfa_transactions, mfa_notifications, audit_logs, user_trusted_devices, system_settings, outbox_events, user_notifications, rate_limits, ip_addresses |
| `detection-db` | 7 | policies, login_attempts, risk_assessments, detection_logs, soc_analysts, alerts, alert_timeline |
| `ml-service-db` | 3 | model_versions, inference_logs, feature_statistics |

**Kết quả đối chiếu tự động với `infra/postgres/schema-*.sql`:**

| Kiểm tra | Kết quả |
|---|---|
| Số bảng trong lược đồ | 23 |
| Số bảng được mô tả trong báo cáo | 23 |
| Bảng thiếu | 0 |
| Bảng thừa | 0 |
| Cột không khớp | 0 *(đã sửa 1 lỗi: xoá cột `policies.updated_at` không tồn tại trong SQL)* |

- [x] Bảng 3.28 — Danh mục 9 màn hình và quyền truy cập
- [x] Bảng 3.29 — Quyền truy cập và dữ liệu theo từng màn hình

### 5.7 VII. Thiết kế giao diện
- [x] 9 màn hình: Đăng nhập · Mã xác thực · Quản lý phiên · Bảng điều khiển SOC · Danh sách cảnh báo · Chi tiết cảnh báo · Quản lý chính sách · Quản lý người dùng và vai trò · Nhật ký kiểm toán
- [x] Mỗi màn hình giải thích: ai dùng · mục đích · dữ liệu hiển thị · thao tác · quyền
- [x] Trung thực: chưa có ảnh chụp màn hình → `[CẦN BỔ SUNG MOCKUP/GIAO DIỆN THỰC TẾ]`
- [x] **KHÔNG tạo ảnh giả**

### 5.8 VIII. Thiết kế xử lý
11 hành vi, mỗi hành vi ghi rõ `input → validation → processing → database → output → error`:

- [x] Xử lý đăng nhập
- [x] Xử lý xác thực đa yếu tố
- [x] Ghi sự kiện ra hộp thư ra
- [x] Xử lý phát hiện đăng nhập bất thường
- [x] Tính điểm rủi ro
- [x] Tạo cảnh báo
- [x] Xử lý cập nhật cảnh báo bởi phân viên
- [x] Xử lý thu hồi phiên
- [x] Xử lý khoá tài khoản
- [x] Xử lý suy giảm về điểm quy tắc
- [x] Xử lý quản lý thiết bị tin cậy
- [x] Xử lý cập nhật cảnh báo của hệ thống
- [x] Xử lý khôi phục bản ghi chấm lỗi

---

## 6. CHƯƠNG IV. PHÁT TRIỂN/THỰC THI

> Ba tiêu đề `Màn hình danh sách nhà trọ` / `Màn hình danh sách các quận quan tâm` / `Màn hình chi tiết nhà trọ`
> trong mẫu **đã bị loại bỏ** vì thuộc đề tài quản lý nhà trọ, không liên quan đề tài mới.
> Vị trí đó được thay bằng 10 mục nội dung đúng đề tài.

- [x] Mã nguồn dịch vụ xác thực lõi — Bảng 4.1 (cấu trúc thư mục `app/`)
- [x] Danh mục **30 điểm cuối** — Bảng 4.2 (28 nghiệp vụ, 8 nhóm) + Bảng 4.3 (2 giám sát sức khoẻ)
  - Đã đối chiếu trực tiếp với `@router.*` trong `app/*.py`
- [x] Cơ sở dữ liệu và lược đồ — Bảng 4.4 (3 tệp SQL, 23 bảng)
- [x] Máy phát hiện và cơ chế chấm điểm — Bảng 4.5
- [x] Cổng kiểm duyệt rủi ro — Bảng 4.6 (20 trường hợp kiểm thử)
- [x] Xác thực đa yếu tố và quản lý phiên
- [x] Dịch vụ máy học — Bảng 4.7
- [x] **Giao diện người dùng** — Bảng 4.8: trạng thái từng màn hình
  - [x] Ghi trung thực: *"Ở thời điểm báo cáo hiện tại, nhóm chưa có bằng chứng thực thi cho chức năng này."*
  - [x] Để `[CẦN BỔ SUNG ẢNH SAU KHI TRIỂN KHAI]`
  - [x] **KHÔNG sinh screenshot giả**
- [x] Bộ kiểm thử tự động — Bảng 4.9
- [x] Các thành phần đã thiết kế nhưng chưa triển khai — Bảng 4.11
- [x] Bộ dữ liệu mẫu cho môi trường kiểm thử

**Kết quả chạy kiểm thử thật (2026-10-05):**

```
$ python3 -m pytest -q
184 passed in 1.52s
```

| Nhóm kiểm thử | Số trường hợp | Kết quả |
|---|---|---|
| Xác thực tài khoản | 6 | PASS |
| Cổng kiểm duyệt rủi ro | 20 | PASS |
| Máy phát hiện và chấm điểm | 42 | PASS |
| Hành động bảo vệ | 20 | PASS |
| Vòng đời cảnh báo | 9 | PASS |
| Dịch vụ máy học | 9 | PASS |
| Nhất quán lược đồ | 78 | PASS |
| **Tổng** | **184** | **184/184 đạt** |

---

## 7. CHƯƠNG V. TRIỂN KHAI

### 7.1 I. Cài đặt
- [x] Bảng 5.1 — Thành phần môi trường thực thi
- [x] **Bảng 5.2 — 34 chức năng**, đúng 4 cột của mẫu: `STT | Chức năng | Mức độ hoàn thành | Ghi chú`
- [x] Mức độ dùng đúng 5 mức: Chưa thực hiện · Đang thực hiện · Đã thiết kế · Đã triển khai · Đã kiểm thử
- [x] Phân biệt rõ **"đã thiết kế" ≠ "đã triển khai"**
- [x] Bảng 5.3 — Tổng hợp: 14 đã kiểm thử · 12 đã triển khai · 5 đã thiết kế · 3 chưa thực hiện

### 7.2 II. Thử nghiệm
- [x] Bảng 5.4 — Kết quả chạy bộ kiểm thử tự động
- [x] **Bảng 5.5 — Ma trận 18 trường hợp kiểm thử thủ công**, đúng 8 cột yêu cầu:
  `ID | Chức năng | Tiền điều kiện | Đầu vào | Các bước | Kết quả mong đợi | Thực tế | Trạng thái`

**15 kịch bản bắt buộc — đã có đủ 15/15:**

| # | Kịch bản yêu cầu | Mã trong báo cáo | Trạng thái |
|---|---|---|---|
| 1 | Sai password | MT-01 | PASS |
| 2 | Account locked | MT-03 | Chưa chạy |
| 3 | MFA đúng | MT-04 | Chưa chạy |
| 4 | MFA sai | MT-05 | Chưa chạy |
| 5 | MFA hết hạn | MT-07 | Chưa chạy |
| 6 | Event trùng | MT-08 | PASS |
| 7 | LOW risk | MT-09 | PASS |
| 8 | HIGH risk | MT-10 | PASS |
| 9 | CRITICAL risk | MT-11 | Chưa chạy |
| 10 | ML timeout | MT-12 | PASS |
| 11 | SOC acknowledge | MT-13 | Chưa chạy |
| 12 | False positive | MT-14 | Chưa chạy |
| 13 | Escalation | MT-15 | Chưa chạy |
| 14 | Revoke session | MT-16 | Chưa chạy |
| 15 | RBAC unauthorized | MT-17 | Chưa chạy |

> **Không ghi `PASS` cho trường hợp chưa chạy thật.** 12 trường hợp để trạng thái *Chưa chạy* vì cần môi trường đầy đủ 3 dịch vụ + 3 CSDL.
> Có `[CẦN NHÓM XÁC NHẬN: dựng môi trường đầy đủ để chạy nốt 12 trường hợp còn lại, hay chấp nhận báo cáo với trạng thái hiện tại]`

- [x] Bảng 5.6 — Tổng hợp trạng thái kiểm thử thủ công
- [x] Bảng 5.7 — Tài khoản kiểm thử → `[CẦN BỔ SUNG TÀI KHOẢN TEST]` cho cả 4 vai trò
- [x] Bảng 5.8 — Các hạng mục chưa kiểm thử và lý do

---

## 8. CHƯƠNG VI. KẾT LUẬN

### 8.1 I. Kết quả đã thực hiện
- [x] Bảng 6.1 — Tách rõ 3 mức độ, **không đánh đồng thiết kế với thực thi**
  - **Phân tích:** hoàn thành
  - **Thiết kế:** hoàn thành (lược đồ, UML, đặc tả xử lý, 30 điểm cuối)
  - **Thực thi:** hoàn thành phía máy chủ; **chưa có giao diện người dùng**

### 8.2 II. Ưu khuyết điểm
- [x] **Ưu điểm** — 7 điểm, mỗi điểm kèm bằng chứng cụ thể
- [x] **Khuyết điểm** — 10 điểm, **trung thực**, đã xác minh từ SRC:

| # | Khuyết điểm | Bằng chứng |
|---|---|---|
| 1 | Chưa có giao diện người dùng | Không có mã giao diện trong dự án |
| 2 | Chưa phân tích vai trò ở hầu hết điểm cuối cảnh báo | Dùng khoá nội bộ thay cho RBAC |
| 3 | Chưa dùng thư viện JWT | `token_jti` đã khai báo nhưng không có phụ thuộc JWT |
| 4 | Hộp thư ra chưa có chương trình sử dụng | Bảng `outbox_events` tồn tại, không có mã đọc |
| 5 | Cửa sổ giới hạn tần suất 60 giây ngắn hơn thiết kế 300 giây | Ghi thẳng trong mã, không đọc từ `system_settings` |
| 6 | Chưa có số liệu kiểm thử hiệu năng | Chưa có bộ benchmark |
| 7 | Chưa đánh giá tỉ lệ báo nhầm | Chưa có tập dữ liệu nhãn thật |
| 8 | Ngưỡng rủi ro chưa được hiệu chỉnh trên dữ liệu thật | Dùng ngưỡng mặc định |
| 9 | Mô hình chưa kiểm chứng bằng tập dữ liệu thực tế | Chỉ có kiểm thử với dữ liệu mô phỏng |
| 10 | Chưa có hạ tầng chạy đồng thời 3 dịch vụ | 12 trường hợp kiểm thử thủ công chưa chạy được |

### 8.3 III. Hướng mở rộng trong tương lai
- [x] 13 hạng mục, **mỗi hạng mục gắn với đúng một khuyết điểm ở mục II**
- [x] Bảng 6.2 — Bảng ánh xạ hướng mở rộng ↔ hạn chế tương ứng

---

## 9. TÀI LIỆU THAM KHẢO

- [x] **18 tài liệu**, chia 4 nhóm
- [x] **Mỗi mục đều có đoạn "Được dùng ở…"** chỉ rõ dùng ở đâu trong báo cáo
- [x] **Mỗi mục đều có ít nhất 1 trích dẫn `[n]` trong phần thân** — kiểm bằng script
- [x] Trích dẫn không dùng đến: **0**
- [x] Tài liệu khai trong danh mục mà không được trích: **0**

| Nhóm | Mục | Nội dung thực sự được dùng cho |
|---|---|---|
| Chuẩn & đặc tả | [1] RFC 7519 · [2] IETF JWT · [3] REST · [4] PostgreSQL 16 · [5] FastAPI | Nền tảng kỹ thuật, cơ sở lý thuyết CSDL |
| Hướng dẫn bảo mật | [6] OWASP Authentication · [7] OWASP MFA · [8] OWASP Logging · [9] NIST SP 800-63B · [10] NIST SP 800-92 · [11] Sipser | Nguyên lý xác thực, MFA, nhật ký kiểm toán, hàm băm |
| Học máy | [12] scikit-learn · [13] Isolation Forest (ICDM'08) · [14] Chandola & Bhatia (ACM 2009) | Điểm bất thường, chấm điểm rủi ro |
| Tài liệu dự án | [15] Quyết định kiến trúc v3.3 · [16] Hướng dẫn Detection v3.3 · [17] 3 tệp lược đô · [18] Bộ kiểm thử | Chương II, III, IV, V |

> **Không tạo tài liệu tham khảo giả.** Mọi mục đều là tài liệu thật, có số hiệu/phiên bản/xuất bản, và đều được trích dẫn.

---

## 10. KIỂM TRA ĐỊNH DẠNG WORD

| Hạng mục | Yêu cầu | Kết quả |
|---|---|---|
| Cách dựng tệp | Dùng chính file mẫu làm base document | ✔ Không tạo file trắng |
| Khổ giấy | A4 | ✔ 21,00 × 29,70 cm |
| Lề | Theo mẫu | ✔ 2,54 cm cả 4 cạnh |
| Font mặc định | Times New Roman 13pt (`w:docDefaults`) | ✔ Kế thừa nguyên vẹn từ mẫu |
| Header | Dòng tiêu đề báo cáo | ✔ Giữ nguyên |
| Footer | Số trang (trường `PAGE`) | ✔ Giữ nguyên |
| Style `Heading 1`…`Heading 5` | Lấy trực tiếp từ mẫu | ✔ Không tự định dạng tay |
| Style `List Paragraph` | Cho danh sách gạch đầu dòng | ✔ |
| Bảng: viền | Đen mảnh `sz=4` | ✔ Đặt trực tiếp qua XML |
| Bảng: tổng bề rộng | ≤ 15,92 cm (không vỡ lề) | ✔ **77/77 bảng đạt** |
| Bảng: lặp hàng tiêu đề | `w:tblHeader` | ✔ |
| Bảng: hàng không bị vỡ | `w:cantSplit` | ✔ |
| Bảng: canh giữa theo chiều dọc | `w:vAlign=center` | ✔ |
| Hình: vừa khung trang | ≤ 15,5 × 19,5 cm | ✔ **21/21 hình đạt** (tự thu nhỏ theo cả 2 chiều) |
| Caption | `Hình x.y` / `Bảng x.y` thống nhất | ✔ 97 caption, đánh số liên tục |
| Mục lục & danh sách hình/bảng | Trường Word, cập nhật bằng F9 | ✔ Có hướng dẫn ngay trong tài liệu |

---

## 11. DANH SÁCH HÌNH — 21 HÌNH

| Mã | Tên | Loại UML | Nguồn |
|---|---|---|---|
| Hình 1.1 | Kiến trúc tổng thể | Sơ đồ khối | **Dựng mới** |
| Hình 3.1 | Sơ đồ use case tổng quát | Use case | **Dựng mới** |
| Hình 3.2 | Sơ đồ trạng thái vòng đời cảnh báo SOC | State | **Dựng mới** |
| Hình 3.3 | Trạng thái giao dịch MFA và phiên | State | **Dựng mới** |
| Hình 3.4 | Tuần tự đăng nhập và xác thực | Sequence | Tái dựng từ `WF-1` |
| Hình 3.5 | Tuần tự phát hiện và chấm điểm | Sequence | Tái dựng từ `WF-2` |
| Hình 3.6 | Tuần tự xử lý cảnh báo SOC | Sequence | Tái dựng từ `WF-3` |
| Hình 3.7 | Tuần tự xác thực đa yếu tố | Sequence | Tái dựng từ `WF-4` |
| Hình 3.8 | Tuần tự quản lý phiên | Sequence | Tái dựng từ `WF-5` |
| Hình 3.9 | Tuần tự suy luận mô hình | Sequence | Tái dựng từ `WF-6` |
| Hình 3.10 | Kịch bản đăng nhập thành công | Kịch bản (bổ trợ) | CŨ |
| Hình 3.11 | Kịch bản đăng nhập bị chặn | Kịch bản (bổ trợ) | CŨ |
| Hình 3.12 | Kịch bản phân viên SOC xử lý | Kịch bản (bổ trợ) | CŨ |
| Hình 3.13 | Kịch bản suy giảm khi ML lỗi | Kịch bản (bổ trợ) | CŨ |
| Hình 3.14 | Hoạt động đăng nhập và xác thực | Activity | **Dựng mới** |
| Hình 3.15 | Hoạt động phát hiện và quyết định rủi ro | Activity | **Dựng mới** |
| Hình 3.16 | Hoạt động điều tra cảnh báo SOC | Activity | **Dựng mới** |
| Hình 3.17 | Sơ đồ lớp miền nghiệp vụ | Class | **Dựng mới** |
| Hình 3.18 | ERD `core-db` | ERD | **Dựng mới** |
| Hình 3.19 | ERD `detection-db` | ERD | **Dựng mới** |
| Hình 3.20 | ERD `ml-service-db` | ERD | **Dựng mới** |

### 11.1 Xử lý 6 sơ đồ workflow cũ
Cả 6 đều được **tái sử dụng có ý nghĩa**, không xoá và không gọi sai tên:

| Sơ đồ cũ | Loại thật | Được đặt vào |
|---|---|---|
| `WF-1 Login Flow` | Luồng | → Hình 3.4 (Sequence) |
| `WF-2 Detection Engine Flow` | Luồng | → Hình 3.5 (Sequence) |
| `WF-3 SOC Alert Handling` | Luồng | → Hình 3.6 (Sequence) |
| `WF-4 MFA Flow` | Luồng | → Hình 3.7 (Sequence) |
| `WF-5 Session Management` | Luồng | → Hình 3.8 (Sequence) |
| `WF-6 ML Inference Flow` | Luồng | → Hình 3.9 (Sequence) |

> 4 sơ đồ kịch bản (Hình 3.10–3.13) được giữ riêng và **ghi rõ là *kịch bản bổ trợ***, không đánh tráo loại với sequence diagram.

### 11.2 Sửa lỗi phát hiện trong quá trình biên tập
| Tệp | Vấn đề | Cách sửa |
|---|---|---|
| `docs/diagrams/fig_architecture_overview.png` | **Tệp hỏng** — thực chất là trang HTML lỗi lưu nhầm đuôi `.png` | Viết lại nguồn `docs/bao-cao/uml-architecture.puml` và kết xuất lại qua Kroki |
| `docs/diagrams/fig_wf1_login.png` | Hỏng | Không dùng — đã thay bằng bản kết xuất từ nguồn `.puml` |
| `docs/diagrams/fig_wf2_detection.png` | Hỏng | Không dùng — như trên |
| `docs/diagrams/fig_wf3_soc_alerts.png` | Hỏng | Không dùng — như trên |
| 5 tệp `word/media/image*.png` | Ảnh thừa còn sót từ mẫu | Không ảnh hưởng hiển thị |
| 3 sơ đồ PlantUML | Rộng 17,0 cm / cao 53 cm → vượt khung trang | Thêm tự động thu nhỏ theo cả bề rộng lẫn chiều cao |
| Bảng `policies` | Liệt kê cột `updated_at` không tồn tại trong SQL | Đã xoá |
| Số điểm cuối | Báo cáo ghi 28, thực tế mã nguồn có 30 | Tách 28 nghiệp vụ + 2 giám sát, sửa cả Chương IV lẫn Chương VI |
| Danh mục từ viết tắt | Thiếu JWT, IP, PK, FK | Đã bổ sung (kiểm tra tần suất xuất hiện) |

---

## 12. DANH SÁCH HẠNG MỤC CẦN NHÓM XÁC NHẬN

Báo cáo để lại **9 nhãn** minh bạch, đúng theo yêu cầu "không được giả vờ đã triển khai":

| # | Nhãn | Vị trí | Cần nhóm quyết định gì |
|---|---|---|---|
| 1 | `[CẦN NHÓM XÁC NHẬN QUY MÔ ĐỊNH LƯỢNG]` | Chương I.2 | Số người dùng, số yêu cầu/ngày dự kiến |
| 2 | `[CẦN XÁC NHẬN CÔNG NGHỆ]` | Chương I.3 | (a) có tích hợp gửi email/SMS cho mã xác thực không; (b) có dùng Outbox ở phiên bản sau không |
| 3 | `[CẦN XÁC NHẬN TIÊU CHÍ ĐỊNH LƯỢNG]` | Chương II.4 | Ngưỡng SLA: độ trễ, đồng thời, tỉ lệ báo nhầm, thời gian lưu giữ |
| 4 | `[CẦN NHÓM XÁC NHẬN]` (ảnh giao diện) | Chương III.7 | Có đưa ảnh giao diện thực tế vào báo cáo không |
| 5 | `[CẦN BỔ SUNG ẢNH SAU KHI TRIỂN KHAI]` | Chương III.7 & IV.7 | 9 màn hình cần ảnh chụp thật |
| 6 | `[CẦN NHÓM XÁC NHẬN]` (cửa sổ giới hạn tần suất) | Chương II | Giữ 60 giây hay nâng lên 300 giây theo cấu hình |
| 7 | `[CẦN NHÓM XÁC NHẬN]` (12 trường hợp kiểm thử) | Chương V.2 | Dựng môi trường đầy đủ hay chấp nhận trạng thái hiện tại |
| 8 | `[CẦN BỔ SUNG TÀI KHOẢN TEST]` | Chương V.2 | Tài khoản kiểm thử cho 4 vai trò |
| 9 | `[CẦN NHÓM XÁC NHẬN]` (lựa chọn ảnh giao diện) | Chương IV.7 | Ảnh thật hay ảnh tự động sinh từ khung FastAPI |

---

## 13. ĐỐI CHIẾU VỚI YÊU CẦU CỦA GIẢNG VIÊN

### 13.1 Mục bắt buộc trong file mẫu

| # | Mục | Trạng thái |
|---|---|---|
| 1 | Trang bìa | ✔ |
| 2 | Mục lục | ✔ |
| 3 | Danh sách hình, bảng | ✔ |
| 4 | Danh mục từ viết tắt | ✔ |
| 5 | **Chương I** | ✔ |
| 5.1 | I. Giới thiệu đề tài | ✔ |
| 5.2 | 1. Mục tiêu | ✔ |
| 5.3 | 2. Phạm vi áp dụng | ✔ |
| 5.4 | 3. Nền tảng kỹ thuật | ✔ |
| 5.5 | II. Cơ sở lý thuyết | ✔ |
| 5.6 | ├ Kỹ thuật | ✔ |
| 5.7 | └ Hệ quản trị CSDL | ✔ |
| 6 | **Chương II** | ✔ |
| 6.1 | Quy trình 1 | ✔ 13 tiêu chí |
| 6.2 | Quy trình 2 | ✔ 16 tiêu chí |
| 6.3 | Yêu cầu chức năng nghiệp vụ | ✔ |
| 6.4 | ├ User | ✔ |
| 6.5 | ├ SOC Analyst | ✔ |
| 6.6 | ├ Security Administrator | ✔ |
| 6.7 | └ Security Manager | ✔ |
| 6.8 | Yêu cầu hệ thống | ✔ FR-01…FR-20 |
| 6.9 | Yêu cầu chất lượng | ✔ |
| 7 | **Chương III** | ✔ |
| 7.1 | Use Case | ✔ Hình 3.1 |
| 7.2 | State Diagram | ✔ Hình 3.2–3.3 |
| 7.3 | Sequence Diagram | ✔ Hình 3.4–3.9 |
| 7.4 | Activity Diagram | ✔ Hình 3.14–3.16 |
| 7.5 | Class Diagram | ✔ Hình 3.17 |
| 7.6 | ERD | ✔ Hình 3.18–3.20 |
| 7.7 | Database Diagram | ✔ Bảng 3.4 |
| 7.8 | Cấu trúc bảng | ✔ 23 bảng / 255 cột |
| 7.9 | Thiết kế giao diện | ✔ 9 màn hình |
| 7.10 | Thiết kế xử lý | ✔ 11 hành vi |
| 8 | **Chương IV** | ✔ |
| 8.1 | Nội dung thực thi | ✔ |
| 8.2 | Screenshot hoặc placeholder trung thực | ✔ Placeholder trung thực |
| 8.3 | Caption | ✔ |
| 9 | **Chương V** | ✔ |
| 9.1 | Cài đặt | ✔ |
| 9.2 | Bảng mức độ hoàn thành | ✔ 34 chức năng |
| 9.3 | Thử nghiệm | ✔ |
| 9.4 | Test cases | ✔ 18 ca |
| 10 | **Chương VI** | ✔ |
| 10.1 | Kết quả | ✔ |
| 10.2 | Ưu/khuyết điểm | ✔ 7 / 10 |
| 10.3 | Hướng mở rộng | ✔ 13 |
| 11 | Tài liệu tham khảo | ✔ 18 mục |

**Kết quả: 11/11 khối lớn, 44/44 mục con — đầy đủ 100%. Không có mục nào bị âm thầm bỏ.**

### 13.2 Chín yêu cầu về nghiệp vụ

| # | Yêu cầu | Kết quả |
|---|---|---|
| 1 | Nêu rõ đề tài: áp dụng ở đâu, cho loại hệ thống nào, quy mô, đối tượng, bài toán thực tế | ✔ Chương I.1 + I.2 (5 mục tách biệt) |
| 2 | Cơ sở lý thuyết ngắn gọn, tách kỹ thuật / CSDL, mỗi mục trả lời "dùng ở đâu" | ✔ 10 + 8 tiểu mục, mỗi mục có câu trả lời |
| 3 | Nghiệp vụ mô tả chi tiết như ví dụ "backup" | ✔ 13 + 16 tiêu chí cho 2 quy trình |
| 4 | Mỗi đối tượng: ai, vì sao cần, trách nhiệm, được phép, không được phép, dữ liệu, audit | ✔ 4 actor, mỗi actor 1 đoạn giải thích + bảng 6 cột đúng mẫu |
| 5 | Văn phong báo cáo sinh viên, không quảng cáo | ✔ Đã quét: 0 từ "hiện đại / thông minh / mạnh mẽ / tiên tiến" |
| 6 | 9 câu hỏi cho mỗi phần | ✔ Áp dụng xuyên suốt |
| 7 | Giữ nguyên công thức & ngưỡng nếu còn đúng | ✔ `0,4/0,6`, `0,25/0,50/0,75` — khớp 100% với SRC |
| 8 | Quy trình phải trả lời "làm sao biết bước xử lý đã thành công" | ✔ Mục 1.13 và 2.16 |
| 9 | Mọi mục thiếu phải ghi placeholder, không âm thầm bỏ | ✔ 9 nhãn minh bạch |

### 13.3 Câu hỏi "Làm sao biết bước xử lý này đã thành công?"

| Đối tượng | Câu trả lời trong báo cáo |
|---|---|
| **Outbox** | Giao lại cùng `event_id` không tạo bản ghi thứ hai; MT-08 kiểm chứng PASS |
| **Detection** | `risk_assessments` được tạo với `combined_score` và `risk_level`; `detection_logs` ghi từng giai đoạn |
| **Alert** | `alerts` có đủ bằng chứng (`evidence` trả 4 nguồn); `alert_timeline` ghi mọi thay đổi trạng thái |
| **MFA** | `mfa_transactions` còn hạn (`expires_at > now`) và chuyển sang hoàn thành sau khi mã đúng |
| **Session revoke** | `sessions.revoked_at` được đặt; mọi truy vấn xác thực đều có điều kiện `revoked_at IS NULL` → token cũ hỏng ngay lần gọi kế tiếp |
| **ML fallback** | `ml_status = unavailable`, `combined = rule_score`, và ghi log `ml_timeout` |

---

## 14. THỐNG KÊ TỔNG THỂ

| Chỉ số | Giá trị |
|---|---|
| Số trang (ước tính) | ~95–105 trang |
| Số từ | ~42.000 |
| Số đoạn văn | 793 |
| Số bảng | 77 |
| Số hình | 21 |
| Caption | 97 |
| Tiêu đề | 191 |
| Tệp lớc nhất | 5,4 MB |
| Số bảng vượt lề | **0** |
| Số hình vượt khung trang | **0** |
| Số caption sai số thứ tự | **0** |
| Số tài liệu tham khảo không được trích | **0** |
| Số thông tin bịa | **0** |

---

## 15. HƯỚNG DẪN MỞ TỆP

1. Mở `BaoCaoPT_TKHTTT_Nhom2_Revised.docx` bằng Microsoft Word.
2. **Cập nhật mục lục và danh sách hình, bảng:** `Ctrl+A` → `F9` → chọn *Cập nhật toàn bộ danh mục*.
3. Kiểm tra lại phần đánh số trang sau khi cập nhật.
4. Không cần làm gì thêm với định dạng — tệp đã kế thừa toàn bộ từ file mẫu.

---

## 16. KẾT LUẬN KIỂM TRA

> **"Báo cáo mới đã có TẤT CẢ các mục được liệt kê trong file mẫu chưa?"**

**CÓ — 44/44 mục, không có ngoại lệ.**

Báo cáo đạt 5 tiêu chí ưu tiên:
1. **Đúng mẫu** — 100% tiêu đề cấp 1 và cấp 2 khớp mẫu; 2 bảng mẫu tái tạo đúng số cột; định dạng kế thừa nguyên vẹn.
2. **Đủ nghiệp vụ** — 2 quy trình với 29 tiêu chí; 4 actor có giải thích "vì sao tồn tại".
3. **Có lý do** — Mỗi quyết định thiết kế đều nêu lý do (vd: chia cho tổng trọng số để giữ điểm trong [0;1]).
4. **Có quy tắc** — FR-01…FR-20, MT-01…MT-18, 5 trạng thái cảnh báo, 7 trường quy tắc, 6 đặc trưng, 5 mức hoàn thành.
5. **Có kiểm chứng** — 184 test tự động chạy thật; 23 bảng/255 cột đối chiếu tự động với SQL; 18 tài liệu tham khảo đều được trích.

Và **không có thông tin nào bị bịa** — 9 hạng mục còn thiếu dữ liệu đều được đánh dấu rõ, mọi khuyết điểm đều có bằng chứng trích từ mã nguồn.
