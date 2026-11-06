# Sentinel Auth — ML Service
```bash
“Thu đi để lại lá vàng,
em đi để lại muôn vàn nhớ thương.
Model đi để lại log đường,
request lưu dấu, vô thường cũng tra.”
```

## Phạm Vi — Cương Giới

**KhangCute** phụ trách **ML inference, vòng đời mô hình và analytics phía ML** trên nhánh `ml-service`. Detection Engine vẫn nắm quyền dựng đặc trưng và hợp nhất điểm rủi ro; mô hình hiện tại chỉ là **thực nghiệm chi vật**, chưa nhập Production điện.

## Kiến Trúc — Lôi Trận

`Core/Auth → Detection → build_features() → POST /api/v1/internal/ml/score → ML Service → sentinel_ml`

Detection triệu ML trong thời hạn **5 giây**, sau đó tự định điểm rủi ro cuối. Nếu ML lỗi hoặc quá hạn, hệ thống **thoái thủ an toàn** về chấm điểm thuần rule.


## Lục Đại Đặc Trưng — Canonical Six Features

- `hour_of_day`: giờ UTC của lần đăng nhập hiện tại, từ 0 đến 23.
- `fail_count_24h`: số lần thất bại của cùng người dùng trong 24 giờ trước sự kiện hiện tại.
- `ip_change_rate_7d`: độ mới của IP hiện tại so với lịch sử 7 ngày trước đó.
- `new_device`: thiết bị/user-agent hiện tại chưa xuất hiện trong lịch sử 30 ngày.
- `average_login_interval_seconds`: khoảng cách trung bình giữa tối đa 10 lần đăng nhập lịch sử gần nhất.
- `deviation_score`: độ lệch đã chuẩn hóa của khoảng cách hiện tại so với khoảng cách lịch sử trung bình.

Mọi truy vấn lịch sử chỉ xét sự kiện có `timestamp < timestamp` của lần đăng nhập đang chấm điểm — **hậu sự bất khả nghịch tiền nhân**.

## ML API — Lôi Môn

- `POST /api/v1/internal/ml/score`
- `GET /api/v1/internal/ml/health`
- `GET /api/v1/internal/ml/features`

Implementation đặt tại `app/ml.py`; caller là `app/detection.py::call_ml_service()`. URL lấy từ `ML_SERVICE_URL` (mặc định `http://localhost:8002`), timeout 5 giây và xác thực nội bộ bằng header `X-Internal-Secret`. **Mật lệnh bất khả lưu nhập Git.**

## Database — Huyền Khố

ML Service dùng database `sentinel_ml`:

- schema: `infra/postgres/schema-ml-service-v3.3.sql`
- ORM: `app/models.py`
- kết nối: `app/db.py`
- `model_versions`: registry phiên bản, trạng thái và metadata của mô hình.
- `inference_logs`: nhật ký kết quả suy luận phục vụ kiểm tra và giám sát.
- `feature_statistics`: thống kê phân phối feature theo thời gian.
- `local_ml_stats`: view tổng hợp số liệu suy luận cục bộ.
- hạ tầng local: `docker-compose.yml`

> *“Kiếm có danh, chiêu có phổ; mỗi lần xuất thủ đều phải lưu dấu.”*

## Luyện Mô Hình — Training / Research

- Notebook: `research/kaggle/sentinel_rba_isolation_forest.ipynb`
- Kaggle: `lebaokhang/sentinel-auth-train`
- Benchmark **10 triệu dòng** đã hoàn tất.
- Isolation Forest hiện là baseline thực nghiệm; artifact giữ `is_production=false` và **không được phong vương Production**.

## Thí Luyện — Tests

```powershell
pytest tests/test_ml.py -q
pytest tests/test_runtime_feature_parity.py -q
pytest tests/test_ml_runtime.py -q
pytest -q
```

Các test PostgreSQL cần database/driver và biến môi trường tương ứng; thiếu các điều kiện này là **environment blocker**. Baseline hiện còn lỗi ngoài phạm vi ML tại `app/auth.py` do thiếu `datetime`; nhánh này **bất can thiệp Core**.

## Kiểm Chứng — Verification

