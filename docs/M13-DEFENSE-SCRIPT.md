# M13 — Kịch bản bảo vệ dự án (10–15 phút)

> Sentinel Auth v3.3 · M13.0 – M13.2

Kịch bản này chạy trên **stack demo LOCAL** của nhóm, không phải môi
trường triển khai công khai.

> **Lưu ý về rubric:** kịch bản được soạn theo phạm vi M13 đã bàn giao.
> **Chưa đối chiếu rubric gốc** — trong repository không có tài liệu nào
> nêu một rubric chấm điểm cụ thể cho buổi bảo vệ.

---

## 0. Trước khi lên sân — checklist 5 phút

```bash
bash scripts/demo_stack.sh status
python scripts/demo_seed_demo.py --seed --manifest-out .ci/demo/fixture-manifest.json
curl -fsS http://127.0.0.1:58000/health && echo " <- API OK"
ls -l .ci/demo/demo-otp.log && cat .ci/demo/otp-log.path
```

**Cổng cố định của demo stack:**

| Thành phần | Địa chỉ |
|---|---|
| Frontend (Vite) | http://127.0.0.1:55173 |
| API (FastAPI) | http://127.0.0.1:58000 |
| PostgreSQL | 127.0.0.1:55432 |
| Redis | 127.0.0.1:56379 |
| SMTP sink | 127.0.0.1:51025 |

**Tài khoản demo** (mật khẩu mặc định `DemoPass!2026`):

| Tài khoản | Vai trò | Dùng cho bước nào |
|---|---|---|
| `demo_user` | USER | bước 1 |
| `demo_analyst` | SOC_ANALYST | bước 4 |
| `demo_admin` | SECURITY_ADMIN | bước 3 |
| `demo_manager` | SECURITY_MANAGER | bước 5 |

---

## 1. Bảng trạng thái — nói thẳng trước khi trình bày

Phần quan trọng nhất của buổi bảo vệ là **nói thẳng những gì chưa
được chứng minh**.

| Hạng mục | Trạng thái | Nói như thế nào |
|---|---|---|
| Demo stack | VERIFIED | chạy thật, 3 database tách biệt, SMTP thật |
| Frontend E2E | VERIFIED | 18 kịch bản Chromium, không mock, CI xanh |
| Pre-token detection | VERIFIED | đo A/B trên stack thật |
| An toàn fixture | VERIFIED | 111 test, 5 lớp gia cố |
| ML artifact | NOT PROMOTED | chưa có model production; fallback rule-only và báo trung thực |
| SMTP | LOCAL CAPTURE SINK | OTP đi qua SMTP hop thật, nhưng sink là script của nhóm |
| Browser scope | CHROMIUM ONLY | chưa chạy Firefox/WebKit trong CI |
| Deployment | LOCAL DEMO | chưa có public deployment, chưa có load test |
| Readiness | STATIC | kiểm tra tĩnh theo cấu hình, chưa có traffic thật để đo |

### Phân biệt SEEDED và REAL — câu hỏi nào cũng hỏi

| Phần | SEEDED (dữ liệu mẫu) | REAL (phát sinh từ luồng thật) |
|---|---|---|
| Alert trong hộp thư SOC | seeded — 5 alert mẫu, đủ mọi trạng thái, để minh họa giao diện | alert thật sinh khi có login event thật |
| Quyết định allow/challenge/block | — | luôn real — do Detection Engine tính ra |
| Hành động bảo vệ | — | luôn real — Detection gọi Core qua HTTP, Core ghi audit log của chính nó |
| Pipeline phát hiện tự động | — | real — probe đăng nhập thật từ IP lạ, Detection chấm điểm thật, Core thu hồi session thật |
| Số liệu analytics Manager | seed tạo nền | cộng dồn từ event thật; phần ML là null/degraded |

**Câu nói an toàn:** "Alert có sẵn trong hộp thư là dữ liệu mẫu để tôi
minh họa giao diện. Còn quyết định có chặn hay không, và hành động bảo
vệ có được thực thi hay không — những cái đó tôi sẽ chạy thật ngay
bây giờ."

---

## 2. Dòng thời gian tổng thể

