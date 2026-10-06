"""Nội dung Chương I - TỔNG QUAN và Chương II - PHÂN TÍCH NỘI DUNG, YÊU CẦU."""

from __future__ import annotations

CHUONG_I: list[tuple[str, object]] = [
    # ---------------------------------------------------------------- I.1
    ("H1", "CHƯƠNG I. TỔNG QUAN"),
    ("H2", "Giới thiệu đề tài"),

    ("H3", "Mục tiêu của đề tài"),
    (
        "P",
        "Đăng nhập là cửa vào duy nhất của một hệ thống thông tin, nhưng cũng là "
        "bề mặt tấn công rộng nhất. Với một tài khoản bị lộ mật khẩu, kẻ tấn công "
        "thường đăng nhập thành công trước khi chủ tài khoản phát hiện ra. Các biện "
        "pháp bảo vệ tĩnh như độ dài mật khẩu hay chính sách phức tạp đều không "
        "phát hiện được tình huống này, vì mật khẩu lúc đó hoàn toàn chính xác. "
        "Vấn đề không nằm ở chất lượng mật khẩu, mà nằm ở bối cảnh của lần đăng "
        "nhập đó: thời điểm, địa chỉ mạng, thiết bị, tần suất thất bại trước đó và "
        "sự lệch so với thói quen của chính người dùng đó.",
    ),
    (
        "P",
        "Đề tài xây dựng một hệ thống phát hiện và cảnh báo đăng nhập bất thường, "
        "gồm ba thành phần dịch vụ tách biệt: Core App xác thực người dùng, "
        "Detection Engine chấm điểm rủi ro, ML Service suy luận mức bất thường. "
        "Hệ thống không chỉ ghi nhận sự kiện đăng nhập mà còn chấm điểm theo chính "
        "sách, phân loại mức rủi ro, sinh cảnh báo kèm bằng chứng, và yêu cầu hệ "
        "thống xác thực phản ứng tương ứng.",
    ),
    ("H4", "Mục tiêu nghiệp vụ"),
    ("P", "Mục tiêu nghiệp vụ của hệ thống gồm bốn nhóm:"),
    (
        "BUL",
        "Ghi nhận đầy đủ mọi lần đăng nhập, kể cả lần thất bại, kèm địa chỉ IP, "
        "thiết bị và thời điểm, để có thể điều tra về sau.",
    ),
    (
        "BUL",
        "Đánh giá rủi ro của mỗi lần đăng nhập dựa trên hành vi quan sát được và "
        "mô hình học máy, thay vì chỉ dựa vào việc mật khẩu có đúng hay không.",
    ),
    (
        "BUL",
        "Tạo cảnh báo có đủ bằng chứng khi rủi ro vượt ngưỡng, chuyển tới phân "
        "viên Trung tâm Giám sát An ninh (SOC) để con người quyết định.",
    ),
    (
        "BUL",
        "Áp dụng biện pháp bảo vệ tức thời: bắt xác thực đa yếu tố trước khi cấp "
        "token, thu hồi phiên đang hoạt động khi rủi ro ở mức nghiêm trọng.",
    ),
    ("H4", "Mục tiêu kỹ thuật"),
    ("P", "Mục tiêu kỹ thuật cụ thể hoá bằng các yêu cầu đo được:"),
    (
        "BUL",
        "Cổng kiểm duyệt rủi ro đồng bộ đặt sau xác thực mật khẩu và trước khi "
        "tạo phiên, sao cho lần đăng nhập rủi ro cao chưa kịp sinh ra token "
        "hợp lệ nào.",
    ),
    (
        "BUL",
        "Cơ chế chấm điểm bất biến theo miền giá trị [0; 1], để công thức gộp "
        "điểm luôn có ý nghĩa bất kể có bao nhiêu quy tắc được bật.",
    ),
    (
        "BUL",
        "Suy giảm êm: khi ML Service không trả lời, hệ thống vẫn chấm được bằng "
        "luật và vẫn ghi được cảnh báo.",
    ),
    (
        "BUL",
        "Mọi sự kiện đăng nhập xử lý idempotent theo khoá event, nên giao lại cùng "
        "sự kiện không sinh bản ghi trùng.",
    ),
    (
        "BUL",
        "Mọi thao tác của con người đều để lại dấu vết kiểm toán đủ để trả lời "
        "câu hỏi ai đã làm gì, vào lúc nào, trên dữ liệu nào.",
    ),
    ("H4", "Hỗ trợ SOC như thế nào"),
    (
        "P",
        "Detection Engine chỉ đưa ra một mức rủi ro và kèm bằng chứng, không tự "
        "kết luận người dùng là kẻ tấn công. Việc phân loại cảnh báo là hợp lệ, "
        "báo nhầm hay cần leo thang thuộc về con người, vì chỉ người mới biết "
        "ngữ cảnh công việc: tài khoản vừa đi công tác nước ngoài, ca đêm hệ thống "
        "chạy tác vụ định kỳ, thay đổi thiết bị sau nâng cấp. Hệ thống cung cấp "
        "cho SOC ba thứ: danh sách cảnh báo đã lọc theo mức rủi ro và thời gian; "
        "hồ sơ điều tra gộp bốn nguồn dữ liệu (cảnh báo, lần đăng nhập, kết quả "
        "chấm điểm, nhật ký từng giai đoạn); và bốn hành động bảo vệ có thể thực "
        "thi kèm lý do. Mọi thao tác của phân viên đều được ghi vào dòng thời gian "
        "của cảnh báo, nên người thứ ba cũng truy vết lại được.",
    ),
    ("H4", "Đầu ra mong muốn của hệ thống"),
    ("P", "Để kiểm chứng, hệ thống phải tạo ra được các đầu ra sau:"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.4, 4.0, 2.0],
            "header": ["Đầu ra", "Nơi lưu", "Dùng để kiểm chứng"],
            "rows": [
                [
                    "Bản ghi lần đăng nhập",
                    "login_attempts",
                    "Mỗi lần gọi endpoint đăng nhập tạo đúng một dòng",
                ],
                [
                    "Kết quả đánh giá rủi ro",
                    "risk_assessments",
                    "Mỗi lần đăng nhập có tối đa một dòng đánh giá",
                ],
                [
                    "Cảnh báo có bằng chứng",
                    "alerts",
                    "Tồn tại cảnh báo khi và chỉ khi mức rủi ro là high hoặc critical",
                ],
                [
                    "Dấu vết từng giai đoạn chấm điểm",
                    "detection_logs",
                    "Có đủ bốn nhóm giai đoạn cho mỗi lần chấm",
                ],
                [
                    "Phiên đăng nhập",
                    "sessions",
                    "Phiên bị thu hồi mất hiệu lực ở lần gọi kế tiếp",
                ],
                [
                    "Dòng thời gian cảnh báo",
                    "alert_timeline",
                    "Mỗi lần chuyển trạng thái có một dòng ghi lại người thực hiện",
                ],
                [
                    "Nhật ký kiểm toán",
                    "audit_logs",
                    "Truy vết được thao tác quản trị và thu hồi phiên",
                ],
            ],
        },
    ),
    ("CAP", "Bảng 1.1  Các đầu ra bắt buộc của hệ thống và nơi lưu trữ"),

    # ---------------------------------------------------------------- I.2
    ("H3", "Phạm vi áp dụng"),
    ("H4", "Bối cảnh áp dụng"),
    (
        "P",
        "Hệ thống được thiết kế cho các ứng dụng web có hệ thống tài khoản nội bộ: "
        "ứng dụng doanh nghiệp, hệ thống quản lý nhân sự, cổng thông tin nội bộ, "
        "và các hệ thống mà mỗi người dùng đều được phân biệt bằng tài khoản. "
        "Đây là bài toán khác với bảo vệ một website công cộng không có đăng nhập, "
        "và cũng khác với hệ thống chỉ có tài khoản dùng chung cho một nhóm nhỏ.",
    ),
    (
        "P",
        "Ranh giới quan trọng là hệ thống có thể nhận diện người dùng sau khi họ "
        "đăng nhập. Khi đã có danh tính, hệ thống mới lưu được lịch sử hành vi để "
        "so sánh, và mới có ý nghĩa khi nói rằng một lần đăng nhập là bất thường. "
        "Hệ thống không đứng trước tường lửa của toàn bộ hạ tầng, mà nằm ngay sau "
        "lớp xác thực, canh giữ lớp đó.",
    ),
    ("H4", "Hệ thống thuộc lớp nào"),
    (
        "P",
        "Về mặt kiến trúc, hệ thống nằm ở lớp ứng dụng, cụ thể là lớp nghiệp vụ "
        "giám sát an ninh, đứng song song với lớp xác thực chứ không thay thế nó. "
        "Hệ thống nhận hai luồng thông tin: luồng đồng bộ trong yêu cầu đăng nhập "
        "(cổng kiểm duyệt trước khi cấp token) và luồng bất đồng bộ sau đó (ghi nhận "
        "sự kiện, chấm điểm, sinh cảnh báo). Về mặt hạ tầng, hệ thống là một cụm "
        "dịch vụ web nội bộ giao tiếp qua HTTP, mỗi dịch vụ có cơ sở dữ liệu riêng.",
    ),
    ("H4", "Đối tượng được bảo vệ"),
    (
        "P",
        "Đối tượng được bảo vệ trực tiếp là tài khoản người dùng và các phiên đăng "
        "nhập của tài khoản đó. Gián tiếp, hệ thống bảo vệ toàn bộ dữ liệu mà tài "
        "khoản đó truy cập được, vì mọi tài khoản bị chiếm đoạt đều là một lỗ hổng "
        "đối với dữ liệu phía sau nó.",
    ),
    ("H4", "Ai vận hành hệ thống"),
    (
        "P",
        "Hệ thống có bốn nhóm người dùng với trách nhiệm khác nhau. Người dùng cuối "
        "tự quản lý phiên và thiết bị tin cậy của mình. Phân viên SOC làm việc "
        "hằng ngày với danh sách cảnh báo, đây là nhóm sử dụng hệ thống nhiều nhất. "
        "Quản trị viên bảo mật thiết lập chính sách chấm điểm, quản lý tài khoản "
        "và quyền truy cập. Quản lý bảo mật giám sát chỉ số tổng hợp và phê duyệt "
        "các trường hợp leo thang. Chi tiết về phạm vi quyền của từng nhóm được "
        "trình bày ở Chương II.",
    ),
    ("H4", "Quy mô áp dụng"),
    (
        "P",
        "Thiết kế hiện tại hướng tới quy mô vừa và nhỏ của một tổ chức đơn vị, cụ "
        "thể là trong doanh nghiệp có vài trăm đến vài nghìn tài khoản, với số lần "
        "đăng nhập tính bằng nghìn mỗi ngày. Các cơ chế đã hiện thực phù hợp với "
        "quy mô này: chấm điểm đồng bộ trước khi cấp token có thời gian chờ cố "
        "định, tra cứu đặc trưng dựa trên lịch sử gần đây, và bảng cảnh báo có "
        "chỉ mục theo trạng thái, mức rủi ro và thời gian tạo.",
    ),
    (
        "P",
        "Với tổ chức lớn hơn, phần cần mở rộng là hạ tầng và cơ chế đồng bộ dữ "
        "liệu, không phải thuật toán chấm điểm. Cụ thể, tần suất ghi sự kiện đăng "
        "nhập và khối lượng dữ liệu lịch sử sẽ đòi hỏi cơ chế xử lý bất đồng bộ "
        "và phân vùng dữ liệu theo thời gian. Báo cáo này chưa có số liệu đo được "
        "về hiệu năng, vì vậy các mục tiêu định lượng cho quy mô lớn chưa được "
        "cam kết.",
    ),
    ("NOTE", "[CẦN NHÓM XÁC NHẬN QUY MÔ ĐỊNH LƯỢNG]"),
    (
        "P",
        "Nhóm chưa có số liệu thực tế về số tài khoản, số yêu cầu đăng nhập mỗi "
        "ngày, hay số cảnh báo trung bình mỗi tuần. Các con số trên là quy mô "
        "thiết kế dự kiến theo định hướng của đề tài, chưa phải số liệu đo. Khi "
        "triển khai và đo tải thực tế, cần cập nhật lại mục này cùng các tiêu chí "
        "chất lượng tương ứng ở Chương II.",
    ),
    ("H4", "Phân biệt ba loại phạm vi"),
    ("H4", "a) Phạm vi nghiệp vụ"),
    (
        "BUL",
        "Xác thực người dùng bằng tên đăng nhập và mật khẩu, có xác thực đa yếu tố "
        "khi cần thiết.",
    ),
    ("BUL",
     "Ghi nhận mọi lần đăng nhập cùng ngữ cảnh kỹ thuật của lần đó."),
    ("BUL",
     "Chấm điểm rủi ro theo chính sách đang kích hoạt, kết hợp luật và mô hình."),
    ("BUL",
     "Sinh cảnh báo kèm bằng chứng khi vượt ngưỡng, và giao cho phân viên SOC."),
    ("BUL",
     "Quản lý vòng đời cảnh báo: tiếp nhận, leo thang, kết luận, báo nhầm."),
    ("BUL",
     "Quản lý phiên của chính người dùng và thiết bị tin cậy."),
    ("BUL",
     "Thực thi hành động bảo vệ: bắt xác thực lại, thu hồi phiên, khoá tài khoản."),
    ("BUL",
     "Ghi nhật ký kiểm toán cho mọi thao tác quản trị và thao tác nhạy cảm."),
    ("H4", "b) Phạm vi kỹ thuật"),
    ("P",
        "Phạm vi kỹ thuật của đồ án gồm ba dịch vụ: Core App phục vụ xác thực và "
        "quản lý phiên; Detection Engine phục vụ chấm điểm và quản lý cảnh báo; "
        "ML Service phục vụ suy luận mức bất thường. Mỗi dịch vụ có cơ sở dữ liệu "
        "riêng, giao tiếp qua HTTP với khoá dùng chung, và hợp đồng định dạng dữ "
        "liệu thống nhất cho sáu đặc trưng đầu vào cùng cấu trúc phản hồi điểm.",
    ),
    ("H4", "c) Những gì không thuộc phạm vi"),
    ("P",
        "Các hạng mục sau được nêu rõ để tránh hiểu nhầm về phạm vi bàn giao:"),
    ("TABLE",
        {
            "caption": None,
            "widths": [1.6, 5.8],
            "header": ["Hạng mục", "Lý do không thuộc phạm vi"],
            "rows": [
                [
                    "Huấn luyện mô hình máy học",
                    "Mô hình chưa được huấn luyện trên tập dữ liệu thực của tổ chức. "
                    "Đồ án dùng một mô hình nền theo quy tắc ghi rõ trong mã nguồn, "
                    "thay cho mô hình Isolation Forest đã huấn luyện.",
                ],
                [
                    "Giao diện người dùng",
                    "Đồ án tập trung phân tích và thiết kế hệ thống. Chưa có bản "
                    "giao diện web hoàn chỉnh để đưa vào báo cáo, mục này được nêu "
                    "rõ ở mục Thiết kế giao diện.",
                ],
                [
                    "Cơ chế hàng đợi phát sự kiện",
                    "Bảng outbox_events đã được thiết kế và khai báo trong lược đồ, "
                    "nhưng chưa có chương trình theo dõi ghi và chuyển sự kiện. Chi "
                    "tiết trạng thái nợ kỹ thuật được ghi ở Chương VI.",
                ],
                [
                    "Báo cáo thống kê xuất ra tệp",
                    "Chỉ có số liệu bảng điều khiển dạng số. Chưa có chức năng kết "
                    "xuất báo cáo định kỳ.",
                ],
                [
                    "Tích hợp với hệ thống bên thứ ba",
                    "Chưa liên kết với dịch vụ danh bạ ngoài, hệ thống thông báo "
                    "tin nhắn, hay dịch vụ tra cứu uy tín địa chỉ IP.",
                ],
                [
                    "Bảo vệ tài khoản phía máy chủ lõi",
                    "Mỗi dịch vụ có cơ sở dữ liệu riêng nên không thể triển khai khóa "
                    "ngoại xuyên cơ sở dữ liệu; các quan hệ đó được kiểm tra ở tầng "
                    "ứng dụng thông qua các điểm cuối nội bộ.",
                ],
                [
                    "Ứng phó sự cố và khôi phục thảm hoạ",
                    "Chưa có quy trình sao lưu định kỳ, chính sách lưu trữ bản sao "
                    "lưu, và bài kiểm tra khôi phục tương ứng.",
                ],
            ],
        },
    ),
    ("CAP", "Bảng 1.2  Các hạng mục ngoài phạm vi của đồ án"),
    ("NOTE",
     "Lưu ý về tính trung thực: những hạng mục ở bảng trên được đánh dấu là ngoài "
     "phạm vi dựa trên việc đối chiếu trực tiếp với mã nguồn và tệp cấu hình của "
     "dự án. Những hạng mục đã thiết kế nhưng chưa có bằng chứng chạy thật được "
     "phân biệch rõ tại Chương IV và Chương V."),

    # ---------------------------------------------------------------- I.3
    ("H3", "Nền tảng kỹ thuật"),
    (
        "P",
        "Mục này trình bày công nghệ đã xác minh trực tiếp từ mã nguồn và tệp cấu "
        "hình của dự án. Mỗi công nghệ đều được ghi kèm vị trí sử dụng cụ thể.",
    ),
    ("TABLE",
        {
            "caption": None,
            "widths": [1.5, 2.1, 3.8],
            "header": ["Thành phần", "Công nghệ", "Vị trí sử dụng trong hệ thống"],
            "rows": [
                [
                    "Ngôn ngữ lập trình",
                    "Python 3.11",
                    "Toàn bộ ba dịch vụ viết bằng Python, khai báo trong tệp cấu "
                    "hình đóng gói.",
                ],
                [
                    "Khung dịch vụ web",
                    "FastAPI",
                    "Xây dựng các điểm cuối HTTP cho cả ba dịch vụ.",
                ],
                    [
                    "Máy chủ ứng dụng",
                    "Uvicorn",
                    "Chạy ứng dụng FastAPI trong gói đóng gói.",
                ],
                [
                    "Cơ sở dữ liệu",
                    "PostgreSQL",
                    "Ba cơ sở dữ liệu độc lập, mỗi dịch vụ dùng một cơ sở dữ liệu.",
                ],
                [
                    "Công cụ ánh xạ đối tượng quan hệ",
                    "SQLAlchemy phiên bản 2",
                    "Định nghĩa 23 lớp thực thể ánh xạ đúng với 23 bảng trong lược đồ.",
                ],
                [
                    "Trình điều khiển cơ sở dữ liệu",
                    "psycopg phiên bản 3",
                    "Kết nối tới PostgreSQL.",
                ],
                [
                    "Kiểm tra dữ liệu đầu vào",
                    "Pydantic phiên bản 2",
                    "Xác thựnh và định nghĩa lược đồ dữ liệu cho mọi điểm cuối.",
                ],
                [
                    "Giao tiếp HTTP giữa các dịch vụ",
                    "HTTPX",
                    "Gọi cổng kiểm duyệt trước token, gọi dịch vụ máy học, và gửi "
                    "hành động bảo vệ ngược lại.",
                ],
                [
                    "Băm mật khẩu",
                    "Argon2id",
                    "Băm mật khẩu người dùng và mã xác thực một lần.",
                ],
                [
                    "Sinh token ngẫu nhiên",
                    "secrets của thư viện chuẩn",
                    "Sinh access token, refresh token và mã xác thực dùng một lần.",
                ],
                [
                    "Băm token",
                    "SHA-256",
                    "Lưu bản băm của token trong bảng phiên, không lưu token dạng rõ.",
                ],
                [
                    "Mô hình máy học",
                    "Mô hình nền theo quy tắc",
                    "ML Service hiện dùng mô hình nền theo quy tắc, chưa phải mô hình "
                    "Isolation Forest đã huấn luyện. Chi tiết ở mục Cơ sở lý "
                    "thuyết và Chương VI.",
                ],
                [
                    "Kiểm thử tự động",
                    "pytest với pytest-asyncio",
                    "Bộ kiểm thử cho xác thực, chấm điểm, suy luận, hành động bảo vệ "
                    "và tính nhất quán lược đồ.",
                ],
                [
                    "Đóng gói",
                    "Docker",
                    "Định nghĩa ảnh chạy ứng dụng, có kiểm tra sức khoẻ dịch vụ.",
                ],
            ],
        },
    ),
    ("CAP", "Bảng 1.3  Nền tảng công nghệ đã xác minh từ dự án"),
    ("H4", "Các thành phần nghiệp vụ"),
    (
        "P",
        "Ngoài công nghệ nền, hệ thống có ba thành phần nghiệp vụ do nhóm thiết kế:",
    ),
    ("BUL",
     "Core App (cổng 8000): xác thực, xác thực đa yếu tố, quản lý phiên, thiết bị "
     "tin cậy, nhật ký kiểm toán, và các điểm cuối nội bộ nhận hành động bảo vệ."),
    ("BUL",
     "Detection Engine (cổng 8001): chấm điểm luật, gọi suy luận, gộp điểm, xếp "
     "mức rủi ro, tạo cảnh báo, quản lý chính sách và cung cấp số liệu bảng điều "
     "khiển."),
    ("BUL",
     "ML Service (cổng 8002): nhận sáu đặc trưng, trả điểm bất thường đã chuẩn hoá, "
     "mã lý do và phiên bản mô hình."),
    ("H4", "Cơ chế truyền sự kiện"),
    (
        "P",
        "Phiên bản thiết kế ban đầu dự kiến mô hình hộp thư ra (outbox) với chương "
        "trình theo dõi gom sự kiện. Thiết kế hiện tại đã thay phần này bằng hai "
        "kênh trực tiếp hơn: một kênh đồng bộ trong yêu cầu đăng nhập để kiểm duyệt "
        "trước khi cấp token, và một kênh ghi trực tiếp bản ghi lần đăng nhập kèm "
        "cờ trạng thái chờ xử lý. Bảng outbox_events vẫn còn trong lược đồ cơ sở dữ "
        "liệu nhưng chưa được mã nguồn sử dụng.",
    ),
    ("H4", "Xác thực và quản lý phiên"),
    (
        "P",
        "Phiên bản thiết kế mô tả cơ chế phát hành JSON Web Token (JWT). Mã nguồn hiện "
        "tại phát hành chuỗi ngẫu nhiên 32 byte, lưu bản băm SHA-256 trong bảng phiên "
        "kèm định danh token và thời hạn một giờ. Trường token_jti đã được khai báo "
        "trong lược độ để sẵn sàng cho cơ chế chuẩn hoá, nhưng thư viện JWT chưa có "
        "trong danh sách phụ thuộc. Báo cáo này mô tả đúng trạng thái mã nguồn, đồng "
        "thời ghi nhận sự khác biệt này là nợ kỹ thuật cần khắc phục.",
    ),
    ("H4", "Công nghệ triển khai"),
    (
        "P",
        "Dự án có tệp định nghĩa ảnh Docker chạy ứng dụng trên nền Python 3.11 rút "
        "gọn, kèm kiểm tra sức khoẻ dịch vụ theo chu kỳ. Chưa có tệp định nghĩa toàn "
        "bộ cụm dịch vụ trong dự án.",
    ),
    (
        "P",
        "Hình dưới đây ghép các thành phần đã xác minh ở trên thành một sơ đồ khối "
        "duy nhất, cho thấy rõ luồng dữ liệu từ người dùng đến cơ sở dữ liệu và trở "
        "lại. Sơ đồ cũng chỉ ra hai vị trí mà hệ thống giao tiếp với bên ngoài: cổng "
        "đăng nhập của Core App và cổng nội bộ nhận yêu cầu chấm điểm của Detection "
        "Engine. Mọi thành phần còn lại đều nằm trong mạng nội bộ.",
    ),
    ("IMG", {"key": "arch", "width_cm": 15.5, "caption": None}),
    ("CAP", "Hình 1.1  Kiến trúc tổng thể của hệ thống theo ba lớp và ba cơ sở dữ liệu"),
    (
        "P",
        "Đọc sơ đồ theo ba lớp: lớp trình bày tiếp nhận thao tác của bốn nhóm người "
        "dùng; lớp ứng dụng thực hiện xác thực, xác thực đa yếu tố, quản lý phiên, "
        "phân quyền và ghi nhật ký kiểm toán; lớp phát hiện chấm điểm và lớp suy luận "
        "tính điểm bất thường. Ba cơ sở dữ liệu nằm ở đáy sơ đồ, mỗi cơ sở dữ liệu "
        "phục vụ một phạm vi nghiệp vụ riêng. Chi tiết về cơ chế ghi sự kiện, chấm "
        "điểm và gộp điểm được trình bày ở Chương II và Chương III.",
    ),
    ("NOTE",
     "[CẦN XÁC NHẬN CÔNG NGHỆ] — Hai hạng mục cần nhóm chốt trước khi nghiệm thu: "
     "(1) có triển khai dịch vụ gửi thư điện tử và tin nhắn ngắn cho mã xác thực hay "
     "không, vì mã nguồn hiện còn ghi chú yêu cầu tích hợp; (2) có chủ định dùng "
     "cơ chế hộp thư ra cho luồng sự kiện bất đồng bộ trong phiên bản tiếp theo hay "
     "không, vì bảng tương ứng đã có trong lược đồ nhưng chưa có chương trình sử dụng."),

    # ================================================================ I.2
    ("H2", "Cơ sở lý thuyết"),
    (
        "P",
        "Mục này chỉ trình bày những kiến thức mà hệ thống thực sự dùng. Mỗi tiểu mục "
        "kết thúc bằng câu trả lời cho câu hỏi kỹ thuật cốt lõi: kỹ thuật đó được "
        "dùng ở đâu trong hệ thống của nhóm.",
    ),
    ("H3", "A. Cơ sở lý thuyết về kỹ thuật"),
    ("H4", "1. Xác thực và xác thực đa yếu tố"),
    (
        "P",
        "Xác thực là kiểm tra danh tính người dùng trước khi cấp quyền truy cập. "
        "Xác thực đa yếu tố bổ sung yếu tố thứ hai trở đi ngoài mật khẩu, chẳng hạn "
        "mã dùng một lần gửi qua thư điện tử, mã theo thời gian sinh ra từ ứng dụng "
        "xác thực, hoặc phê duyệt trên thiết bị. Yếu tố thứ hai có điểm yếu riêng: "
        "nó chỉ mạnh khi kẻ tấn công không có quyền truy cập kênh truyền yếu tố đó.",
    ),
    ("P",
        "Trong hệ thống, xác thực được thực hiện tại điểm cuối đăng nhập bằng cách đối "
        "chiếu mật khẩu sau khi băm bằng Argon2id. Xác thực đa yếu tố được kích hoạt "
        "theo hai đường: quản trị viên đặt cờ bắt buộc cho tài khoản, hoặc cổng kiểm "
        "duyệt rủi ro phát hiện lần đăng nhập ở mức cao hoặc nghiêm trọng và đặt cờ "
        "xác thực một lần. Mã xác thực dùng một lần gồm sáu chữ số, sinh bằng bộ sinh "
        "số ngẫu nhiên an toàn, băm trước khi lưu, và hết hạn sau năm phút."),
    ("H4", "2. Phân quyền theo vai trò"),
    (
        "P",
        "Phân quyền theo vai trò gán quyền cho nhóm vai trò thay vì cho từng người. "
        "Một tài khoản có thể mang nhiều vai trò, và mỗi vai trò mở một tập chức năng "
        "riêng. Cách này giảm việc cấp quyền tuỳ ý, nhưng đòi hỏi phải thiết kế cẩn "
        "thật danh sách quyền của từng vai trò, vì một quyền gán sai là lỗ hổng.",
    ),
    ("P",
        "Hệ thống khai báo bốn vai trò trong bảng vai trò: người dùng, quản trị viên "
        "bảo mật, phân viên SOC, và quản lý bảo mật. Bảng trung gian gán vai trò cho "
        "tài khoản, có ràng buộc duy nhất trên cặp tài khoản và vai trò, và lưu lại "
        "ai gán và khi nào gán. Tuy nhiên, tại thời điểm báo cáo, phần lớn các điểm "
        "cuối quản lý cảnh báo chỉ kiểm tra khoá dịch vụ nội bộ chứ chưa phân tích "
        "vai trò người gọi. Đây là hạng mục nợ kỹ thuật được nêu thẳng ở Chương VI."),
    ("H4", "3. Phiên đăng nhập và token"),
    (
        "P",
        "Phiên đăng nhập là khoảng thời gian người dùng được coi là đã xác thực. Mỗi "
        "lần đăng nhập tạo một bản ghi phiên chứa mã định danh token, bản băm token, "
        "địa chỉ IP, thông tin thiết bị và thời hạn. Token được làm mới bằng cách xoay "
        "mã, và thu hồi phiên bằng cách đánh dấu thời điểm thu hồi.",
    ),
    ("P",
        "Hệ thống lưu bản băm SHA-256 của token chứ không lưu token dạng rõ, nên kẻ đọc "
        "được cơ sở dữ liệu cũng không dùng lại được token. Điểm kiểm soát thu hồi là "
        "cột thời điểm thu hồi: mọi cơ chế thu hồi, dù do người dùng, quản trị viên "
        "hay Detection Engine yêu cầu, đều dẫn về cùng một cập nhật là đặt cột này. "
        "Mọi truy vấn xác thực đều kèm điều kiện phiên chưa bị thu hồi, nên một phiên "
        "mất hiệu lực ngay ở lần gọi kế tiếp chứ không phải chờ hết hạn."),
    ("H4", "4. Phát hiện đăng nhập bất thường theo quy tắc"),
    (
        "P",
        "Phát hiện theo quy tắc so sánh thuộc tính của sự kiện hiện tại với điều kiện "
        "do người quản trị định nghĩa. Mỗi quy tắc gồm bảy trường bắt buộc: tên để "
        "hiển thị, trường đặc trưng được đối chiếu, toán tử so sánh, giá trị, trọng "
        "số biểu thị độ tin cậy của quy tắc, điểm biểu thị mức nghiêm trọng khi quy "
        "tắc chạy, và cờ bật tắt. Điểm khác biệt so với cách tính tổng đơn giản là "
        "chia cho tổng trọng số của tất cả quy tắc đang bật, kể cả quy tắc không chạy.",
    ),
    ("P",
        "Cách chia đó giữ điểm quy tắc luôn trong khoảng [0; 1] bất kể bật bao nhiêu "
        "quy tắc, nhờ đó công thức gộp điểm với điểm máy học vẫn có ý nghĩa. Trong hệ "
        "thống, các quy tắc nằm trong cột JSONB của bảng chính sách, quản trị viên "
        "có thể tạo và kích hoạt chính sách mà không phải sửa mã nguồn. Quy tắc cấu "
        "hình sai bị bỏ qua và ghi nhật ký, không làm hỏng toàn bộ kết quả chấm."),
    ("H4", "5. Điểm bất thường bằng máy học"),
    (
        "P",
        "Cách tiếp cận học không giám sát tìm ra cấu trúc bất thường trong dữ liệu mà "
        "không cần gán nhãn trước. Thuật toán Isolation Forest phổ biến vì đặc trưng: "
        "xây cây phân tách ngẫu nhiên trên tập dữ liệu, và điểm cách ly càng thấp thì "
        "mẫu đó càng hiếm, tức càng bất thường. Điểm thu được chuẩn hoá về khoảng "
        "[0; 1], trong đó không là giá trị bình thường nhất.",
    ),
    ("P",
        "Trong hệ thống, Detection Engine tạo sáu đặc trưng từ lịch sử đăng nhập rồi gửi "
        "sang ML Service. Cần lưu ý rằng điểm bất thường không phải xác suất tấn công: "
        "một lần đăng nhập có thể bất thường mà hoàn toàn lành tính, ví dụ người dùng "
        "đi công tác nước ngoài. Vì vậy hệ thống dùng điểm này như một tín hiệu để nâng "
        "mức rủi ro, chứ không dùng để tự quyết định. Tại thời điểm báo cáo, ML "
        "Service dùng mô hình nền theo quy tắc, chưa phải Isolation Forest đã huấn "
        "luyện trên dữ liệu thực."),
    ("H4", "6. Chấm điểm rủi ro"),
    (
        "P",
        "Chấm điểm rủi ro là phép gộp nhiều tín hiệu thành một số duy nhất trong "
        "khoảng [0; 1], rồi chia khoảng số đó thành các mức để quyết định hành động. "
        "Điểm mấu chốt là trọng số phải cộng lại bằng một, và khi một nguồn tín hiệu "
        "vắng mặt thì phải quyết định rõ sẽ xử lý thế nào.",
    ),
    (
        "P",
        "Hệ thống dùng trọng số bốn phần mười cho điểm quy tắc và sáu phần mười cho "
        "điểm máy học, rồi chia khoảng thành bốn mức theo ngưỡng. Khi máy học không "
        "trả lời, hệ thống dùng nguyên điểm quy tắc mà không chia lại trọng số. "
        "Hệ quả có chủ ý: khi mất tín hiệu máy học, tổng điểm thấp hơn, nên hệ thống "
        "thận trọng hơn thay vì lạc quan hơn."),
    ("H4", "7. Xử lý sự kiện bất đồng bộ và tính lũy đẳng"),
    (
        "P",
        "Xử lý bất đồng bộ đặt công việc nặng ra khỏi luồng yêu cầu của người dùng, "
        "để phản hồi không phụ thuộc vào thời gian chấm điểm. Điểm yếu là tính lũy "
        "đẳng: nếu sự kiện được giao lại, hệ thống có thể xử lý hai lần và sinh ra "
        "hai bản ghi. Cách chống là gắn mỗi sự kiện một khoá, và kiểm tra khoá đó "
        "trước khi xử lý.",
    ),
    (
        "P",
        "Hệ thống dùng mã định danh sự kiện làm khoá lũy đẳng: Detection Engine kiểm "
        "tra sự kiện đã tồn tại chưa trước khi chấm. Các hành động bảo vệ cũng có khoá "
        "lũy đẳng riêng, nên giao lại sau thời gian chờ quá hạn là thao tác rỗng chứ "
        "không phải thu hồi phiên lần thứ hai."),
    ("H4", "8. Nhật ký kiểm toán"),
    (
        "P",
        "Nhật ký kiểm toán ghi lại ai đã làm gì, vào lúc nào, trên tài nguyên nào, với "
        "trạng thái trước và sau. Khác với nhật ký kỹ thuật thường xoay vòng để tiết kiệm "
        "dung lượng, nhật ký kiểm toán có tính bất biến và phải truy vết được nhiều "
        "năm.",
    ),
    (
        "P",
        "Hệ thống có hai lớp nhật ký phục vụ hai mục đích khác nhau. Bảng nhật ký kiểm "
        "toán thuộc Core App ghi thao tác quản trị và thao tác nhạy cảm như thu hồi "
        "phiên. Bảng nhật ký phát hiện thuộc Detection Engine ghi dấu vết từng giai "
        "đoạn chấm điểm, cho phép trả lời câu hỏi vì sao một lần đăng nhập nhận được "
        "mức rủi ro đó. Bảng dòng thời gian cảnh báo ghi thao tác của phân viên SOC "
        "trên từng cảnh báo."),
    ("H4", "9. Vòng đời cảnh báo"),
    (
        "P",
        "Vòng đời cảnh báo mô tả các trạng thái mà một cảnh báo đi qua và ai được "
        "phép thực hiện chuyển trạng thái. Thiết kế tốt phải phân biệt được lúc cảnh "
        "báo chờ xem với lúc đã có người nhận trách nhiệm, và phải ghi lại mọi bước "
        "chuyển để sau này tái hiện được diễn biến.",
    ),
    (
        "P",
        "Hệ thống dùng bốn trạng thái: mở, đã tiếp nhận, đã kết luận, và báo nhầm. "
        "Mọi lần chuyển trạng thái ghi một dòng vào bảng dòng thời gian kèm giá trị "
        "cũ, giá trị mới, người thực hiện và ghi chú. Riêng trạng thái báo nhầm được "
        "tách ra vì nó mang thông tin phục vụ hiệu chỉnh chính sách, không phải thông "
        "tin phục vụ xử lý sự cố."),
    ("H4", "10. Suy giảm êm"),
    (
        "P",
        "Suy giảm êm là nguyên tắc thiết kế để hệ thống vẫn hoạt động ở mức chấp nhận "
        "được khi một thành phần hỏng, thay vì sập hoàn toàn. Với hệ thống bảo mật, "
        "nguyên tắc này đặt ra câu hỏi thú vị: nên đóng cửa hay mở cửa khi công cụ "
        "giám sát hỏng.",
    ),
    (
        "P",
        "Hệ thống trả lời theo hai hướng khác nhau, tuỳ mức độ nghiêm trọng. Cổng kiểm "
        "duyệt trước khi cấp token chọn mở cửa: nếu Detection Engine sập mà khoá cả "
        "hệ thống thì hậu quả lớn hơn nhiều so với lọt một lần đăng nhập không được "
        "chấm điểm, và đường phản ứng hậu kỳ vẫn bảo đảm thu hồi phiên. Ngược lại, "
        "khi gọi ML Service mà không có phản hồi, hệ thống vẫn tạo cảnh báo dựa trên "
        "điểm quy tắc, vì bỏ qua cảnh báo là mất dấu vết tấn công."),

    # ================================================================ I.2 (B)
    ("H3", "B. Cơ sở lý thuyết về hệ quản trị cơ sở dữ liệu"),
    ("H4", "1. Hệ quản trị cơ sở dữ liệu được sử dụng"),
    (
        "P",
        "Hệ thống sử dụng PostgreSQL. Lý do chọn: hỗ trợ kiểu dữ liệu JSONB để lưu "
        "cấu trúc quy tắc và bằng chứng chấm điểm mà không cần tách bảng; hỗ trợ kiểu "
        "địa chỉ mạng để chuẩn hoá địa chỉ IP; có ràng buộc kiểm tra (CHECK) để ràng "
        "buộc tập giá trị của các cột trạng thái ngay trong cơ sở dữ liệu; và hỗ trợ "
        "cơ chế khóa ngoại với hành vi xoá rõ ràng.",
    ),
    ("H4", "2. Giao dịch và tính nhất quán"),
    (
        "P",
        "Giao dịch bảo đảm nhóm thao tác thành công trọn vẹn hoặc thất bại trọn vẹn. "
        "Điểm mấu chốt trong hệ thống này là thứ tự commit: Detection Engine commit "
        "kết quả chấm điểm và cảnh báo trước, rồi mới gửi hành động bảo vệ. Nhờ vậy "
        "khi Core App chậm hoặc chết, đánh giá đã ghi vẫn còn nguyên và có thể xử lý "
        "lại.",
    ),
    (
        "P",
        "Nguyên tắc còn lại là không nuốt lỗi âm thầm. Khi chấm điểm ném lỗi ngoài dự "
        "kiến, bản ghi lần đăng nhập được đánh dấu là lỗi chứ không bị xoá, kèm một "
        "dòng nhật ký. Hàm quét lại các bản ghi lỗi đã có kiểm thử, nhưng chưa được "
        "nối vào bộ lập lịch nào."),
    ("H4", "3. Khoá chính, khoá ngoại và toàn vẹn dữ liệu"),
    (
        "P",
        "Khoá chính định danh duy nhất phổ quát sinh tự động cho mọi bảng. Khoá ngoại "
        "được khai báo ở mọi quan hệ trong phạm vi một cơ sở dữ liệu, kèm hành vi xoá "
        "tường minh: xoá nhóm sẽ xoá luôn phiên và giao dịch xác thực, xoá người dùng "
        "sẽ đặt null cho các dòng nhật ký thay vì xoá, nhờ vậy lịch sử kiểm toán không "
        "bị mất. Ràng buộc duy nhất chống trùng được đặt cho cặp tài khoản và vai trò.",
    ),
    ("P",
        "Điểm đáng chú ý về tính toàn vẹn trong hệ thống này: có ràng buộc bất biến "
        "chống trường hợp có hai chính sách cùng kích hoạt. Vì điều kiện này có vẻ "
        "phụ thuộc vào chính bảng đang khai báo, việc thiết kế đã sử dụng biểu thức "
        "phụ thuộc ở mức ràng buộc cấp bảng. Đây là điểm cần kiểm thử lại khi dựng "
        "cơ sở dữ liệu thật."),
    ("H4", "4. Chỉ mục"),
    (
        "P",
        "Chỉ mục quyết định tốc độ truy vấn và có chi phí ghi thêm. Nguyên tắc chọn "
        "chỉ mục trong hệ thống là chỉ mục theo đúng truy vấn tần suất cao: tra cứu "
        "phiên theo tài khoản người dùng, tra cứu lần đăng nhập theo mã sự kiện để "
        "kiểm tra lũy đẳng, tính số lần thất bại trong hai mươi bốn giờ, và lọc cảnh "
        "báo theo trạng thái, mức rủi ro, người được giao và thời gian tạo.",
    ),
    (
        "P",
        "Có hai chỉ mục một phần (chỉ lập trên một tập con dòng) đáng chú ý. Chỉ mục "
        "trên bảng phiên chỉ lập cho dòng có mã định danh token, và chỉ mục trên bảng "
        "phiên cấp họ có điều kiện chỉ lập cho nhóm thiết bị tin cậy còn hiệu lực. Cách "
        "này giữ chỉ mục nhỏ và chỉ trả về đúng nhóm cần dùng."),
    ("H4", "5. Vì sao dữ liệu được tách theo dịch vụ"),
    (
        "P",
        "Kiến trúc ba cơ sở dữ liệu độc lập đặt ra ba yêu cầu xung khắc: ranh giới "
        "dữ liệu rõ ràng, hiệu năng, và tính sẵn sàng. Tách theo dịch vụ đáp ứng cả ba.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.7, 3.7, 2.0],
            "header": ["Cơ sở dữ liệu", "Phạm vi dữ liệu", "Đặc điểm truy cập"],
            "rows": [
                [
                    "core-db",
                    "Tài khoản, vai trò, phiên, giao dịch xác thực, thiết bị tin "
                    "cậy, nhật ký kiểm toán, tham số hệ thống, thông báo, bộ đếm "
                    "giới hạn tần suất",
                    "Tần suất ghi cao, đọc rất cao",
                ],
                [
                    "detection-db",
                    "Chính sách chấm điểm, lần đăng nhập, kết quả đánh giá, nhật ký "
                    "chấm điểm, hồ sơ phân viên, cảnh báo, dòng thời gian cảnh báo",
                    "Ghi nặng theo sự kiện, đọc nặng theo truy vấn điều tra",
                ],
                [
                    "ml-service-db",
                    "Sổ đăng ký phiên bản mô hình, nhật ký suy luận, thống kê đặc "
                    "trưng",
                    "Ghi mỗi lần suy luận, đọc theo chu kỳ phân tích",
                ],
            ],
        },
    ),
    ("CAP", "Bảng 1.4  Phân tách dữ liệu theo ba cơ sở dữ liệu"),
    (
        "P",
        "Ranh giới trong thiết kế được vẽ bằng nguyên tắc: dữ liệu thuộc quyền sở hữu "
        "và vòng đời của dịch vụ nào thì nằm trong cơ sở dữ liệu của dịch vụ đó. Mỗi "
        "dịch vụ chỉ có một cơ sở dữ liệu, không truy cập chéo cơ sở dữ liệu của nhau. "
        "Hệ quả trực tiếp là các khóa ngoại không thể khai báo xuyên biên giới, và các "
        "quan hệ đó phải được xác minh ở tầng ứng dụng.",
    ),
    ("H4", "6. Quan hệ xuyên cơ sở dữ liệu và cách xác minh ở tầng ứng dụng"),
    (
        "P",
        "Có ba quan hệ xuyên cơ sở dữ liệu trong thiết kế. Cột mã người dùng trong "
        "bảng hồ sơ phân viên của detection-db trỏ tới bảng người dùng của core-db. Cột "
        "người thực hiện trong bảng dòng thời gian cảnh báo cũng vậy. Cột người tạo "
        "trong bảng chính sách cũng vậy.",
    ),
    (
        "P",
        "Vì không thể khai báo khóa ngoại, hệ thống bổ sung điểm cuối nội bộ cho phép "
        "Core App tra cứu thông tin người dùng kèm danh sách vai trò, để Detection "
        "Engine và quy trình SOC dùng để xác minh danh tính. Đây là cơ chế thay thế ở "
        "mức ứng dụng cho ràng buộc toàn vẹn mà cơ sở dữ liệu không thể bảo đảm. Hệ "
        "quả cần nói rõ: nếu một tài khoản bị xoá ở core-db, các tham chiếu còn lại "
        "trong detection-db sẽ trỏ vào giá trị không tồn tại, và việc phát hiện trường "
        "hợp này cần một cơ chế đối chiếu định kỳ. Cơ chế đó chưa được hiện thực."),
    ("H4", "7. Dữ liệu nhạy cảm và cách bảo vệ"),
    (
        "P",
        "Ba loại dữ liệu trong hệ thống cần chú ý về mức độ nhạy cảm khác nhau. Dữ liệu "
        "xác thực nhạy cảm nhất: mật khẩu bằng hàm băm chậm có muối, mã xác thực một "
        "lần băm trước khi lưu, token bằng băm SHA-256, và địa chỉ IP gắn với giao "
        "dịch xác thực được băm trước khi lưu. Dữ liệu phát hiện cần giữ lâu để điều "
        "tra: lịch sử lần đăng nhập và kết quả chấm điểm. Dữ liệu suy luận dễ tái "
        "tạo nhất: mỗi dòng nhật ký suy luận lưu sáu đặc trưng đầu vào nên có thể phát "
        "lại để kiểm tra kết quả."),
    ("H4", "8. Vì sao không dùng mô hình liên kết chặt"),
    (
        "P",
        "Mô hình liên kết chặt dùng chung một cơ sở dữ liệu cho mọi thành phần. Với hệ "
        "thống nhỏ, cách đó đơn giản hơn. Hệ thống này chọn mô hình tách biệt vì ba "
        "lý do. Thứ nhất, ranh giới trách nhiệm: Detection Engine không nên có quyền "
        "ghi vào bảng phiên của Core App. Thứ hai, hiệu năng: tải ghi dày đặc của quá "
        "trình chấm điểm không nên tranh chấp với tải đọc dày đặc của quá trình xác "
        "thực trên cùng bảng hệ thống tệp và bộ đệm. Thứ ba, tính sẵn sàng: Detection "
        "Engine chấm điểm lỗi không được làm sập khả năng đăng nhập.",
    ),
    (
        "P",
        "Đổi lại, mô hình tách biệt đòi hỏi giải quyết bốn bài toán mà mô hình liên kết "
        "chặt không có: giao tiếp xuyên biên giới, khóa lũy đẳng, đối chiếu trạng thái, "
        "và giao dịch phân tán. Thiết kế hiện tại đã giải quyết hai bài toán đầu bằng "
        "giao thức HTTP có khoá dùng chung và khoá lũy đẳng; hai bài toán sau được ghi "
        "nhận là nợ kỹ thuật tại Chương VI."),
]