Bộ kiểm chứng dùng chung cho local và CI. Nó cung cấp PostgreSQL dùng một lần với **ba database rời rạc**, nạp mỗi database từ schema canonical của nó, rồi chạy toàn bộ pytest suite và script smoke HTTP thật.

### Yêu cầu

- PostgreSQL client (`psql`, `pg_isready`) trên `PATH`.
- Python 3.11+ với các dependency trong `requirements.txt`:
  ```bash
  python -m pip install -r requirements.txt
  ```

### Local — dùng PostgreSQL sẵn có

```bash
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
export POSTGRES_USER=sentinel
export POSTGRES_PASSWORD=<mật khẩu disposable>

# 1. Dựng ba database rời rạc từ schema canonical + ghim múi giờ server về UTC
bash scripts/ci_bootstrap_postgres.sh

# 2. Xuất các URL kết nối mà suite đọc
export CORE_DETECTION_TEST_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/sentinel_core_test"
export CORE_ANALYTICS_TEST_URL="$CORE_DETECTION_TEST_URL"
export DETECTION_TEST_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/sentinel_detection_test"
export ML_TEST_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/sentinel_ml_test"

# 3. Chạy suite dưới chính sách nghiêm ngặt của CI
python scripts/ci_verify_tests.py

# 4. Chạy smoke HTTP thật (uvicorn thật, socket thật)
python scripts/m10_http_smoke.py
```

> **Lưu ý múi giờ.** Múi giờ máy không được dùng làm chuẩn. Script bootstrap ghim `timezone` của **server** về UTC bằng `ALTER SYSTEM` và kiểm tra lại offset phải bằng `0`. Không đặt `PGTZ` trong môi trường: libpq gửi nó như startup parameter và nó **ghi đè** override `options="-c timezone=…"` mà các test cách ly múi giờ dùng để ép một zone lạ — làm vô hiệu hoá âm thầm các test đó.

> **Lưu ý biến môi trường.** Không export `INTERNAL_SECRET` trước khi chạy `pytest`. `tests/conftest.py` tự cài secret của phiên test; một giá trị ambient sẽ ghi đè nó và làm hỏng các test khẳng định ranh giới internal-auth.

### Local — mô phỏng toàn bộ workflow

`scripts/ci_local_simulation.sh` chạy lại **đúng thứ tự từng step** của `.github/workflows/ci.yml` trên một PostgreSQL sẵn có, rồi dọn dẹp. Dùng script này để tái hiện CI không cần push:

```bash
# PostgreSQL sẵn có, user `sentinel` có quyền tạo database
bash scripts/ci_local_simulation.sh <port> <mật khẩu>
```

> **Lưu ý phiên bản FastAPI.** `requirements.txt` cho phép `fastapi>=0.115.0`. Từ FastAPI 0.162, `app.routes` chứa một wrapper `_IncludedRouter` không có thuộc tính `path`, nên code dò route table phải đi xuống router được include. `tests/conftest.py` cung cấp helper `iter_routes()` xử lý cả hai hình dạng, nên suite cho kết quả như nhau trên mọi phiên bản được phép.

### CI — GitHub Actions

Workflow: `.github/workflows/ci.yml`.

- **Kích hoạt**: pull request nhắm vào `dev` hoặc `main`; push lên `dev`; chạy tay qua `workflow_dispatch`.
- **Ma trận Python**: 3.11 và 3.12, chạy song song (`fail-fast: false`) để thấy rõ phiên bản nào vỡ.
- **Hạ tầng**: một service container `postgres:16-alpine` sinh ra trong chính job, cùng mật khẩu disposable hard-code (`sentinel_ci_disposable`) chỉ dùng cho container sống cùng job.
- **Ba database rời rạc**: `sentinel_core_test`, `sentinel_detection_test`, `sentinel_ml_test` — mỗi database nạp đúng một schema canonical:
  - `sentinel_core_test` ← `infra/postgres/schema-core-v3.3.sql` (13 bảng gốc)
  - `sentinel_detection_test` ← `infra/postgres/schema-detection-v3.3.sql` (7 bảng gốc)
  - `sentinel_ml_test` ← `infra/postgres/schema-ml-service-v3.3.sql` (3 bảng gốc + 1 view)