| Bước | Nội dung | Thời lượng |
|---|---|---|
| 0 | Mở đầu + trạng thái trung thực | 1–2 phút |
| 1 | Đăng nhập bình thường | 1,5 phút |
| 2 | Phát hiện bất thường + pre-token gate | 3 phút |
| 3 | MFA / hành động bảo vệ | 2 phút |
| 4 | SOC điều tra và xử lý | 3 phút |
| 5 | Manager quan sát kết quả | 2 phút |
| 6 | Chốt: bằng chứng, giới hạn, hướng đi tiếp | 1,5 phút |

Nếu bị rút ngắn còn 10 phút: bỏ bước 3, gộp bước 1 vào bước 2.
Không được bỏ bước 0 và bước 6.

---

## 3. Bước 0 — Mở đầu (1–2 phút)

**Mục tiêu:** định khung bài trình bày và chủ động nói thẳng trạng thái.

**Nói:**

> "Sentinel Auth v3.3 là hệ thống quản lý cảnh báo đăng nhập bất thường:
> ba bounded context tách biệt — Core phục vụ xác thực, Detection phục
> vụ chấm điểm rủi ro, ML phục vụ suy luận — giao tiếp qua HTTP với
> shared secret, không context nào đọc database của context khác.
>
> Tôi sẽ trình bày theo một câu chuyện: một người dùng đăng nhập bình
> thường, rồi một lần đăng nhập bất thường bị hệ thống chặn lại trước
> khi kịp cấp token, rồi SOC điều tra và xử lý, và cuối cùng Manager
> quan sát kết quả.
>
> Trước khi bắt đầu, tôi nói thẳng trạng thái: những gì tôi sẽ chạy
> hôm nay là **trên stack demo local của nhóm**, không phải môi trường
> triển khai công khai. ML artifact **chưa được promote**, nên phần ML
> sẽ chạy fallback rule-only — và đó là trạng thái trung thực, không
> phải lỗi. Phạm vi browser đã kiểm chứng là Chromium."

**Bằng chứng cần chụp:** ảnh màn hình bảng trạng thái (bảng ở mục 1),
URL demo stack.

**Khôi phục nếu hỏng:** không có gì để khôi phục — bước này chỉ nói.

---

## 4. Bước 1 — Đăng nhập bình thường (1,5 phút)

**Mục tiêu:** chứng minh luồng xác thực thật, có MFA thật qua SMTP thật.

**Vai trò:** `demo_user` (USER).

**Thao tác trên UI:**

1. Mở http://127.0.0.1:55173
2. Đăng nhập `demo_user` / `DemoPass!2026`
3. Vào trang **Sessions** — xem danh sách phiên đang hoạt động
4. Mở trang **Devices** — xem thiết bị đã tin cậy

**Kết quả mong đợi:** đăng nhập thành công, có access token, danh sách
session và thiết bị hiển thị dữ liệu thật từ database Core.

**Bằng chứng cần chụp:** ảnh màn hình trang Sessions sau khi đăng nhập.

**Điểm cần nói:** *"Đây là token thật, session thật, trong database thật.
Backend là một FastAPI monolith, nhưng router của ba bounded context
được mount trên các prefix riêng, và chúng không bao giờ mở database
của nhau."*

---

## 5. Bước 2 — Phát hiện bất thường và pre-token gate (3 phút)

**Đây là bước quan trọng nhất của buổi trình bày.**

**Mục tiêu:** chứng minh Detection Engine quyết định kết quả đăng nhập
TRƯỚC khi token được cấp — không phải sau khi.

**Vai trò:** `demo_user` (USER) nhưng đăng nhập từ một IP lạ.

**Thao tác — chạy probe (nhanh nhất và chắc chắn nhất):**

```bash
python scripts/demo_pre_token_probe.py
```

**Kết quả mong đợi — dòng quan trọng nhất của buổi trình bày:**

```
RUN 1 (the gate ON):  status=200 token=HELD   mfa_required=True
RUN 2 (the gate OFF): status=200 token=ISSUED mfa_required=False
```

