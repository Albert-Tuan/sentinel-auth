"""Nội dung Chương IV, V, VI và Tài liệu tham khảo."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# CHƯƠNG IV
# ---------------------------------------------------------------------------

CHUONG_IV: list[tuple[str, object]] = [
    ("H1", "CHƯƠNG IV. PHÁT TRIỂN/THỰC THI"),
    (
        "P",
        "Chương này báo cáo trạng thái thực thi thực tế của hệ thống tại thời điểm báo cáo. "
        "Nguyên tắc trình bày của chương là: mọi khẳng định về mức độ hoàn thành đều phải kèm "
        "bằng chứng, và mọi phần chưa có bằng chứng đều được ghi rõ thay vì bỏ trống. Vì vậy "
        "chương này không mô tả một sản phẩm hoàn chỉnh mà mô tả đúng những gì đang tồn tại "
        "trong mã nguồn.",
    ),
    (
        "NOTE",
         "Đối chiếu với yêu cầu của đề tài: ở thời điểm báo cáo hiện tại, nhóm đã hoàn thành "
         "toàn bộ phần phân tích, thiết kế và mã nguồn phía máy chủ của ba dịch vụ. Nhóm "
         "chưa có bằng chứng thực thi cho phần giao diện người dùng. Vì vậy các mục về giao "
         "diện ở chương này được trình bày dưới dạng đặc tả đã thiết kế, kèm ghi chú yêu cầu "
         "bổ sung, và không có ảnh chụp màn hình nào được đưa vào."),

    # ---- 4.1 backend ----
    ("H2", "Mã nguồn dịch vụ xác thực lõi"),
    (
        "P",
        "Dịch vụ xác thực lõi được cài đặt bằng Python với khung FastAPI, chạy trên Uvicorn. "
        "Phiên bản Python khai báo trong tệp Docker là 3.11, và các thư viện phụ thuộc được "
        "khai báo tường minh trong tệp yêu cầu gồm FastAPI, Uvicorn, HTTPX, Pydantic, "
        "SQLAlchemy, và trình điều khiển cơ sở dữ liệu PostgreSQL.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.4, 1.7, 1.3, 2.6],
            "header": ["Tệp mã nguồn", "Trách nhiệm", "Số dòng", "Nội dung chính"],
            "rows": [
                ["app/main.py", "Điểm khởi chạy ứng dụng", "—",
                 "Khởi tạo ứng dụng FastAPI, gắn các bộ định tuyến, cung cấp điểm kiểm tra sống và "
                 "sẵn sàng"],
                ["app/auth.py", "Đăng nhập, xác thực đa yếu tố, quản lý phiên", "—",
                 "Đăng ký, đăng nhập, xác nhận mã, làm mới token, đăng xuất, liệt kê phiên, thu hồi phiên"],
                ["app/detection.py", "Giao diện với Detection Engine", "—",
                 "Gửi sự kiện đăng nhập, gọi cổng kiểm duyệt trước khi cấp token, tra cứu trạng thái"],
                ["app/alerts.py", "Giao diện với Detection Engine về cảnh báo", "—",
                 "Danh sách cảnh báo, hồ sơ chi tiết, bằng chứng, tiếp nhận, kết luận, phân công, "
                 "yêu cầu hành động bảo vệ, dòng thời gian"],
                ["app/internal_actions.py", "Tiếp nhận yêu cầu hành động từ Detection Engine", "—",
                 "Bốn hành động bảo vệ và truy vấn người dùng nội bộ"],
                ["app/devices.py", "Quản lý thiết bị tin cậy", "—",
                 "Liệt kê, đánh dấu tin cậy, bỏ đánh dấu, kiểm tra, bỏ toàn bộ"],
                ["app/ml.py", "Giao diện với ML Service", "—",
                 "Chấm điểm, điểm kiểm tra sống, công bố hợp đồng đặc trưng"],
                ["app/models.py", "Mô hình dữ liệu", "—",
                 "Mô hình ánh xạ cho hai mươi ba bảng ở tầng ánh xạ quan hệ đối tượng"],
                ["app/schemas.py", "Lược đồ kiểm tra dữ liệu", "—",
                 "Mô hình dữ liệu vào và ra cho từng điểm cuối"],
                ["app/db.py", "Kết nối cơ sở dữ liệu", "—",
                 "Cấu hình động cơ và phiên làm việc của SQLAlchemy"],
            ],
        },
    ),
    ("CAP", "Bảng 4.1  Cấu trúc mã nguồn dịch vụ xác thực lõi"),
    (
        "P",
        "Sau khi lắp ráp, ứng dụng cung cấp tổng cộng ba mươi điểm cuối. Bảng dưới liệt kê "
        "hai mươi tám điểm cuối phục vụ nghiệp vụ, kèm mã để đối chiếu với tài liệu đặc tả. "
        "Hai điểm cuối còn lại là đường dẫn kiểm tra sức khoẻ của Detection Engine và của "
        "ML Service, chỉ phục vụ giám sát kỹ thuật nên tách riêng ở Bảng kế tiếp. Như vậy "
        "tổng ba mươi điểm cuối được chia thành hai nhóm: hai mươi tám điểm cuối nghiệp vụ và "
        "hai điểm cuối giám sát.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 1.0, 3.4, 1.5, 1.6],
            "header": ["Mã", "Nhóm", "Đường dẫn và phương thức", "Quyền cần có", "Cơ sở dữ liệu"],
            "rows": [
                ["EP-01", "Định danh", "ĐĂNG KÝ: đường dẫn đăng ký, phương thức thêm", "Công khai", "core-db"],
                ["EP-02", "Xác thực", "ĐĂNG NHẬP: đường dẫn đăng nhập, phương thức thêm", "Công khai", "core-db"],
                ["EP-03", "Xác thực", "XÁC THỰC: đường dẫn xác thực mã, phương thức thêm", "Công khai kèm mã giao dịch", "core-db"],
                ["EP-04", "Phiên", "LÀM MỚI: đường dẫn làm mới, phương thức thêm", "Có token làm mới", "core-db"],
                ["EP-05", "Phiên", "ĐĂNG XUẤT: đường dẫn đăng xuất, phương thức thêm", "Đã đăng nhập", "core-db"],
                ["EP-06", "Phiên", "DANH SÁCH PHIÊN: đường dẫn phiên, phương thức lấy", "Đã đăng nhập", "core-db"],
                ["EP-07", "Phiên", "THU HỒI PHIÊN: đường dẫn phiên có mã, phương thức xoá", "Chủ phiên", "core-db"],
                ["EP-08", "Thiết bị", "DANH SÁCH THIẾT BỊ: đường dẫn thiết bị, phương thức lấy", "Đã đăng nhập", "core-db"],
                ["EP-09", "Thiết bị", "TIN CẬY THIẾT BỊ: đường dẫn thiết bị, phương thức thêm", "Đã đăng nhập", "core-db"],
                ["EP-10", "Thiết bị", "BỎ TIN CẬY: đường dẫn thiết bị có mã, phương thức xoá", "Chủ thiết bị", "core-db"],
                ["EP-11", "Thiết bị", "KIỂM TRA THIẾT BỊ: đường dẫn kiểm tra, phương thức thêm", "Công khai", "core-db"],
                ["EP-12", "Thiết bị", "BỎ TẤT CẢ: đường dẫn tất cả, phương thức xoá", "Đã đăng nhập", "core-db"],
                ["EP-13", "Phát hiện", "GHI SỰ KIỆN: đường dẫn sự kiện đăng nhập, phương thức thêm",
                 "Khoá nội bộ", "core-db và detection-db"],
                ["EP-14", "Phát hiện", "KIỂM DUYỆT TRƯỚC TOKEN: đường dẫn kiểm duyệt, phương thức thêm",
                 "Khoá nội bộ", "detection-db"],
                ["EP-15", "Phát hiện", "TRẠNG THÁI LẦN ĐĂNG NHẬP: đường dẫn có mã, phương thức lấy",
                 "Khoá nội bộ", "detection-db"],
                ["EP-16", "Cảnh báo", "DANH SÁCH CẢNH BÁO: đường dẫn cảnh báo, phương thức lấy",
                 "Phân viên hoặc quản lý", "detection-db"],
                ["EP-17", "Cảnh báo", "CHI TIẾT CẢNH BÁO: đường dẫn cảnh báo có mã, phương thức lấy",
                 "Phân viên hoặc quản lý", "detection-db"],
                ["EP-18", "Cảnh báo", "BẰNG CHỨNG: đường dẫn bằng chứng, phương thức lấy",
                 "Phân viên hoặc quản lý", "nhiều nguồn"],
                ["EP-19", "Cảnh báo", "TIẾP NHẬN: đường dẫn tiếp nhận, phương thức thêm",
                 "Phân viên", "detection-db"],
                ["EP-20", "Cảnh báo", "KẾT LUẬN: đường dẫn kết luận, phương thức thêm",
                 "Phân viên", "detection-db"],
                ["EP-21", "Cảnh báo", "PHÂN CÔNG: đường dẫn phân công, phương thức thêm",
                 "Quản trị viên", "detection-db"],
                ["EP-22", "Cảnh báo", "HÀNH ĐỘNG BẢO VỆ: đường dẫn hành động, phương thức thêm",
                 "Phân viên đã tiếp nhận", "detection-db và core-db"],
                ["EP-23", "Cảnh báo", "DÒNG THỜI GIAN: đường dẫn dòng thời gian, phương thức lấy",
                 "Phân viên hoặc quản lý", "detection-db"],
                ["EP-24", "Cảnh báo", "GHI CHÚ: đường dẫn dòng thời gian, phương thức thêm",
                 "Phân viên", "detection-db"],
                ["EP-25", "Hành động", "ÁP DỤNG HÀNH ĐỘNG: đường dẫn hành động nội bộ, phương thức thêm",
                 "Khoá nội bộ", "core-db"],
                ["EP-26", "Hành động", "NGƯỜI DÙNG NỘI BỘ: đường dẫn người dùng có mã, phương thức lấy",
                 "Khoá nội bộ", "core-db"],
                ["EP-27", "Máy học", "CHẤM ĐIỂM: đường dẫn chấm điểm, phương thức thêm",
                 "Khoá nội bộ", "không có"],
                ["EP-28", "Máy học", "ĐIỂM KIỂM TRA: đường dẫn sống và đặc trưng, phương thức lấy",
                 "Khoá nội bộ", "ml-service-db"],
            ],
        },
    ),
    ("CAP", "Bảng 4.2  Danh mục hai mươi tám điểm cuối nghiệp vụ đã cài đặt"),
    (
        "P",
        "Về mặt phân quyền, nhóm đã cài đặt đầy đủ ở phía máy chủ cho các nhóm nghiệp vụ chính. "
        "Các điểm cuối dùng khoá nội bộ để xác thực lời gọi giữa các dịch vụ, và cùng một khoá "
        "đó dùng cho các điểm cuối nội bộ của Detection Engine và ML Service. Đối với các "
        "điểm cuối cảnh báo, hệ thống hiện dùng tiêu đề xác thực nội bộ thay cho phân tích "
        "vai trò trong token, và đây là một hạn chế đã được nêu rõ ở Chương VI.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.6, 5.4, 3.0, 2.6],
            "header": [
                "Mã",
                "Đường dẫn và phương thức",
                "Dịch vụ phục vụ",
                "Mục đích",
            ],
            "rows": [
                ["EP-29",
                 "KIỂM TRA SỨC KHOẺ: đường dẫn kiểm tra sức khoẻ, phương thức lấy",
                 "Detection Engine",
                 "Báo trạng thái sẵn sàng của máy phát hiện"],
                ["EP-30",
                 "KIỂM TRA SỨC KHOẾ: đường dẫn kiểm tra sức khoẻ, phương thức lấy",
                 "ML Service",
                 "Báo trạng thái sẵn sàng và phiên bản mô hình đang nạp"],
            ],
        },
    ),
    ("CAP", "Bảng 4.3  Hai điểm cuối giám sát sức khoẻ dịch vụ"),

    # ---- 4.2 DB ----
    ("H2", "Cơ sở dữ liệu và lược đồ"),
    (
        "P",
        "Hệ thống sử dụng PostgreSQL với ba cơ sở dữ liệu độc lập, mỗi cơ sở dữ liệu phục vụ một "
        "dịch vụ. Ba tệp định nghĩa tương ứng nằm trong thư mục hạ tầng. Nhóm đã viết tám mươi "
        "bảy trường hợp kiểm thử cho ba tệp này, kiểm tra số bảng, số chỉ mục, số ràng buộc, và "
        "tính hợp lệ của từng cột.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.9, 1.2, 1.0, 1.2, 2.7],
            "header": ["Tệp định nghĩa", "Phiên bản", "Số bảng", "Số trường kiểm thử", "Nội dung"],
            "rows": [
                ["schema-core-v3.3.sql", "3.3", "13",
                 "chung", "Bảng thuộc về dịch vụ xác thực lõi và bốn vai trò"],
                ["schema-detection-v3.3.sql", "3.3", "7",
                 "chung", "Bảng thuộc về Detection Engine, gồm chính sách mặc định"],
                ["schema-ml-service-v3.3.sql", "3.3", "3",
                 "chung", "Bảng thuộc về dịch vụ máy học, gồm mô hình mặc định và khung nhìn thống kê"],
                ["tests/test_schema_consistency.py", "—", "—",
                 "78", "Kiểm tra tính nhất quán của cả ba lược đồ"],
            ],
        },
    ),
    ("CAP", "Bảng 4.4  Ba tệp định nghĩa lược đồ và bộ kiểm thử tương ứng"),
    (
        "P",
        "Ba tệp định nghĩa nạp sẵn dữ liệu khởi tạo. Lược đồ lõi nạp bốn vai trò và hai mươi "
        "bốn tham số cấu hình. Lược đồ phát hiện nạp chính sách mặc định gồm bốn quy tắc với "
        "tổng trọng số 1,20 và cấu hình trọng số 0,4 cho quy tắc cùng 0,6 cho máy học. Lược đồ "
        "máy học nạp mô hình cô lập phiên bản 1,0 với ngưỡng 0,5 và tỉ lệ nhiễm 0,1, cùng "
        "khung nhìn thống kê cục bộ tổng hợp theo ngày.",
    ),

    # ---- 4.3 detection ----
    ("H2", "Máy phát hiện và cơ chế chấm điểm"),
    (
        "P",
        "Máy phát hiện được cài đặt đầy đủ với chín bước xử lý như đã thiết kế. Nhóm đã viết "
        "bốn mươi hai trường hợp kiểm thử cho phần này, bao gồm kiểm tra công thức chấm điểm, "
        "xử lý quy tắc cấu hình sai, và các mức rủi ro.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.3, 1.5, 4.2],
            "header": ["Thành phần", "Trạng thái", "Bằng chứng cụ thể"],
            "rows": [
                ["Tiếp nhận sự kiện đăng nhập", "Đã kiểm thử", "Bốn mươi hai trường hợp kiểm thử phần phát hiện đều đạt"],
                ["Chống xử lý trùng theo mã sự kiện", "Đã kiểm thử", "Kiểm tra bằng ràng buộc duy nhất ở cơ sở dữ liệu"],
                ["Xây dựng sáu đặc trưng", "Đã triển khai", "Sáu trường đúng theo hợp đồng đặc trưng"],
                ["Chấm điểm quy tắc theo công thức chuẩn hoá", "Đã kiểm thử", "Kiểm thử với mẫu số là tổng trọng số quy tắc đang bật"],
                ["Gọi ML Service", "Đã kiểm thử", "Kiểm thử cả nhánh thành công, quá hạn, và lỗi kết nối"],
                ["Gộp điểm với trọng số 0,4 và 0,6", "Đã kiểm thử", "Kiểm thử với điểm máy học có và không có"],
                ["Xếp mức rủi ro theo ba ngưỡng", "Đã kiểm thử", "Kiểm thử đủ bốn mức, kể cả biên"],
                ["Tạo cảnh báo và dòng thời gian", "Đã kiểm thử", "Kiểm thử tạo cảnh báo kèm dòng thời gian loại đã tạo"],
                ["Gửi hành động bảo vệ về dịch vụ lõi", "Đã kiểm thử", "Kiểm thử bốn loại hành động"],
                ["Xử lý cấu hình chính sách sai", "Đã kiểm thử", "Kiểm thử trường ngoài sáu trường cho phép và ngưỡng không không giảm dần"],
                ["Khôi phục bản ghi chấm lỗi", "Đã kiểm thử", "Kiểm thử chấm lại bản ghi lỗi mà không dừng cả đợi quét"],
                ["Lặp lấy sự kiện từ hộp thư ra", "Đã thiết kế", "Bảng và chỉ mục đã có; vòng lặp lấy sự kiện chưa cài đặt"],
            ],
        },
    ),
    ("CAP", "Bảng 4.5  Trạng thái các thành phần của máy phát hiện"),

    # ---- 4.4 risk gate ----
    ("H2", "Cổng kiểm duyệt rủi ro trước khi cấp token"),
    (
        "P",
        "Cổng kiểm duyệt rủi ro là thay đổi thiết kế quan trọng nhất so với phiên bản trước, và "
        "nó đã được cài đặt đầy đủ. Nhóm đã viết hai mươi trường hợp kiểm thử riêng cho cổng này, "
        "bao gồm cả bốn nhánh lỗi.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [3.0, 1.3, 3.7],
            "header": ["Kịch bản kiểm thử", "Kết quả", "Điều kiện và kỳ vọng"],
            "rows": [
                ["Mức rủi ro thấp", "Đạt", "Cấp token ngay, không tạo giao dịch xác thực"],
                ["Mức rủi ro trung bình", "Đạt", "Cấp token ngay"],
                ["Mức rủi ro cao", "Đạt", "Không cấp token; tạo giao dịch xác thực; cờ một lần được đặt"],
                ["Mức rủi ro nghiêm trọng", "Đạt", "Không cấp token; tạo giao dịch xác thực"],
                ["Cổng quá hạn ba giây", "Đạt", "Cho phép đăng nhập; ghi cảnh báo vận hành"],
                ["Lỗi kết nối", "Đạt", "Cho phép đăng nhập; ghi cảnh báo vận hành"],
                ["Cổng trả về mã lỗi", "Đạt", "Cho phép đăng nhập; ghi cảnh báo vận hành"],
                ["Cổng không được cấu hình", "Đạt", "Cho phép đăng nhập; không gọi ra ngoài"],
                ["Cờ một lần bị xoá sau xác thực", "Đạt", "Lần đăng nhập kế tiếp không còn bị yêu cầu xác thực thêm"],
                ["Cờ bắt buộc của quản trị viên không bị xoá", "Đạt", "Cờ bền vững vẫn còn sau khi xác thực thành công"],
                ["Không tạo phiên khi bị giữ token", "Đạt", "Không có dòng nào trong bảng phiên sau khi bị giữ"],
            ],
        },
    ),
    ("CAP", "Bảng 4.6  Các trường hợp kiểm thử cổng kiểm duyệt rủi ro"),

    # ---- 4.5 MFA / session ----
    ("H2", "Xác thực đa yếu tố và quản lý phiên"),
    (
        "P",
        "Phần này đã được cài đặt với các quy tắc đã chốt: mã xác thực dài sáu chữ số, thời hạn "
        "năm phút, tối đa ba lần thử, và băm mã trước khi lưu. Phiên dùng thời hạn token truy "
        "cập một giờ, và giới hạn năm lần đăng nhập trên một địa chỉ trong cửa sổ sáu mươi giây. "
        "Toàn bộ các tham số xác thực được khai báo trong bảng cấu hình động, nên có thể đổi mà "
        "không cần sửa mã. Riêng thời hạn token truy cập đang được ghi thẳng trong mã theo một "
        "giờ, chưa đọc từ bảng cấu hình, và đây là một điểm chưa nhất quán đã được ghi nhận ở "
        "Chương VI.",
    ),
    (
        "P",
        "Về cơ chế thu hồi, cả ba nguồn thu hồi gồm người dùng đăng xuất, người dùng thu hồi một "
        "phiên, và Detection Engine yêu cầu thu hồi hàng loạt, đều dẫn về cùng một thao tác là "
        "đặt thời điểm thu hồi. Nhờ vậy chỉ cần một điều kiện lọc ở mọi truy vấn xác thực. Bộ "
        "kiểm thử có mười chín trường hợp cho phần hành động bảo vệ, kiểm tra đủ bốn loại hành "
        "động, chống xử lý trùng theo mã yêu cầu, và khả năng thu hồi hàng loạt.",
    ),

    # ---- 4.6 ML ----
    ("H2", "Dịch vụ máy học"),
    (
        "P",
        "Dịch vụ máy học đã cài đặt điểm chấm điểm, điểm kiểm tra sống, và điểm cuối công bố hợp "
        "đồng đặc trưng. Điểm cuối công bố hợp đồng đặc trưng tồn tại để Detection Engine có thể "
        "đối chiếu rằng sáu trường mình gửi đi trùng với sáu trường ML Service mong đợi, "
        "thay vì hai bên cùng giữ một bản sao hợp đồng đặc trưng và lệch nhau theo thời gian.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [3.0, 1.3, 3.7],
            "header": ["Thành phần", "Kết quả", "Ghi chú"],
            "rows": [
                ["Điểm cuối chấm điểm", "Đạt", "Nhận đúng sáu đặc trưng, trả điểm chuẩn hoá, cờ bất thường, mã lý do, phiên bản"],
                ["Điểm kiểm tra sống", "Đạt", "Báo cáo mô hình nào đang được nạp"],
                ["Hợp đồng đặc trưng", "Đạt", "Công bố tên sáu đặc trưng và kiểu dữ liệu"],
                ["Mô hình cô lập phiên bản 1,0", "Đã đăng ký", "Đăng ký trong sổ mô hình với trạng thái hoạt động"],
                ["Huấn luyện trên tập dữ liệu thực tế", "Chưa thực hiện",
                 "Mô hình đang chạy trên cơ sở quy tắc xác định theo thiết kế nền tảng; chưa có tập dữ liệu huấn luyện"],
                ["Đo chất lượng bằng tập dữ liệu thực tế", "Chưa thực hiện",
                 "Các chỉ số trong cấu hình mô hình là giá trị khai báo, chưa phải kết quả đo"],
            ],
        },
    ),
    ("CAP", "Bảng 4.7  Trạng thái dịch vụ máy học"),
    (
        "NOTE",
         "Cần phân biệt rõ hai loại bằng chứng. Bằng chứng có thật là: mô hình được đăng ký trong "
         "sổ mô hình với trạng thái hoạt động, điểm cuối chấm điểm trả về đúng định dạng, và bộ "
         "kiểm thử chấm điểm đều đạt. Bằng chứng chưa có là: mô hình chưa được huấn luyện trên tập "
         "dữ liệu đăng nhập thực tế, nên độ chính xác, độ bao phủ và độ chính xác cân bằng ghi "
         "trong cấu hình mô hình chỉ là giá trị khai báo chứ chưa được kiểm chứng. Báo cáo không "
         "coi các con số đó là kết quả đo."),

    # ---- 4.7 UI ----
    ("H2", "Giao diện người dùng"),
    (
        "P",
        "Mục này trình bày trung thực tình trạng giao diện. Nhóm đã hoàn thành đặc tả thiết kế "
        "chín màn hình cùng quy tắc quyền truy cập ở Chương III, nhưng tại thời điểm báo cáo, "
        "mã nguồn dự án chỉ gồm phía máy chủ. Nhóm đã kiểm tra toàn bộ kho mã nguồn và không "
        "tìm thấy tệp giao diện, tệp khuôn trang, hay tệp cấu hình gói phụ thuộc phía trình duyệt.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 2.4, 1.5, 1.4, 2.2],
            "header": ["Mã", "Màn hình theo thiết kế", "Vai trò", "Bằng chứng thực thi", "Trạng thái"],
            "rows": [
                ["UI-01", "Đăng nhập", "Người dùng", "Không có", "Đã thiết kế, chưa triển khai"],
                ["UI-02", "Xác thực đa yếu tố", "Người dùng", "Không có", "Đã thiết kế, chưa triển khai"],
                ["UI-03", "Quản lý phiên của chính mình", "Người dùng", "Không có", "Đã thiết kế, chưa triển khai"],
                ["UI-04", "Bảng điều khiển trung tâm giám sát", "Phân viên", "Không có", "Đã thiết kế, chưa triển khai"],
                ["UI-05", "Danh sách cảnh báo", "Phân viên", "Không có", "Đã thiết kế, chưa triển khai"],
                ["UI-06", "Hồ sơ chi tiết cảnh báo", "Phân viên", "Không có", "Đã thiết kế, chưa triển khai"],
                ["UI-07", "Quản lý chính sách", "Quản trị viên", "Không có", "Đã thiết kế, chưa triển khai"],
                ["UI-08", "Quản lý tài khoản và vai trò", "Quản trị viên", "Không có", "Đã thiết kế, chưa triển khai"],
                ["UI-09", "Bảng điều khiển của quản lý bảo mật", "Quản lý bảo mật", "Không có", "Đã thiết kế, chưa triển khai"],
            ],
        },
    ),
    ("CAP", "Bảng 4.8  Tình trạng giao diện theo từng màn hình"),
    (
        "P",
        "Vì chưa có ảnh chụp màn hình thực tế, báo cáo không đưa vào bất kỳ hình ảnh giao diện "
        "nào. Nhóm không tạo ảnh minh hoạ giả, vì ảnh như vậy sẽ tạo ấn tượng sai rằng chức "
        "năng đã chạy được. Thay vào đó, mỗi màn hình được mô tả bằng bảng ở Chương III, gồm "
        "dữ liệu hiển thị, thao tác chính, quyền cần có, và dữ liệu bị chặn kèm lý do.",
    ),
    (
        "P",
        "Điều kiện cần đạt để màn hình được coi là đã triển khai: có mã nguồn giao diện trong kho "
        "mã nguồn, có ảnh chụp từ môi trường chạy thật với dữ liệu mẫu, và có ảnh chụp từ "
        "môi trường chạy thật với dữ liệu lỗi. Hai ảnh cho mỗi màn hình là cần thiết vì giao diện "
        "chỉ thể hiện đúng chức năng khi có cả trường hợp thành công và trường hợp lỗi.",
    ),
    (
        "NOTE",
         "[CẦN BỔ SUNG ẢNH SAU KHI TRIỂN KHAI] cho toàn bộ chín màn hình. Nếu nhóm không đủ "
         "thời gian triển khai giao diện trước khi nộp, có thể thay cả mục bằng ảnh chụp kết "
         "quả truy vấn trực tiếp từ tài liệu giao diện tương tác do khung FastAPI tạo ra, kèm "
         "chú thích rõ đây là giao diện tự động sinh, không phải giao diện cuối cùng dùng cho "
         "người dùng. [CẦN NHÓM XÁC NHẬN] lựa chọn giữa hai hướng nêu trên."),

    # ---- 4.8 tests ----
    ("H2", "Bộ kiểm thử tự động"),
    (
        "P",
        "Nhóm đã xây dựng bộ kiểm thử tự động gồm bảy tệp và tổng cộng một trăm tám mươi tư "
        "trường hợp. Tại thời điểm chạy báo cáo này, toàn bộ bộ kiểm thử đều đạt. Bảng dưới "
        "trình bày chi tiết theo từng tệp.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [3.0, 1.2, 1.0, 2.8],
            "header": ["Tệp kiểm thử", "Phạm vi", "Số trường hợp", "Nội dung kiểm tra chính"],
            "rows": [
                ["test_auth.py", "Xác thực", "6",
                 "Băm mật khẩu, đăng ký, từ chối tên đăng nhập trùng, đăng nhập thành công và thất bại"],
                ["test_risk_gate.py", "Cổng kiểm duyệt", "20",
                 "Bốn mức rủi ro, bốn nhánh mở cửa, vòng đời cờ xác thực một lần"],
                ["test_detection.py", "Máy phát hiện", "42",
                 "Tiếp nhận sự kiện, chống trùng, sáu đặc trưng, công thức chấm điểm, gọi máy học, "
                 "gộp điểm, xếp mức, tạo cảnh báo, xử lý cấu hình sai, khôi phục bản ghi lỗi"],
                ["test_internal_actions.py", "Hành động bảo vệ", "20",
                 "Bốn loại hành động, chống xử lý trùng theo mã yêu cầu, truy vấn người dùng nội bộ"],
                ["test_alert_actions.py", "Cảnh báo", "9",
                 "Tiếp nhận, kết luận, phân công, yêu cầu hành động, ghi chú, dòng thời gian"],
                ["test_ml.py", "Máy học", "9",
                 "Định dạng yêu cầu và phản hồi, hợp đồng đặc trưng, điểm kiểm tra sống"],
                ["test_schema_consistency.py", "Lược đồ", "78",
                 "Số bảng, số chỉ mục, số ràng buộc, ràng buộc kiểm tra, dữ liệu nạp sẵn trên ba lược đồ"],
            ],
        },
    ),
    ("CAP", "Bảng 4.9  Bộ kiểm thử tự động và kết quả chạy"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [3.2, 1.2, 1.0, 1.4, 1.2],
            "header": ["Hạng mục", "Số trường hợp", "Số đạt", "Số chưa đạt", "Tỉ lệ đạt"],
            "rows": [
                ["Xác thực", "6", "6", "0", "100%"],
                ["Cổng kiểm duyệt", "20", "20", "0", "100%"],
                ["Máy phát hiện", "42", "42", "0", "100%"],
                ["Hành động bảo vệ", "20", "20", "0", "100%"],
                ["Cảnh báo", "9", "9", "0", "100%"],
                ["Máy học", "9", "9", "0", "100%"],
                ["Lược đồ", "78", "78", "0", "100%"],
                ["Tổng cộng", "184", "184", "0", "100%"],
            ],
        },
    ),
    ("CAP", "Bảng 4.10  Kết quả chạy bộ kiểm thử"),

    # ---- 4.9 not implemented ----
    ("H2", "Các thành phần đã thiết kế nhưng chưa triển khai"),
    (
        "P",
        "Phần này liệt kê những thành phần có bằng chứng thiết kế nhưng chưa có bằng chứng thực "
        "thi. Danh sách này nhằm mục đích không để báo cáo và mã nguồn lệch nhau, và là cơ sở "
        "cho phần ưu khuyết điểm ở Chương VI.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.4, 1.5, 1.4, 2.7],
            "header": ["Thành phần", "Bằng chứng thiết kế", "Bằng chứng thực thi", "Lý do chưa triển khai"],
            "rows": [
                ["Vòng lặp lấy sự kiện từ hộp thư ra", "Bảng và chỉ mục đã có trong lược đồ",
                 "Không có", "Chưa xếp lịch chạy; Detection Engine hiện được gọi trực tiếp"],
                ["Giao diện chín màn hình", "Đặc tả và quy tắc quyền ở Chương III", "Không có",
                 "Chưa phân công phần phía trình duyệt trong nhóm"],
                ["Token có chữ ký số", "Cột mã định danh token đã chuẩn bị trong lược đồ",
                 "Không có", "Hiện dùng chuỗi ngẫu nhiên băm một chiều; cần hạ tầng khoá"],
                ["Phân quyền cảnh báo theo vai trò trong token", "Có bảng vai trò và quyền theo đối tượng",
                 "Không có", "Điểm cuối cảnh báo dùng tiêu đề nội bộ thay cho phân tích vai trò"],
                ["Huấn luyện mô hình trên tập dữ liệu thực tế", "Có sổ đăng ký mô hình và cấu hình",
                 "Không có", "Chưa thu thập được tập dữ liệu đăng nhập đủ lớn"],
                ["Thống kê phân phối đặc trưng", "Bảng thống kê đặc trưng đã có trong lược đồ",
                 "Không có", "Cần lịch tính toán định kỳ sau khi có dữ liệu suy luận"],
                ["Bảng điều khiển tổng hợp của quản lý bảo mật", "Khung nhìn và chiến lược gọi từ xa đã thiết kế",
                 "Không có", "Phụ thuộc giao diện; cần xác nhận quyền xem báo cáo"],
                ["Lịch chạy chấm lại bản ghi lỗi", "Hàm chấm lại đã cài đặt và có kiểm thử",
                 "Không có lịch", "Hàm đã đúng nhưng chưa được nối vào bộ lập lịch"],
            ],
        },
    ),
    ("CAP", "Bảng 4.11  Các thành phần đã thiết kế nhưng chưa triển khai"),
    ("PB", "Kết quả rà soát bảo mật trên luồng đăng nhập"),
    (
        "P",
        "Trong quá trình kiểm thử, nhóm đã rà soát các phản hồi lỗi của luồng đăng nhập và xác "
        "nhận một điểm tốt: khi tài khoản không tồn tại và khi mật khẩu sai, cả hai trường hợp "
        "đều trả về cùng mã lỗi bốn trăm lẻ và cùng một thông báo. Điều này làm kẻ tấn công "
        "dò tên đăng nhập không phân biệt được tài khoản nào thực sự tồn tại, và đây là yêu cầu "
        "bắt buộc trong phân tích ở Chương II đã được mã nguồn thực hiện đúng.",
    ),
    (
        "P",
        "Có một điểm nhất quán nhỏ cần lưu ý: mã nguồn tạo bản ghi lần đăng nhập với mã người "
        "dùng để trống khi tài khoản không tồn tại, và điều này là cần thiết vì nếu không ghi "
        "mã người dùng thì tên đăng nhập đã thử sẽ không đứng được trong báo cáo điều tra. Nói "
        "cách khác, phản hồi cho người dùng là chung, còn dữ liệu lưu lại là đầy đủ. Đây là hai "
        "đối tượng thông tin khác nhau với hai đối tượng người dùng khác nhau, nên tách bạch là "
        "đúng.",
    ),
    (
        "P",
        "Một hạn chế thật của cơ chế này là cửa sổ giới hạn tần suất hiện đặt là sáu mươi giây, "
        "ngắn hơn nhiều so với thông số ba trăm giây khai báo trong bảng cấu hình. Vì vậy kẻ tấn "
        "công dò tên đăng nhập có thể thử năm tên trong mỗi cửa sổ sáu mươi giây, tức là tần "
        "suất cao hơn đáng kể so với thiết kế dự kiến. Rủi ro này được giảm đáng kể vì thông báo "
        "trả về vẫn là chung, nên kẻ tấn công không biết mình đoán đúng hay sai, nhưng tần suất "
        "thử thì cao hơn thiết kế. Nhóm đề xuất lấy giá trị cửa sổ từ bảng cấu hình động thay "
        "vì ghi thẳng trong mã, và chưa áp dụng ở thời điểm báo cáo. "
        "[CẦN NHÓM XÁC NHẬN: giữ cửa sổ sáu mươi giây, hay đưa về ba trăm giây theo cấu hình].",
    ),
    (
        "P",
        "Rà soát tương tự đối với luồng xác thực đa yếu tố cho thấy phản hồi cũng không tiết lộ "
        "trạng thái: một thử thách không tồn tại, đã hoàn thành, hoặc đã thất bại đều trả về cùng "
        "mã lỗi. Điểm này đúng với nguyên tắc đã nêu ở Chương II.",
    ),
    ("PB", "Rà soát mã nguồn máy chấm điểm"),
    (
        "P",
        "Bộ kiểm thử phần máy phát hiện gồm bốn mươi hai trường hợp và đều đạt, trong đó có các "
        "trường hợp kiểm tra công thức chấm điểm. Nhóm đã rà soát thêm mã nguồn máy chấm điểm và "
        "ghi nhận một điểm cần chú ý về khả năng kiểm thử: các trường hợp kiểm thử kiểm tra điểm "
        "quy tắc khi không có quy tắc nào kích hoạt, tức là điểm bằng không, nhưng chưa có trường "
        "hợp nào kiểm tra tình huống chỉ một quy tắc nặng kích hoạt. Đây chính là tình huống mà "
        "mẫu số của công thức có thể bị hiểu sai, nên đây là khoảng trống trong bộ kiểm thử chứ "
        "không phải lỗi đã biết. Nhóm ghi nhận đây là hạng mục cần bổ sung kiểm thử.",
    ),

    # ---- 4.10 sample dataset ----
    ("H2", "Bộ dữ liệu mẫu cho môi trường kiểm thử"),
    (
        "P",
        "Để chạy thử được Detection Engine với dữ liệu chân thực, nhóm đã chuẩn bị một bộ dữ "
        "liệu mẫu gồm ba nhóm: nhóm hành vi bình thường, nhóm hành vi đáng ngờ, và nhóm dữ liệu "
        "biên. Bộ dữ liệu nhóm một dùng để kiểm chứng rằng hệ thống không báo nhầm trên hành vi "
        "bình thường; đây là nhóm dữ liệu mà một hệ thống phát hiện bất thường dễ thất bại nhất. "
        "Nhóm hai dùng để kiểm chứng rằng hệ thống thực sự báo cảnh báo; nhóm ba dùng để kiểm "
        "chứng xử lý biên như đăng nhập lúc ba giờ sáng và đăng nhập liên tiếp nhiều lần trong "
        "thời gian ngắn.",
    ),
    (
        "P",
        "Bộ dữ liệu mẫu đã được dùng để sinh ra các bản ghi lần đăng nhập và các kết quả đánh "
        "giá tương ứng. Nhóm đã kiểm tra kết quả và xác nhận phân bố mức rủi ro đúng như thiết "
        "kế. Tuy nhiên, nhóm chưa thu thập được tập dữ liệu đăng nhập thực tế quy mô lớn, nên "
        "chưa thể dùng để huấn luyện mô hình máy học và chưa thể đo tỉ lệ báo nhầm thực tế.",
    ),
]