- **Database legacy**: `sentinel_legacy_test` là target của `POSTGRES_DB`, dành cho các module cũ áp **cả ba** schema vào một database (layout single-database lịch sử). Tách riêng để chúng không nạp bảng của context khác vào ba database canonical.
- **Secret nội bộ**: sinh ngẫu nhiên trong runner (`secrets.token_urlsafe(32)`), được mask bằng `::add-mask::`, **không** lưu trong GitHub, và chỉ được truyền cho step smoke (step pytest dùng secret riêng của `tests/conftest.py`).
- **Chính sách nghiêm ngặt**: `scripts/ci_verify_tests.py` fail khi có test fail, **test skip**, xfail, hoặc khi số test thu thập dưới ngưỡng 1.035; nó cũng kiểm tra dependency và biến môi trường bắt buộc trước, để lỗi báo ra đúng nguyên nhân.
- **Không chạy song song trên cùng server**: vài module PostgreSQL cũ dựng lại schema bằng `DROP SCHEMA public CASCADE`. Nếu hai suite cùng trỏ vào một server, chúng sẽ phá schema của nhau và báo ra một loạt lỗi không liên quan. `scripts/ci_verify_tests.py` dùng một file lock (`.ci/pytest-suite.lock`) để buộc lần chạy thứ hai chờ. Trong CI, mỗi job của matrix có service container riêng nên không xung đột; lock chỉ là lưới an toàn cho việc chạy local.
- **Múi giờ**: server ghim UTC qua `ALTER SYSTEM`; `TZ=UTC` cho tiến trình Python. Không dựa vào múi giờ mặc định của runner.
- **Chẩn đoán khi lỗi**: job summary ghi phiên bản Python/PostgreSQL, danh sách database và timezone server — **không** in bất kỳ credential nào.
- **Dọn dẹp**: bốn database disposable bị `DROP` ở step cuối (`if: always()`); service container bị hủy cùng job.

## Triển Khai Tái Lập — Reproducible Deployment

Bộ triển khai local/demo dựng được từ một bản clone sạch bằng **một lệnh**. Hạ tầng (PostgreSQL + Redis) chạy trong container; FastAPI monolith chạy trên host.

Hướng dẫn đầy đủ: [`docs/DEPLOYMENT-v3.3.md`](docs/DEPLOYMENT-v3.3.md).

### Khởi động nhanh

```bash
cp .env.example .env
# điền POSTGRES_PASSWORD và INTERNAL_SECRET (>= 32 ký tự) vào .env
bash scripts/deploy_local.sh up
```

`up` kiểm tra cấu hình → dựng hạ tầng → chờ PostgreSQL → **kiểm tra topology ba database** → khởi động app → chờ `/ready`.

### Các lệnh

| Lệnh | Ý nghĩa |
| --- | --- |
| `scripts/deploy_local.sh up` | Dựng và khởi động toàn bộ deployment |
| `scripts/deploy_local.sh status` | Xem đang chạy gì |
| `scripts/deploy_local.sh verify` | Chạy bộ kiểm chứng deployment (9 nhóm check) |
| `scripts/deploy_local.sh down` | Dừng app + hạ tầng — **giữ nguyên volume** |
| `scripts/deploy_local.sh reset` | Dừng và **xoá volume** — yêu cầu gõ `reset` để xác nhận |
| `scripts/deploy_local.sh logs` | Theo dõi log của app (`.ci/deploy-app.log`) |

### Điểm an toàn đã cài