**Lưu ý về policy:** probe tự đảm bảo policy của demo (`m13-demo-active`)
đang là policy đang áp dụng trước khi chấm điểm, và trả lại policy cũ
về sau. Lý do: chỉ được có **một** policy active tại một thời điểm, và
kịch bản E2E-05 của browser suite đã kích hoạt policy của riêng nó —
làm policy demo bị vô hiệu. Khi đó đăng nhập rủi ro bị chấm điểm thấp
hơn ngưỡng `high`, và gate **đúng** là cấp token. Đó là sự thật về
policy, nhưng vô dụng về gate. Nếu bạn thấy dòng log báo policy demo
"không có trong dịch vụ", đó là thông báo bình thường — probe đã xử lý
việc đó.

**Lưu ý về địa chỉ IP:** probe đăng nhập từ một địa chỉ mà tài khoản
**chưa từng dùng**, và tự chọn địa chỉ đó từ lịch sử của chính tài
khoản. Lý do: rule `impossible_travel` đo **mức độ mới** của địa chỉ
(`1 - số lần đăng nhập từ IP này / tổng số lần trong 7 ngày`). Nếu đăng
nhập từ một IP đã quen, mức độ mới giảm xuống dưới ngưỡng 0.8, rule
không kích hoạt, và gate **đúng** là cấp token — sự thật về rule, nhưng
vô dụng về gate. Do đó mỗi lần chạy probe sẽ in ra một địa chỉ khác
nhau, ví dụ `the login under test comes from 203.0.113.19 (never used
before)`. Đây là hành vi đúng, không phải lỗi.

**Vì sao đây là bằng chứng mạnh:** hai lần chạy dùng **cùng database,
cùng policy đang active, cùng lịch sử rủi ro đã gieo, cùng tài khoản**.
Biến duy nhất là `RUN_PRE_TOKEN_CHECK`. Nếu gate không quyết định, hai
lần chạy sẽ cho kết quả giống nhau. Chỉ khi chúng **khác nhau** thì
mới chứng minh được chính gate đã giữ token.

**Đi theo sau khi chạy probe — xem quyết định của Detection:**

```bash
grep "pre-token-check" .ci/demo/api.log | tail -3
grep "internal/actions" .ci/demo/api.log | tail -3
```

Trong log sẽ thấy một lần đăng nhập bất thường như sau:

```
POST /api/v1/internal/pre-token-check   200 OK
POST /api/v1/internal/login-events      202 Accepted
POST /api/v1/internal/actions           200 OK
POST /api/v1/auth/login                 200 OK
```

**Điểm cần nói — vì sao `pre-token-check` đứng đầu:** nó là lần gọi
đồng bộ, được `await` trước khi Core quyết định có cấp token hay không.
Nó chỉ là một lần ĐỌC đánh giá rủi ro và **không ghi gì cả** — không
attempt, không assessment, không alert.

`login-events` là lần ghi duy nhất, và cũng là lần ghi duy nhất tạo ra
attempt, assessment và alert. Nếu gate ghi riêng, một lần đăng nhập sẽ
sinh ra hai alert.

`internal/actions` là Detection gọi ngược lại Core để thi hành hành
động bảo vệ — nó chạy SONG SONG với lúc Core đang giao response, nên
vị trí của nó trong log có thể đổi. Điều bất biến là: **pre-token-check
luôn đứng trước `auth/login`**, và `auth/login` trả `200` với
`access_token` rỗng — tức là token đã bị giữ trước khi client nhận
được bất cứ thứ gì.

Dòng `auth/login` đứng cuối vì response chỉ được ghi ra sau khi handler
trả về, còn handler đã chờ cả lần giao event.

**Bằng chứng cần chụp:**

1. Ảnh màn hình terminal chạy probe với 2 dòng RUN 1 / RUN 2.
2. Ảnh màn hình log API cho thấy `pre-token-check` đứng trước `auth/login`.
3. Nếu giảng viên hỏi về hành động bảo vệ, mở audit log của Core.

**Khôi phục nếu hỏng:**

- Nếu probe báo 429: đó là rate limit 5 lần/phút của login. Chờ 1 phút
  rồi chạy lại — probe tự retry nhưng vẫn nên chạy khi stack rảnh.
