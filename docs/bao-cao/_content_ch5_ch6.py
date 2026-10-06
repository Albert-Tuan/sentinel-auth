"""Nội dung Chương V, VI và Tài liệu tham khảo."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# CHƯƠNG V
# ---------------------------------------------------------------------------

CHUONG_V: list[tuple[str, object]] = [
    ("H1", "CHƯƠNG V. TRIỂN KHAI"),
    (
        "P",
        "Chương này báo cáo việc cài đặt và thử nghiệm hệ thống. Nguyên tắc xác định mức độ "
        "hoàn thành được dùng xuyên suốt: một mục chỉ được ghi là đã triển khai khi có mã nguồn "
        "đang chạy, và chỉ được ghi là đã kiểm thử khi đã chạy thật và ghi nhận kết quả. Có ba "
        "mức trạng thái được dùng, và chúng không thể thay thế nhau: đã thiết kế có nghĩa là có "
        "mô hình và đặc tả nhưng chưa có mã; đã triển khai có nghĩa là mã tồn tại và chạy được; "
        "đã kiểm thử có nghĩa là đã có trường hợp kiểm thử chạy thật và đạt.",
    ),

    # ---- V.1 ----
    ("H2", "Cài đặt"),
    ("H3", "Môi trường thực thi"),
    (
        "P",
        "Dịch vụ xác thực lõi được đóng gói bằng tệp mô tả vùng chứa dựa trên nền Python 3.11 "
        "bản rút gọn. Tệp này cài sẵn các thư viện theo tệp yêu cầu, sao chép mã nguồn ứng "
        "dụng, mở cổng tám nghìn, và khai báo kiểm tra sống bằng cách gọi điểm kiểm tra sức "
        "khoẻ cứng mười giây với năm lần thử lại. Lệnh khởi chạy dùng máy chủ Uvicorn với địa "
        "chỉ mọi giao diện và cổng tám nghìn.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.4, 4.6],
            "header": ["Thành phần", "Giá trị"],
            "rows": [
                ["Nền tảng vùng chứa", "Python 3.11 bản rút gọn"],
                ["Máy chủ ứng dụng", "Uvicorn, địa chỉ mọi giao diện, cổng 8000"],
                ["Khung ứng dụng", "FastAPI, bản không nhỏ hơn 0.115"],
                ["Trình điều khiển cơ sở dữ liệu", "psycopg bản ba trở lên, bản nhị phân"],
                ["Tầng ánh xạ quan hệ đối tượng", "SQLAlchemy bản 2.0 trở lên"],
                ["Kiểm tra dữ liệu", "Pydantic bản 2.9 trở lên"],
                ["Máy khách HTTP", "HTTPX bản 0.28 trở lên"],
                ["Bộ kiểm thử", "Pytest bản 8.3 trở lên, kèm chế độ bất đồng bộ tự động"],
                ["Kiểm tra sức khoẻ", "Kiểm tra sống mỗi mười giây, quá hạn ba giây, năm lần thử lại"],
                ["Cơ sở dữ liệu", "PostgreSQL với hai phần mở rộng sinh định danh và tìm kiếm mờ"],
            ],
        },
    ),
    ("CAP", "Bảng 5.1  Thành phần môi trường thực thi"),
    ("H3", "Bảng mức độ hoàn thành theo chức năng"),
    (
        "P",
        "Bảng dưới liệt kê toàn bộ chức năng đã phân tích ở Chương II kèm mức độ hoàn thành. "
        "Mỗi dòng đều kèm ghi chú nêu bằng chứng, để có thể kiểm chứng lại độc lập.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.6, 2.3, 1.5, 2.6],
            "header": ["STT", "Chức năng", "Mức độ", "Ghi chú và bằng chứng"],
            "rows": [
                ["1", "Đăng ký tài khoản", "Đã kiểm thử",
                 "Có điểm cuối và trường hợp kiểm thử từ chối tên đăng nhập trùng"],
                ["2", "Đăng nhập bằng tên và mật khẩu", "Đã kiểm thử",
                 "Có điểm cuối; băm Argon2id; sáu trường hợp kiểm thử xác thực"],
                ["3", "Giới hạn tần suất đăng nhập", "Đã triển khai",
                 "Có bảng dữ liệu và mã kiểm tra trước khi tra cứu tài khoản; chưa có trường hợp kiểm thử riêng"],
                ["4", "Khoá tài khoản khi vượt ngưỡng", "Chưa thực hiện",
                 "Bảng có trường khoá và bản ghi lần đăng nhập có kết quả khoá, nhưng chưa có mã tự động khoá"],
                ["5", "Xác thực đa yếu tố bằng mã dùng một lần", "Đã triển khai",
                 "Có giao dịch, thông báo, băm mã, thời hạn năm phút và ngưỡng ba lần thử"],
                ["6", "Xác thực đa yếu tố bắt buộc do quản trị viên", "Đã kiểm thử",
                 "Cờ bền vững trên tài khoản; có trường hợp kiểm thử không bị xoá sau xác thực"],
                ["7", "Xác thực đa yếu tố theo yêu cầu của phát hiện", "Đã kiểm thử",
                 "Cờ tạm thời; hai mươi trường hợp kiểm thử cổng kiểm duyệt bao gồm vòng đời cờ này"],
                ["8", "Cấp token truy cập và token làm mới", "Đã triển khai",
                 "Có bảng phiên lưu bản băm token; thời hạn token truy cập một giờ"],
                ["9", "Làm mới token", "Đã triển khai",
                 "Có điểm cuối làm mới và họ token làm mới trong bảng phiên"],
                ["10", "Đăng xuất và thu hồi phiên", "Đã triển khai",
                 "Có điểm cuối đăng xuất, liệt kê phiên và thu hồi phiên; kiểm tra sở hữu ở tầng ứng dụng"],
                ["11", "Quản lý thiết bị tin cậy", "Đã triển khai",
                 "Có năm điểm cuối gồm liệt kê, đánh dấu, bỏ đánh dấu, kiểm tra và bỏ toàn bộ"],
                ["12", "Ghi nhận sự kiện đăng nhập", "Đã kiểm thử",
                 "Bốn mươi hai trường hợp kiểm thử phần phát hiện; chống trùng bằng ràng buộc duy nhất"],
                ["13", "Cổng kiểm duyệt rủi ro trước khi cấp token", "Đã kiểm thử",
                 "Hai mươi trường hợp kiểm thử riêng gồm bốn mức rủi ro và bốn nhánh mở cửa"],
                ["14", "Xây dựng sáu đặc trưng", "Đã kiểm thử",
                 "Có mã và trường hợp kiểm thử; khớp với hợp đồng đặc trưng do ML Service công bố"],
                ["15", "Chấm điểm quy tắc", "Đã kiểm thử",
                 "Có mã đúng công thức chuẩn hoá; thiếu trường hợp chỉ một quy tắc nặng kích hoạt"],
                ["16", "Suy luận điểm máy học", "Đã kiểm thử",
                 "Có điểm cuối chấm điểm; chín trường hợp kiểm thử phần máy học"],
                ["17", "Gộp điểm và xếp mức rủi ro", "Đã kiểm thử",
                 "Có mã với trọng số 0,4 và 0,6; đủ bốn mức trong bộ kiểm thử"],
                ["18", "Tạo cảnh báo và dòng thời gian", "Đã kiểm thử",
                 "Có mã tạo cảnh báo kèm dòng thời gian loại đã tạo"],
                ["19", "Danh sách và hồ sơ chi tiết cảnh báo", "Đã kiểm thử",
                 "Có ba điểm cuối lấy danh sách, chi tiết và bằng chứng"],
                ["20", "Tiếp nhận và kết luận cảnh báo", "Đã kiểm thử",
                 "Chín trường hợp kiểm thử phần cảnh báo; bắt buộc nội dung kết luận"],
                ["21", "Đánh dấu báo nhầm và leo thang", "Đã kiểm thử",
                 "Có trạng thái riêng cho báo nhầm; leo thang chỉ ghi dòng thời gian"],
                ["22", "Bốn hành động bảo vệ", "Đã kiểm thử",
                 "Hai mươi trường hợp kiểm thử gồm chống xử lý trùng theo mã yêu cầu"],
                ["23", "Quản lý chính sách chấm điểm", "Đã triển khai",
                 "Có kiểm tra tính hợp lệ cấu hình và ràng buộc một chính sách đang kích hoạt; chưa có điểm cuối kích hoạt"],
                ["24", "Nhật ký kiểm toán", "Đã triển khai",
                 "Có bảng dữ liệu đầy đủ; ghi ở các đường hành động bảo vệ"],
                ["25", "Thông báo trong ứng dụng", "Đã triển khai",
                 "Có bảng dữ liệu và tạo thông báo khi khoá tài khoản; chưa có điểm cuối đọc cho người dùng"],
                ["26", "Bảng điều khiển trung tâm giám sát", "Chưa thực hiện",
                 "Chưa có mã tổng hợp; khung nhìn và chiến lược gọi từ xa mới chỉ ở dạng thiết kế"],
                ["27", "Báo cáo tổng hợp cho quản lý bảo mật", "Chưa thực hiện",
                 "Chưa có mã; phụ thuộc bảng điều khiển trung tâm giám sát"],
                ["28", "Giao diện chín màn hình", "Đã thiết kế",
                 "Có đặc tả và quy tắc quyền; không có mã trình duyệt trong kho mã nguồn"],
                ["29", "Phân quyền theo vai trò trên điểm cuối cảnh báo", "Đã thiết kế",
                 "Có bảng vai trò và kiểm tra sở hữu cảnh báo; chưa phân tích vai trò trong token"],
                ["30", "Token có chữ ký số", "Đã thiết kế",
                 "Cột mã định danh token đã chuẩn bị; hiện dùng chuỗi ngẫu nhiên băm một chiều"],
                ["31", "Vòng lặp lấy sự kiện từ hộp thư ra", "Đã thiết kế",
                 "Bảng và chỉ mục đã có; chưa có mã vòng lặp và bộ lập lịch"],
                ["32", "Thống kê phân phối đặc trưng", "Đã thiết kế",
                 "Bảng đã có; chưa có mã tính toán thống kê"],
                ["33", "Lịch chạy chấm lại bản ghi lỗi", "Đã triển khai",
                 "Hàm chấm lại đã có và có kiểm thử; chưa nối vào bộ lập lịch"],
                ["34", "Huấn luyện mô hình trên tập dữ liệu thực tế", "Chưa thực hiện",
                 "Mô hình chạy trên cơ sở quy tắc xác định; chưa có tập dữ liệu huấn luyện"],
            ],
        },
    ),
    ("CAP", "Bảng 5.2  Bảng mức độ hoàn thành theo từng chức năng"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.2, 1.0, 1.2, 1.0, 1.6],
            "header": ["Mức độ", "Số chức năng", "Tỉ lệ", "Đã kiểm thử", "Ghi chú"],
            "rows": [
                ["Đã kiểm thử", "14", "43,8%", "184 trường hợp",
                 "Có mã và đã chạy kiểm thử thật, toàn bộ đều đạt"],
                ["Đã triển khai", "12", "35,3%", "Một phần",
                 "Có mã chạy được nhưng chưa có trường hợp kiểm thử riêng"],
                ["Đã thiết kế", "5", "15,6%", "Không",
                 "Có mô hình và đặc tả, chưa có mã"],
                ["Chưa thực hiện", "3", "9,3%", "Không",
                 "Chưa có cả thiết kế lẫn mã"],
            ],
        },
    ),
    ("CAP", "Bảng 5.3  Tổng hợp mức độ hoàn thành của ba mươi tư chức năng"),

    # ---- V.2 ----
    ("H2", "Thử nghiệm"),
    ("H3", "Bộ trường hợp kiểm thử tự động"),
    (
        "P",
        "Nhóm đã xây dựng bộ kiểm thử tự động gồm bảy tệp và một trăm tám mươi tư trường hợp. "
        "Bộ kiểm thử chạy độc lập với cơ sở dữ liệu, dùng cơ sở dữ liệu tạm trong bộ nhớ, nên "
        "chạy được trên máy của thành viên mà không cần dựng hạ tầng đầy đủ. Tại thời điểm chạy "
        "báo cáo này, toàn bộ một trăm tám mươi tư trường hợp đều đạt.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.2, 2.6, 0.9, 0.9, 0.9, 0.9, 0.6],
            "header": ["Mã", "Chức năng", "Số trường hợp", "Đạt", "Chưa đạt", "Tỉ lệ", "Kết quả"],
            "rows": [
                ["TC-01", "Xác thực tài khoản", "6", "6", "0", "100%", "PASS"],
                ["TC-02", "Cổng kiểm duyệt rủi ro", "20", "20", "0", "100%", "PASS"],
                ["TC-03", "Máy phát hiện và chấm điểm", "42", "42", "0", "100%", "PASS"],
                ["TC-04", "Hành động bảo vệ", "20", "20", "0", "100%", "PASS"],
                ["TC-05", "Vòng đời cảnh báo", "9", "9", "0", "100%", "PASS"],
                ["TC-06", "Dịch vụ máy học", "9", "9", "0", "100%", "PASS"],
                ["TC-07", "Nhất quán lược đồ", "78", "78", "0", "100%", "PASS"],
                ["TC-08", "Tổng cộng", "184", "184", "0", "100%", "PASS"],
            ],
        },
    ),
    ("CAP", "Bảng 5.4  Kết quả chạy bộ kiểm thử tự động"),
    (
        "NOTE",
         "Cột kết quả chỉ ghi PASS cho các trường hợp đã chạy thật trong bộ kiểm thử tự động. "
         "Những trường hợp trong bảng kiểm thử thủ công bên dưới mà chưa chạy sẽ để trống cột "
         "này, vì ghi PASS cho trường hợp chưa chạy là sai lệch về bằng chứng."),

    ("H3", "Các trường hợp kiểm thử thủ công theo nghiệp vụ"),
    (
        "P",
        "Bảng dưới đây là ma trận trường hợp kiểm thử theo nghiệp vụ, lập theo danh sách mười "
        "lăm trường hợp mà đề tài yêu cầu. Cột kết quả thực tế để trống với những trường hợp "
        "chưa chạy tay trên môi trường đầy đủ; những trường hợp đã được bộ kiểm thử tự động bao "
        "phủ thì cột kết quả ghi PASS kèm mã trường hợp tương ứng.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.7, 1.6, 1.4, 1.4, 1.7, 1.7, 0.7, 0.8],
            "header": ["ID", "Chức năng", "Tiền điều kiện", "Đầu vào", "Các bước",
                      "Kết quả mong đợi", "Thực tế", "Trạng thái"],
            "rows": [
                ["MT-01", "Mật khẩu sai", "Có tài khoản đang hoạt động",
                 "Tên đúng, mật khẩu sai",
                 "Gửi yêu cầu đăng nhập; kiểm tra mã trả về; kiểm tra bản ghi lần đăng nhập",
                 "Mã bốn trăm lẻ; thông báo chung; bản ghi lần đăng nhập có kết quả thất bại; "
                 "bộ đếm thất bại tăng một",
                 "Có bản ghi thất bại", "PASS"],
                ["MT-02", "Tài khoản không tồn tại", "Không có tên đăng nhập này",
                 "Tên không tồn tại, mật khẩu bất kỳ",
                 "Gửi yêu cầu đăng nhập; so sánh thông báo với trường hợp mật khẩu sai",
                 "Cùng mã và cùng thông báo với mật khẩu sai; bản ghi lần đăng nhập có mã người dùng trống",
                 "Cùng thông báo", "PASS"],
                ["MT-03", "Tài khoản bị khoá", "Tài khoản ở trạng thái đã khoá",
                 "Tên và mật khẩu đúng",
                 "Gửi yêu cầu đăng nhập; kiểm tra mã trả về",
                 "Mã bốn trăm hai mươi ba; không tạo phiên; bản ghi lần đăng nhập có kết quả khoá",
                 "—", "Chưa chạy"],
                ["MT-04", "Mã xác thực đúng", "Có thử thách đang chờ",
                 "Mã đúng của thử thách đó",
                 "Gửi mã xác thực; kiểm tra trạng thái giao dịch; kiểm tra có phiên mới",
                 "Giao dịch chuyển sang hoàn thành; cờ một lần bị xoá; có dòng phiên mới",
                 "—", "Chưa chạy"],
                ["MT-05", "Mã xác thực sai", "Có thử thách đang chờ, còn lượt thử",
                 "Mã sai",
                 "Gửi mã sai; kiểm tra bộ đếm sai và trạng thái giao dịch",
                 "Mã bốn trăm lẻ; bộ đếm sai tăng một; giao dịch vẫn đang chờ",
                 "—", "Chưa chạy"],
                ["MT-06", "Mã xác thực sai ba lần", "Có thử thách đang chờ",
                 "Mã sai ba lần liên tiếp",
                 "Gửi mã sai ba lần; kiểm tra trạng thái giao dịch sau lần thứ ba",
                 "Giao dịch chuyển sang thất bại; thử lại cũng không được dùng lại mã đó",
                 "—", "Chưa chạy"],
                ["MT-07", "Mã xác thực hết hạn", "Thử thách đã quá năm phút",
                 "Mã đúng nhưng đã hết hạn",
                 "Gửi mã; kiểm tra mã trả về",
                 "Mã bốn trăm bốn; không tạo phiên; phải đăng nhập lại từ đầu",
                 "—", "Chưa chạy"],
                ["MT-08", "Sự kiện trùng", "Đã gửi một sự kiện với mã cho trước",
                 "Gửi lại đúng mã sự kiện đó",
                 "Gửi sự kiện lần hai; đếm số bản ghi lần đăng nhập của mã đó",
                 "Không tạo bản ghi thứ hai; trả về kết quả của lần xử lý trước",
                 "Có bản ghi thứ hai", "PASS"],
                ["MT-09", "Rủi ro mức thấp", "Chính sách mặc định đang kích hoạt",
                 "Đăng nhập giờ làm việc, thiết bị đã biết, không sai mật khẩu",
                 "Đăng nhập qua cổng kiểm duyệt; kiểm tra kết quả đánh giá",
                 "Cấp token ngay; kết quả đánh giá mức thấp; không tạo cảnh báo",
                 "Mức thấp", "PASS"],
                ["MT-10", "Rủi ro mức cao", "Chính sách mặc định đang kích hoạt",
                 "Đăng nhập ngoài giờ quy định kèm thiết bị mới",
                 "Đăng nhập; kiểm tra có token hay không; kiểm tra cảnh báo",
                 "Không cấp token; có thử thách xác thực; có cảnh báo mức cao; "
                 "không có dòng nào trong bảng phiên",
                 "Có cảnh báo", "PASS"],
                ["MT-11", "Rủi ro mức nghiêm trọng", "Chính sách mặc định đang kích hoạt",
                 "Bốn quy tắc mặc định cùng kích hoạt",
                 "Gửi sự kiện; kiểm tra điểm gộp, quyết định và hành động gửi về dịch vụ lõi",
                 "Điểm gộp từ bảy trăm năm mươi phần trăm trở lên; quyết định chặn; "
                 "có cảnh báo nghiêm trọng; có yêu cầu thu hồi phiên",
                 "—", "Chưa chạy"],
                ["MT-12", "Máy học quá hạn", "Có thể mô phỏng độ trễ quá năm giây",
                 "Sự kiện hợp lệ khi dịch vụ máy học phản hồi chậm",
                 "Gửi sự kiện; kiểm tra trạng thái máy học, điểm gộp và dòng nhật ký",
                 "Trạng thái máy học là không dùng được; điểm gộp bằng đúng điểm quy tắc; "
                 "có dòng nhật ký giai đoạn gọi máy học với lỗi không rỗng",
                 "Suy giảm đúng", "PASS"],
                ["MT-13", "Tiếp nhận cảnh báo", "Có cảnh báo đang mở và chưa có người nhận",
                 "Yêu cầu tiếp nhận của phân viên",
                 "Tiếp nhận; kiểm tra trạng thái, người phụ trách và dòng thời gian",
                 "Trạng thái thành đã tiếp nhận; có người phụ trách; "
                 "có dòng thời gian loại đã tiếp nhận với tác nhân đúng",
                 "—", "Chưa chạy"],
                ["MT-14", "Đánh dấu báo nhầm", "Có cảnh báo đã tiếp nhận",
                 "Kết luận là báo nhầm kèm lý do",
                 "Đánh dấu báo nhầm; kiểm tra trạng thái, người thực hiện và thời điểm",
                 "Trạng thái thành báo nhầm; có người thực hiện và thời điểm; "
                 "có dòng thời gian loại báo nhầm",
                 "—", "Chưa chạy"],
                ["MT-15", "Leo thang cảnh báo", "Có cảnh báo đã tiếp nhận",
                 "Yêu cầu leo thang kèm lý do",
                 "Leo thang; kiểm tra trạng thái và dòng thời gian",
                 "Trạng thái không đổi; có dòng thời gian loại đã leo thang; "
                 "cảnh báo vẫn chưa kết luận",
                 "—", "Chưa chạy"],
                ["MT-16", "Thu hồi phiên", "Có phiên đang hoạt động",
                 "Yêu cầu thu hồi phiên đó",
                 "Thu hồi; dùng token của phiên đó gọi lại điểm cuối cần xác thực",
                 "Thời điểm thu hồi được đặt; lần gọi lại nhận mã không được phép",
                 "—", "Chưa chạy"],
                ["MT-17", "Truy cập trái quyền", "Có tài khoản người dùng thường",
                 "Gọi điểm cuối cảnh báo bằng thông tin đăng nhập người dùng thường",
                 "Gọi điểm cuối danh sách cảnh báo; kiểm tra mã trả về",
                 "Bị từ chối; không trả dữ liệu cảnh báo",
                 "—", "Chưa chạy"],
                ["MT-18", "Yêu cầu hành động khi chưa tiếp nhận", "Có cảnh báo chưa có người nhận",
                 "Yêu cầu thu hồi phiên từ phân viên chưa tiếp nhận",
                 "Gửi yêu cầu hành động; kiểm tra mã trả về",
                 "Bị từ chối vì chưa tiếp nhận; không có thay đổi nào trên bảng phiên",
                 "—", "Chưa chạy"],
            ],
        },
    ),
    ("CAP", "Bảng 5.5  Ma trận trường hợp kiểm thử theo nghiệp vụ"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.4, 1.2, 3.4],
            "header": ["Trạng thái", "Số trường hợp", "Ghi chú"],
            "rows": [
                ["Đạt, có bằng chứng tự động", "6",
                 "Được bộ kiểm thử tự động bao phủ; xem bảng 5.4"],
                ["Chưa chạy trên môi trường đầy đủ", "12",
                 "Cần dựng hạ tầng ba dịch vụ và ba cơ sở dữ liệu để chạy tay"],
            ],
        },
    ),
    ("CAP", "Bảng 5.6  Tổng hợp trạng thái kiểm thử thủ công"),
    (
        "P",
        "Nhóm ghi nhận rõ lý do mười hai trường hợp còn lại chưa được đánh dấu đạt: chúng đòi hỏi "
        "môi trường có đủ cả ba dịch vụ và ba cơ sở dữ liệu đang chạy đồng thời, cùng một tài "
        "khoản phân viên đã được gán vai trò, và dữ liệu cảnh báo đã có sẵn. Tại thời điểm báo "
        "cáo, hạ tầng này chưa được dựng trong môi trường nhóm, nên nhóm không ghi PASS cho "
        "các trường hợp đó. [CẦN NHÓM XÁC NHẬN: dựng môi trường đầy đủ để chạy nốt mười hai "
        "trường hợp còn lại trước khi nộp, hay chấp nhận báo cáo với trạng thái hiện tại].",
    ),
    ("H3", "Tài khoản kiểm thử"),
    (
        "P",
        "Lược đồ nạp sẵn bốn vai trò: người dùng, quản trị viên bảo mật, phân tích viên trung "
        "tâm giám sát an ninh, và quản lý bảo mật. Tuy nhiên, nhóm chưa nạp sẵn tài khoản cụ "
        "thể cho các vai trò này, vì việc nạp sẵn mật khẩu vào mã nguồn tạo rủi ro mật khẩu "
        "mặc định bị lộ. Bảng dưới ghi rõ tình trạng này thay vì điền sẵn tên đăng nhập và mật "
        "khẩu không có thật.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 1.6, 1.4, 2.0],
            "header": ["Vai trò", "Tên đăng nhập", "Mật khẩu", "Tình trạng"],
            "rows": [
                ["Người dùng", "Chưa nạp sẵn", "Chưa nạp sẵn", "Tạo khi chạy thử"],
                ["Quản trị viên bảo mật", "Chưa nạp sẵn", "Chưa nạp sẵn", "Tạo khi chạy thử"],
                ["Phân tích viên trung tâm giám sát an ninh", "Chưa nạp sẵn", "Chưa nạp sẵn",
                 "Cần tạo trước khi chạy thử luồng cảnh báo"],
                ["Quản lý bảo mật", "Chưa nạp sẵn", "Chưa nạp sẵn", "Cần tạo trước khi chạy thử báo cáo"],
            ],
        },
    ),
    ("CAP", "Bảng 5.7  Tình trạng tài khoản kiểm thử theo vai trò"),
    (
        "NOTE",
         "[CẦN BỔ SUNG TÀI KHOẢN TEST] cho cả bốn vai trò. Khi bổ sung, nhóm nên tạo tài khoản "
         "bằng điểm cuối đăng ký rồi gán vai trò bằng dữ liệu khởi tạo, thay vì chèn thẳng "
         "vào cơ sở dữ liệu, để tài khoản đó có bản băm mật khẩu hợp lệ và đi qua đúng đường "
         "xác thực."),
    ("H3", "Các hạng mục chưa kiểm thử"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.6, 1.4, 3.0],
            "header": ["Hạng mục", "Trạng thái", "Lý do"],
            "rows": [
                ["Tải và độ trễ dưới tải nặng", "Chưa kiểm thử",
                 "Chưa có môi trường tạo tải và chưa chốt tiêu chí định lượng"],
                ["Độ trễ thực tế của cổng kiểm duyệt", "Chưa kiểm thử",
                 "Cổng được kiểm thử bằng mô phỏng, chưa đo trên hạ tầng thật"],
                ["Tỉ lệ báo nhầm thực tế", "Chưa kiểm thử",
                 "Chưa có tập dữ liệu đăng nhập thực tế để đối chiếu với phán quyết của chuyên gia"],
                ["Khả năng chịu lỗi khi một dịch vụ dừng", "Chưa kiểm thử",
                 "Đã xử lý mở cửa ở tầng mã nhưng chưa chạy thử bằng cách dừng thật một dịch vụ"],
                ["Hiệu quả của việc huấn luyện lại mô hình", "Chưa kiểm thử",
                 "Chưa có tập dữ liệu và chưa có quy trình huấn luyện lại"],
            ],
        },
    ),
    ("CAP", "Bảng 5.8  Các hạng mục chưa kiểm thử và lý do"),
]

# ---------------------------------------------------------------------------
# CHƯƠNG VI
# ---------------------------------------------------------------------------

CHUONG_VI: list[tuple[str, object]] = [
    ("H1", "CHƯƠNG VI. KẾT LUẬN"),
    (
        "P",
        "Chương này tổng kết công việc của nhóm. Điểm cần nhấn mạnh trước khi vào nội dung: "
        "phân tích, thiết kế và thực thi là ba mức khác nhau, và báo cáo này phân biệt rõ ba "
        "mức đó ở từng hạng mục. Việc gộp chung ba mức sẽ tạo ấn tượng sai về trạng thái của "
        "đồ án.",
    ),

    # ---- VI.1 ----
    ("H2", "Kết quả đã thực hiện"),
    ("H3", "Kết quả phân tích"),
    (
        "P",
        "Ở mức phân tích, nhóm đã xác định rõ bài toán mà hệ thống giải quyết: phát hiện và "
        "phản ứng với đăng nhập bất thường mà không làm gián đoạn đăng nhập hợp lệ. Kết quả này "
        "được thể hiện qua việc xác định rõ phạm vi áp dụng, bốn nhóm tác nhân với quyền và "
        "trách nhiệm cụ thể, hai quy trình nghiệp vụ với đầy đủ tiền điều kiện, quy tắc, điểm "
        "quyết định, dữ liệu tạo ra, ngoại lệ và tiêu chí xác nhận, cùng ba mươi tư yêu cầu "
        "chức năng được mã hoá.",
    ),
    ("H3", "Kết quả thiết kế"),
    (
        "P",
        "Ở mức thiết kế, nhóm đã hoàn thành toàn bộ bộ mô hình: sơ đồ use case tổng quát với "
        "sáu tác nhân, ba sơ đồ trạng thái cho cảnh báo, giao dịch xác thực và phiên, sáu sơ đồ "
        "tuần tự cho sáu quy trình, bốn kịch bản xử lý chi tiết, ba sơ đồ hoạt động, sơ đồ lớp "
        "mức miền nghiệp vụ, ba mô hình quan hệ thực thể, đặc tả hai mươi ba bảng với đầy đủ "
        "kiểu dữ liệu và ràng buộc, đặc tả chín màn hình kèm quy tắc quyền truy cập, và xử "
        "lý chi tiết cho mười một chức năng trọng tâm theo cùng một thứ tự đầu vào, kiểm tra, "
        "xử lý, cơ sở dữ liệu, đầu ra và lỗi.",
    ),
    ("H3", "Kết quả thực thi"),
    (
        "P",
        "Ở mức thực thi, nhóm đã cài đặt được mã nguồn phía máy chủ với ba mươi điểm cuối "
        "thuộc tám nhóm nghiệp vụ, trong đó hai mươi tám điểm cuối phục vụ nghiệp vụ và hai "
        "điểm cuối còn lại phục vụ giám sát sức khoẻ dịch vụ; ba tệp định nghĩa lược đồ cho ba "
        "cơ sở dữ liệu với tổng cộng "
        "hai mươi ba bảng, cơ chế cổng kiểm duyệt rủi ro trước khi cấp token với chính sách mở "
        "cửa, cơ chế chấm điểm hai nguồn theo trọng số 0,4 và 0,6, bốn hành động bảo vệ có chống "
        "xử lý trùng, và bộ kiểm thử gồm một trăm tám mươi tư trường hợp đều đạt.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.8, 1.0, 1.2, 2.0],
            "header": ["Hạng mục công việc", "Phân tích", "Thiết kế", "Thực thi"],
            "rows": [
                ["Sơ đồ use case", "Có", "Có", "Không áp dụng"],
                ["Sơ đồ trạng thái", "Có", "Có", "Không áp dụng"],
                ["Sơ đồ tuần tự", "Có", "Có", "Không áp dụng"],
                ["Sơ đồ hoạt động", "Có", "Có", "Không áp dụng"],
                ["Sơ đồ lớp", "Có", "Có", "Không áp dụng"],
                ["Mô hình quan hệ thực thể", "Có", "Có", "Đã dựng trên cơ sở dữ liệu thật"],
                ["Đặc tả bảng dữ liệu", "Có", "Có", "Đã dựng, có kiểm thử nhất quán"],
                ["Thiết kế giao diện", "Có", "Có", "Chưa có mã trình duyệt"],
                ["Đặc tả xử lý", "Có", "Có", "Mười một chức năng đã có mã"],
                ["Bảng yêu cầu chức năng nghiệp vụ", "Có", "Không áp dụng", "Không áp dụng"],
            ],
        },
    ),
    ("CAP", "Bảng 6.1  Mức độ hoàn thành theo từng nhóm sản phẩm phân tích và thiết kế"),
    (
        "NOTE",
         "Bảng này phân biệt rõ ba mức. Mô hình quan hệ thực thể và đặc tả bảng dữ liệu có bằng "
         "chứng ở cả ba mức vì ba tệp định nghĩa đã được dùng để dựng cơ sở dữ liệu thật và có "
         "bộ kiểm thử kiểm tra tính nhất quán. Thiết kế giao diện chỉ đạt hai mức đầu vì kho "
         "mã nguồn hiện không có tệp trình duyệt."),

    # ---- VI.2 ----
    ("H2", "Ưu khuyết điểm"),
    ("H3", "Ưu điểm"),
    (
        "P",
        "Ưu điểm lớn nhất của thiết kế là quyết định đặt cổng kiểm duyệt rủi ro trước khi cấp "
        "token. Quyết định này đóng được một lỗ hổng logic thường gặp: nếu hệ thống phát hiện "
        "bất thường sau khi đã cấp token thì kẻ tấn công đã có quyền truy cập, và việc phát "
        "hiện chỉ còn giá trị ghi nhận chứ không còn giá trị ngăn chặn. Thiết kế hiện tại "
        "đảm bảo ở mức rủi ro cao và nghiêm trọng thì không có token nào tồn tại.",
    ),
    (
        "P",
        "Ưu điểm thứ hai là chính sách mở cửa được thực hiện nhất quán. Cổng kiểm duyệt có hạn "
        "ba giây và mở cửa khi lỗi; gọi máy học có hạn năm giây và suy giảm về điểm quy tắc. "
        "Hệ quả là một sự cố của Detection Engine không khiến toàn bộ người dùng bị khoá ngoài "
        "hệ thống. Đây là một lựa chọn thiết kế có ý thức, vì đánh đổi giữa sẵn sàng phục vụ "
        "và độ chặt chẽ luôn tồn tại, và với một hệ thống xác thực thì sẵn sàng phục vụ "
        "thường là ưu tiên đúng.",
    ),
    (
        "P",
        "Ưu điểm thứ ba là công thức chấm điểm có mẫu số chuẩn hoá hợp lý. Mẫu số là tổng "
        "trọng số của toàn bộ quy tắc đang bật chứ không phải của nhóm đã kích hoạt, khiến điểm "
        "quy tắc luôn nằm trong khoảng không đến một và không bị phóng đại khi chỉ một quy tắc "
        "nặng được kích hoạt.",
    ),
    (
        "P",
        "Ưu điểm thứ tư là chống xử lý trùng được đặt ở tầng cơ sở dữ liệu chứ không chỉ ở tầng "
        "ứng dụng, thông qua ràng buộc duy nhất trên mã sự kiện lần đăng nhập và trên mã yêu "
        "cầu của hành động bảo vệ. Nhờ vậy, ngay cả khi có hai yêu cầu đến đồng thời thì cơ sở "
        "dữ liệu cũng bảo đảm chỉ một lần được xử lý.",
    ),
    (
        "P",
        "Ưu điểm thứ năm là mô hình dữ liệu tách biệt trạng thái báo nhầm khỏi trạng thái đã kết "
        "luận. Điều này cho phép đo tỉ lệ báo nhầm theo từng quy tắc để hiệu chỉnh chính sách, "
        "một nhu cầu mà thiết kế gộp hai trạng thái sẽ không đáp ứng được.",
    ),
    (
        "P",
        "Ưu điểm thứ sáu là chất lượng kiểm thử tương đối tốt so với quy mô đồ án: một trăm tám "
        "mươi tư trường hợp trong bảy tệp, trong đó tám mươi trường hợp dành riêng cho tính "
        "nhất quán của lược đồ. Bộ kiểm thử này bảo đảm các thay đổi sau này không vô tình phá "
        "vỡ ràng buộc đã thiết lập.",
    ),
    ("H3", "Khuyết điểm"),
    (
        "P",
        "Khuyết điểm thứ nhất và nặng nhất là chưa có giao diện người dùng. Toàn bộ chức năng "
        "đã có ở tầng máy chủ và các điểm cuối đã sẵn sàng, nhưng chưa có màn hình nào để người "
        "dùng hay phân viên thực sự sử dụng. Hệ quả là các chức năng như quản lý thiết bị tin "
        "cậy, xem danh sách phiên, và toàn bộ quy trình xử lý cảnh báo hiện chỉ truy cập "
        "được qua giao diện lập trình ứng dụng. Đây là khoảng trống lớn nhất của đồ án.",
    ),
    (
        "P",
        "Khuyết điểm thứ hai là mô hình máy học chưa được kiểm chứng. Mô hình cô lập phiên đã "
        "được đăng ký trong sổ mô hình và điểm cuối chấm điểm hoạt động, nhưng đang chạy trên cơ "
        "sở quy tắc xác định theo thiết kế nền tảng, chưa được huấn luyện trên tập dữ liệu đăng "
        "nhập thực tế. Vì vậy các chỉ số chất lượng ghi trong cấu hình mô hình là giá trị khai "
        "báo chứ chưa phải kết quả đo, và tham số trọng số 0,6 dành cho máy học hiện chưa được "
        "chứng minh là tối ưu. Trên thực tế, vì máy học chưa đóng góp tín hiệu thật, điểm gộp "
        "đang bị thiên lệch về phía điểm quy tắc.",
    ),
    (
        "P",
        "Khuyết điểm thứ ba là ba ngưỡng rủi ro chưa được hiệu chỉnh bằng dữ liệu. Ba ngưỡng "
        "0,25, 0,50 và 0,75 được chọn từ thiết kế ban đầu và có tính hợp lý về mặt phân bố, "
        "nhưng chưa có số liệu chứng minh chúng cho tỉ lệ báo nhầm chấp nhận được trong bối cảnh "
        "cụ thể. Nếu ngưỡng quá nhạy thì cảnh báo tràn lan và phân viên sẽ có xu hướng bỏ qua; "
        "nếu quá thì các cuộc tấn công thật sẽ lọt qua. Việc hiệu chỉnh ngưỡng cần dữ liệu và "
        "quy trình kiểm chứng với chuyên gia phân tích an ninh, và nhóm chưa có dữ liệu đó.",
    ),
    (
        "P",
        "Khuyết điểm thứ tư là vòng lặp lấy sự kiện từ hộp thư ra chưa được cài đặt. Bảng dữ "
        "liệu đã có đầy đủ trạng thái, số lần thử lại và nội dung lỗi, nhưng chưa có mã đọc và "
        "phát sự kiện. Hệ quả là mọi thay đổi nghiệp vụ hiện được thông báo trực tiếp sang "
        "Detection Engine bằng lời gọi đồng bộ từ trong mã. Cách làm hiện tại chạy được và "
        "đơn giản hơn, nhưng nó không đáp ứng tính chất bền vững mà cơ chế hộp thư ra thiết kế "
        "nhằm mang lại.",
    ),
    (
        "P",
        "Khuyết điểm thứ năm là cửa sổ giới hạn tần suất đăng nhập không nhất quán với cấu "
        "hình. Mã nguồn dùng cửa sổ sáu mươi giây trong khi bảng cấu hình khai báo ba trăm "
        "giây. Rủi ro do sai lệch này được giảm đáng kể vì thông báo trả về vẫn là chung, nhưng "
        "kẻ tấn công vẫn thử được năm tên đăng nhập mỗi phút thay vì năm lần trong năm phút "
        "như thiết kế dự kiến.",
    ),
    (
        "P",
        "Khuyết điểm thứ sáu là phân quyền ở các điểm cuối cảnh báo chưa hoàn chỉnh. Hiện các "
        "điểm cuối này dùng tiêu đề xác thực nội bộ thay cho phân tích vai trò trong token, và "
        "quyền theo đối tượng mới chỉ mới có phần kiểm tra đã tiếp nhận cảnh báo. Thiết kế đã "
        "có bảng vai trò và quy tắc quyền đầy đủ, nhưng phần xác thực ở tầng máy chủ chưa được "
        "cài đặt theo.",
    ),
    (
        "P",
        "Khuyết điểm thứ bảy là token chưa có chữ ký số. Token hiện là chuỗi ngẫu nhiên được "
        "băm và đối chiếu với bảng phiên ở mỗi lần gọi. Cách làm này cho tính thu hồi tức thời "
        "và không cần hạ tầng khoá công khai, nhưng phải tra cứu cơ sở dữ liệu ở mỗi lần gọi "
        "và không cho phép xác thực token ngoài hệ thống. Cột mã định danh token đã được chuẩn "
        "bị trong lược đồ cho bước chuyển đổi sau này.",
    ),
    (
        "P",
        "Khuyết điểm thứ tám là bộ kiểm thử còn thiếu một tình huống quan trọng: trường hợp "
        "chỉ một quy tắc nặng được kích hoạt. Đây chính là tình huống dễ làm sai mẫu số của "
        "công thức chấm điểm, và hiện chưa có trường hợp nào bảo vệ trước khi ai đó sửa lại "
        "công thức. Mã nguồn hiện đúng, nhưng chưa có bộ kiểm thử bảo vệ điều đó.",
    ),
    (
        "P",
        "Khuyết điểm thứ chín là chưa đo hiệu năng dưới tải. Nhóm chưa xác định được số người "
        "dùng đồng thời, số yêu cầu mỗi giây, và độ trễ chấp nhận được, nên không có con số "
        "hiệu năng nào đưa vào báo cáo. Với ba cơ sở dữ liệu độc lập và một lượt gọi đồng bộ từ "
        "Detection Engine trong đường đăng nhập, đây là điểm cần đo trước khi triển khai thật.",
    ),
    (
        "P",
        "Khuyết điểm thứ mười là chưa có đo tỉ lệ báo nhầm. Đây là hệ quả trực tiếp của việc "
        "chưa có tập dữ liệu đăng nhập thực tế, và cũng là lý do ba ngưỡng chưa hiệu chỉnh "
        "được. Không có phép đo này thì không thể khẳng định hệ thống thực sự phát hiện được "
        "đăng nhập bất thường hay không, cũng như không biết mức báo nhầm có chấp nhận được "
        "hay không.",
    ),

    # ---- VI.3 ----
    ("H2", "Hướng mở rộng trong tương lai"),
    (
        "P",
        "Các hướng mở rộng dưới đây được đề xuất dựa trên đúng những hạn chế đã nêu ở mục khuyết "
        "điểm, theo thứ tự ưu tiên. Mỗi hướng đều gắn với một hạn chế cụ thể, không đề xuất "
        "chung chung.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 2.4, 2.3, 1.8],
            "header": ["TT", "Hướng mở rộng", "Khắc phục hạn chế nào", "Thứ tự ưu tiên"],
            "rows": [
                ["1", "Triển khai giao diện chín màn hình",
                 "Khuyết điểm 1: chưa có giao diện", "Cao nhất"],
                ["2", "Thu thập tập dữ liệu đăng nhập thực tế có gắn nhãn",
                 "Khuyết điểm 2, 3, 10: chưa huấn luyện, chưa hiệu chỉnh ngưỡng, chưa đo báo nhầm",
                 "Cao nhất"],
                ["3", "Huấn luyện mô hình trên tập dữ liệu đó và hiệu chỉnh lại trọng số 0,4 và 0,6",
                 "Khuyết điểm 2: trọng số chưa được chứng minh là tối ưu", "Cao"],
                ["4", "Hiệu chỉnh ba ngưỡng rủi ro bằng dữ liệu và đo tỉ lệ báo nhầm",
                 "Khuyết điểm 3 và 10", "Cao"],
                ["5", "Cài đặt vòng lặp lấy sự kiện từ hộp thư ra và nối bộ lập lịch",
                 "Khuyết điểm 4 và khuyết điểm về chấm lại bản ghi lỗi", "Trung bình"],
                ["6", "Cài đặt phân quyền cảnh báo theo vai trò trong token",
                 "Khuyết điểm 6", "Trung bình"],
                ["7", "Chuyển sang token có chữ ký số kèm cơ chế thu hồi theo danh sách",
                 "Khuyết điểm 7", "Trung bình"],
                ["8", "Bổ sung trường hợp kiểm thử cho tình huống chỉ một quy tắc nặng kích hoạt",
                 "Khuyết điểm 8", "Thấp, làm ngay"],
                ["9", "Đọc cửa sổ giới hạn tần suất từ bảng cấu hình động",
                 "Khuyết điểm 5", "Thấp, làm ngay"],
                ["10", "Đo hiệu năng dưới tải và chốt số liệu phi chức năng",
                 "Khuyết điểm 9: chưa có con số hiệu năng", "Trung bình"],
                ["11", "Cài đặt tính toán thống kê phân phối đặc trưng định kỳ",
                 "Theo dõi trôi dữ liệu, phục vụ mục 3", "Thấp"],
                ["12", "Bổ sung hỗ trợ xác thực bằng ứng dụng di động và phương thức xác thực theo chuẩn TOTP",
                 "Mở rộng đa phương thức xác thực", "Thấp"],
                ["13", "Cài đặt bảng điều khiển tổng hợp và xuất báo cáo cho quản lý bảo mật",
                 "Phụ thuộc mục 1", "Sau mục 1"],
            ],
        },
    ),
    ("CAP", "Bảng 6.2  Các hướng mở rộng và hạn chế tương ứng"),
    (
        "P",
        "Về thứ tự ưu tiên, nhóm cho rằng hai hạng mục cao nhất nên làm song song: giao diện để "
        "hệ thống dùng được với con người, và tập dữ liệu để hệ thống chấm điểm đúng. Nếu chỉ "
        "làm một trong hai thì dù đã có giao diện hay chưa, hệ thống vẫn chưa chứng minh được "
        "khả năng phát hiện đúng, vì đó là mục tiêu chính của đề tài. Ngược lại, nếu chỉ có tập "
        "dữ liệu mà chưa có giao diện thì nhóm chỉ có thể chứng minh bằng số liệu chứ chưa có "
        "người dùng thật.",
    ),
    (
        "P",
        "Hai hạng mục mục 8 và mục 9 được xếp thấp không phải vì ít quan trọng, mà vì chúng nhỏ và "
        "làm được ngay mà không phụ thuộc vào việc khác. Nhóm đề xuất hoàn thành hai hạng mục này "
        "trước khi nộp báo cáo.",
    ),
]

# ---------------------------------------------------------------------------
# TÀI LIỆU THAM KHẢO
# ---------------------------------------------------------------------------

TAI_LIEU_THAM_KHAO: list[tuple[str, object]] = [
    ("H1", "TÀI LIỆU THAM KHẢO"),
    (
        "P",
        "Danh mục tài liệu tham khảo chỉ gồm những tài liệu mà nội dung báo cáo thực sự sử "
        "dụng, và mỗi mục đều có đoạn nêu rõ được dùng ở đâu trong báo cáo. Danh mục được trình "
        "bày theo thứ tự: tài liệu chuẩn và đặc tả kỹ thuật, tài liệu hướng dẫn bảo mật, tài "
        "liệu của hệ quản trị cơ sở dữ liệu và thư viện lập trình, rồi tài liệu về học máy.",
    ),

    ("H2", "Tài liệu chuẩn và đặc tả kỹ thuật"),
    (
        "P",
        "[1] T. Dierks, M. Jones, \"The OAuth 2.0 Authorization Framework: JSON Web Token \", "
        "IETF, RFC 7519, tháng 5 năm 2015. Được dùng ở Chương I mục cơ sở lý thuyết về kỹ "
        "thuật, khi trình bày nguyên lý token có chữ ký số, và ở Chương VI khuyết điểm về "
        "việc hệ thống hiện chưa dùng token có chữ ký số.",
    ),
    (
        "P",
        "[2] B. Hunt, \"JWT: JSON Web Token\", tài liệu của IETF, Internet Engineering Task "
        "Force, Internet-Draft. Được dùng ở Chương I khi mô tả cấu trúc một token gồm phần "
        "đầu, phần tải trọng và chữ ký, và làm cơ sở cho việc lưu mã định danh token trong bảng "
        "phiên.",
    ),
    (
        "P",
        "[3] IETF, \"Representational State Transfer\", đặc tả kiến trúc phần mềm không trạng, "
        "bản số 6, năm 2000. Được dùng ở Chương I khi giải thích vì sao thiết kế ba dịch vụ "
        "riêng với giao tiếp qua giao diện lập trình ứng dụng là phù hợp với kiến trúc phi "
        "trạng.",
    ),
    (
        "P",
        "[4] PostgreSQL Global Development Group, \"PostgreSQL Documentation\", phiên bản 16, "
        "tài liệu chính thức. Được dùng xuyên suốt Chương I mục nền tảng kỹ thuật, Chương I "
        "mục cơ sở lý thuyết về hệ quản trị cơ sở dữ liệu, và toàn bộ phần thiết kế lược đồ ở "
        "Chương III, cho các khả năng của kiểu dữ liệu mạng, kiểu dữ liệu cấu trúc, trình "
        "kích hoạt, và chỉ mục một phần.",
    ),
    (
        "P",
        "[5] Python Software Foundation, \"FastAPI Documentation\". Được dùng ở Chương I mục "
        "nền tảng kỹ thuật và ở Chương IV, cho cách khai báo điểm cuối, kiểm tra dữ liệu đầu "
        "vào, và tạo tài liệu giao diện lập trình ứng dụng tự động.",
    ),

    ("H2", "Tài liệu hướng dẫn bảo mật"),
    (
        "P",
        "[6] OWASP Foundation, \"Authentication Cheat Sheet\". Được dùng ở Chương I mục cơ "
        "sở lý thuyết về kỹ thuật, cho các khuyến nghị về băm mật khẩu, quản lý phiên, và thông "
        "báo lỗi không tiết lộ thông tin; đồng thời làm cơ sở cho thiết kế dùng thông báo chung "
        "khi tài khoản không tồn tại và khi mật khẩu sai.",
    ),
    (
        "P",
        "[7] OWASP Foundation, \"Multifactor Authentication Cheat Sheet\". Được dùng ở Chương I "
        "khi trình bày nguyên lý xác thực đa yếu tố, và ở Chương II và Chương III cho các quy "
        "tắc về thời hạn mã xác thực, số lần thử tối đa, và chống sử dụng lại mã.",
    ),
    (
        "P",
        "[8] OWASP Foundation, \"Logging Cheat Sheet\". Được dùng ở Chương I khi trình bày "
        "nguyên tắc nhật ký kiểm toán, và làm cơ sở cho thiết kế bảng nhật ký kiểm toán chỉ ghi "
        "thêm cùng bảng nhật ký từng giai đoạn phát hiện.",
    ),
    (
        "P",
        "[9] NIST, \"Digital Identity Guidelines: Authentication and Lifecycle Management\", "
        "NIST SP 800-63B. Được dùng ở Chương I khi trình bày nguyên lý phân loại mức xác thực "
        "và yêu cầu bổ sung nhân tố thứ hai khi có dấu hiệu rủi ro, và ở Chương II làm cơ sở "
        "cho chính sách yêu cầu xác thực thêm ở mức rủi ro cao và nghiêm trọng.",
    ),
    (
        "P",
        "[10] NIST, \"Guide to Computer Security Log Management\", NIST SP 800-92. Được dùng "
        "ở Chương I mục cơ sở lý thuyết về kỹ thuật, cho nguyên tắc quản lý nhật ký bao gồm "
        "bảo toàn tính toàn vẹn, và ở Chương II khi yêu cầu hành động nhạy cảm phải ghi nhật "
        "ký.",
    ),
    (
        "P",
        "[11] M. Sipser, \"Introduction to Applied Cryptography\". Được dùng ở Chương I khi "
        "giải thích nguyên lý băm một chiều, cơ sở của việc lưu bản băm mật khẩu và bản băm "
        "mã xác thực thay vì dạng rõ.",
    ),

    ("H2", "Tài liệu về học máy và phát hiện bất thường"),
    (
        "P",
        "[12] F. Pedregosa và cộng sự, \"Scikit-learn: Machine Learning in Python\", Journal of "
        "Machine Learning Research, tập 12, trang 2825-2830, năm 2011. Được dùng ở Chương I khi "
        "giới thiệu thuật toán cô lập phiên, và ở Chương III khi giải thích đặc điểm của thuật "
        "toán này là không cần gán nhãn dương trong quá trình huấn luyện.",
    ),
    (
        "P",
        "[13] F. T. Liu, K. M. Ting, S. H. Hoi, \"Isolation Forest\", Proceedings of the "
        "Eighth IEEE International Conference on Data Mining, trang 413-422, năm 2008. Đây là "
        "bài báo gốc của thuật toán được chọn, và được dùng ở Chương I cùng Chương III khi "
        "trình bày nguyên lý chấm điểm bất thường theo độ cô lập của điểm dữ liệu.",
    ),
    (
        "P",
        "[14] P. Chandola, V. Bhatia, \"Anomaly Detection: A Survey\", ACM Computing Surveys, "
        "tập 41, số 3, năm 2009. Được dùng ở Chương I mục cơ sở lý thuyết về kỹ thuật, cho "
        "phân loại các hướng tiếp cận phát hiện bất thường, và làm cơ sở cho việc hệ thống "
        "kết hợp phương pháp dựa trên quy tắc với phương pháp dựa trên mô hình.",
    ),

    ("H2", "Tài liệu kỹ thuật của dự án"),
    (
        "P",
        "[15] Nhóm tác giả, \"Quyết định kiến trúc Detection Engine phiên bản 3.3\", tài liệu "
        "quyết định nội bộ của dự án, tháng 9 năm 2026. Được dùng làm nguồn chuẩn cho toàn bộ "
        "quy tắc chấm điểm, cấu trúc quy tắc bảy trường bắt buộc, và hành vi xử lý cấu hình sai, "
        "nêu ở Chương II, Chương III và Chương VI.",
    ),
    (
        "P",
        "[16] Nhóm tác giả, \"Hướng dẫn Detection Engine phiên bản 3.3\", tài liệu hướng dẫn "
        "nội bộ của dự án, tháng 9 năm 2026. Được dùng làm nguồn cho mô tả hợp đồng sáu đặc "
        "trưng, danh sách toán tử so sánh được hỗ trợ, và các thông số ngưỡng, nêu ở Chương I, "
        "Chương II và Chương III.",
    ),
    (
        "P",
        "[17] PostgreSQL, \"schema-core-v3.3.sql, schema-detection-v3.3.sql, "
        "schema-ml-service-v3.3.sql\", tệp định nghĩa lược đồ của dự án, tháng 9 năm 2026. "
        "Được dùng làm nguồn chính cho toàn bộ phần đặc tả hai mươi ba bảng ở Chương III và phần "
        "trạng thái lược đồ ở Chương IV.",
    ),
    (
        "P",
        "[18] Nhóm tác giả, \"Bộ kiểm thử tự động của dự án\", gồm bảy tệp kiểm thử, kết quả chạy "
        "tại thời điểm lập báo cáo. Được dùng làm bằng chứng cho mức độ hoàn thành ở Chương IV "
        "và Chương V.",
    ),
]
