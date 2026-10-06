"""Nội dung Chương III - PHÂN TÍCH THIẾT KẾ HỆ THỐNG (phần 1: UML)."""

from __future__ import annotations

CHUONG_III_A: list[tuple[str, object]] = [
    ("H1", "CHƯƠNG III. PHÂN TÍCH THIẾT KẾ HỆ THỐNG"),
    (
        "P",
        "Chương này chuyển kết quả phân tích ở Chương II thành mô hình. Mỗi loại mô hình "
        "trả lời một câu hỏi khác nhau: sơ đồ trạng thái trả lời một đối tượng có thể ở "
        "trạng thái nào và chuyển sang trạng thái nào; sơ đồ tuần tự trả lời các thành phần "
        "trao đổi tin nhắn theo thứ tự nào; sơ đồ hoạt động trả lời quy trình gồm những "
        "bước và những nhánh quyết định nào; sơ đồ lớp trả lời trách nhiệm của từng lớp và "
        "quan hệ giữa chúng.",
    ),

    # ================================================================ III.1
    ("H2", "Sơ đồ use case"),
    (
        "P",
        "Sơ đồ use case tổng quát thể hiện toàn bộ chức năng của hệ thống và các tác "
        "nhân có quyền thực hiện chúng. Hệ thống có bốn tác nhân con người và hai tác nhân "
        "hệ thống.",
    ),
    ("IMG", {"key": "usecase", "width_cm": 17.5, "caption": None}),
    ("CAP", "Hình 3.1  Sơ đồ use case tổng quát của hệ thống"),
    ("P", "Bảng dưới liệt kê các tác nhân và chức năng tương ứng:"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.7, 2.0, 3.7],
            "header": ["Tác nhân", "Loại", "Phạm vi chức năng"],
            "rows": [
                [
                    "Người dùng hệ thống", "Con người",
                    "Đăng nhập, xác thực đa yếu tố, quản lý phiên của chính mình, quản lý "
                    "thiết bị tin cậy, xem thông báo",
                ],
                [
                    "SOC Analyst", "Con người",
                    "Xem danh sách và hồ sơ điều tra cảnh báo, tiếp nhận, ghi chú, yêu "
                    "cầu hành động bảo vệ, kết luận, đánh dấu báo nhầm, leo thang, xem "
                    "bảng điều khiển",
                ],
                [
                    "Security Administrator", "Con người",
                    "Quản lý chính sách, quản lý tài khoản và vai trò, thu hồi phiên của "
                    "người khác, điều chỉnh tham số, xem nhật ký kiểm toán",
                ],
                [
                    "Security Manager", "Con người",
                    "Xem bảng điều khiển tổng hợp, xem cảnh báo quan trọng, phê duyệt leo "
                    "thang, theo dõi tỉ lệ báo nhầm, xuất báo cáo",
                ],
                [
                    "Detection Engine", "Hệ thống",
                    "Ghi nhận sự kiện đăng nhập, kiểm duyệt trước khi cấp token, chấm điểm, "
                    "tạo cảnh báo, gửi hành động bảo vệ, phục hồi bản ghi lỗi",
                ],
                [
                    "ML Service", "Hệ thống",
                    "Nhận sáu đặc trưng, trả điểm bất thường đã chuẩn hoá, cờ bất thường, "
                    "mã lý do và phiên bản mô hình",
                ],
            ],
        },
    ),
    ("CAP", "Bảng 3.1  Các tác nhân và phạm vi chức năng"),
    ("P", "Các quan hệ trong sơ đồ được phân hai loại:"),
    ("BUL",
     "Quan hệ bao hàm (include) biểu thị hành vi bắt buộc luôn phải chạy. Ví dụ, quy "
     "trình đăng nhập luôn phải kiểm duyệt rủi ro trước khi cấp token, và việc kiểm "
     "duyệt rủi ro luôn kéo theo việc chấm điểm, chấm điểm luôn gọi suy luận máy học."),
    ("BUL",
     "Quan hệ mở rộng (extend) biểu thị hành vi tùy chọn chỉ chạy trong điều kiện riêng. "
     "Ví dụ, xác thực đa yếu tố mở rộng quy trình đăng nhập khi có rủi ro cao; yêu cầu hành "
     "động bảo vệ chỉ mở rộng quy trình tiếp nhận cảnh báo khi phân viên đã tiếp nhận."),
    ("H3", "Mô tả các chức năng quan trọng"),
    ("P", "Bảng dưới mô tả chín chức năng, tập trung vào chức năng có ràng buộc nghiệp vụ "
          "chặt nhất."),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.6, 1.7, 1.0, 4.1],
            "header": ["Mã", "Chức năng", "Tác nhân", "Mô tả và điều kiện tiên quyết"],
            "rows": [
                ["UC-01", "Đăng nhập", "Người dùng",
                 "Xác thực tên đăng nhập và mật khẩu, kiểm tra trạng thái tài khoản, kiểm "
                 "duyệt rủi ro, rồi tạo phiên hoặc phát thử thách xác thực. Tiên quyết: "
                 "chưa vượt ngưỡng tần suất. Bao hàm kiểm duyệt rủi ro và ghi sự kiện."],
                ["UC-02", "Xác thực đa yếu tố", "Người dùng",
                 "Xác nhận mã xác thực cho giao dịch đang chờ. Tiên quyết: giao dịch còn "
                 "hiệu lực và chưa dùng. Mở rộng quy trình đăng nhập."],
                ["UC-05", "Kiểm duyệt rủi ro trước khi cấp token", "Detection Engine",
                 "Chấm điểm lần đăng nhập trước khi token tồn tại; trả về mức rủi ro và cờ "
                 "yêu cầu xác thực. Chỉ chặn ở mức cao và nghiêm trọng; mở cửa khi lỗi."],
                ["UC-07", "Chấm điểm rủi ro", "Detection Engine",
                 "Đánh giá quy tắc trên sáu đặc trưng, gọi suy luận máy học, gộp điểm và xếp "
                 "mức. Tiên quyết: có chính sách đang kích hoạt. Bao hàm gọi suy luận máy học."],
                ["UC-09", "Tạo cảnh báo", "Detection Engine",
                 "Tạo cảnh báo ở trạng thái mở kèm lý do và cụm điểm. Tiên quyết: mức rủi ro "
                 "là cao hoặc nghiêm trọng. Bao hàm ghi dòng thời gian."],
                ["UC-10", "Thực thi hành động bảo vệ", "Detection Engine",
                 "Gửi yêu cầu hành động sang Core App kèm lý do, mã cảnh báo và khoá lũy "
                 "đẳng. Thực hiện sau khi đã commit đánh giá và cảnh báo; nuốt lỗi khi gọi thất bại."],
                ["UC-14", "Tiếp nhận cảnh báo", "SOC Analyst",
                 "Ghi nhận trách nhiệm xử lý cảnh báo. Tiên quyết: cảnh báo chưa có người "
                 "nhận. Bắt buộc ghi dòng thời gian. Bao hàm xem dòng thời gian."],
                ["UC-15", "Kết luận hoặc đánh dấu báo nhầm", "SOC Analyst",
                 "Kết thúc vòng đời cảnh báo. Bắt buộc có nội dung kết luận; ghi người thực "
                 "hiện và thời điểm. Bao hàm ghi dòng thời gian."],
                ["UC-18", "Yêu cầu hành động bảo vệ", "SOC Analyst",
                 "Thực hiện một trong bốn hành động bảo vệ kèm lý do. Mở rộng quy trình "
                 "tiếp nhận cảnh báo. Phản hồi trả về số phiên đã thu hồi; ghi audit."],
                ["UC-20", "Quản lý chính sách", "Security Administrator",
                 "Xem, kiểm tra tính hợp lệ và kích hoạt chính sách chấm điểm. Ràng buộc chỉ "
                 "một chính sách kích hoạt; từ chối kích hoạt chính sách sai."],
                ["UC-11", "Khôi phục bản ghi chấm lỗi", "Detection Engine",
                 "Quét các bản ghi lần đăng nhập ở trạng thái lỗi và chấm lại. Tiên quyết: "
                 "có bản ghi lỗi. Một bản ghi lỗi không được dừng cả đợt quét."],
            ],
        },
    ),
    ("CAP", "Bảng 3.2  Mô tả các chức năng quan trọng của hệ thống"),

    # ================================================================ III.2
    ("H2", "Sơ đồ trạng thái"),
    (
        "P",
        "Hệ thống có ba đối tượng có vòng đời rõ ràng đáng biểu diễn bằng sơ đồ trạng "
        "thái: cảnh báo SOC, giao dịch xác thực đa yếu tố, và phiên đăng nhập. Ba sơ đồ "
        "này trả lời câu hỏi khác nhau: cảnh báo cho biết vòng đời xử lý của một sự cố, giao "
        "dịch xác thực cho biết một thử thách có thể kết thúc thế nào, và phiên cho biết "
        "một quyền truy cập sống bao lâu.",
    ),
    ("H3", "Trạng thái cảnh báo SOC"),
    ("P",
        "Cảnh báo có bốn trạng thái. Điểm cần lưu ý trong thiết kế là trạng thái báo nhầm "
        "được tách riêng chứ không gộp vào đã kết luận, vì đây là hai thông tin khác nhau về "
        "mặt nghiệp vụ: kết luận là thông tin phục vụ xử lý sự cố, còn báo nhầm là thông tin "
        "phục vụ hiệu chỉnh chính sách. Trộn lẫn hai loại này sẽ làm mất khả năng đo tỉ lệ "
        "báo nhầm theo từng quy tắc.",
    ),
    ("IMG", {"key": "state_alert", "width_cm": 12.0, "caption": None}),
    ("CAP", "Hình 3.2  Sơ đồ trạng thái vòng đời cảnh báo SOC"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.7, 1.5, 4.2],
            "header": ["Trạng thái", "Ý nghĩa", "Ai có quyền chuyển sang"],
            "rows": [
                ["open", "Vừa tạo, chưa có người nhận trách nhiệm",
                 "Detection Engine tạo ra; phân viên SOC chuyển sang các trạng thái tiếp theo"],
                ["acknowledged", "Đã có người nhận, đang trong quá trình điều tra",
                 "Phân viên SOC, khi tiếp nhận cảnh báo chưa có người nhận"],
                ["resolved", "Đã có kết luận điều tra",
                 "Phân viên SOC; bắt buộc có nội dung kết luận, người kết luận và thời điểm"],
                ["false_positive", "Xác nhận hệ thống đã báo nhầm",
                 "Phân viên SOC; dùng để hiệu chỉnh chính sách"],
            ],
        },
    ),
    ("CAP", "Bảng 3.3  Ý nghĩa và quyền chuyển trạng thái của cảnh báo"),
    ("P",
        "Mọi lần chuyển trạng thái đều sinh một dòng trong bảng dòng thời gian, ghi lại loại "
        "sự kiện, người thực hiện, giá trị cũ, giá trị mới và ghi chú. Leo thang là ngoại lệ: "
        "nó không đóng cảnh báo mà chỉ ghi thêm dòng thời gian, vì vấn đề chưa được giải "
        "quyết và cần tiếp tục theo dõi.",
    ),
    ("H3", "Trạng thái giao dịch xác thực đa yếu tố"),
    ("IMG", {"key": "state_mfa_session", "width_cm": 9.5, "caption": None}),
    ("CAP", "Hình 3.3  Sơ đồ trạng thái của giao dịch MFA và phiên đăng nhập"),
    (
        "P",
        "Giao dịch xác thực có bốn trạng thái kết thúc. Điểm thiết kế cần lưu ý là ngưỡng "
        "ba lần thử: bộ đếm sai tăng mỗi lần, và khi đạt ngưỡng thì giao dịch chuyển sang "
        "trạng thái thất bại, không phải trạng thái chờ. Hệ quả là mã đó không thử lại được, "
        "kể cả khi người dùng nhập đúng từ một lần thử sai trước đó. Đây là lựa chọn có "
        "chủ ý để chống dò mã, và phía người dùng chỉ cần đăng nhập lại để tạo giao dịch mới.",
    ),
    ("H3", "Trạng thái phiên đăng nhập"),
    (
        "P",
        "Phiên có ba trạng thái kết thúc: đang hoạt động, đã thu hồi, và đã hết hạn. Điểm "
        "thiết kế cốt lõi nằm ở chỗ tất cả các cơ chế thu hồi, dù do người dùng, quản trị "
        "viên hay Detection Engine yêu cầu, đều dẫn về cùng một thao tác: đặt thời điểm thu "
        "hồi. Nhờ vậy chỉ cần một điều kiện lọc duy nhất trong mọi truy vấn xác thực, và một "
        "phiên bị thu hồi mất hiệu lực ngay ở lần gọi kế tiếp chứ không phải chờ hết thời hạn "
        "một giờ.",
    ),
    ("P",
        "Sự khác biệt giữa thu hồi và hết hạn có ý nghĩa kiểm toán: phiên bị thu hồi là "
        "kết quả của một quyết định, nên nó xuất hiện trong nhật ký kiểm toán và trong cụm "
        "điểm của cảnh báo; còn phiên hết hạn là chuyện thường ngày và không ai xử lý.",
    ),

    # ================================================================ III.3
    ("H2", "Sơ đồ tuần tự"),
    (
        "P",
        "Sơ đồ tuần tự mô tả trình tự trao đổi tin nhắn giữa các thành phần. Hệ thống có "
        "sáu quy trình chính, mỗi quy trình một sơ đồ. Các sơ đồ này được kế thừa từ bộ sơ "
        "đồ quy trình đã có của dự án, sau khi hiệu chỉnh cho khớp với cổng kiểm duyệt rủi "
        "ro và bốn hành động bảo vệ mới.",
    ),
    ("H3", "Tuần tự đăng nhập"),
    (
        "P",
        "Sơ đồ tuần tự đăng nhập thể hiện đầy đủ tám bước đã mô tả ở Chương II, với hai "
        "điểm cần chú ý là vị trí của cổng kiểm duyệt rủi ro và điều kiện thất bại mở cửa. "
        "Cổng nằm sau bước xác thực mật khẩu, nên người dùng sai mật khẩu không tốn một lượt "
        "gọi Detection; và cổng nằm trước bước tạo phiên, nên khi rủi ro cao thì không có "
        "token nào được tạo.",
    ),
    ("IMG", {"key": "seq_login", "width_cm": 16.0, "caption": None}),
    ("CAP", "Hình 3.4  Sơ đồ tuần tự quy trình đăng nhập và xác thực"),
    ("H3", "Tuần tự phát hiện"),
    (
        "P",
        "Sơ đồ tuần tự phát hiện thể hiện luồng bất đồng bộ: Detection Engine nhận sự kiện, "
        "xây dựng đặc trưng, đánh giá quy tắc, gọi ML Service, gộp điểm, tạo cảnh báo, rồi "
        "gửi hành động bảo vệ. Sơ đồ này thể hiện rõ ba nhánh xử lý lỗi: quy tắc cấu hình "
        "sai, cấu hình ngưỡng sai, và ML Service không phản hồi.",
    ),
    ("IMG", {"key": "seq_detection", "width_cm": 15.0, "caption": None}),
    ("CAP", "Hình 3.5  Sơ đồ tuần tự quy trình phát hiện và chấm điểm rủi ro"),
    ("H3", "Tuần tự xử lý cảnh báo SOC"),
    (
        "P",
        "Sơ đồ tuần tự xử lý cảnh báo thể hiện vòng đời cảnh báo từ lúc Detection tạo ra "
        "đến khi phân viên SOC kết luận. Sơ đồ đặc biệt nhấn mạnh cơ chế thu hồi phiên: "
        "Detection Engine chỉ gửi yêu cầu hành động, còn việc cập nhật bảng phiên thuộc về "
        "Core App, và phản hồi trả về số phiên đã thu hồi để đối chiếu.",
    ),
    ("IMG", {"key": "seq_soc", "width_cm": 15.0, "caption": None}),
    ("CAP", "Hình 3.6  Sơ đồ tuần tự quy trình xử lý cảnh báo SOC"),
    ("H3", "Tuần tự xác thực đa yếu tố"),
    ("IMG", {"key": "seq_mfa", "width_cm": 15.0, "caption": None}),
    ("CAP", "Hình 3.7  Sơ đồ tuần tự quy trình xác thực đa yếu tố"),
    ("H3", "Tuần tự quản lý phiên"),
    ("IMG", {"key": "seq_session", "width_cm": 14.0, "caption": None}),
    ("CAP", "Hình 3.8  Sơ đồ tuần tự quản lý phiên đăng nhập"),
    ("H3", "Tuần tự suy luận mô hình"),
    (
        "P",
        "Sơ đồ tuần tự suy luận mô hình mô tả hợp đồng giữa Detection Engine và ML Service, "
        "bao gồm định dạng yêu cầu gồm sáu đặc trưng và định dạng phản hồi gồm điểm chuẩn "
        "hoá, cờ bất thường, phiên bản mô hình và danh sách mã lý do. Sơ đồ cũng thể hiện "
        "bốn nhánh lỗi, mỗi nhánh dẫn tới một giá trị trạng thái ML khác nhau được lưu vào "
        "kết quả đánh giá.",
    ),
    ("IMG", {"key": "seq_ml", "width_cm": 14.0, "caption": None}),
    ("CAP", "Hình 3.9  Sơ đồ tuần tự quy trình suy luận mô hình"),
    ("H3", "Các kịch bản xử lý chi tiết"),
    (
        "P",
        "Ngoài sáu sơ đồ trên, nhóm bổ sung bốn kịch bản xử lý chi tiết cho các nhánh lỗi "
        "và các trường hợp biên. Bốn kịch bản này được tách riêng vì mỗi kịch bản thể hiện "
        "một quyết định thiết kế mà nếu không vẽ ra rất dễ bị hiểu sai.",
    ),
    ("IMG", {"key": "st01", "width_cm": 12.0, "caption": None}),
    ("CAP", "Hình 3.10  Kịch bản đăng nhập thành công theo đường không cảnh báo"),
    ("P",
        "Kịch bản này là trường hợp đường chuẩn: cổng kiểm duyệt trả mức thấp, token được cấp "
        "ngay, bản ghi lần đăng nhập vẫn được ghi lại để chấm điểm ở luồng bất đồng bộ và sinh "
        "kết quả đánh giá mức thấp. Kịch bản này nhắc lại một điểm dễ quên: kể cả khi cổng "
        "không chặn, hệ thống vẫn ghi và chấm điểm đầy đủ.",
    ),
    ("IMG", {"key": "st03", "width_cm": 13.0, "caption": None}),
    ("CAP", "Hình 3.11  Kịch bản đăng nhập bị chặn ở mức rủi ro nghiêm trọng"),
    ("P",
        "Kịch bản này thể hiện tác động kép của mức nghiêm trọng: cổng đồng bộ chặn trước khi "
        "cấp token, và luồng bất đồng bộ sau đó vẫn tạo cảnh báo rồi gửi yêu cầu thu hồi "
        "phiên. Hai luồng bổ trợ lẫn nhau: luồng đồng bộ ngăn quyền truy cập, luồng bất đồng "
        "bộ tạo hồ sơ để điều tra.",
    ),
    ("IMG", {"key": "st04", "width_cm": 12.0, "caption": None}),
    ("CAP", "Hình 3.12  Kịch bản phân viên SOC tiếp nhận và kết luận cảnh báo"),
    ("IMG", {"key": "st06", "width_cm": 12.0, "caption": None}),
    ("CAP", "Hình 3.13  Kịch bản suy giảm về điểm quy tắc khi ML Service lỗi"),
    (
        "NOTE",
         "Bốn kịch bản này được nhóm lại như sơ đồ bổ trợ, không thay thế cho sáu sơ đồ tuần "
         "tự chính ở trên. Lý do: chúng thuộc loại kịch bản, tức là một đường đi cụ thể của "
         "quy trình, trong khi sơ đồ tuần tự chính mô tả toàn bộ quy trình kể cả các nhánh. "
         "Cách trình bày này tránh việc gọi nhầm một luồng con là toàn bộ quy trình."),

    # ================================================================ III.4
    ("H2", "Sơ đồ hoạt động"),
    (
        "P",
        "Sơ đồ hoạt động mô tả quy trình gồm các bước và các nhánh quyết định. Ba quy "
        "trình được biểu diễn: đăng nhập kèm xác thực đa yếu tố, phát hiện kèm quyết định "
        "rủi ro, và điều tra cảnh báo của phân viên SOC. Mỗi sơ đồ được chia thành các "
        "phân vùng theo giai đoạn để dễ đối chiếu với phần mô tả ở Chương II.",
    ),
    ("H3", "Hoạt động đăng nhập và xác thực"),
    (
        "P",
        "Sơ đồ gồm bốn phân vùng: kiểm soát tần suất, xác thực thông tin đăng nhập, cổng "
        "kiểm duyệt rủi ro, và quyết định tạo phiên. Điểm cần chú ý là phân vùng cổng kiểm "
        "duyệt nằm sau phân vùng xác thực, thể hiện đúng thứ tự đã chốt trong thiết kế.",
    ),
    ("IMG", {"key": "act_login", "width_cm": 12.0, "caption": None}),
    ("CAP", "Hình 3.14  Sơ đồ hoạt động quy trình đăng nhập và xác thực"),
    ("H3", "Hoạt động phát hiện và quyết định rủi ro"),
    (
        "P",
        "Sơ đồ gồm sáu phân vùng: chọn chính sách, kiểm tra cấu hình, chấm quy tắc, gọi ML "
        "Service, gộp điểm, và tạo cảnh báo cùng gửi hành động. Sơ đồ thể hiện rõ hai quyết "
        "định về độ trễ: cổng kiểm duyệt có hạn ba giây và mở cửa khi lỗi, còn gọi ML "
        "Service có hạn năm giây nhưng vẫn tiếp tục xử lý bằng điểm quy tắc.",
    ),
    ("IMG", {"key": "act_detection", "width_cm": 12.0, "caption": None}),
    ("CAP", "Hình 3.15  Sơ đồ hoạt động quy trình phát hiện và quyết định rủi ro"),
    ("H3", "Hoạt động điều tra cảnh báo"),
    (
        "P",
        "Sơ đồ mô tả năm phân vùng của phân viên SOC: tiếp cận cảnh báo, thu thập bằng "
        "chứng, quyết định tiếp nhận, điều tra và phản ứng, và kết luận. Điểm cần chú ý là "
        "nhánh thu thập bằng chứng gọi cả bốn bảng cộng một điểm cuối nội bộ của Core App, "
        "vì danh tính người bị nghi ngờ nằm ở cơ sở dữ liệu khác.",
    ),
    ("IMG", {"key": "act_soc", "width_cm": 12.0, "caption": None}),
    ("CAP", "Hình 3.16  Sơ đồ hoạt động quy trình điều tra cảnh báo SOC"),

    # ================================================================ III.5
    ("H2", "Sơ đồ lớp"),
    (
        "P",
        "Sơ đồ lớp biểu diễn ở mức miền nghiệp vụ và tầng ứng dụng, không phải ở mức bảng cơ "
        "sở dữ liệu. Lý do tách hai mức này: bảng cơ sở dữ liệu phản ánh cấu trúc lưu trữ, "
        "còn lớp nghiệp vụ phản ánh trách nhiệm và quy tắc. Trộn hai mức sẽ khiến sơ đồ lớp "
        "trở thành bản sao của sơ đồ quan hệ thực thể và mất đi ý nghĩa về thiết kế.",
    ),
    ("IMG", {"key": "class", "width_cm": 17.0, "caption": None}),
    ("CAP", "Hình 3.17  Sơ đồ lớp miền nghiệp vụ của hệ thống"),
    ("H4", "Nhóm lớp xác thực"),
    (
        "P",
        "Lớp thực thể người dùng giữ thông tin định danh, bản băm mật khẩu, trạng thái và hai "
        "cờ điều khiển xác thực đa yếu tố. Cờ bắt buộc có tính bền vững do quản trị viên "
        "đặt; cờ xác thực một lần có tính tạm thời do phát hiện đặt và được xoá ngay sau khi "
        "xác thực thành công. Lớp điều khiển xác thực điều phối đăng nhập và xác nhận mã, "
        "trong đó có hai phương thức nội bộ là kiểm tra giới hạn tần suất và kiểm duyệt rủi ro.",
    ),
    (
        "P",
        "Lớp thực thể phiên giữ bản băm token, mã định danh token, thời hạn và thời điểm thu "
        "hồi, với ba phương thức là kiểm tra hiệu lực, thu hồi, và xoay token. Lớp điều khiển "
        "phiên tạo, liệt kê và thu hồi phiên; việc thu hồi được kiểm tra sở hữu ở tầng ứng "
        "dụng để người dùng không thể thu hồi phiên của người khác.",
    ),
    ("H4", "Nhóm lớp phát hiện"),
    (
        "P",
        "Lớp thực thể lần đăng nhập là trung tâm của nhóm này, liên kết một-một với kết quả "
        "đánh giá và một-nhiều với cảnh báo. Ràng buộc một-một với kết quả đánh giá được thực "
        "thi ở mức cơ sở dữ liệu, nên không thể có hai kết quả cho cùng một lần đăng nhập, "
        "kể cả khi quá trình chấm lại chạy nhiều lần.",
    ),
    (
        "P",
        "Nhóm lớp dịch vụ chia theo trách nhiệm: lớp xây dựng đặc trưng đọc lịch sử đăng nhập; "
        "lớp đánh giá quy tắc lấy danh sách quy tắc từ chính sách và trả về điểm cùng danh "
        "sách quy tắc đã chạy; lớp chấm điểm gộp hai điểm và xếp mức; lớp dịch vụ phát hiện "
        "điều phối toàn bộ pha máy và là điểm vào của cả ba điểm cuối nội bộ; lớp điều phối "
        "hành động gửi yêu cầu sang Core App; lớp dịch vụ cảnh báo thực hiện vòng đời cảnh báo.",
    ),
    ("H4", "Nhóm lớp suy luận và hợp đồng"),
    (
        "P",
        "Lớp dịch vụ suy luận sử dụng lớp mô hình bất thường, hiện là mô hình nền theo "
        "quy tắc. Cả hai đều nằm trong gói ML Service, được Detection Engine gọi qua HTTP chứ "
        "không gọi trực tiếp. Nhóm lớp hợp đồng gồm bốn cấu trúc dữ liệu trao đổi: yêu cầu "
        "ghi sự kiện, yêu cầu kiểm duyệt trước token, phản hồi kiểm duyệt, và cặp yêu cầu "
        "phản hồi hành động bảo vệ.",
    ),
    ("H4", "Quan hệ chính và số lượng"),
    (
        "P",
        "Ba quan hệ cần lưu ý về số lượng. Người dùng có từ không đến nhiều phiên và từ "
        "không đến nhiều giao dịch xác thực, vì một người dùng có thể chưa đăng nhập hoặc "
        "chưa từng bị yêu cầu xác thực thêm. Một lần đăng nhập có đúng nhiều nhất một kết "
        "quả đánh giá, nhưng có thể có từ không đến nhiều cảnh báo, vì chính sách có thể tạo "
        "nhiều cảnh báo cho cùng một lần đăng nhập trong các phiên bản mở rộng. Một cảnh báo "
        "có từ không đến nhiều dòng thời gian, vì mỗi lần ghi chú hay chuyển trạng thái đều "
        "là một dòng.",
    ),
    (
        "NOTE",
         "Quan hệ giữa bảng người dùng ở core-db và bảng hồ sơ phân viên ở detection-db không "
         "thể vẽ bằng quan hệ khóa ngoại, vì hai bảng nằm ở hai cơ sở dữ liệu khác nhau. "
         "Trong sơ đồ lớp, quan hệ đó được thể hiện gián tiếp qua lớp dịch vụ cảnh báo và hợp "
         "đồng truy vấn người dùng nội bộ. Mối quan hệ xuyên cơ sở dữ liệu này được trình "
         "bày đầy đủ ở mục Thiết kế cơ sở dữ liệu."),

    # ================================================================ III.6 (part 1)
    ("H2", "Thiết kế cơ sở dữ liệu"),
    ("H3", "Mô hình ERD"),
    (
        "P",
        "Mô hình quan hệ thực thể được lập cho ba cơ sở dữ liệu, mỗi cơ sở dữ liệu một sơ "
        "đồ. Ba sơ đồ dùng ký hiệu Chen với thể hiện quan hệ và số nhiều rõ ràng, và đánh "
        "dấu đầy đủ khoá chính, khoá ngoại và ràng buộc duy nhất.",
    ),
    ("IMG", {"key": "erd_core", "width_cm": 17.0, "caption": None}),
    ("CAP", "Hình 3.18  Mô hình quan hệ thực thể của cơ sở dữ liệu core-db"),
    ("IMG", {"key": "erd_detection", "width_cm": 17.0, "caption": None}),
    ("CAP", "Hình 3.19  Mô hình quan hệ thực thể của cơ sở dữ liệu detection-db"),
    ("IMG", {"key": "erd_ml", "width_cm": 11.0, "caption": None}),
    ("CAP", "Hình 3.20  Mô hình quan hệ thực thể của cơ sở dữ liệu ml-service-db"),
    ("H3", "Sơ đồ quan hệ bảng"),
    (
        "P",
        "Bảng dưới tóm tắt quan hệ giữa các bảng, kèm cột khóa chính và khóa ngoại. Đây là "
        "dạng rút gọn của ERD ở dạng bảng, thuận tiện để tra cứu.",
    ),
    ("TABLE",
        {
            "caption": None,
            "widths": [1.6, 1.6, 1.6, 1.5, 1.7],
            "header": ["Bảng", "Khóa chính", "Khóa ngoại", "Số nhiều", "Hành vi khi xoá"],
            "rows": [
                ["users", "id", "—", "—", "—"],
                ["roles", "id", "—", "—", "—"],
                ["user_roles", "id",
                 "user_id đến users; role_id đến roles; assigned_by đến users",
                 "nhiều đến một với users, roles và users", "Xoá theo khi xoá người dùng"],
                ["ip_addresses", "id", "—", "—", "—"],
                ["sessions", "id",
                 "user_id đến users; ip_address_id đến ip_addresses",
                 "nhiều đến một", "Xoá theo khi xoá người dùng; đặt trống khi xoá địa chỉ"],
                ["mfa_transactions", "id",
                 "user_id đến users; notification_id đến mfa_notifications",
                 "nhiều đến một với cả hai", "Xoá theo khi xoá người dùng; đặt trống khi xoá thông báo"],
                ["mfa_notifications", "id", "mfa_transaction_id đến mfa_transactions",
                 "nhiều đến một", "Xoá theo"],
                ["audit_logs", "id", "actor_id đến users",
                 "nhiều đến không hoặc một", "Đặt trống, giữ nguyên dòng nhật ký"],
                ["user_trusted_devices", "id", "user_id đến users", "nhiều đến một", "Xoá theo"],
                ["system_settings", "key", "updated_by đến users",
                 "nhiều đến không hoặc một", "Đặt trống"],
                ["outbox_events", "id", "—", "—", "—"],
                ["user_notifications", "id", "user_id đến users", "nhiều đến một", "Xoá theo"],
                ["rate_limits", "ip_address và action", "—", "—", "—"],
                ["policies", "id", "created_by đến users ở core-db",
                 "không hoặc một", "Không có khóa ngoại thật"],
                ["login_attempts", "id",
                 "event_id duy nhất; policy_id đến policies; primary_alert_id đến alerts",
                 "nhiều đến không hoặc một với policies; không hoặc một với alerts", "Đặt trống"],
                ["risk_assessments", "id",
                 "login_attempt_id đến login_attempts, duy nhất; policy_id đến policies",
                 "một đến một với login_attempts; không hoặc một với policies", "Xoá theo login_attempts"],
                ["detection_logs", "id", "login_attempt_id đến login_attempts",
                 "nhiều đến không hoặc một", "Đặt trống, giữ nguyên dòng nhật ký"],
                ["soc_analysts", "id", "user_id đến users ở core-db, duy nhất",
                 "một đến không hoặc một", "Không có khóa ngoại thật"],
                ["alerts", "id",
                 "login_attempt_id đến login_attempts; policy_id đến policies; "
                 "assigned_to_id và resolved_by_id đến soc_analysts",
                 "nhiều đến một với login_attempts; không hoặc một với policies và soc_analysts",
                 "Xoá theo login_attempts; đặt trống cho policies và soc_analysts"],
                ["alert_timeline", "id", "alert_id đến alerts",
                 "nhiều đến một", "Xoá theo"],
                ["model_versions", "id", "trained_by đến users ở core-db",
                 "không hoặc một", "Không có khóa ngoại thật"],
                ["inference_logs", "id", "model_version_id đến model_versions",
                 "nhiều đến không hoặc một", "Không xoá theo"],
                ["feature_statistics", "id", "—", "—", "—"],
            ],
        },
    ),
    ("CAP", "Bảng 3.4  Quan hệ giữa các bảng, khóa chính và khóa ngoại"),
    (
        "NOTE",
         "Cột khóa ngoại của bảng policies, soc_analysts, model_versions và các cột người "
         "thực hiện trong bảng alert_timeline trỏ tới bảng users ở cơ sở dữ liệu khác. Vì "
         "vậy chúng không phải khóa ngoại thật, chỉ là quy ước đặt tên. Cơ chế xác minh các "
         "quan hệ đó ở tầng ứng dụng được trình bày ở mục 3.6.3."),
]