- Nếu probe báo lỗi database: kiểm tra `CORE_DATABASE_URL` trong shell có
  trùng với `.env.demo` không.
- Nếu cả hai lần chạy đều HELD: nghĩa là tài khoản đang bị cờ MFA
  một lần từ trước. Chạy lại lệnh seed để xóa cờ đó.

---

## 6. Bước 3 — MFA và hành động bảo vệ (2 phút)

**Mục tiêu:** chứng minh hệ thống phân biệt được MFA thường (tài khoản
có cờ sẵn) với MFA do Detection ra lệnh (hành động bảo vệ), và chứng
minh hành động bảo vệ thực sự thay đổi trạng thái ở Core.

**Vai trò:** `demo_admin` (SECURITY_ADMIN).

**Thao tác trên UI:**

1. Đăng nhập `demo_admin` / `DemoPass!2026`
2. Hệ thống trả về mfa_required — màn hình yêu cầu OTP
3. Lấy OTP từ sink:

```bash
tail -20 .ci/demo/demo-otp.log
```

4. Nhập OTP → đăng nhập thành công
5. Vào trang **User Directory** — xem danh sách tài khoản
6. Vào trang **Audit Log** — xem lịch sử thao tác

**Kết quả mong đợi:** OTP đến thật qua SMTP hop, xác thực thành công,
danh bạ và audit log hiển thị dữ liệu thật.

**Hai loại MFA — nói rõ để không bị hỏi nhầm:**

| Loại | Nguyên nhân | Bằng chứng |
|---|---|---|
| MFA cố định | tài khoản có cờ `admin_mfa_required` | `demo_admin` luôn phải MFA |
| MFA do Detection ra lệnh | hành động bảo vệ `REQUIRE_MFA` đặt cờ `detection_mfa_once` | bước 4, và dòng audit log của Core |

**Điểm cần nói về SMTP:** *"OTP đi qua một SMTP hop thật. Sink là một
script Python của nhóm, không phải mail server production — nhưng nó là
giao thức SMTP thật, và mã OTP phải đúng thì mới verify được."*

**Bằng chứng cần chụp:** ảnh màn hình màn hình MFA, ảnh log chứa OTP,
ảnh trang Audit Log.

**Khôi phục nếu hỏng:**

- "Invalid MFA code": lấy đúng offset mới — đọc đuôi log SAU khi bấm
  đăng nhập, không đọc mã cũ ở đầu log.
- "no OTP arrived": kiểm tra sink còn sống (`smtp.log`) và đường dẫn log
  trong `.ci/demo/otp-log.path` khớp với nơi API gửi.
- Quên mật khẩu demo: `python scripts/demo_seed_demo.py --seed` sẽ đặt
  lại mật khẩu theo `.env.demo`.

---

## 7. Bước 4 — SOC điều tra và xử lý (3 phút)

**Mục tiêu:** chứng minh SOC thấy được bằng chứng, ra quyết định, và
quyết định đó **thực sự thay đổi trạng thái ở Core**.

**Vai trò:** `demo_analyst` (SOC_ANALYST).

**Thao tác trên UI:**

1. Đăng nhập `demo_analyst` / `DemoPass!2026`
2. Vào trang **Alert Queue** — danh sách cảnh báo
3. Lọc theo trạng thái `open` và mức rủi ro
4. Mở một alert → xem **Evidence** và **Timeline**
5. Bấm **Acknowledge** → ghi nhận phụ trách
6. Mở hộp thoại hành động → chọn `REQUIRE_MFA` → nhập lý do → xác nhận
7. Xem Timeline cập nhật có ghi nhận hành động

**Kết quả mong đợi:** hộp thoại đóng lại, hiện thông báo hành động đã
áp dụng, và Timeline có một mục mới ghi lại hành động kèm lý do.

**Chứng minh hành động thực sự thay đổi trạng thái ở Core:**

Sau khi bấm xác nhận, mở tab mới hoặc chạy lệnh này để xem audit log
của Core:

```bash
grep "protective_action" .ci/demo/api.log | tail -3
```

