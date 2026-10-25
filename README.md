# Sentinel Auth — ML Service

## Scope

Khang phụ trách ML inference, vòng đời mô hình và analytics phía ML trên nhánh `ml-service`. Detection Engine vẫn sở hữu việc dựng đặc trưng và hợp nhất điểm rủi ro; mô hình hiện tại chỉ là kết quả thực nghiệm, chưa được phát hành production.

## Architecture

`Core/Auth → Detection → build_features() → POST /api/v1/internal/ml/score → ML Service → sentinel_ml`

Detection gọi ML với thời hạn 5 giây rồi tự quyết định điểm rủi ro cuối. Khi ML lỗi hoặc quá hạn, hệ thống suy giảm an toàn về chấm điểm thuần rule.

## Canonical six features

- `hour_of_day`: giờ UTC của lần đăng nhập hiện tại, từ 0 đến 23.
- `fail_count_24h`: số lần thất bại của cùng người dùng trong 24 giờ trước sự kiện hiện tại.
- `ip_change_rate_7d`: độ mới của IP hiện tại so với lịch sử 7 ngày trước đó.
- `new_device`: thiết bị/user-agent hiện tại chưa xuất hiện trong lịch sử 30 ngày.
- `average_login_interval_seconds`: khoảng cách trung bình giữa tối đa 10 lần đăng nhập lịch sử gần nhất.
- `deviation_score`: độ lệch đã chuẩn hóa của khoảng cách hiện tại so với khoảng cách lịch sử trung bình.

Các truy vấn lịch sử chỉ xét sự kiện có `timestamp < timestamp` của lần đăng nhập đang chấm điểm.

## ML API

- `POST /api/v1/internal/ml/score`
- `GET /api/v1/internal/ml/health`
- `GET /api/v1/internal/ml/features`

Implementation nằm tại `app/ml.py`; caller là `app/detection.py::call_ml_service()`. URL lấy từ `ML_SERVICE_URL` (mặc định `http://localhost:8002`), timeout 5 giây và xác thực nội bộ bằng header `X-Internal-Secret`. Không ghi secret vào tài liệu được theo dõi bởi Git.

## Database

ML Service dùng database `sentinel_ml`:

- schema: `infra/postgres/schema-ml-service-v3.3.sql`
- ORM: `app/models.py`
- kết nối: `app/db.py`
- `model_versions`: registry phiên bản, trạng thái và metadata của mô hình.
- `inference_logs`: nhật ký kết quả suy luận phục vụ kiểm tra và giám sát.
- `feature_statistics`: thống kê phân phối feature theo thời gian.
- `local_ml_stats`: view tổng hợp số liệu suy luận cục bộ.
- hạ tầng local: `docker-compose.yml`

## Training / Research

- Notebook: `research/kaggle/sentinel_rba_isolation_forest.ipynb`
- Kaggle: `lebaokhang/sentinel-auth-train`
- Benchmark 10 triệu dòng đã hoàn tất.
- Isolation Forest hiện là baseline thực nghiệm; artifact giữ `is_production=false` và không được promote.

## Tests

```powershell
pytest tests/test_ml.py -q
pytest tests/test_runtime_feature_parity.py -q
pytest tests/test_ml_runtime.py -q
pytest -q
```

Các test PostgreSQL cần database/driver và biến môi trường tương ứng; thiếu các điều kiện này là environment blocker. Baseline hiện còn lỗi ngoài phạm vi ML tại `app/auth.py` do thiếu `datetime`; không sửa Core trong nhánh này.

## Repository map

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

## Current status

- Feature parity đã được sửa; runtime và model registry đã được triển khai.
- Benchmark 10M cho thấy Isolation Forest có tín hiệu ATO yếu/không ổn định; chưa đạt acceptance gate để tích hợp production.
- Không promote artifact, không tuning thêm và không thay đổi Detection trước khi có quyết định của owner.
- PR hiện vẫn chờ human review.
- `dev` là baseline chỉ đọc; mọi công việc ML thực hiện tại `sentinel-auth-ml-service-worktree`.