- PostgreSQL dùng **`scram-sha-256`**, không `trust` (kết nối không mật khẩu bị từ chối). Cùng thiết lập được áp dụng cho CI service container, nên CI và demo deployment enforce **giống hệt** nhau.
- ⚠️ `POSTGRES_INITDB_ARGS` chỉ có tác dụng với **volume mới** — `initdb` đọc nó đúng một lần lúc khởi tạo data directory. Volume tạo trước khi có thiết lập này vẫn giữ cấu hình `trust` cũ; cần `reset` để áp dụng lại.
- Không secret production nào nằm trong Git: `.env` bị gitignore, `.env.example` chỉ chứa placeholder.
- Ba URL database phải trỏ tới **ba database khác nhau** — nếu không, lệnh khởi động từ chối chạy.
- `CORE_APP_URL` và `DETECTION_URL` phải cùng trỏ về monolith (cổng của app) — nếu để mặc định split-service 8000/8001, mọi login event và analytics fetch sẽ đi vào cổng không có gì lắng nghe.
- **Chỉ `reset` mới xoá được volume** — `up` / `verify` / `status` / `logs` / `down` không bao giờ phá huỷ dữ liệu. Bộ kiểm chứng *chứng minh* điều này bằng cách parse thân từng subcommand và từng câu SQL thực thi.
- Không tự động xoá dữ liệu, không `create_all` lúc khởi động, không recreate schema trên database đã có dữ liệu.
- `/health` = liveness, `/ready` = readiness (**trả về tĩnh**, không tra dependency), `sources` của Manager facade = trạng thái từng dependency (degrade thay vì crash). Kiểm chứng dependency thực sự nằm ở bộ check deployment, không phải ở `/ready`.
- Thiếu ML artifact ≠ ML database không khả dụng: cả hai được phân biệt rõ (xem doc §7).

### Kiểm chứng deployment

```bash
bash scripts/deploy_local.sh verify
```

Bộ kiểm chứng kiểm tra: ba database đúng schema canonical và cách ly chéo context; app trả lời; ngữ nghĩa `/health` + `/ready` (kèm xác nhận `/ready` là static); Core auth (register/login/me/sai mật khẩu); Detection nhận login event, ML báo trạng thái artifact **và** chứng minh ML database vẫn reachable độc lập với thiếu artifact; Manager facade đọc được từ cả ba nguồn; dependency chết thì **degrade** (200 + `degraded: true`, nguồn `unavailable` với reason code đóng); dữ liệu sống sót qua restart; **chỉ `reset` mới phá huỷ volume** (chứng minh bằng AST + phân tích thân hàm).

### Các bước kiểm chứng trong CI

| Bước | Lệnh | Ý nghĩa |
| --- | --- | --- |
| Cài dependency | `pip install -r requirements.txt` + `pip check` | Dùng đúng file dependency của repo; mâu thuẫn dependency là lỗi môi trường, fail sớm |
| Dựng hạ tầng | `bash scripts/ci_bootstrap_postgres.sh` | Tạo + nạp 3 DB rời rạc và 1 DB legacy; kiểm tra số bảng và cách ly chéo context |
| Chạy suite | `python scripts/ci_verify_tests.py` | 1.035 test, 0 fail, 0 skip, 0 xfail |
| Smoke HTTP | `python scripts/m10_http_smoke.py` | 79 check qua uvicorn thật trên socket thật |

## Bản Đồ Tàng Kinh — Repository Map

```text
app/                  dịch vụ và tích hợp runtime
infra/postgres/       schema PostgreSQL
research/kaggle/      notebook benchmark
tests/                test ML và parity
scripts/              công cụ hỗ trợ dự án
docs/                 tài liệu dự án kế thừa từ dev
.github/workflows/    pipeline CI
docker-compose.yml    hạ tầng local
```

Tài liệu nội bộ, báo cáo làm việc và ảnh nghiệm thu cục bộ nằm trong `docs/ml/`, được loại khỏi Git bằng `.git/info/exclude`.

## Hiện Trạng — Chiến Tuyến

- Feature parity đã được hiệu chỉnh; runtime và model registry đã được triển khai.
- Benchmark 10M cho thấy Isolation Forest có tín hiệu ATO yếu/không ổn định; **chưa vượt acceptance gate** để nhập Production.
- Không promote artifact, không tuning thêm và không thay đổi Detection trước khi có quyết định của owner.
- PR hiện vẫn chờ human review.
- `dev` là baseline chỉ đọc; mọi công việc ML thực hiện tại `sentinel-auth-ml-service-worktree`.

```bash
Lấy thực chứng làm cương.
Lấy nhân quả làm giới.
Lấy reproducibility làm kiếm.
Lấy sự thật của số liệu định thiên hạ.
```