Bản ghi sẽ có `actor_type: system` và lý do do Detection gửi sang. Đây
là bằng chứng mạnh hơn nhiều so với việc nhìn UI, vì nó do chính Core
ghi lại khi nhận hành động qua boundary nội bộ.

**Điểm cần nói:** *"SOC không bao giờ ghi thẳng vào database của Core.
SOC gửi yêu cầu qua boundary nội bộ, Core tự áp dụng và tự ghi audit
log. Nếu Core từ chối, hệ thống báo 'HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG'
thay vì im lặng."*

**Bằng chứng cần chụp:** ảnh hộp thoại hành động (trước khi xác nhận),
ảnh Timeline sau khi xác nhận, ảnh dòng audit log của Core.

**Khôi phục nếu hỏng:**

- Hộp thoại không đóng: bấm Escape hoặc bấm nền ngoài.
- Báo lỗi 422 khi gửi: lý do là bắt buộc, không được để trống.
- Báo "HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG": đây là hành vi ĐÚNG khi Core
  không biết chủ thể alert. Đó là kịch bản 502 trong scenario D.
  Nói rõ đây là trường hợp thất bại trung thực, không phải lỗi demo.

---

## 8. Bước 5 — Manager quan sát kết quả (2 phút)

**Mục tiêu:** chứng minh lớp analytics của Manager phản ánh đúng dữ liệu
và **báo cáo trung thực** khi ML chưa sẵn sàng.

**Vai trò:** `demo_manager` (SECURITY_MANAGER).

**Thao tác trên UI:**

1. Đăng nhập `demo_manager` / `DemoPass!2026`
2. Vào khu vực **Analytics** — có 5 màn hình
3. Xem dashboard tổng quan: số lần đăng nhập, số alert, phân bố rủi ro
4. Xem màn hình xu hướng theo thời gian (hour / day bucket)

**Kết quả mong đợi:** biểu đồ và số liệu hiển thị dữ liệu thật từ các
event đã phát sinh; phần ML hiển thị trạng thái degraded, KHÔNG hiển
thị một model production.

**Điểm cần nói — trung thực về ML:** *"Artifact ML chưa được promote,
nên dashboard báo trạng thái degraded và không có model version nào
đang hoạt động. Hệ thống đang chạy phép tính rule-only. Đây là hành
vi được thiết kế: khi ML không sẵn sàng, hệ thống vẫn chấm điểm được
bằng rule và nói rõ là đang ở chế độ nào, chứ không giả vờ có model."*

**Điểm cần nói — null khác 0:** *"Một metric không có dữ liệu được hiển
thị là 'không có dữ liệu', không bao giờ hiển thị là 0. Đây là điều
kiện được kiểm thử trong browser suite."*

**Bằng chứng cần chụp:** ảnh dashboard, ảnh phần ML báo degraded.

**Khôi phục nếu hỏng:**

- Trang trắng: kiểm tra `/ready` còn xanh không.
- Số liệu bằng 0: đó là dữ liệu thật — event chưa sinh ra. Chạy lại
  bước 2 để sinh event thật, rồi tải lại trang.
- Báo degraded ở nhiều nguồn: là trạng thái đúng khi một nguồn lỗi;
  hệ thống trả 200 kèm null cho từng nguồn lỗi, và 503 khi tất cả.

---

## 9. Bước 6 — Chốt: bằng chứng, giới hạn, hướng đi tiếp (1,5 phút)

**Mục tiêu:** kết thúc bằng bằng chứng cụ thể và công khai điều chưa
làm được.

**Nói:**

> "Tóm lại, trong hôm nay tôi đã chứng minh bằng hành động, trên stack
> thật: một lần đăng nhập bình thường thành công; một lần đăng nhập từ
> IP lạ bị Detection chấm điểm và bị giữ token TRƯỚC khi token được cấp —
> tôi chứng minh điều đó bằng cách so sánh A/B trên cùng một database;
> SOC ra lệnh bảo vệ và hệ thống thực thi, có ghi vào audit log của
> Core; và Manager nhìn thấy dữ liệu đó cùng trạng thái degraded của
> ML."

**Số liệu để nêu (đều có bằng chứng trong repository):**

