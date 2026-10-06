"""Nội dung Chương III phần 2: cấu trúc bảng, thiết kế giao diện, thiết kế xử lý."""

from __future__ import annotations

CHUONG_III_B: list[tuple[str, object]] = [
    ("H3", "Cấu trúc các bảng"),
    (
        "P",
        "Phần này mô tả từng bảng theo cấu trúc thực tế đã khai báo trong các tệp định "
        "nghĩa cơ sở dữ liệu của dự án. Mỗi bảng được trình bày bằng một bảng thuộc tính "
        "gồm tên cột, kiểu dữ liệu, khoá chính hoặc ngoại, khả năng để trống, ràng buộc duy "
        "nhất, giá trị mặc định và ý nghĩa. Các ràng buộc kiểm tra được đặt ở mức cơ sở dữ "
        "liệu được ghi rõ trong cột ghi chú, vì chúng là cơ chế bảo vệ cuối cùng khi mã ứng "
        "dụng có lỗi.",
    ),
    (
        "NOTE",
         "Tất cả bảng trong phần này đã được khai báo trong tệp định nghĩa và đã được dựng "
         "trên cơ sở dữ liệu thật. Bảy bảng nằm ở cơ sở dữ liệu core-db, bảy bảng nằm ở "
         "cơ sở dữ liệu detection-db, và ba bảng nằm ở cơ sở dữ liệu ml-service-db. Nhóm đã "
         "chạy bộ kiểm thử kiểm tra tính nhất quán của lược đồ, gồm kiểm tra tổng số bảng, "
         "tổng số chỉ mục và tổng số ràng buộc, và toàn bộ bộ kiểm thử đều đạt."),
    ("H4", "Nhóm 1: cơ sở dữ liệu core-db"),
    ("P", "Bảy bảng phục vụ định danh, xác thực, quản lý phiên và kiểm toán."),

    # ---- users ----
    ("H5", "Bảng users - tài khoản người dùng"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh tài khoản"],
                ["username", "TEXT", "—", "—", "—",
                 "Tên đăng nhập; duy nhất; dài 3 đến 50 ký tự; chỉ gồm chữ, số và gạch dưới"],
                ["password_hash", "TEXT", "—", "—", "—", "Bản băm Argon2id của mật khẩu"],
                ["email", "TEXT", "—", "—", "NULL",
                 "Thư điện tử; duy nhất khi có giá trị; định dạng được kiểm tra bằng biểu thức thường lệnh"],
                ["full_name", "TEXT", "—", "—", "NULL", "Họ và tên hiển thị"],
                ["status", "TEXT", "—", "—", "'active'",
                 "Chỉ nhận một trong ba giá trị active, suspended, locked; có ràng buộc kiểm tra"],
                ["admin_mfa_required", "BOOLEAN", "—", "—", "FALSE",
                 "Quản trị viên bắt buộc xác thực thêm; có tính bền vững"],
                ["detection_mfa_once", "BOOLEAN", "—", "—", "FALSE",
                 "Cờ tạm thời do phát hiện đặt, bị xoá sau khi xác thực thành công"],
                ["last_login_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm đăng nhập thành công gần nhất"],
                ["failed_login_count", "INTEGER", "—", "—", "0", "Số lần đăng nhập sai liên tiếp"],
                ["locked_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm bị khoá tài khoản"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo; có trình kích hoạt cập nhật tự động"],
                ["updated_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm sửa đổi gần nhất"],
            ],
        },
    ),
    ("CAP", "Bảng 3.5  Cấu trúc bảng users"),

    # ---- roles / user_roles ----
    ("H5", "Bảng roles - định nghĩa vai trò"),
    (
        "P",
        "Bảng vai trò là bảng tham chiếu, được nạp sẵn bốn vai trò: người dùng, quản trị viên "
        "bảo mật, phân tích viên trung tâm giám sát an ninh, và quản lý bảo mật. Cột tên tiếng "
        "Việt tồn tại để giao diện hiển thị đúng ngôn ngữ mà không cần dịch ở tầng trình bày.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "TEXT", "Có", "—", "—",
                 "Mã vai trò; ví dụ USER, SECURITY_ADMIN, SOC_ANALYST, SECURITY_MANAGER"],
                ["name", "TEXT", "—", "—", "—", "Tên vai trò tiếng Anh"],
                ["name_vi", "TEXT", "—", "—", "—", "Tên vai trò tiếng Việt dùng cho giao diện"],
                ["description", "TEXT", "—", "—", "NULL", "Mô tả phạm vi trách nhiệm"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
            ],
        },
    ),
    ("CAP", "Bảng 3.6  Cấu trúc bảng roles"),
    ("H5", "Bảng user_roles - gán vai trò cho người dùng"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh bản ghi gán vai trò"],
                ["user_id", "UUID", "—", "Có", "—",
                 "Tham chiếu users; xoá theo khi xoá người dùng; lập chỉ mục theo cột này"],
                ["role_id", "TEXT", "—", "Có", "—", "Tham chiếu roles; không cho xoá vai trò đang dùng"],
                ["assigned_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm gán vai trò"],
                ["assigned_by", "UUID", "—", "Có", "NULL",
                 "Người thực hiện gán; đặt trống nếu người gán không còn tồn tại"],
            ],
        },
    ),
    ("CAP", "Bảng 3.7  Cấu trúc bảng user_roles"),
    (
        "NOTE",
         "Ràng buộc duy nhất trên cặp cột người dùng và vai trò đảm bảo một người không thể có "
         "hai bản ghi cùng một vai trò. Đây là ràng buộc bắt buộc vì nếu không có nó, một người "
         "dùng có thể xuất hiện hai lần trong kết quả truy vấn quyền, và việc kiểm tra quyền "
         "sẽ cho kết quả khó dự đoán."),

    # ---- sessions ----
    ("H5", "Bảng sessions - phiên đăng nhập"),
    (
        "P",
        "Bảng phiên lưu bản băm token thay vì lưu token dạng rõ. Lý do: nếu bảng này bị lộ thì "
        "kẻ tấn công vẫn không dùng được token, vì token đã bị băm một chiều. Cột mã định danh "
        "token được chuẩn bị sẵn cho cơ chế thu hồi theo danh sách, khi nào chuyển sang token "
        "có chữ ký số.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh phiên"],
                ["user_id", "UUID", "—", "Có", "—", "Tham chiếu users; xoá theo khi xoá người dùng"],
                ["access_token_hash", "TEXT", "—", "—", "—",
                 "Bản băm token truy cập; có chỉ mục vì được dùng để tra cứu ở mỗi lần gọi"],
                ["refresh_token_hash", "TEXT", "—", "—", "NULL", "Bản băm token làm mới"],
                ["refresh_token_family", "UUID", "—", "—", "NULL",
                 "Định danh họ token; chỉ mục một phần dùng cho kiểm tra tái sử dụng token"],
                ["token_jti", "TEXT", "—", "—", "NULL",
                 "Mã định danh token; duy nhất khi có giá trị; dùng cho danh sách thu hồi"],
                ["expires_at", "TIMESTAMPTZ", "—", "—", "—", "Thời điểm hết hạn; lập chỉ mục"],
                ["last_activity_at", "TIMESTAMPTZ", "—", "—", "NULL", "Lần hoạt động gần nhất"],
                ["revoked_at", "TIMESTAMPTZ", "—", "—", "NULL",
                 "Thời điểm thu hồi; điều kiện lọc thống nhất cho mọi cơ chế thu hồi"],
                ["ip_address_id", "UUID", "—", "Có", "NULL",
                 "Tham chiếu ip_addresses; đặt trống nếu địa chỉ bị xoá"],
                ["user_agent", "TEXT", "—", "—", "NULL", "Chuỗi định danh trình duyệt"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo phiên"],
                ["updated_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm sửa đổi gần nhất"],
            ],
        },
    ),
    ("CAP", "Bảng 3.8  Cấu trúc bảng sessions"),

    # ---- mfa ----
    ("H5", "Bảng mfa_transactions - giao dịch xác thực"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh giao dịch; cũng là định danh giao dịch trả về cho người dùng"],
                ["user_id", "UUID", "—", "Có", "—", "Tham chiếu users; xoá theo khi xoá người dùng"],
                ["mfa_type", "TEXT", "—", "—", "'one_time'",
                 "one_time cho yêu cầu của phát hiện, persistent cho yêu cầu của quản trị viên"],
                ["status", "TEXT", "—", "—", "'pending'",
                 "Chỉ nhận pending, completed, expired, failed; có ràng buộc kiểm tra"],
                ["bound_ip", "INET", "—", "—", "NULL", "Địa chỉ lúc phát thử thách, dùng để phát hiện lệch địa chỉ"],
                ["notification_id", "UUID", "—", "Có", "NULL", "Tham chiếu mfa_notifications; đặt trống nếu thông báo bị xoá"],
                ["fail_count", "INTEGER", "—", "—", "0", "Số lần nhập sai; đạt ngưỡng thì giao dịch thất bại"],
                ["expires_at", "TIMESTAMPTZ", "—", "—", "—", "Thời điểm hết hạn; lập chỉ mục theo người dùng và trạng thái"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
                ["updated_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm sửa đổi gần nhất"],
            ],
        },
    ),
    ("CAP", "Bảng 3.9  Cấu trúc bảng mfa_transactions"),
    ("H5", "Bảng mfa_notifications - vòng đời thông báo mã xác thực"),
    (
        "P",
        "Bảng này tách riêng khỏi giao dịch xác thực vì một giao dịch có thể phát nhiều lần "
        "thử thông báo, ví dụ khi thử gửi lại mã. Mỗi lần gửi là một dòng, nên có thể trả lời "
        "câu hỏi mã đã gửi đi mấy lần và lần gửi nào thất bại vì lý do gì.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh lần gửi thông báo"],
                ["mfa_transaction_id", "UUID", "—", "Có", "—",
                 "Tham chiếu giao dịch; xoá theo khi xoá giao dịch"],
                ["channel", "TEXT", "—", "—", "'email'",
                 "Kênh gửi; chỉ nhận email, sms, totp; có ràng buộc kiểm tra"],
                ["recipient", "TEXT", "—", "—", "—", "Địa chỉ nhận; lập chỉ mục"],
                ["mfa_code_hash", "TEXT", "—", "—", "—", "Bản băm mã xác thực; không lưu mã dạng rõ"],
                ["sent_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm phát thông báo"],
                ["delivered_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm xác nhận đã đến nơi"],
                ["failed_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm gửi thất bại"],
                ["failure_reason", "TEXT", "—", "—", "NULL", "Mã lý do gửi thất bại"],
                ["expires_at", "TIMESTAMPTZ", "—", "—", "—", "Thời điểm hết hạn hiệu lực"],
                ["verified_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm mã được xác nhận đúng"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
            ],
        },
    ),
    ("CAP", "Bảng 3.10  Cấu trúc bảng mfa_notifications"),

    # ---- audit / devices / settings / outbox / notifications / rate limits / ip ----
    ("H5", "Bảng audit_logs - nhật ký kiểm toán"),
    (
        "P",
        "Nhật ký kiểm toán được thiết kế theo nguyên tắc chỉ ghi thêm, không sửa và không xoá. "
        "Hai cột trạng thái trước và sau lưu ở dạng đối tượng cấu trúc, nhờ vậy có thể khôi "
        "phục hoặc đối chiếu mà không cần bảng con. Cột mã yêu cầu cho phép truy vết một thao "
        "tác qua nhiều dịch vụ trong cùng một lần xử lý.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh dòng nhật ký"],
                ["request_id", "UUID", "—", "—", "NULL",
                 "Mã yêu cầu; lập chỉ mục; dùng để truy vết thao tác qua nhiều dịch vụ"],
                ["actor_id", "UUID", "—", "Có", "NULL",
                 "Người thực hiện; tham chiếu users; đặt trống nếu tài khoản bị xoá"],
                ["actor_type", "TEXT", "—", "—", "—", "Chỉ nhận user hoặc system; có ràng buộc kiểm tra"],
                ["action", "TEXT", "—", "—", "—", "Tên hành động; lập chỉ mục"],
                ["resource", "TEXT", "—", "—", "—", "Loại tài nguyên bị tác động; lập chỉ mục"],
                ["resource_id", "UUID", "—", "—", "NULL", "Định danh tài nguyên"],
                ["before_state", "JSONB", "—", "—", "NULL", "Trạng thái trước khi thay đổi"],
                ["after_state", "JSONB", "—", "—", "NULL", "Trạng thái sau khi thay đổi"],
                ["change_reason", "TEXT", "—", "—", "NULL", "Lý do thay đổi; bắt buộc với hành động nhạy cảm"],
                ["ip_address", "INET", "—", "—", "NULL", "Địa chỉ thực hiện"],
                ["user_agent", "TEXT", "—", "—", "NULL", "Chuỗi định danh trình duyệt"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm ghi; lập chỉ mục"],
            ],
        },
    ),
    ("CAP", "Bảng 3.11  Cấu trúc bảng audit_logs"),
    ("H5", "Bảng user_trusted_devices - thiết bị tin cậy"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh thiết bị tin cậy"],
                ["user_id", "UUID", "—", "Có", "—", "Tham chiếu users; xoá theo"],
                ["device_fingerprint", "TEXT", "—", "—", "—",
                 "Vân tay thiết bị; lập chỉ mục; duy nhất theo cặp người dùng và vân tay"],
                ["device_name", "TEXT", "—", "—", "NULL", "Tên thiết bị hiển thị cho người dùng"],
                ["last_ip", "INET", "—", "—", "NULL", "Địa chỉ lần dùng gần nhất"],
                ["last_user_agent", "TEXT", "—", "—", "NULL", "Chuỗi định danh trình duyệt lần gần nhất"],
                ["last_used_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm dùng gần nhất"],
                ["expires_at", "TIMESTAMPTZ", "—", "—", "NULL", "Hết hạn; NULL nghĩa là không hết hạn"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
            ],
        },
    ),
    ("CAP", "Bảng 3.12  Cấu trúc bảng user_trusted_devices"),
    ("H5", "Bảng system_settings - cấu hình động"),
    (
        "P",
        "Bảng cấu hình động cho phép đổi tham số vận hành mà không cần sửa mã và khởi động lại "
        "dịch vụ. Khoá chính là tên tham số, và cột kiểu giá trị cho phép kiểm tra kiểu dữ liệu "
        "trước khi lưu. Nhóm đã nạp sẵn hai mươi bốn tham số thuộc năm nhóm, trong đó có tham "
        "số bí mật dùng để xác thực thông tin giữa các dịch vụ.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["key", "TEXT", "Có", "—", "—", "Tên tham số; ví dụ mfa.otp_ttl_seconds"],
                ["value", "TEXT", "—", "—", "—", "Giá trị tham số dạng văn bản"],
                ["value_type", "TEXT", "—", "—", "'string'",
                 "Kiểu giá trị; chỉ nhận string, integer, boolean, json; có ràng buộc kiểm tra"],
                ["description", "TEXT", "—", "—", "NULL", "Giải thích tham số"],
                ["category", "TEXT", "—", "—", "'general'",
                 "Nhóm cấu hình; chỉ nhận auth, mfa, rate_limit, detection, notification, general; lập chỉ mục"],
                ["updated_by", "UUID", "—", "Có", "NULL", "Người sửa gần nhất; tham chiếu users"],
                ["updated_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm sửa gần nhất; có trình kích hoạt"],
            ],
        },
    ),
    ("CAP", "Bảng 3.13  Cấu trúc bảng system_settings"),
    ("H5", "Bảng outbox_events - hộp thư ra giao dịch"),
    (
        "P",
        "Bảng hộp thư ra là mấu chốt của cơ chế xử lý bất đồng bộ an toàn. Mọi sự kiện phát "
        "sau khi giao dịch nghiệp vụ đã cam kết được ghi ở đây, nên không thể xảy ra tình huống "
        "đã tạo phiên nhưng mất sự kiện. Cột trạng thái và số lần thử lại cho phép vòng lặp "
        "lấy sự kiện biết sẽ thử bao nhiêu lần và vì sao lần cuối thất bại.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh sự kiện"],
                ["aggregate_type", "TEXT", "—", "—", "—", "Loại thực thể phát sinh sự kiện, ví dụ user, session"],
                ["aggregate_id", "UUID", "—", "—", "—", "Định danh thực thể; lập chỉ mục theo cặp với loại"],
                ["event_type", "TEXT", "—", "—", "—", "Loại sự kiện; lập chỉ mục"],
                ["version", "INTEGER", "—", "—", "1", "Phiên bản cấu trúc sự kiện để tương thích ngược"],
                ["payload", "JSONB", "—", "—", "—", "Nội dung sự kiện; bắt buộc có giá trị"],
                ["headers", "JSONB", "—", "—", "NULL", "Tiêu đề bổ sung cho hàng đợi sự kiện"],
                ["status", "TEXT", "—", "—", "'pending'",
                 "Chỉ nhận pending, processing, published, failed; có ràng buộc kiểm tra"],
                ["retry_count", "INTEGER", "—", "—", "0", "Số lần đã thử lại"],
                ["max_retries", "INTEGER", "—", "—", "3", "Số lần thử lại tối đa"],
                ["last_error", "TEXT", "—", "—", "NULL", "Nội dung lỗi của lần thất bại gần nhất"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()",
                 "Thời điểm tạo; chỉ mục một phần chỉ gồm các dòng chờ xử lý"],
                ["published_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm phát thành công"],
            ],
        },
    ),
    ("CAP", "Bảng 3.14  Cấu trúc bảng outbox_events"),
    ("H5", "Bảng user_notifications - thông báo trong ứng dụng"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Ċnh danh thông báo"],
                ["user_id", "UUID", "—", "Có", "—", "Tham chiếu users; xoá theo"],
                ["type", "TEXT", "—", "—", "—",
                 "Chỉ nhận tám loại đã định nghĩa, gồm mfa_success, mfa_failed, new_login, "
                 "password_changed, account_locked, account_unlocked, alert_resolved, system"],
                ["title", "TEXT", "—", "—", "—", "Tiêu đề thông báo"],
                ["body", "TEXT", "—", "—", "—", "Nội dung thông báo"],
                ["link", "TEXT", "—", "—", "NULL", "Đường dẫn điều hướng khi bấm thông báo"],
                ["priority", "TEXT", "—", "—", "'normal'",
                 "Chỉ nhận low, normal, high, urgent; lập chỉ mục"],
                ["read", "BOOLEAN", "—", "—", "FALSE", "Đã đọc hay chưa; chỉ mục một phần cho thông báo chưa đọc"],
                ["read_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm đánh dấu đã đọc"],
                ["expires_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm thông báo hết hiệu lực"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo; lập chỉ mục"],
            ],
        },
    ),
    ("CAP", "Bảng 3.15  Cấu trúc bảng user_notifications"),
    ("H5", "Bảng rate_limits - bộ đếm giới hạn tần suất"),
    (
        "P",
        "Bảng giới hạn tần suất dùng khoá ghép hai cột làm khoá chính, tức là mỗi cặp địa chỉ và "
        "loại hành động chỉ có một bộ đếm. Bộ đếm được đặt lại theo cửa sổ thời gian khi thời "
        "điểm bắt đầu cửa sổ đã quá hạn, nên không cần công việc dọn dẹp định kỳ.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["ip_address", "INET", "Có", "—", "—", "Địa chỉ nguồn; lập chỉ mục riêng"],
                ["action", "TEXT", "Có", "—", "—", "Loại hành động, ví dụ login"],
                ["count", "INTEGER", "—", "—", "1", "Số lần đã thực hiện; ràng buộc không âm"],
                ["max_count", "INTEGER", "—", "—", "5", "Ngưỡng cho phép; ràng buộc lớn hơn không"],
                ["window_start", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm bắt đầu cửa sổ; lập chỉ mục"],
            ],
        },
    ),
    ("CAP", "Bảng 3.16  Cấu trúc bảng rate_limits"),
    ("H5", "Bảng ip_addresses - địa chỉ nguồn đã gặp"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh nội bộ của địa chỉ"],
                ["ip_address", "INET", "—", "—", "—", "Địa chỉ; duy nhất; kiểu mạng dùng sẵn cho IPv4 và IPv6"],
                ["country_code", "TEXT", "—", "—", "NULL", "Mã quốc gia; lập chỉ mục"],
                ["country_name", "TEXT", "—", "—", "NULL", "Tên quốc gia"],
                ["is_proxy", "BOOLEAN", "—", "—", "FALSE", "Cờ địa chỉ thuộc dạng tiến bộ"],
                ["is_vpn", "BOOLEAN", "—", "—", "FALSE", "Cờ địa chỉ thuộc dạng mạng riêng ảo"],
                ["is_tor", "BOOLEAN", "—", "—", "FALSE", "Cờ địa chỉ thuộc dạng mạng ẩn danh"],
                ["first_seen_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Lần gặp đầu tiên; lập chỉ mục"],
                ["last_seen_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Lần gặp gần nhất"],
            ],
        },
    ),
    ("CAP", "Bảng 3.17  Cấu trúc bảng ip_addresses"),

    # ================================================================ detection-db
    ("H4", "Nhóm 2: cơ sở dữ liệu detection-db"),
    ("P", "Bảy bảng lưu toàn bộ dữ liệu phát hiện, chấm điểm và xử lý cảnh báo."),
    ("H5", "Bảng policies - chính sách chấm điểm"),
    (
        "P",
        "Bảng chính sách lưu tập quy tắc ở dạng đối tượng cấu trúc thay vì tách thành bảng con. "
        "Lý do thiết kế: tập quy tắc luôn được đọc và ghi cùng nhau như một khối, không có "
        "nhu cầu truy vấn một quy tắc đơn lẻ; tách bảng con sẽ tăng số lượng truy vấn mà không "
        "mang lại lợi ích gì. Ràng buộc duy nhất chỉ cho phép tối đa một chính sách đang kích "
        "hoạt, được thiết lập bằng ràng buộc kiểm tra ở mức cơ sở dữ liệu chứ không dựa vào "
        "quy tắc ở tầng ứng dụng.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh chính sách"],
                ["version", "TEXT", "—", "—", "—", "Mã phiên bản; duy nhất; lập chỉ mục"],
                ["name", "TEXT", "—", "—", "NULL", "Tên chính sách"],
                ["description", "TEXT", "—", "—", "NULL", "Mô tả phạm vi áp dụng"],
                ["rules", "JSONB", "—", "—", "'[]'",
                 "Tập quy tắc; mỗi quy tắc có bảy trường bắt buộc: tên, trường, toán tử, "
                 "giá trị, trọng số, điểm, cờ bật; trường chỉ nhận đúng sáu tên đặc trưng đã thống nhất"],
                ["config", "JSONB", "—", "—", "'{}'",
                 "Cấu hình gồm trọng số quy tắc và máy học phải cộng lại bằng một, và ba ngưỡng "
                 "phải không giảm dần"],
                ["is_active", "BOOLEAN", "—", "—", "FALSE",
                 "Chính sách đang áp dụng; ràng buộc chỉ cho phép tối đa một dòng có giá trị đúng"],
                ["created_by", "UUID", "—", "Quy ước", "NULL",
                 "Tham chiếu quy ước tới users ở cơ sở dữ liệu khác; không phải khoá ngoại thật"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
                ["activated_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm kích hoạt"],
                ["deactivated_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm ngừng áp dụng"],
            ],
        },
    ),
    ("CAP", "Bảng 3.18  Cấu trúc bảng policies"),
    ("H5", "Bảng login_attempts - lần đăng nhập"),
    (
        "P",
        "Bảng lần đăng nhập là bảng trung tâm của Detection Engine, và là bảng mà cổng kiểm "
        "duyệt ghi vào trước khi cấp token. Cột mã sự kiện có ràng buộc duy nhất và chính là "
        "khoá chống xử lý trùng: nếu cùng một sự kiện được gửi hai lần, lần thứ hai sẽ bị "
        "từ chối bởi cơ sở dữ liệu chứ không phải bởi kiểm tra ở tầng ứng dụng.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh lần đăng nhập"],
                ["event_id", "UUID", "—", "—", "—",
                 "Mã sự kiện do Core App sinh; duy nhất; khoá chống xử lý trùng"],
                ["user_id", "UUID", "—", "Quy ước", "NULL",
                 "Tham chiếu quy ước tới users ở core-db; để trống khi đăng nhập thất bại"],
                ["username_attempted", "TEXT", "—", "—", "NULL", "Tên đăng nhập đã thử; lập chỉ mục"],
                ["outcome", "TEXT", "—", "—", "—",
                 "Chỉ nhận tám giá trị: success, failure, mfa_required, mfa_success, "
                 "mfa_failed, blocked, locked, rate_limited"],
                ["mfa_used", "BOOLEAN", "—", "—", "FALSE", "Lần đăng nhập có dùng xác thực thêm hay không"],
                ["ip_address", "INET", "—", "—", "NULL", "Địa chỉ nguồn; lập chỉ mục"],
                ["user_agent", "TEXT", "—", "—", "NULL", "Chuỗi định danh trình duyệt"],
                ["timestamp", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm xảy ra sự kiện; lập chỉ mục"],
                ["status", "TEXT", "—", "—", "'pending'",
                 "Chỉ nhận pending, processed, failed; cho biết sự kiện đã xử lý xong chưa"],
                ["policy_id", "UUID", "—", "Có", "NULL", "Tham chiếu policies; đặt trống nếu chính sách bị xoá"],
                ["request_id", "UUID", "—", "—", "gen_random_uuid()", "Mã yêu cầu; lập chỉ mục"],
                ["primary_alert_id", "UUID", "—", "Có", "NULL", "Tham chiếu alerts; đặt trống nếu cảnh báo bị xoá"],
                ["risk_level", "TEXT", "—", "—", "NULL", "Mức rủi ro cuối cùng; lập chỉ mục"],
                ["detection_decision", "TEXT", "—", "—", "NULL", "Quyết định cuối cùng: allow, challenge, block"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
                ["updated_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm sửa gần nhất; có trình kích hoạt"],
            ],
        },
    ),
    ("CAP", "Bảng 3.19  Cấu trúc bảng login_attempts"),
    ("H5", "Bảng risk_assessments - kết quả đánh giá rủi ro"),
    (
        "P",
        "Quan hệ một đến một giữa lần đăng nhập và kết quả đánh giá được thực thi bằng ràng "
        "buộc duy nhất trên cột tham chiếu. Điều này có hai hệ quả có lợi: không thể có hai "
        "kết quả cho cùng một lần đăng nhập, và mỗi lần đăng nhập đã chấm điểm đều có kết quả "
        "để tra cứu, nên không phải quét bảng để tìm kết quả của một lần đăng nhập cụ thể.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh kết quả đánh giá"],
                ["login_attempt_id", "UUID", "—", "Có", "—",
                 "Tham chiếu login_attempts; duy nhất; xoá theo khi xoá lần đăng nhập"],
                ["policy_id", "UUID", "—", "Có", "NULL", "Tham chiếu policies; đặt trống nếu chính sách bị xoá"],
                ["rule_score", "NUMERIC(5,4)", "—", "—", "NULL", "Điểm quy tắc trong khoảng không đến một"],
                ["ml_score", "NUMERIC(5,4)", "—", "—", "NULL", "Điểm máy học; để trống khi máy học không dùng được"],
                ["combined_score", "NUMERIC(5,4)", "—", "—", "NULL", "Điểm gộp cuối cùng"],
                ["ml_status", "TEXT", "—", "—", "NULL", "Chỉ nhận success, unavailable, error; lập chỉ mục"],
                ["ml_model_version", "TEXT", "—", "—", "NULL", "Mã phiên bản mô hình đã dùng"],
                ["rule_hits", "JSONB", "—", "—", "NULL", "Danh sách quy tắc đã kích hoạt"],
                ["ml_reason_codes", "JSONB", "—", "—", "NULL", "Danh sách mã lý do từ máy học"],
                ["ml_features_used", "JSONB", "—", "—", "NULL", "Sáu đặc trưng đã truyền cho máy học"],
                ["risk_level", "TEXT", "—", "—", "NULL", "Mức rủi ro đã phân loại; lập chỉ mục"],
                ["decision", "TEXT", "—", "—", "NULL", "Quyết định: allow, challenge, block"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
            ],
        },
    ),
    ("CAP", "Bảng 3.20  Cấu trúc bảng risk_assessments"),
    ("H5", "Bảng detection_logs - nhật ký từng giai đoạn phát hiện"),
    (
        "P",
        "Bảng nhật ký phát hiện ghi lại từng giai đoạn xử lý thay vì chỉ ghi kết quả cuối. "
        "Bốn loại giai đoạn được phân biệt bằng cột phân loại với ràng buộc kiểm tra: đánh giá "
        "quy tắc, gọi máy học, gộp điểm, và gửi hành động. Nhờ vậy, khi cần trả lời câu hỏi "
        "làm sao biết bước xử lý này đã thành công và kết quả có thể sử dụng, có thể tra theo "
        "từng giai đoạn thay vì suy đoán từ kết quả cuối.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh dòng nhật ký"],
                ["login_attempt_id", "UUID", "—", "Có", "NULL",
                 "Tham chiếu login_attempts; đặt trống, giữ nguyên dòng nhật ký, nếu lần đăng nhập bị xoá"],
                ["request_id", "UUID", "—", "—", "NULL", "Mã yêu cầu; lập chỉ mục"],
                ["stage", "TEXT", "—", "—", "—",
                 "Chỉ nhận rule_evaluation, ml_call, scoring, action_sent; lập chỉ mục"],
                ["stage_detail", "TEXT", "—", "—", "NULL", "Chi tiết giai đoạn"],
                ["rule_id", "UUID", "—", "—", "NULL", "Định danh quy tắc"],
                ["rule_name", "TEXT", "—", "—", "NULL", "Tên quy tắc"],
                ["triggered", "BOOLEAN", "—", "—", "NULL", "Quy tắc có kích hoạt hay không; chỉ mục một phần"],
                ["score_contribution", "NUMERIC(5,4)", "—", "—", "NULL",
                 "Đóng góp của quy tắc vào điểm quy tắc, đã chuẩn hoá"],
                ["decision", "TEXT", "—", "—", "NULL", "Quyết định ghi nhận ở giai đoạn này; lập chỉ mục"],
                ["reason", "TEXT", "—", "—", "NULL", "Mã lý do"],
                ["details", "JSONB", "—", "—", "NULL", "Dữ liệu chi tiết của giai đoạn"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm ghi; lập chỉ mục"],
            ],
        },
    ),
    ("CAP", "Bảng 3.21  Cấu trúc bảng detection_logs"),
    ("H5", "Bảng soc_analysts - hồ sơ phân viên"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh hồ sơ phân viên"],
                ["user_id", "UUID", "—", "Quy ước", "—",
                 "Tham chiếu quy ước tới users ở core-db; duy nhất; không phải khoá ngoại thật"],
                ["display_name", "TEXT", "—", "—", "NULL", "Tên hiển thị trên hồ sơ cảnh báo"],
                ["is_active", "BOOLEAN", "—", "—", "TRUE", "Còn hoạt động hay không; lập chỉ mục"],
                ["max_alerts", "INTEGER", "—", "—", "50", "Số cảnh báo tối đa được phân công đồng thời"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
                ["updated_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm sửa gần nhất; có trình kích hoạt"],
            ],
        },
    ),
    ("CAP", "Bảng 3.22  Cấu trúc bảng soc_analysts"),
    ("H5", "Bảng alerts - cảnh báo"),
    (
        "P",
        "Cột trạng thái của bảng cảnh báo có bốn giá trị, tách riêng báo nhầm khỏi đã kết "
        "luận. Ba cột người thực hiện được tách theo vai trò: người được phân công, người kết "
        "luận, và người ghi chú nằm ở bảng dòng thời gian. Tách như vậy để trả lời được hai "
        "câu hỏi khác nhau: ai đang phụ trách cảnh báo này, và ai đã kết luận nó là gì.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh cảnh báo"],
                ["login_attempt_id", "UUID", "—", "Có", "—", "Tham chiếu login_attempts; xoá theo"],
                ["policy_id", "UUID", "—", "Có", "NULL", "Tham chiếu policies; đặt trống nếu chính sách bị xoá"],
                ["request_id", "UUID", "—", "—", "NULL", "Mã yêu cầu của lần đăng nhập gốc"],
                ["status", "TEXT", "—", "—", "'open'",
                 "Chỉ nhận open, acknowledged, resolved, false_positive; lập chỉ mục"],
                ["risk_level", "TEXT", "—", "—", "NULL", "Mức rủi ro; lập chỉ mục"],
                ["detection_reason", "TEXT", "—", "—", "NULL", "Lý do phát sinh cảnh báo"],
                ["detection_scores", "JSONB", "—", "—", "NULL",
                 "Cụm ba điểm quy tắc, máy học và gộp"],
                ["assigned_to_id", "UUID", "—", "Có", "NULL", "Phân viên phụ trách; đặt trống nếu hồ sơ bị xoá"],
                ["resolved_by_id", "UUID", "—", "Có", "NULL", "Phân viên đã kết luận"],
                ["resolved_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm kết luận"],
                ["resolution", "TEXT", "—", "—", "NULL", "Nội dung kết luận; bắt buộc khi kết luận"],
                ["notes", "TEXT", "—", "—", "NULL", "Ghi chú"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo; lập chỉ mục"],
                ["updated_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm sửa gần nhất; có trình kích hoạt"],
            ],
        },
    ),
    ("CAP", "Bảng 3.23  Cấu trúc bảng alerts"),
    ("H5", "Bảng alert_timeline - dòng thời gian cảnh báo"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh dòng thời gian"],
                ["alert_id", "UUID", "—", "Có", "—", "Tham chiếu alerts; xoá theo khi xoá cảnh báo"],
                ["event_type", "TEXT", "—", "—", "—",
                 "Chỉ nhận chín loại: created, acknowledged, assigned, unassigned, escalated, "
                 "note_added, status_changed, resolved, false_positive; lập chỉ mục"],
                ["actor_id", "UUID", "—", "Quy ước", "NULL", "Tham chiếu quy ước tới users ở core-db"],
                ["actor_type", "TEXT", "—", "—", "—", "Chỉ nhận user hoặc system; có ràng buộc kiểm tra"],
                ["old_value", "TEXT", "—", "—", "NULL", "Giá trị trước khi đổi"],
                ["new_value", "TEXT", "—", "—", "NULL", "Giá trị sau khi đổi"],
                ["comment", "TEXT", "—", "—", "NULL", "Nội dung ghi chú hoặc lý do"],
                ["ip_address", "INET", "—", "—", "NULL", "Địa chỉ thực hiện"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm ghi; lập chỉ mục"],
            ],
        },
    ),
    ("CAP", "Bảng 3.24  Cấu trúc bảng alert_timeline"),

    # ================================================================ ml-service-db
    ("H4", "Nhóm 3: cơ sở dữ liệu ml-service-db"),
    ("P", "Bảy bảng còn lại là ba bảng của dịch vụ máy học."),
    ("H5", "Bảng model_versions - sổ đăng ký mô hình"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh phiên bản mô hình"],
                ["name", "TEXT", "—", "—", "—", "Tên mô hình"],
                ["version", "TEXT", "—", "—", "—", "Mã phiên bản; duy nhất; lập chỉ mục"],
                ["algorithm", "TEXT", "—", "—", "'IsolationForest'", "Thuật toán; lập chỉ mục"],
                ["description", "TEXT", "—", "—", "NULL", "Mô tả mô hình"],
                ["model_path", "TEXT", "—", "—", "—", "Đường dẫn tệp mô hình trên đĩa"],
                ["config", "JSONB", "—", "—", "'{}'",
                 "Cấu hình gồm ngưỡng, tỉ lệ nhiễm, số cây, và các chỉ số đo"],
                ["status", "TEXT", "—", "—", "'staged'",
                 "Chỉ nhận staged, active, archived, failed; lập chỉ mục"],
                ["is_production", "BOOLEAN", "—", "—", "FALSE",
                 "Đang phục vụ sản xuất; ràng buộc chỉ cho phép tối đa một mô hình sản xuất đang hoạt động"],
                ["trained_by", "UUID", "—", "Quy ước", "NULL", "Tham chiếu quy ước tới users ở core-db"],
                ["training_date", "TIMESTAMPTZ", "—", "—", "NULL", "Ngày huấn luyện"],
                ["deployed_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm đưa vào phục vụ"],
                ["archived_at", "TIMESTAMPTZ", "—", "—", "NULL", "Thời điểm lưu trữ"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
                ["updated_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm sửa gần nhất; có trình kích hoạt"],
            ],
        },
    ),
    ("CAP", "Bảng 3.25  Cấu trúc bảng model_versions"),
    ("H5", "Bảng inference_logs - nhật ký suy luận"),
    (
        "P",
        "Nhật ký suy luận lưu cả đầu vào lẫn đầu ra, nên có thể phân tích ngược tại sao hệ "
        "thống đã xếp một lần đăng nhập là bất thường. Cột mã yêu cầu có ràng buộc duy nhất, "
        "vừa chống ghi trùng vừa cho phép truy vết chéo với bảng nhật ký phát hiện ở cơ sở dữ "
        "liệu khác.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh lần suy luận"],
                ["request_id", "UUID", "—", "—", "—", "Mã yêu cầu; duy nhất; lập chỉ mục"],
                ["model_version_id", "UUID", "—", "Có", "NULL", "Tham chiếu model_versions"],
                ["model_version_used", "TEXT", "—", "—", "—", "Mã phiên bản thực tế đã dùng"],
                ["features", "JSONB", "—", "—", "—", "Sáu đặc trưng đầu vào"],
                ["raw_score", "NUMERIC(10,6)", "—", "—", "NULL", "Điểm thô của mô hình"],
                ["normalized_score", "NUMERIC(5,4)", "—", "—", "—", "Điểm sau chuẩn hoá; bắt buộc có giá trị"],
                ["is_anomaly", "BOOLEAN", "—", "—", "—", "Cờ bất thường; lập chỉ mục"],
                ["reason_codes", "JSONB", "—", "—", "'[]'", "Danh sách mã lý do"],
                ["model_status", "TEXT", "—", "—", "'ready'", "Chỉ nhận ready, degraded, error; lập chỉ mục"],
                ["processing_time_ms", "INTEGER", "—", "—", "NULL", "Thời gian xử lý tính bằng mili giây"],
                ["error_message", "TEXT", "—", "—", "NULL", "Nội dung lỗi nếu có"],
                ["ip_address", "INET", "—", "—", "NULL", "Địa chỉ nguồn"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm ghi; lập chỉ mục"],
            ],
        },
    ),
    ("CAP", "Bảng 3.26  Cấu trúc bảng inference_logs"),
    ("H5", "Bảng feature_statistics - thống kê phân phối đặc trưng"),
    (
        "P",
        "Bảng thống kê đặc trưng phục vụ theo dõi trôi dữ liệu. Ý nghĩa của nó trong thiết kế "
        "này: nếu phân phối của một đặc trưng thay đổi mạnh so với thời điểm huấn luyện, "
        "thì điểm bất thường mà mô hình trả về không còn đáng tin, dù kỹ thuật không báo lỗi.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.4, 0.7, 0.7, 0.9, 2.2],
            "header": ["Cột", "Kiểu", "PK", "FK", "Mặc định", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["id", "UUID", "Có", "—", "gen_random_uuid()", "Định danh bản ghi thống kê"],
                ["feature_name", "TEXT", "—", "—", "—", "Tên đặc trưng; lập chỉ mục"],
                ["timestamp", "TIMESTAMPTZ", "—", "—", "NOW()", "Mốc thời gian thống kê; lập chỉ mục"],
                ["count", "BIGINT", "—", "—", "0", "Số mẫu quan sát"],
                ["mean", "NUMERIC(10,6)", "—", "—", "NULL", "Trung bình"],
                ["std", "NUMERIC(10,6)", "—", "—", "NULL", "Độ lệch chuẩn"],
                ["min", "NUMERIC(10,6)", "—", "—", "NULL", "Giá trị nhỏ nhất"],
                ["max", "NUMERIC(10,6)", "—", "—", "NULL", "Giá trị lớn nhất"],
                ["p25", "NUMERIC(10,6)", "—", "—", "NULL", "Phân vị hai mươi lăm"],
                ["p50", "NUMERIC(10,6)", "—", "—", "NULL", "Trung vị"],
                ["p75", "NUMERIC(10,6)", "—", "—", "NULL", "Phân vị bảy mươi lăm"],
                ["p95", "NUMERIC(10,6)", "—", "—", "NULL", "Phân vị chín mươi lăm"],
                ["anomaly_rate", "NUMERIC(5,4)", "—", "—", "NULL", "Tỉ lệ bất thường"],
                ["created_at", "TIMESTAMPTZ", "—", "—", "NOW()", "Thời điểm tạo"],
            ],
        },
    ),
    ("CAP", "Bảng 3.27  Cấu trúc bảng feature_statistics"),
    (
        "NOTE",
         "Tổng cộng hai mươi ba bảng: mười ba bảng ở cơ sở dữ liệu core-db, bảy bảng ở cơ "
         "sở dữ liệu detection-db, và ba bảng ở cơ sở dữ liệu ml-service-db. Nhóm đã viết bộ "
         "kiểm thử kiểm tra tính nhất quán của lược đồ, xác nhận đúng số bảng, số chỉ mục và "
         "số ràng buộc trên từng cơ sở dữ liệu. Bộ kiểm thử này chạy cùng bộ kiểm thử của "
         "dự án và hiện đều đạt."),

    # ================================================================ III.7 UI
    ("H2", "Thiết kế giao diện"),
    (
        "P",
        "Giao diện của hệ thống được thiết kế theo nguyên tắc mỗi vai trò có một bề mặt làm "
        "việc riêng, vì các vai trò có mục tiêu công việc khác nhau. Người dùng chỉ cần một "
        "màn hình đăng nhập và một màn hình phiên của chính mình; phân viên giám sát cần một "
        "bảng điều khiển và danh sách cảnh báo; quản trị viên cần màn hình cấu hình; quản lý "
        "bảo mật cần bảng số liệu tổng hợp mà không cần thao tác.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 2.2, 1.5, 2.0, 1.5],
            "header": ["Mã", "Màn hình", "Ai dùng", "Dữ liệu hiển thị", "Thao tác chính"],
            "rows": [
                ["UI-01", "Đăng nhập", "Người dùng",
                 "Tên đăng nhập, mật khẩu, biểu tượng bảo mật thiết bị",
                 "Nhập thông tin, gửi, xem thông báo yêu cầu xác thực thêm"],
                ["UI-02", "Xác thực đa yếu tố", "Người dùng",
                 "Mã xác thực sáu chữ số, thời gian còn lại, số lần thử còn lại",
                 "Nhập mã, yêu cầu gửi lại mã, quay lại đăng nhập"],
                ["UI-03", "Quản lý phiên của chính mình", "Người dùng",
                 "Danh sách phiên đang hoạt động gồm thiết bị, địa chỉ, thời điểm và thời hạn",
                 "Xem, thu hồi phiên, đánh dấu thiết bị tin cậy, thu hồi tất cả"],
                ["UI-04", "Bảng điều khiển trung tâm giám sát", "Phân viên",
                 "Số cảnh báo theo trạng thái, theo mức rủi ro, theo giờ trong ngày, cảnh báo mới nhất",
                 "Lọc theo trạng thái và mức, chuyển tới danh sách cảnh báo tương ứng"],
                ["UI-05", "Danh sách cảnh báo", "Phân viên",
                 "Mã cảnh báo, mức rủi ro, trạng thái, người dùng, địa chỉ, thời điểm, người phụ trách",
                 "Lọc, sắp xếp, phân trang, mở hồ sơ chi tiết"],
                ["UI-06", "Hồ sơ chi tiết cảnh báo", "Phân viên",
                 "Cụm điểm, quy tắc kích hoạt, mã lý do máy học, lịch sử đăng nhập, danh sách phiên, dòng thời gian",
                 "Tiếp nhận, ghi chú, yêu cầu hành động bảo vệ, kết luận, đánh dấu báo nhầm"],
                ["UI-07", "Quản lý chính sách", "Quản trị viên",
                 "Danh sách chính sách, trạng thái kích hoạt, tập quy tắc, trọng số và ngưỡng",
                 "Xem, kiểm tra tính hợp lệ, kích hoạt, so sánh phiên bản"],
                ["UI-08", "Quản lý tài khoản và vai trò", "Quản trị viên",
                 "Danh sách tài khoản, trạng thái, vai trò được gán, cờ bắt buộc xác thực thêm",
                 "Gán hoặc gỡ vai trò, khoá hoặc mở khoá, bắt buộc xác thực thêm, thu hồi phiên"],
                ["UI-09", "Bảng điều khiển của quản lý bảo mật", "Quản lý bảo mật",
                 "Số cảnh báo theo ngày, cơ cấu mức rủi ro, tỉ lệ báo nhầm, danh sách tài khoản rủi ro cao",
                 "Xem, xuất báo cáo, phê duyệt leo thang"],
            ],
        },
    ),
    ("CAP", "Bảng 3.28  Danh mục màn hình và quyền truy cập"),
    (
        "P",
        "Với mỗi màn hình, quyền truy cập được kiểm tra ở hai lớp. Lớp thứ nhất là quyền theo "
        "vai trò: người dùng không thể gọi được điểm cuối cảnh báo, và phân viên không thể gọi "
        "được điểm cuối kích hoạt chính sách. Lớp thứ hai là quyền theo đối tượng: khi phân "
        "viên yêu cầu hành động bảo vệ, hệ thống kiểm tra xem cảnh báo đó đã được phân viên đó "
        "tiếp nhận hay chưa, và nếu chưa thì từ chối. Hai lớp kiểm tra tách bạch vì lý do "
        "khác nhau: lớp một chặn người dùng nhầm chức năng, lớp hai chặn việc xử lý cảnh báo "
        "vượt quy trình.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 2.2, 1.6, 1.7, 1.7],
            "header": ["Mã", "Màn hình", "Quyền cần có", "Dữ liệu được phép thấy", "Bị chặn với lý do"],
            "rows": [
                ["UI-01", "Đăng nhập", "Công khai", "Chỉ dữ liệu nhập của chính mình", "Không có ràng buộc"],
                ["UI-02", "Xác thực đa yếu tố", "Công khai kèm mã giao dịch hợp lệ",
                 "Chỉ giao dịch của chính mình", "Không có ràng buộc"],
                ["UI-03", "Quản lý phiên của chính mình", "Đã đăng nhập",
                 "Chỉ phiên của chính mình",
                 "Người dùng khác không được thấy hoặc thu hồi phiên của họ"],
                ["UI-04", "Bảng điều khiển trung tâm giám sát", "Phân tích viên hoặc quản lý bảo mật",
                 "Số liệu tổng hợp, không có thông tin định danh",
                 "Người dùng thường không có quyền; không có thông tin chi tiết tài khoản"],
                ["UI-05", "Danh sách cảnh báo", "Phân tích viên hoặc quản lý bảo mật",
                 "Cảnh báo trong phạm vi phụ trách",
                 "Người dùng thường không có quyền"],
                ["UI-06", "Hồ sơ chi tiết cảnh báo", "Phân tích viên hoặc quản lý bảo mật",
                 "Bằng chứng của một cảnh báo, gồm lịch sử đăng nhập của người bị nghi ngờ",
                 "Phân viên chưa tiếp nhận không được thực hiện hành động bảo vệ"],
                ["UI-07", "Quản lý chính sách", "Quản trị viên bảo mật",
                 "Toàn bộ tập quy tắc và ngưỡng",
                 "Phân viên và người dùng không được sửa chính sách"],
                ["UI-08", "Quản lý tài khoản và vai trò", "Quản trị viên bảo mật",
                 "Danh sách tài khoản và vai trò",
                 "Phân viên không được cấp hoặc gỡ vai trò"],
                ["UI-09", "Bảng điều khiển của quản lý bảo mật", "Quản lý bảo mật",
                 "Số liệu tổng hợp theo ngày và tài khoản rủi ro cao",
                 "Không cho thực hiện thao tác trên cảnh báo cụ thể"],
            ],
        },
    ),
    ("CAP", "Bảng 3.29  Quyền truy cập và dữ liệu theo màn hình"),
    (
        "NOTE",
         "Ở thời điểm báo cáo hiện tại, nhóm đã hoàn thành thiết kế giao diện và quy tắc quyền "
         "truy cập cho chín màn hình nêu trên, nhưng chưa có bằng chứng thực thi giao diện "
         "người dùng. Vì vậy phần này trình bày ở dạng đặc tả thiết kế, không kèm ảnh chụp "
         "màn hình. Mục này nằm ở Chương III vì đó là thiết kế, còn phần ảnh thực thi được "
         "nêu trung thực ở Chương IV và đánh dấu là chưa có. "
         "[CẦN NHÓM XÁC NHẬN: có đưa ảnh giao diện thực tế vào báo cáo hay không, và nếu có "
         "thì ảnh chụp từ môi trường nào]."),

    # ================================================================ III.8
    ("H2", "Thiết kế xử lý"),
    (
        "P",
        "Phần này trình bày xử lý chi tiết cho chín chức năng trọng tâm. Mỗi mục đi theo "
        "cùng một thứ tự: dữ liệu đầu vào, kiểm tra dữ liệu, xử lý, thao tác cơ sở dữ liệu, "
        "kết quả đầu ra, và xử lý lỗi. Thứ tự này được giữ nhất quán để có thể đối chiếu với "
        "mã nguồn theo từng chức năng.",
    ),

    ("H3", "Xử lý đăng nhập"),
    (
        "P",
        "Đầu vào gồm tên đăng nhập, mật khẩu, địa chỉ nguồn và chuỗi định danh trình duyệt. "
        "Kiểm tra dữ liệu gồm bốn lớp. Lớp một là giới hạn tần suất theo địa chỉ, dựa trên "
        "bảng giới hạn tần suất với ngưỡng năm lần trong cửa sổ ba trăm giây. Lớp hai là "
        "định dạng đầu vào, với tên đăng nhập chỉ chứa chữ, số và gạch dưới. Lớp ba là tra "
        "cứu tài khoản và kiểm tra trạng thái, trong đó tài khoản không tồn tại và mật khẩu sai "
        "trả về cùng một thông điệp để không tiết lộ sự tồn tại của tên đăng nhập. Lớp bốn là "
        "băm và so khớp mật khẩu bằng Argon2id.",
    ),
    (
        "P",
        "Sau bốn lớp kiểm tra, hệ thống ghi nhận lần đăng nhập vào bảng hộp thư ra để xử lý "
        "bất đồng bộ, đồng thời gọi đồng bộ cổng kiểm duyệt rủi ro. Cổng kiểm duyệt có hạn ba "
        "giây và trả về một trong ba trạng thái: cho phép, yêu cầu xác thực thêm, hoặc không "
        "phản hồi. Nếu không phản hồi, hệ thống cho phép đăng nhập và ghi cảnh báo vận hành, "
        "vì ưu tiên là giữ được đường đăng nhập hơn là siết chặt hơn.",
    ),
    (
        "P",
        "Nếu cổng trả về mức cao hoặc nghiêm trọng, hệ thống đặt cờ yêu cầu xác thực một "
        "lần, tạo giao dịch xác thực với thời hạn năm phút, gửi mã, và trả về mã trạng thái yêu "
        "cầu xác thực cùng mã giao dịch. Điểm cần nhấn mạnh là ở nhánh này không có phiên và "
        "không có token nào được tạo. Nếu cổng cho phép, hệ thống tạo phiên, lưu bản băm token "
        "vào bảng phiên, và trả về token truy cập cùng token làm mới.",
    ),
    (
        "P",
        "Xử lý lỗi chia làm hai nhóm. Lỗi người dùng gồm sai thông tin, vượt tần suất, và tài "
        "khoản bị khoá; các lỗi này trả về mã lỗi tương ứng và ghi vào bảng lần đăng nhập với "
        "kết quả tương ứng. Lỗi hệ thống gồm không kết nối được cơ sở dữ liệu và không gọi "
        "được Detection Engine; lỗi thứ nhất trả về lỗi máy chủ, lỗi thứ hai được xử lý theo "
        "chính sách mở cửa. Tiêu chí xác nhận quy trình thành công là: bản ghi lần đăng nhập đã "
        "tồn tại ở Detection Engine, và nếu không bị chặn thì có một dòng trong bảng phiên "
        "với thời điểm thu hồi còn trống.",
    ),

    ("H3", "Xử lý xác thực đa yếu tố"),
    (
        "P",
        "Đầu vào gồm mã giao dịch và mã xác thực. Kiểm tra dữ liệu gồm năm bước theo thứ tự: "
        "giao dịch có tồn tại không; giao dịch có thuộc về người đang xác thực không; giao "
        "dịch còn hiệu lực không, xét theo thời điểm hết hạn; số lần thử còn lại không; và "
        "mã có khớp với bản băm đã lưu không. Bản băm được so khớp bằng hàm so sánh thời "
        "gian hằng số, để không rò rỉ thông tin qua thời gian thực hiện.",
    ),
    (
        "P",
        "Khi mã đúng, hệ thống đánh dấu giao dịch hoàn thành, xoá cờ yêu cầu xác thực một "
        "lần nếu đó là giao dịch do phát hiện yêu cầu, tạo phiên, và ghi nhận kết quả màu "
        "xanh trong bảng lần đăng nhập. Khi mã sai, bộ đếm sai tăng một; nếu đạt ngưỡng ba "
        "lần thì giao dịch chuyển sang trạng thái thất bại, và kết quả màu đỏ được ghi lại. Xử "
        "lý lỗi: mã sai trong giới hạn cho phép trả về thông báo còn số lần thử; giao dịch hết "
        "hạn hoặc đã hoàn thành trả về lỗi không tìm thấy, để tránh tiết lộ trạng thái thật.",
    ),

    ("H3", "Ghi sự kiện ra hộp thư ra"),
    (
        "P",
        "Đầu vào là sự kiện nghiệp vụ cần thông báo. Xử lý gồm ba bước: tạo mã sự kiện duy "
        "nhất, ghi một dòng vào bảng hộp thư ra với trạng thái chờ xử lý, và ghi cùng giao "
        "dịch với thay đổi nghiệp vụ. Vì ghi hộp thư ra nằm trong cùng giao dịch, nên hoặc "
        "cả hai cùng thành công, hoặc cả hai cùng được hoàn tác. Đây chính là nội dung của "
        "cơ chế hộp thư ra giao dịch: không tồn tại tình huống đã tạo phiên nhưng mất sự "
        "kiện.",
    ),
    (
        "P",
        "Hiện tại bảng hộp thư ra đã được dựng và có đầy đủ chỉ mục, trạng thái, số lần thử "
        "lại và nội dung lỗi, nhưng vòng lặp lấy sự kiện chưa được cài đặt. Phần xử lý lỗi và "
        "tiêu chí xác nhận cho vòng lặp lấy sự kiện được trình bày ở mục Xử lý khôi phục bản "
        "ghi chấm lỗi, là phần đã có bộ kiểm thử. Phần chưa có bằng chứng thực thi được nêu "
        "trung thực ở Chương IV và Chương V.",
    ),

    ("H3", "Xử lý phát hiện đăng nhập bất thường"),
    (
        "P",
        "Đầu vào là sự kiện đăng nhập gồm mã sự kiện, định danh người dùng nếu có, kết quả, "
        "địa chỉ nguồn, chuỗi định danh trình duyệt, thời điểm, cờ có dùng xác thực thêm, và "
        "mã yêu cầu. Kiểm tra dữ liệu gồm kiểm tra mã sự kiện trùng, kiểm tra kết quả thuộc "
        "tập giá trị hợp lệ, và kiểm tra định dạng địa chỉ. Xử lý gồm chín bước theo thứ tự: "
        "ghi bản ghi lần đăng nhập; chọn chính sách đang kích hoạt; xây dựng sáu đặc trưng; "
        "chấm điểm quy tắc; gọi máy học; gộp điểm và xếp mức; ghi kết quả đánh giá; tạo cảnh "
        "báo nếu mức cao hoặc nghiêm trọng; và cuối cùng là gửi hành động bảo vệ nếu có.",
    ),
    (
        "P",
        "Thao tác cơ sở dữ liệu gồm năm bản ghi: bản ghi lần đăng nhập, bản ghi kết quả đánh "
        "giá, các dòng nhật ký cho từng giai đoạn, bản ghi cảnh báo nếu có, và dòng thời gian "
        "cảnh báo nếu có. Kết quả đầu ra là mã trạng thái chấp nhận yêu cầu kèm mức rủi ro và "
        "mã cảnh báo nếu có.",
    ),
    (
        "P",
        "Xử lý lỗi chia thành bốn nhóm. Nhóm một là lỗi cấu hình chính sách: quy tắc thiếu "
        "trường bắt buộc, quy tắc dùng trường ngoài sáu trường cho phép, trọng số quy tắc và "
        "máy học không cộng lại bằng một, hoặc ngưỡng không không giảm dần. Xử lý là bỏ qua "
        "phần cấu hình sai và dùng giá trị mặc định, đồng thời ghi mã lý do; hệ thống không "
        "dừng vì một quy tắc hỏng. Nhóm hai là lỗi gọi máy học: quá hạn năm giây, lỗi kết "
        "nối, hoặc mã lỗi từ máy chủ; xử lý là tiếp tục bằng điểm quy tắc và ghi trạng thái "
        "máy học là không dùng được. Nhóm ba là sự kiện trùng: mã sự kiện đã tồn tại thì trả "
        "về lần xử lý trước mà không xử lý lại. Nhóm bốn là lỗi gửi hành động về Core App: "
        "ghi cảnh báo vận hành và nuốt lỗi, để không làm mất cảnh báo đã tạo.",
    ),
    (
        "NOTE",
         "Điểm thiết kế cần nhấn mạnh ở nhóm hai: khi máy học không dùng được, điểm gộp bằng "
         "đúng điểm quy tắc, và điểm quy tắc có xu hướng cao hơn điểm gộp thông thường. Điều "
         "này là cố ý, vì khi mất một nguồn tín hiệu thì điểm quy tắc không còn được giảm nhẹ "
         "bởi điểm máy học. Hệ quả là hệ thống nhạy cảm hơn trong những điều kiện ML lỗi, và "
         "đây là hệ quả được chấp nhận có chủ ý, không phải lỗi."),

    ("H3", "Tính điểm rủi ro"),
    (
        "P",
        "Đầu vào là sáu đặc trưng và tập quy tắc của chính sách đang kích hoạt. Bước một, đánh "
        "giá từng quy tắc: với mỗi quy tắc đang bật, so sánh giá trị đặc trưng với giá trị "
        "quy tắc theo toán tử quy định; nếu kích hoạt thì đóng góp bằng điểm nhân với trọng "
        "số. Bước hai, chuẩn hoá: tổng các đóng góp chia cho tổng trọng số của toàn bộ quy "
        "tắc đang bật, rồi cắt ở giá trị một. Cắt ở một là cần thiết vì khi chỉ có một quy "
        "tắc nặng được bật, tổng đóng góp có thể vượt một.",
    ),
    (
        "P",
        "Bước ba, chuẩn hoá mẫu số là điểm cốt lõi của công thức. Mẫu số là tổng trọng số của "
        "toàn bộ quy tắc đang bật, chứ không phải tổng trọng số của các quy tắc đã kích hoạt. "
        "Nếu dùng mẫu số là tổng của nhóm đã kích hoạt, thì chỉ cần một quy tắc nặng kích "
        "hoạt là điểm quy tắc đạt một, và mọi lần đăng nhập trở thành nghiêm trọng. Với chính "
        "sách mặc định, tổng trọng số là 1,20. Ví dụ tính với giờ đăng nhập bằng hai, số lần "
        "sai trong ngày bằng năm, thiết bị mới bằng đúng, và độ lệch bằng 0,8, tổng đóng góp là "
        "0,91, chia cho 1,20 cho điểm quy tắc xấp xỉ 0,7583. Nếu máy học trả về 0,72 thì điểm "
        "gộp là 0,4 nhân 0,7583 cộng 0,6 nhân 0,72, xấp xỉ 0,7353, thuộc mức cao, nên yêu cầu "
        "xác thực thêm và tạo cảnh báo. Nếu máy học quá hạn thì điểm gộp bằng 0,7583, thuộc "
        "mức nghiêm trọng.",
    ),
    (
        "P",
        "Bước bốn, gộp điểm: nếu máy học thành công thì điểm gộp bằng 0,4 nhân điểm quy "
        "tắc cộng 0,6 nhân điểm máy học; nếu máy học không thành công thì điểm gộp bằng điểm "
        "quy tắc. Bước năm, xếp mức theo ba ngưỡng: dưới 0,25 là thấp; từ 0,25 đến dưới 0,50 "
        "là trung bình; từ 0,50 đến dưới 0,75 là cao; từ 0,75 trở lên là nghiêm trọng. Bước sáu, "
        "chuyển mức thành quyết định: thấp và trung bình thì cho phép; cao thì yêu cầu xác thực "
        "thêm và tạo cảnh báo; nghiêm trọng thì chặn, tạo cảnh báo, và yêu cầu thu hồi toàn bộ "
        "phiên.",
    ),
    (
        "P",
        "Xử lý lỗi đã nêu ở mục xử lý phát hiện. Tiêu chí xác nhận: bản ghi kết quả đánh giá có "
        "đủ ba điểm hoặc có trạng thái máy học giải thích cho việc thiếu điểm máy học, tổng "
        "các đóng góp của quy tắc bằng đúng điểm quy tắc, và trường mức rủi ro khớp với kết "
        "quả so với ba ngưỡng trong chính sách.",
    ),

    ("H3", "Tạo cảnh báo"),
    (
        "P",
        "Đầu vào là kết quả đánh giá ở mức cao hoặc nghiêm trọng. Kiểm tra dữ liệu: mức rủi ro "
        "phải thuộc hai giá trị nêu trên và lần đăng nhập phải tồn tại. Xử lý: tạo bản ghi cảnh "
        "báo với trạng thái mở, mức rủi ro, lý do phát sinh, và cụm ba điểm; tạo một dòng thời "
        "gian loại đã tạo với tác nhân là hệ thống; cập nhật cột cảnh báo chính của lần đăng "
        "nhập. Điều kiện không tạo cảnh báo: mức thấp hoặc trung bình, cũng là khi chính sách "
        "có cờ tắt tạo cảnh báo cho mức đó.",
    ),
    (
        "P",
        "Xử lý lỗi: nếu không tạo được cảnh báo thì bản ghi lần đăng nhập vẫn được cập nhật với "
        "mức rủi ro và quyết định, và ghi một dòng nhật ký giai đoạn gộp điểm với nội dung lỗi. "
        "Tiêu chí xác nhận: truy vấn cảnh báo theo mã lần đăng nhập trả về đúng một cảnh báo "
        "mở, và dòng thời gian có bản ghi loại đã tạo.",
    ),

    ("H3", "Xử lý cập nhật cảnh báo bởi phân viên"),
    (
        "P",
        "Đầu vào gồm mã cảnh báo, thao tác yêu cầu, và nội dung kèm theo. Kiểm tra dữ liệu gồm "
        "bốn bước: cảnh báo có tồn tại không; trạng thái hiện tại có cho phép thao tác này "
        "không; nếu là yêu cầu hành động bảo vệ thì cảnh báo đã được phân viên đó tiếp nhận "
        "chưa; và người dùng có vai trò phù hợp không. Xử lý khác nhau theo thao tác: tiếp "
        "nhận thì đặt trạng thái thành đã tiếp nhận và gán phân viên; ghi chú thì tạo dòng "
        "thời gian loại đã ghi chú; kết luận thì đặt trạng thái thành đã kết luận, ghi người "
        "kết luận, thời điểm, và nội dung kết luận; đánh dấu báo nhầm thì đặt trạng thái thành "
        "báo nhầm và ghi người thực hiện; leo thang thì chỉ ghi dòng thời gian mà không đổi trạng "
        "thái.",
    ),
    (
        "P",
        "Xử lý lỗi: cảnh báo không tồn tại trả về lỗi không tìm thấy; thao tác không hợp lệ với "
        "trạng thái hiện tại trả về lỗi xung đột; thiếu nội dung kết luận trả về lỗi dữ liệu "
        "không hợp lệ; chưa tiếp nhận mà yêu cầu hành động bảo vệ trả về lỗi không được phép. "
        "Tiêu chí xác nhận: trạng thái cảnh báo đúng như yêu cầu, và dòng thời gian có bản ghi "
        "loại tương ứng với tác nhân và thời điểm của lần thực hiện.",
    ),

    ("H3", "Xử lý thu hồi phiên"),
    (
        "P",
        "Đầu vào gồm mã phiên, và lý do do người hoặc hệ thống đưa ra. Kiểm tra dữ liệu: mã phiên "
        "có tồn tại không; nếu do người dùng thực hiện thì phiên có thuộc về chính họ không; "
        "phiên đã bị thu hồi trước đó chưa. Xử lý: đặt thời điểm thu hồi, và ghi dòng nhật ký "
        "kiểm toán với trạng thái trước và sau. Nếu do hệ thống thực hiện thì cần đếm và trả về "
        "số phiên đã thu hồi.",
    ),
    (
        "P",
        "Điểm thiết kế cần lưu ý: vì cả ba cơ chế thu hồi đều dẫn về cùng một cột thời điểm thu "
        "hồi, nên chỉ cần một điều kiện lọc ở mọi truy vấn xác thực, và một phiên bị thu hồi mất "
        "hiệu lực ngay ở lần gọi kế tiếp chứ không phải chờ hết thời hạn. Tiêu chí xác nhận: "
        "dùng token của phiên đó gọi lại điểm cuối cần xác thực thì nhận mã lỗi không được "
        "phép; với thu hồi hàng loạt, số phiên báo trả về bằng số dòng được cập nhật.",
    ),

    ("H3", "Xử lý khoá tài khoản"),
    (
        "P",
        "Đầu vào gồm mã người dùng và lý do. Kiểm tra dữ liệu: tài khoản có tồn tại và đang hoạt "
        "động không. Xử lý: đặt trạng thái thành đã khoá, ghi thời điểm khoá, đặt thời điểm thu "
        "hồi cho mọi phiên đang hoạt động, tạo thông báo trong ứng dụng cho người dùng, và ghi "
        "dòng nhật ký kiểm toán.",
    ),
    (
        "P",
        "Điểm thiết kế cần lưu ý ở chính sách mức nghiêm trọng: hệ thống chọn thu hồi phiên "
        "thay vì khoá tài khoản, vì thu hồi rẻ và có thể gỡ lại nếu phát hiện báo nhầm, còn khoá "
        "tài khoản là biện pháp nặng và cần con người can thiệp. Do đó hành động khoá tài "
        "khoản được giữ lại cho thao tác thủ công của phân viên hoặc quản trị viên. Tiêu chí "
        "xác nhận: tài khoản không đăng nhập được, và người dùng nhận được thông báo giải thích "
        "lý do.",
    ),

    ("H3", "Xử lý suy giảm về điểm quy tắc"),
    (
        "P",
        "Đầu vào là lần đăng nhập đã chấm điểm quy tắc, cùng lý do máy học không dùng được: quá "
        "hạn, lỗi kết nối, mã lỗi từ máy chủ, hoặc dữ liệu đặc trưng không hợp lệ. Xử lý: giữ "
        "nguyên điểm quy tắc, đặt điểm máy học và mã phiên bản mô hình là rỗng, đặt trạng thái "
        "máy học tương ứng lý do, ghi một dòng nhật ký giai đoạn gọi máy học với nội dung lỗi, "
        "và tiếp tục tính mức rủi ro bằng điểm quy tắc. Kết quả đầu ra vẫn là một kết quả đánh "
        "giá đầy đủ với quyết định hợp lệ.",
    ),
    (
        "P",
        "Tiêu chí xác nhận: bản ghi kết quả đánh giá có trường trạng thái máy học khác thành "
        "công, điểm gộp bằng đúng điểm quy tắc, và bảng nhật ký phát hiện có dòng giai đoạn gọi "
        "máy học với nội dung lỗi không rỗng. Nếu chỉ kiểm tra điểm gộp thì không đủ, vì một "
        "lần chấm điểm đúng bằng quy tắc vẫn có thể là hệ quả của một lỗi âm thầm."),

    ("H3", "Xử lý quản lý thiết bị tin cậy"),
    (
        "P",
        "Đầu vào là vân tay thiết bị do phía máy khách tạo, và thao tác đánh dấu tin cậy hoặc "
        "bỏ đánh dấu. Kiểm tra dữ liệu: vân tay có hợp lệ không; thiết bị đã tin cậy chưa; thời "
        "hạn còn hiệu lực không. Xử lý: tạo hoặc cập nhật bản ghi thiết bị tin cậy với thời hạn "
        "ba mươi ngày tính từ lần dùng gần nhất, đồng thời cập nhật địa chỉ và chuỗi định danh "
        "trình duyệt của lần dùng đó. Thao tác bỏ đánh dấu xoá bản ghi, nên thiết bị đó trở lại "
        "trạng thái chưa tin cậy.",
    ),
    (
        "P",
        "Xử lý lỗi: vân tay rỗng hoặc quá ngắn bị từ chối ở tầng kiểm tra dữ liệu đầu vào; "
        "đánh dấu trùng được xử lý bằng cách cập nhật bản ghi sẵn có thay vì tạo bản ghi mới, "
        "nhờ ràng buộc duy nhất theo cặp người dùng và vân tay. Tiêu chí xác nhận: truy vấn "
        "thiết bị tin cậy trả về đúng một bản ghi với thời hạn còn hiệu lực.",
    ),

    ("H3", "Xử lý cập nhật cảnh báo của hệ thống"),
    (
        "P",
        "Đầu vào là hành động bảo vệ do Detection Engine gửi, gồm loại hành động, mã người dùng, "
        "mã cảnh báo, lý do, và mã yêu cầu. Kiểm tra dữ liệu: loại hành động thuộc tập bốn hành "
        "động hợp lệ; người dùng có tồn tại; mã yêu cầu có bị xử lý trùng không. Xử lý: với "
        "thu hồi toàn bộ phiên thì cập nhật mọi phiên đang hoạt động và đếm số dòng bị ảnh "
        "hưởng; với thu hồi một phiên thì cập nhật đúng phiên được chỉ định; với khoá tài khoản "
        "thì đặt trạng thái và tạo thông báo; với yêu cầu xác thực thêm thì đặt cờ trên tài "
        "khoản. Mọi trường hợp đều ghi dòng nhật ký kiểm toán với lý do đi kèm.",
    ),
    (
        "P",
        "Xử lý lỗi: mã yêu cầu trùng thì trả về kết quả của lần xử lý trước mà không tác động "
        "lần hai; người dùng không tồn tại hoặc loại hành động không hợp lệ thì trả về lỗi dữ "
        "liệu không hợp lệ. Tiêu chí xác nhận: số phiên đã thu hồi trả về khớp với số dòng "
        "thực sự được cập nhật, và dòng nhật ký kiểm toán có bản ghi hành động tương ứng.",
    ),
    ("H3", "Xử lý khôi phục bản ghi chấm lỗi"),
    (
        "P",
        "Đầu vào là danh sách bản ghi lần đăng nhập ở trạng thái lỗi. Xử lý: với mỗi bản ghi, "
        "chạy lại toàn bộ chuỗi chấm điểm như một lần đăng nhập mới, rồi cập nhật kết quả vào "
        "bản ghi cũ. Yêu cầu quan trọng: một bản ghi lỗi không được dừng cả đợi quét, vì nếu "
        "một bản ghi lỗi vĩnh viễn thì nó chiếm mã khoá một-một với kết quả đánh giá, và mọi "
        "lần chấm lại sau đó với lần đăng nhập đó đều không thể ghi kết quả.",
    ),
    (
        "P",
        "Xử lý lỗi: nếu một bản ghi lỗi không chấm lại được thì ghi mã lý do và tiếp tục với "
        "bản ghi tiếp theo. Tiêu chí xác nhận: sau khi chạy, không còn bản ghi lần đăng nhập nào "
        "ở trạng thái lỗi mà không có một bản ghi kết quả đánh giá tương ứng.",
    ),
]
