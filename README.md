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

## Bản Đồ Tàng Kinh — Repository Map

```text
app/                  dịch vụ và tích hợp runtime
infra/postgres/       schema PostgreSQL
research/kaggle/      notebook benchmark
tests/                test ML và parity
scripts/              công cụ hỗ trợ dự án
docs/                 tài liệu dự án kế thừa từ dev
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