| Con số | Nguồn |
|---|---|
| 1487 test backend, 0 skip | CI run 46143555230 |
| 18 kịch bản Chromium, 0 mock | CI run 46143555230 |
| 111 test an toàn đích database | CI run 46143555230 |
| 55 check demo scenario | chạy local |
| 7 check probe pre-token | local + CI |

### Phần chưa làm được, nói thẳng

| Hạng mục | Lý do | Kế hoạch |
|---|---|---|
| Promote ML artifact | chưa đạt gate chấp nhận | cần dữ liệu đủ và một lần đánh giá gate |
| Public deployment | chưa có hạ tầng | sau khi M13 được merge |
| Load test | chưa chạy | cần môi trường staging |
| Firefox và WebKit | CI chỉ cấu hình Chromium | thêm project vào playwright config |
| Readiness động | endpoint hiện là kiểm tra tĩnh theo cấu hình | cần traffic thật để đo |

---

## 10. Bảng các câu hỏi khó và câu trả lời

| Câu hỏi | Trả lời |
|---|---|
| Hệ thống có tự học không? | Chưa có artifact được promote. Luồng đã đầy đủ: train, đăng ký version, inference, fallback. Điểm dừng có chủ đích là ở bước promote. |
| Nếu Detection chết thì sao? | Core fail open theo thiết kế — ưu tiên sẵn có đăng nhập hơn là chặn cả hệ thống. Có test riêng cho đường này. |
| Detection có ghi vào database của Core không? | Không. Boundary qua HTTP với X-Internal-Secret. Test chứng minh Core không bao giờ mở connection tới database của Detection. |
| Một đăng nhập tạo ra bao nhiêu alert? | Một. Gate chỉ đọc, không ghi. Lần ghi duy nhất là login-events. |
| SOC có sửa trực tiếp bảng của Core không? | Không. SOC gửi hành động qua boundary; Core tự áp dụng và tự ghi audit log. |
| Test có mock không? | Browser suite không mock gì. OTP đọc từ log SMTP thật, 502 đến từ subject Core không biết, degraded đến từ việc đổi tên bảng ML. |
| Demo có dùng dữ liệu giả không? | Có, và tôi nói rõ: alert mẫu để minh họa giao diện. Mọi quyết định và mọi hành động bảo vệ là thật. |
| An toàn database thế nào? | 5 lớp gia cố, 111 test. Không có biến môi trường nào nới được allowlist. |

---

## 11. Khôi phục trạng thái demo sau khi thao tác thất bại

Các lệnh dưới đây **không phá hủy** dữ liệu. Chỉ `reset` mới phá hủy,
và `reset` hỏi trước.

| Tình huống | Lệnh khôi phục |
|---|---|
| cờ MFA một lần bị kích hoạt ngoài ý muốn | `python scripts/demo_seed_demo.py --seed` |
| probe để lại dữ liệu rủi ro (không thể xảy ra — probe tự dọn) | `python scripts/demo_seed_demo.py --seed` |
| stack chạy lỗi sau khi sửa cấu hình | `bash scripts/demo_stack.sh restart` |
| frontend không khởi động lại | `bash scripts/demo_stack.sh restart` |
| muốn trạng thái sạch hoàn toàn | `bash scripts/demo_stack.sh reset` — hỏi xác nhận, mất dữ liệu |
| muốn kiểm tra stack còn sống không | `bash scripts/demo_stack.sh status` |

---

## 12. Tài liệu liên quan

* [M13-ACCEPTANCE-MATRIX.md](M13-ACCEPTANCE-MATRIX.md) — ma trận nghiệm thu, kèm bằng chứng và số liệu có nguồn
* [M13-FULLSTACK-DEPLOYMENT.md](M13-FULLSTACK-DEPLOYMENT.md) — hướng dẫn dựng từ clone sạch và xử lý sự cố
* [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md) — fixture tái lập được và manifest
* [M13-DEMO-SCENARIOS.md](M13-DEMO-SCENARIOS.md) — sáu kịch bản demo
* [M13-BROWSER-E2E-REPORT.md](M13-BROWSER-E2E-REPORT.md) — báo cáo browser E2E và các lỗi tìm được
