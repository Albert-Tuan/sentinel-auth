"""Nội dung Chương II - PHÂN TÍCH NỘI DUNG, YÊU CẦU."""

from __future__ import annotations

CHUONG_II: list[tuple[str, object]] = [
    ("H1", "CHƯƠNG II. PHÂN TÍCH NỘI DUNG, YÊU CẦU"),
    (
        "P",
        "Chương này tập trung vào nghiệp vụ, chưa chuyển sang mô hình UML. Mỗi quy "
        "trình được trình bày theo cùng một bộ mục để có thể đối chiếu: mục tiêu, "
        "tác nhân, điều kiện kích hoạt, tiền điều kiện, dữ liệu đầu vào, các bước xử "
        "lý, quy định áp dụng, điểm quyết định, dữ liệu được tạo hoặc cập nhật, kết "
        "quả đầu ra, ngoại lệ, nhật ký kiểm toán, và tiêu chí xác nhận quy trình đã "
        "thành công.",
    ),

    # ================================================================ II.1
    ("H2", "Giới thiệu quy trình 1"),
    ("H3", "QUY TRÌNH ĐĂNG NHẬP VÀ XÁC THỰC NGƯỜI DÙNG"),
    ("H4", "1.1 Tên quy trình và mục tiêu"),
    (
        "P",
        "Tên quy trình: Đăng nhập và xác thực người dùng. Mục tiêu là xác minh danh "
        "tính người gọi và, khi danh tính đúng nhưng bối cảnh đáng ngờ, buộc người đó "
        "xác thực lại trước khi nhận bất kỳ token nào. Quy trình kết thúc ở một trong "
        "ba kết cục: cấp phiên và token, yêu cầu xác thực đa yếu tố, hoặc từ chối.",
    ),
    ("H4", "1.2 Tác nhân và điều kiện kích hoạt"),
    (
        "P",
        "Tác nhân trực tiếp là người dùng hệ thống. Tác nhân hệ thống tham gia là "
        "Detection Engine, được gọi ở bước kiểm duyệt rủi ro. Điều kiện kích hoạt là "
        "lời gọi điểm cuối đăng nhập. Tiền điều kiện: dịch vụ đang hoạt động; cơ sở dữ "
        "liệu truy cập được; nếu cổng kiểm duyệt được bật thì Detection Engine phải "
        "sẵn sàng, nếu không quy trình vẫn chạy theo chế độ mở cửa.",
    ),
    ("H4", "1.3 Dữ liệu đầu vào"),
    ("P", "Đầu vào trực tiếp gồm tên đăng nhập và mật khẩu. Đầu vào gián tiếp do hệ thống tự thu thập:"),
    ("BUL", "Địa chỉ IP lấy từ tiêu đề chuyển tiếp, không lấy từ nội dung yêu cầu để tránh bị giả mạo."),
    ("BUL", "Chuỗi định danh thiết bị lấy từ tiêu đề trình duyệt."),
    ("BUL", "Mã định danh yêu cầu sinh ra để đối chiếu giữa các bước."),
    ("H4", "1.4 Các bước xử lý chi tiết"),
    ("P", "Quy trình gồm tám bước theo thứ tự cố định. Thứ tự này có chủ ý: bước kiểm "
          "soát tần suất đặt trước để chặn tấn công dò mật khẩu, và cổng kiểm duyệt rủi "
          "ro đặt sau xác thực mật khẩu để người dùng sai mật khẩu không tiêu tốn một "
          "lượt gọi Detection."),
    ("P", "Bước một, kiểm soát tần suất theo địa chỉ IP và hành động đăng nhập, với "
          "ngưỡng mặc định năm lần trong cửa sổ sáu mươi giây. Vượt ngưỡng thì ghi một "
          "bản ghi lần đăng nhập với kết quả bị giới hạn tần suất, rồi từ chối với mã "
          "trả về nghìn không bốn trăm hai mươi chín. Chỉ khi còn trong ngưỡng mới tăng "
          "bộ đếm."),
    ("P", "Bước hai, tra cứu tài khoản theo tên đăng nhập. Nếu không tìm thấy, ghi "
          "bản ghi lần đăng nhập với kết quian thất bại và mã người dùng để trống, rồi "
          "trả thông báo chung chung. Việc dùng thông báo chung có chủ ý: phân biệt "
          "tài khoản không tồn tại với mật khẩu sai sẽ cho kẻ tấn công biết tên đăng "
          "nhập nào hợp lệ."),
    ("P", "Bước ba, đối chiếu mật khẩu bằng cách băm và so sánh với giá trị đã lưu. Sai "
          "thì tăng bộ đếm thất bại trên tài khoản, ghi bản ghi lần đăng nhập, trả thông "
          "báo chung. Đối chiếu đúng thì đặt lại bộ đếm về không."),
    ("P", "Bước bốn, kiểm tra trạng thái tài khoản. Nếu đang bị khoá, ghi bản ghi lần "
          "đăng nhập với kết quả khoá tài khoản, rồi trả mã bốn trăm hai mươi ba."),
    ("P", "Bước năm, cổng kiểm duyệt rủi ro. Xem chi tiết ở mục 1.5."),
    ("P", "Bước sáu, quyết định có yêu cầu xác thực đa yếu tố hay không. Xem chi tiết ở mục 1.6."),
    ("P", "Bước bảy, nếu không yêu cầu xác thực thêm thì tạo phiên. Sinh access token và "
          "refresh token dưới dạng chuỗi ngẫu nhiên 32 byte, sinh mã định danh token, "
          "ghi bản ghi phiên với bản băm token, thời hạn một giờ, địa chỉ IP và thông tin "
          "thiết bị. Cập nhật thời điểm đăng nhập gần nhất, ghi bản ghi lần đăng nhập với "
          "kết quả thành công, rồi trả cặp token."),
    ("P", "Bước tám, nếu có yêu cầu xác thực thêm thì dừng ở bước sáu, không tạo phiên."),
    ("H4", "1.5 Cổng kiểm duyệt rủi ro trước khi cấp token"),
    (
        "P",
        "Đây là điểm khác biệt quan trọng nhất của thiết kế so với mô hình chỉ ghi nhận "
        "sau. Với mô hình chỉ ghi nhận sau, kẻ có mật khẩu đúng sẽ nhận được token hợp lệ "
        "và có tối đa thời hạn của token để dùng hệ thống trước khi bị thu hồi. Thiết "
        "kế này chèn một cổng kiểm duyệt đồng bộ nằm sau bước xác thực mật khẩu và trước "
        "khi tạo phiên.",
    ),
    ("P", "Cổng gửi tên đăng nhập, mã người dùng, địa chỉ IP và thông tin thiết bị tới "
          "Detection Engine, với thời gian chờ tối đa ba giây. Detection Engine chấm "
          "điểm và trả về mức rủi ro, quyết định, cờ yêu cầu xác thực, và cờ suy giảm."),
    ("P", "Quy tắc áp dụng: chỉ hai mức rủi ro cao và nghiêm trọng mới bị giữ token. "
          "Các mức thấp và trung bình được phục vụ ngay, nhằm giữ độ trễ thấp cho người "
          "dùng bình thường. Khi bị giữ, hệ thống đặt cờ xác thực một lần và phát thử "
          "thách xác thực, đồng thời không tạo phiên và không phát hành token."),
    ("H4", "1.6 Quy định về xác thực đa yếu tố"),
    ("P", "Điều kiện phát sinh thử thách xác thực là quản trị viên đặt cờ bắt buộc cho "
          "tài khoản, hoặc cổng kiểm duyệt rủi ro đặt cờ xác thực một lần."),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.8, 2.2, 3.4],
            "header": ["Thuộc tính", "Giá trị", "Giải thích"],
            "rows": [
                ["Loại thử thách", "one_time hoặc persistent",
                 "Chọn theo nguồn phát sinh: cờ quản trị cho loại bền vững, cờ phát "
                 "hiện cho loại dùng một lần."],
                ["Thời hạn", "5 phút",
                 "Tính từ thời điểm tạo giao dịch xác thực."],
                ["Số lần thử tối đa", "3",
                 "Đạt ngưỡng thì giao dịch chuyển trạng thái thất bại và không thử lại được."],
                ["Kênh mặc định", "email",
                 "Mã sáu chữ số sinh bằng bộ sinh ngẫu nhiên an toàn."],
                ["Lưu mã", "Băm trước khi lưu",
                 "Mã xác thực được băm bằng thuật toán chậm có muối, không lưu dạng rõ."],
                ["Liên kết địa chỉ IP", "Lưu bản băm địa chỉ",
                 "Gắn thử thách với bối cảnh IP phát sinh."],
                ["Sau khi thành công", "Tạo phiên, xoá cờ nếu là loại một lần",
                 "Người dùng nhận token như thường lệ."],
            ],
        },
    ),
    ("CAP", "Bảng 2.1  Quy định về xác thực đa yếu tố"),
    ("H4", "1.7 Quy định chính sách của quy trình"),
    ("P", "Bảng sau liệt kê các quy định áp dụng và giá trị cụ thể:"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.7, 2.9, 3.8],
            "header": ["STT", "Quy định", "Giá trị áp dụng"],
            "rows": [
                ["1", "Ngưỡng giới hạn tần suất đăng nhập", "5 lần trên một địa chỉ IP trong cửa sổ 60 giây"],
                ["2", "Thông báo khi tài khoản không tồn tại và khi mật khẩu sai",
                 "Giống nhau: thông báo chung về thông tin đăng nhập không hợp lệ"],
                ["3", "Thời hạn access token", "1 giờ kể từ thời điểm tạo phiên"],
                ["4", "Thời hạn thử thách xác thực", "5 phút"],
                ["5", "Số lần thử xác thực tối đa", "3 lần, đạt ngưỡng thì giao dịch thất bại"],
                ["6", "Mức rủi ro bị giữ token", "Chỉ mức cao và nghiêm trọng"],
                ["7", "Thời gian chờ cổng kiểm duyệt", "3 giây"],
                ["8", "Xử lý khi cổng kiểm duyệt lỗi", "Mở cửa: vẫn cho đăng nhập, ghi nhật ký cảnh báo"],
                ["9", "Điều kiện đặt lại bộ đếm thất bại", "Khi đối chiếu mật khẩu thành công"],
                ["10", "Lưu trữ token", "Chỉ lưu bản băm, không lưu giá trị dạng rõ"],
            ],
        },
    ),
    ("CAP", "Bảng 2.2  Các quy định chính sách của quy trình đăng nhập"),
    ("H4", "1.8 Điểm quyết định trong quy trình"),
    (
        "P",
        "Quy trình có bốn điểm quyết định, mỗi điểm đều dẫn tới một kết cục khác nhau:",
    ),
    ("BUL",
     "Điểm quyết định 1, vượt ngưỡng tần suất: ghi bản ghi với kết quả bị giới hạn tần "
     "suất và từ chối với mã bốn trăm hai mươi chín."),
    ("BUL",
     "Điểm quyết định 2, mức rủi ro từ cổng kiểm duyệt: cao hoặc nghiêm trọng thì giữ "
     "token và bắt xác thực; thấp hoặc trung bình, hoặc cổng lỗi, thì đi tiếp."),
    ("BUL",
     "Điểm quyết định 3, cờ bắt buộc xác thực: có bất kỳ cờ nào thì phát thử thách và "
     "dừng quy trình tại đó."),
    ("BUL",
     "Điểm quyết định 4, kết quả xác thực thêm: mã đúng thì tạo phiên; mã sai thì tăng "
     "bộ đếm sai, đạt ba lần thì khoá giao dịch; quá hạn thì trả mã bốn trăm bốn."),
    ("H4", "1.9 Dữ liệu được tạo hoặc cập nhật"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.3, 2.0, 3.1],
            "header": ["Bảng", "Thao tác", "Điều kiện"],
            "rows": [
                ["rate_limits", "Tăng bộ đếm hoặc tạo dòng mới", "Mỗi lần gọi điểm cuối đăng nhập"],
                ["login_attempts", "Tạo một dòng", "Mỗi lần gọi điểm cuối đăng nhập, bất kể kết quả"],
                ["users.failed_login_count", "Tăng khi sai mật khẩu, đặt lại khi đúng", "Bước xác thực mật khẩu"],
                ["users.detection_mfa_once", "Đặt thành đúng", "Cổng kiểm duyệt trả về mức cao hoặc nghiêm trọng"],
                ["users.last_login_at", "Cập nhật thời điểm", "Tạo phiên thành công"],
                ["mfa_transactions", "Tạo dòng trạng thái chờ", "Khi phát thử thách xác thực"],
                ["mfa_notifications", "Tạo dòng với mã đã băm", "Kèm theo tạo giao dịch xác thực"],
                ["ip_addresses", "Tạo nếu chưa có, cập nhật thời điểm thấy lần cuối", "Khi tạo phiên"],
                ["sessions", "Tạo dòng phiên", "Xác thực hoàn tất, không cần thử thách thêm"],
            ],
        },
    ),
    ("CAP", "Bảng 2.3  Dữ liệu được tạo hoặc cập nhật trong quy trình đăng nhập"),
    ("H4", "1.10 Kết quả đầu ra"),
    ("P", "Quy trình có ba kết quả đầu ra duy nhất, tương ứng với ba kết cục:"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.6, 1.3, 4.5],
            "header": ["Kết cục", "Mã trả về", "Nội dung phản hồi"],
            "rows": [
                ["Cấp phiên và token", "200", "Access token, refresh token, mã định danh phiên"],
                ["Yêu cầu xác thực thêm", "200",
                 "Cờ yêu cầu xác thực là đúng, access token và refresh token rỗng, "
                 "mã định danh phiên là mã của giao dịch xác thực dùng để gọi điểm cuối xác nhận"],
                ["Từ chối", "401, 423, 429",
                 "Thông báo chung về thông tin không hợp lệ, tài khoản bị khoá, hoặc "
                 "quá nhiều lần gọi"],
            ],
        },
    ),
    ("CAP", "Bảng 2.4  Các kết quả đầu ra của quy trình đăng nhập"),
    ("H4", "1.11 Xử lý ngoại lệ"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.4, 1.5, 3.5],
            "header": ["Tình huống", "Mã trả về", "Cách xử lý"],
            "rows": [
                ["Tài khoản không tồn tại", "401",
                 "Ghi bản ghi lần đăng nhập với mã người dùng để trống; trả thông báo chung"],
                ["Mật khẩu sai", "401",
                 "Tăng bộ đếm thất bại trên tài khoản; ghi bản ghi; trả thông báo chung"],
                ["Tài khoản bị khoá", "423", "Ghi bản ghi với kết quả khoá; trả mã bốn trăm hai mươi ba"],
                ["Vượt ngưỡng tần suất", "429", "Ghi bản ghi với kết quả giới hạn tần suất; từ chối"],
                ["Thử thách xác thực không tồn tại hoặc quá hạn", "404",
                 "Không tạo phiên; người dùng phải đăng nhập lại từ đầu"],
                ["Mã xác thực sai", "401", "Tăng bộ đếm sai; ghi bản ghi kết quả xác thực thất bại"],
                ["Mã xác thực sai ba lần", "401",
                 "Giao dịch chuyển trạng thái thất bại; các lần sau không thử lại được"],
                ["Mã xác thực đã dùng", "400", "Từ chối để chống tái sử dụng mã"],
                ["Cổng kiểm duyệt không phản hồi", "200",
                 "Mở cửa: coi như không có rủi ro, ghi nhật ký cảnh báo, cấp token bình thường"],
                ["Cổng kiểm duyệt trả mã lỗi", "200", "Mở cửa, ghi nhật ký"],
                ["Cổng kiểm duyệt trả nội dung không phải JSON", "200", "Mở cửa, ghi nhật ký"],
                ["Cổng kiểm duyệt báo suy giảm", "200", "Mở cửa, tuyệt đối không coi là rủi ro cao"],
            ],
        },
    ),
    ("CAP", "Bảng 2.5  Xử lý ngoại lệ của quy trình đăng nhập"),
    ("NOTE",
     "Điểm cần lưu ý về tính nhất quán: cổng kiểm duyệt rủi ro trả về mã thành công cho "
     "phía người dùng trong mọi trường hợp lỗi của chính nó, vì lỗi nằm ở Detection "
     "Engine chứ không phải ở thông tin người dùng gửi. Lỗi chỉ được ghi vào nhật ký phía "
     "máy chủ để đội vận hành xử lý."),
    ("H4", "1.12 Nhật ký và kiểm toán"),
    (
        "P",
        "Quy trình này sinh hai loại dấu vết. Bản ghi lần đăng nhập ghi lại kết quả của mỗi "
        "lần gọi, kể cả các lần thất bại, và là đầu vào cho quy trình phát hiện ở mục 2. "
        "Nhật ký phát hiện của Detection Engine ghi lại việc cổng kiểm duyệt đã chấm điểm, "
        "và ghi cảnh báo vào nhật ký ứng dụng khi chế độ mở cửa được kích hoạt do cổng "
        "lỗi. Các thao tác thu hồi phiên sinh sau quy trình này được ghi vào bảng nhật ký "
        "kiểm toán.",
    ),
    ("H4", "1.13 Tiêu chí xác nhận quy trình thành công"),
    ("P", "Quy trình được xem là chạy đúng khi đồng thời thoả mãn các tiêu chí sau:"),
    (
        "BUL",
         "Mỗi lần gọi điểm cuối đăng nhập tạo đúng một dòng trong bảng lần đăng nhập, "
         "kể cả khi bị từ chối ở bước nào."),
    ("BUL",
     "Khi cổng kiểm duyệt trả mức cao hoặc nghiêm trọng: không có dòng nào trong bảng "
     "phiên được tạo cho lần đăng nhập đó."),
    ("BUL",
     "Khi cổng kiểm duyệt lỗi: bảng phiên vẫn có dòng, đồng thời nhật ký cảnh báo ghi "
     "rõ nguyên nhân mở cửa."),
    ("BUL",
     "Khi thử thách xác thực được trả về: có đúng một giao dịch xác thực ở trạng thái chờ "
     "và một bản ghi thông báo mã đã băm, không có bản ghi phiên nào."),
    ("BUL",
     "Khi xác thực thành công: giao dịch chuyển sang trạng thái hoàn thành, có bản ghi "
     "phiên, và cờ xác thực một lần được xoá nếu có."),
    ("BUL",
     "Mật khẩu và mã xác thực không tồn tại ở dạng rõ trong bất kỳ bảng nào; chỉ có bản "
     "băm."),
    ("BUL",
     "Địa chỉ IP lấy từ tiêu đề chuyển tiếp, không lấy từ nội dung yêu cầu, nên thay "
     "đổi giá trị trong nội dung không làm sai lệch địa chỉ ghi nhận."),

    # ================================================================ II.2
    ("H2", "Giới thiệu quy trình 2"),
    ("H3", "QUY TRÌNH PHÁT HIỆN ĐĂNG NHẬP BẤT THƯỜNG VÀ XỬ LÝ CẢNH BÁO SOC"),
    ("H4", "2.1 Tên quy trình và mục tiêu"),
    (
        "P",
        "Tên quy trình: Phát hiện đăng nhập bất thường và xử lý cảnh báo SOC. Mục tiêu là "
        "biến mỗi lần đăng nhập đã ghi nhận thành một mức rủi ro có căn cứ, và biến mức "
        "rủi ro cao thành một cảnh báo có bằng chứng mà con người có thể hành động. "
        "Quy trình chạy theo hai pha: pha máy, hoàn toàn tự động; và pha người, do phân "
        "viên SOC thực hiện.",
    ),
    ("H4", "2.2 Tác nhân và điều kiện kích hoạt"),
    (
        "P",
        "Tác nhân hệ thống: Detection Engine và ML Service. Tác nhân con người: phân viên "
        "SOC trong pha người. Điều kiện kích hoạt pha máy là sự xuất hiện của một bản ghi "
        "lần đăng nhập ở trạng thái chờ xử lý, do pha trước của quy trình đăng nhập tạo ra. "
        "Điều kiện kích hoạt pha người là sự xuất hiện của một cảnh báo ở trạng thái mở.",
    ),
    ("H4", "2.3 Dữ liệu đầu vào"),
    (
        "P",
        "Đầu vào pha máy là bản ghi lần đăng nhập, gồm: mã định danh sự kiện làm khoá "
        "lũy đẳng, mã người dùng hoặc để trống, tên đăng nhập đã thử, kết quả, cờ đã dùng "
        "xác thực thêm, địa chỉ IP, chuỗi định danh thiết bị, và thời điểm. Ngoài ra, "
        "Core App có thể gửi kèm tập đặc trưng đã tính sẵn; nếu có, hệ thống ghi nhận "
        "đặc trưng do đó được cung cấp từ nguồn nào.",
    ),
    (
        "P",
        "Đầu vào pha người là danh sách cảnh báo đã lọc, và khi chọn một cảnh báo là hồ sơ "
        "điều tra gộp từ bốn bảng: cảnh báo, lần đăng nhập, kết quả đánh giá rủi ro, và "
        "nhật ký chấm điểm từng giai đoạn.",
    ),
    ("H4", "2.4 Sáu đặc trưng đầu vào và cách tính"),
    (
        "P",
        "Sáu đặc trưng là đầu vào duy nhất mà cả quy tắc lẫn mô hình máy học đều được "
        "phép tham chiếu. Hệ thống tính chúng từ lịch sử đăng nhập của chính người dùng "
        "đó, vì vậy mỗi người có một ngưỡng bất thường riêng.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.6, 1.2, 1.2, 3.4],
            "header": ["Đặc trưng", "Kiểu", "Khoảng", "Cách tính trong hệ thống"],
            "rows": [
                ["hour_of_day", "Số nguyên", "0 đến 23", "Lấy giờ trong ngày của thời điểm đăng nhập"],
                ["fail_count_24h", "Số nguyên", "Từ 0",
                 "Đếm số lần đăng nhập có kết quả thất bại trong 24 giờ gần nhất, "
                 "không tính lần đang chấm"],
                ["ip_change_rate_7d", "Số thực", "0 đến 1",
                 "Tỉ lệ số địa chỉ IP khác nhau trong 7 ngày gần nhất so với tổng số IP "
                 "đã quan sát, tính cả IP của lần đang chấm"],
                ["new_device", "Đúng sai", "Không áp dụng",
                 "Chuỗi định danh thiết bị chưa từng xuất hiện trong 30 ngày gần nhất"],
                ["average_login_interval_seconds", "Số nguyên", "Từ 0",
                 "Trung bình khoảng cách thời gian giữa các lần đăng nhập liên tiếp, "
                 "lấy tối đa 10 lần gần nhất"],
                ["deviation_score", "Số thực", "0 đến 1",
                 "Độ lệch giữa khoảng cách thực tế của lần đang xét và khoảng cách trung "
                 "bình, chuẩn hoá về khoảng không vượt quá 1"],
            ],
        },
    ),
    ("CAP", "Bảng 2.6  Sáu đặc trưng đầu vào và cách tính"),
    ("NOTE",
     "Vì sao chỉ sáu đặc trưng: đây là điểm cân bằng giữa độ phủ và độ tin cậy. Thêm "
     "đặc trưng làm tăng khả năng bắt được hành vi bất thường, đồng thời tăng nguy cơ báo "
     "nhầm khi lịch sử người dùng còn ngắn. Giới hạn ở sáu đặc trưng cũng giữ cho hợp "
     "đồng giữa Detection Engine và ML Service được gọn và dễ kiểm chứng."),
    ("H4", "2.5 Cấu trúc quy tắc và cách tính điểm quy tắc"),
    (
        "P",
        "Mỗi quy tắc gồm bảy trường bắt buộc. Bảng sau mô tả từng trường:",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.4, 1.2, 4.8],
            "header": ["Trường", "Bắt buộc", "Ý nghĩa và ràng buộc"],
            "rows": [
                ["name", "Có", "Tên quy tắc, duy nhất trong một chính sách; hiển thị cho phân viên SOC"],
                ["field", "Có", "Tên một trong sáu đặc trưng; giá trị khác sẽ bị loại khỏi danh sách"],
                ["operator", "Có", "Phép so sánh; xem bảng phía dưới"],
                ["value", "Có", "Giá trị so sánh; với toán tử khoảng phải là mảng đúng hai phần tử"],
                ["weight", "Có", "Độ tin cậy của quy tắc, trong khoảng không vượt quá 1"],
                ["score", "Có", "Mức nghiêm trọng khi quy tắc chạy, trong khoảng không vượt quá 1"],
                ["enabled", "Có", "Cờ bật tắt quy tắc"],
            ],
        },
    ),
    ("CAP", "Bảng 2.7  Bảy trường bắt buộc của một quy tắc"),
    (
        "P",
        "Chính sách mặc định của hệ thống có bốn quy tắc đang bật, với tổng trọng số là "
        "một phẩm hai phần mười:",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.0, 2.0, 1.6, 1.1, 1.1, 1.6],
            "header": ["Tên quy tắc", "Đặc trưng", "Điều kiện", "Trọng số", "Điểm", "Ý nghĩa"],
            "rows": [
                ["unusual_hour", "hour_of_day", "Ngoài khoảng 7 đến 22", "0,30", "0,80",
                 "Đăng nhập ngoài khung giờ 07:00 đến 22:59"],
                ["multiple_failures", "fail_count_24h", "Từ 3 lần trở lên", "0,40", "0,90",
                 "Có ít nhất ba lần thất bại trong 24 giờ"],
                ["new_device", "new_device", "Bằng đúng", "0,20", "0,50",
                 "Đăng nhập từ thiết bị chưa từng thấy"],
                ["high_deviation", "deviation_score", "Từ 0,70 trở lên", "0,30", "0,70",
                 "Hành vi lệch mạnh so với thói quen của chính người dùng đó"],
            ],
        },
    ),
    ("CAP", "Bảng 2.8  Chính sách chấm điểm mặc định"),
    (
        "P",
        "Công thức tính điểm quy tắc chia cho tổng trọng số của tất cả quy tắc đang bật, "
        "kể cả những quy tắc không chạy:",
    ),
    ("CODE", "Đóng góp của quy tắc  =  điểm của quy tắc  ×  trọng số của quy tắc"),
    ("CODE", "điểm quy tắc  =  min(1,0 ;  tổng đóng góp  /  tổng trọng số của các quy tắc đang bật)"),
    (
        "P",
        "Nếu không có quy tắc nào đang bật thì điểm quy tắc bằng không. Quy tắc cấu hình sai "
        "bị loại khỏi danh sách và khỏi mẫu số, kèm ghi nhật ký, để một quy tắc sai không "
        "làm thay đổi kết quả của các quy tắc hợp lệ.",
    ),
    ("H4", "2.6 Gọi ML Service và xử lý khi ML không phản hồi"),
    (
        "P",
        "Detection Engine gửi sáu đặc trưng sang ML Service với thời gian chờ năm giây, "
        "kèm khoá dùng chung. ML Service trả về điểm bất thường đã chuẩn hoá trong khoảng "
        "không vượt quá một, cờ bất thường, phiên bản mô hình, và danh sách mã lý do.",
    ),
    (
        "P",
        "Bảng sau mô tả bốn tình huống và cách xử lý, trong đó cột ml_status được lưu vào "
        "bảng kết quả đánh giá để sau này truy vết:",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.6, 1.5, 1.4, 2.9],
            "header": ["Tình huống", "ml_status", "ml_score", "combined_score"],
            "rows": [
                ["ML phản hồi bình thường", "success", "Giá trị trong khoảng 0 đến 1",
                 "Tổng trọng số nhân với điểm quy tắc cộng với tổng trọng số nhân với điểm ML"],
                ["ML quá thời gian chờ", "unavailable", "NULL", "Bằng đúng điểm quy tắc"],
                ["ML trả mã lỗi", "error", "NULL", "Bằng đúng điểm quy tắc"],
                ["ML trả nội dung không hợp lệ", "error", "NULL", "Bằng đúng điểm quy tắc"],
            ],
        },
    ),
    ("CAP", "Bảng 2.9  Bốn tình huống gọi ML Service và cách tính điểm"),
    (
        "P",
        "Điểm cần nhấn mạnh: hệ thống không chia lại trọng số khi ML không phản hồi. Vì "
        "vậy tổng điểm sẽ thấp hơn so với khi có ML, tức hệ thống thận trọng hơn. Hành vi "
        "này có chủ ý vì theo tinh thần không có tín hiệu máy học thì không nên phóng đại "
        "mức rủi ro, đồng thời tránh việc hệ thống hạ cảnh báo chỉ vì dịch vụ phụ hỏng.",
    ),
    ("H4", "2.7 Công thức gộp điểm và phân loại mức rủi ro"),
    ("CODE", "điểm gộp  =  0,4  ×  điểm quy tắc  +  0,6  ×  điểm máy học      (khi máy học phản hồi)"),
    ("CODE", "điểm gộp  =  điểm quy tắc                                   (khi máy học không phản hồi)"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.5, 2.0, 1.4, 1.6, 1.9],
            "header": ["Mức rủi ro", "Khoảng điểm", "Quyết định", "Hành động", "Có tạo cảnh báo"],
            "rows": [
                ["Thấp", "Nhỏ hơn 0,25", "allow", "ALLOW", "Không"],
                ["Trung bình", "Từ 0,25 đến nhỏ hơn 0,50", "allow", "ALLOW_LOG", "Không"],
                ["Cao", "Từ 0,50 đến nhỏ hơn 0,75", "challenge", "REQUIRE_MFA", "Có"],
                ["Nghiêm trọng", "Từ 0,75 trở lên", "block", "BLOCK_ALERT", "Có"],
            ],
        },
    ),
    ("CAP", "Bảng 2.10  Bốn mức rủi ro, quyết định và hành động tương ứng"),
    (
        "P",
        "Ngưỡng lấy từ cấu hình của chính sách đang kích hoạt, nên có thể điều chỉnh "
        "không cần sửa mã nguồn. Cấu hình sai không làm hỏng quy trình: hệ thống ghi nhật "
        "ký và dùng ngưỡng mặc định để tiếp tục.",
    ),
    ("H4", "2.8 Ví dụ tính tay để kiểm chứng công thức"),
    (
        "P",
        "Ví dụ sau dùng bốn quy tắc mặc định với đặc trưng: đăng nhập lúc hai giờ sáng, "
        "năm lần thất bại trong 24 giờ, thiết bị mới, độ lệch 0,8.",
    ),
    ("TABLE",
        {
            "caption": None,
            "widths": [2.6, 1.8, 1.4, 2.6],
            "header": ["Quy tắc chạy", "Điểm × Trọng số", "Đóng góp", "Sau khi chia mẫu số"],
            "rows": [
                ["unusual_hour", "0,80 × 0,30", "0,240", "0,2000"],
                ["multiple_failures", "0,90 × 0,40", "0,360", "0,3000"],
                ["new_device", "0,50 × 0,20", "0,100", "0,0833"],
                ["high_deviation", "0,70 × 0,30", "0,210", "0,1750"],
                ["Tổng", "Tổng trọng số là 1,20", "0,910", "0,7583"],
            ],
        },
    ),
    ("CAP", "Bảng 2.11  Ví dụ tính điểm quy tắc theo chính sách mặc định"),
    ("P", "Suy ra ba kết quả khác nhau từ cùng một tập đặc trưng:"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.4, 1.4, 1.6, 1.6, 1.4],
            "header": ["Tình huống", "Điểm quy tắc", "Điểm ML", "Điểm gộp", "Mức rủi ro"],
            "rows": [
                ["ML phản hồi điểm 0,72", "0,7583", "0,72",
                 "0,4 × 0,7583 + 0,6 × 0,72 = 0,7353", "Cao"],
                ["ML quá thời gian chờ", "0,7583", "NULL", "0,7583", "Nghiêm trọng"],
                ["Không có quy tắc nào chạy", "0,0000", "0,72",
                 "0,4 × 0 + 0,6 × 0,72 = 0,4320", "Trung bình"],
            ],
        },
    ),
    ("CAP", "Bảng 2.12  Ba tình huống cùng đặc trưng, ba kết quả khác nhau"),
    ("NOTE",
     "Điểm cần lưu ý khi trình bày kết quả: cùng một hành vi nhưng mức rủi ro khác nhau "
     "tùy thuộc ML Service có phản hồi hay không. Vì vậy khi điều tra một cảnh báo, phân "
     "viên SOC cần xem cột ml_status trong kết quả đánh giá để biết chấm điểm có đầy đủ "
     "hay không. Nếu ml_status là unavailable hoặc error, cảnh báo được tạo ra nhưng chỉ dựa "
     "trên luật, và đó là lý do dễ xảy ra báo nhầm hơn trong các ca đó."),
    ("H4", "2.9 Điều kiện tạo cảnh báo và không tạo cảnh báo"),
    ("P", "Quy tắc về mặt logic rất gọn: có tạo cảnh báo khi và chỉ khi mức rủi ro là cao "
          "hoặc nghiêm trọng. Hai mức thấp và trung bình chỉ ghi kết quả đánh giá và nhật ký."),
    (
        "P",
        "Có một điểm dễ hiểu nhầm cần nêu rõ: mức cao vẫn tạo cảnh báo, kể cả khi người "
        "dùng đã vượt qua bước xác thực thêm và đăng nhập được. Lý do là người dùng đó vẫn "
        "có thể là chủ tài khoản thật đang bị lợi dụng, hoặc là chính tài khoản đó đang bị "
        "dò mật khẩu. Cảnh báo cho phân viên SOC theo dõi xu hướng thay vì chỉ xử lý từng "
        "sự kiện.",
    ),
    (
        "P",
        "Ngoài ra còn ba trường hợp đặc biệt không tạo cảnh báo dù có thể có điểm cao: khi "
        "không có chính sách nào đang kích hoạt, hệ thống cho phép đăng nhập và ghi nhật ký "
        "lý do; khi chính sách có cấu hình sai, hệ thống dùng giá trị mặc định rồi xử lý "
        "bình thường; và khi quá trình chấm điểm gặp lỗi ngoài dự kiến, bản ghi lần đăng "
        "nhập được đánh dấu là lỗi để chờ chấm lại, chưa tạo cảnh báo.",
    ),
    ("H4", "2.10 Pha máy: các bước xử lý chi tiết"),
    ("P", "Pha máy gồm bảy bước, kết thúc bằng việc gửi hành động bảo vệ nếu có:"),
    ("BUL", "Bước một, xác thực khoá dùng chung; sai hoặc thiếu thì từ chối với mã bốn trăm một."),
    ("BUL", "Bước hai, tra cứu theo mã định danh sự kiện. Nếu đã có, trả về bản ghi cũ và trạng thái hiện tại, không chấm lại. Đây là cơ chế lũy đẳng: giao lại cùng sự kiện không sinh bản ghi trùng."),
    ("BUL", "Bước ba, tạo bản ghi lần đăng nhập ở trạng thái chờ xử lý, rồi tính sáu đặc trưng."),
    ("BUL", "Bước bốn, đánh giá quy tắc và gọi ML Service. Ghi nhật ký cho từng quy tắc chạy kèm đóng góp đã chuẩn hoá, và ghi nhật ký cho mỗi quy tắc bị loại."),
    ("BUL", "Bước năm, gộp điểm, xếp mức rủi ro, ghi bảng kết quả đánh giá với đầy đủ ba điểm, trạng thái ML, các quy tắc đã chạy, mã lý do ML và tập đặc trưng đã dùng."),
    ("BUL", "Bước sáu, nếu mức rủi ro cao hoặc nghiêm trọng thì tạo cảnh báo ở trạng thái mở, ghi lý do phát hiện và cụm điểm, rồi trỏ ngược từ bản ghi lần đăng nhập tới cảnh báo chính."),
    ("BUL", "Bước bảy, commit xong thì mới gửi hành động bảo vệ sang Core App. Thứ tự này bảo đảm Core App chậm hoặc chết không thể làm mất đánh giá và cảnh báo đã ghi. Kết quả trả về là mã chấp nhận kèm mã định danh bản ghi và trạng thái xử lý."),
    ("H4", "2.11 Bốn hành động bảo vệ và điều kiện dùng"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.8, 1.2, 1.3, 3.1],
            "header": ["Hành động", "Tự động", "Gửi khi", "Tác dụng"],
            "rows": [
                ["REQUIRE_MFA", "Có", "Mức rủi ro cao",
                 "Bắt xác thực đa yếu tố ở lần đăng nhập kế tiếp, đồng thời thu hồi mọi "
                 "phiên đang hoạt động"],
                ["REVOKE_SESSIONS", "Có", "Mức rủi ro nghiêm trọng",
                 "Thu hồi toàn bộ phiên đang hoạt động của tài khoản"],
                ["LOCK_USER", "Không", "Phân viên SOC yêu cầu",
                 "Khoá tài khoản và thu hồi phiên; dùng khi đã điều tra và có bằng chứng rõ"],
                ["FORCE_LOGOUT", "Không", "Phân viên SOC yêu cầu",
                 "Buộc rời toàn bộ phiên, tách khỏi khoá tài khoản để thể hiện ý định khác"],
            ],
        },
    ),
    ("CAP", "Bảng 2.13  Bốn hành động bảo vệ và điều kiện sử dụng"),
    (
        "P",
        "Hai quyết định thiết kế đáng giải thích vì sao mức nghiêm trọng không dùng khoá "
        "tài khoản. Một là khoá tài khoản là hành động khó đảo ngược: nếu mô hình báo "
        "nhầm, người dùng hợp lệ bị khoá và không tự thoát ra được nếu không có quản trị "
        "viên mở khoá. Hai là thu hồi phiên rẻ và đảo ngược được: kẻ tấn công mất quyền "
        "truy cập ngay, còn người dùng hợp lệ chỉ tốn thêm một bước xác thực. Vì báo nhầm "
        "của mô hình là tình huống thường gặp còn hậu quả khoá oan thì nghiêm trọng, nhóm "
        "chọn phương án đảo ngược được cho trường hợp tự động, và giữ khoá tài khoản làm "
        "hành động thủ công cho con người.",
    ),
    ("P",
        "Quyết định còn lại là hành động bắt xác thực phải kèm thu hồi phiên. Lý do: cờ "
        "xác thực một lần chỉ có tác dụng cho lần đăng nhập kế tiếp, còn token đã cấp trước "
        "đó vẫn hợp lệ tới hết một giờ. Nếu không thu hồi thì yêu cầu xác thực trở nên vô "
        "nghĩa, vì người đã có token không cần xác thực để tiếp tục dùng hệ thống.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.8, 5.6],
            "header": ["Đặc tính", "Giá trị"],
            "rows": [
                ["Thời gian chờ khi gửi hành động", "3 giây, để không giữ yêu cầu chấm điểm mở chờ"],
                ["Xử lý lỗi", "Ghi nhật ký và nuốt lỗi; Detection Engine không được chết vì lỗi của Core App"],
                ["Khoá lũy đẳng", "Khoá có dạng tiền tố Detection, mã bản ghi lần đăng nhập, tên hành động; giao lại sau thời gian chờ quá hạn là thao tác rỗng"],
                ["Mã cảnh báo đính kèm", "Gửi kèm để phân viên SOC đối chiếu được giữa hai cơ sở dữ liệu"],
            ],
        },
    ),
    ("CAP", "Bảng 2.14  Đặc tính vận hành của việc gửi hành động bảo vệ"),
    ("H4", "2.12 Pha người: vòng đời cảnh báo"),
    (
        "P",
        "Cảnh báo có bốn trạng thái. Mở là trạng thái vừa tạo, chưa có người nhận. Đã tiếp "
        "nhận là khi một phân viên nhận trách nhiệm, kèm người được giao. Đã kết luận là khi "
        "có kết luận điều tra và người kết luận. Báo nhầm là trạng thái riêng dành cho ca "
        "hệ thống nhầm, mang thông tin phục vụ hiệu chỉnh chính sách.",
    ),
    (
        "P",
        "Có bốn hành động mà phân viên SOC thực hiện. Tiếp nhận: ghi nhận trách nhiệm. Ghi "
        "chú: bổ sung thông tin điều tra. Yêu cầu hành động bảo vệ: thực thi một trong bốn "
        "hành động ở bảng 2.13. Kết luận hoặc đánh dấu báo nhầm: kết thúc vòng đời cảnh báo. "
        "Riêng leo thang được ghi thêm vào dòng thời gian mà không đóng cảnh báo, vì vấn đề "
        "chưa được giải quyết.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.5, 1.2, 4.7],
            "header": ["Hành động", "Ai thực hiện", "Quy định"],
            "rows": [
                ["Xem danh sách cảnh báo", "Phân viên SOC, quản trị viên, quản lý bảo mật",
                 "Lọc theo trạng thái, mức rủi ro, người được giao và khoảng thời gian; phân trang"],
                ["Xem hồ sơ điều tra", "Phân viên SOC, quản trị viên",
                 "Gộp cảnh báo, lần đăng nhập, kết quả đánh giá và nhật ký chấm điểm"],
                ["Tiếp nhận", "Phân viên SOC",
                 "Chỉ được khi chưa có người nhận; nếu đã có người nhận thì trả mã xung đột"],
                ["Ghi chú điều tra", "Phân viên SOC",
                 "Ghi vào dòng thời gian với loại sự kiện ghi chú; không đổi trạng thái"],
                ["Yêu cầu hành động bảo vệ", "Phân viên SOC, quản trị viên",
                 "Bắt buộc có lý do; hệ thống trả về số phiên đã thu hồi"],
                ["Kết luận", "Phân viên SOC",
                 "Bắt buộc có nội dung kết luận; ghi người kết luận và thời điểm"],
                ["Đánh dấu báo nhầm", "Phân viên SOC",
                 "Dùng khi xác nhận hệ thống nhầm; phải ghi người thực hiện và thời điểm"],
                ["Leo thang", "Phân viên SOC",
                 "Ghi vào dòng thời gian; chuyển quyết định phê duyệt lên quản lý bảo mật"],
            ],
        },
    ),
    ("CAP", "Bảng 2.15  Hành động của phân viên SOC và quy định kèm theo"),
    ("H4", "2.13 Xử lý sự kiện trùng"),
    (
        "P",
        "Có ba tầng chống xử lý trùng. Tầng thứ nhất là ràng buộc duy nhất trên mã định "
        "danh sự kiện ở cấp cơ sở dữ liệu: hai lần ghi cùng một mã định danh không thể "
        "cùng tồn tại. Tầng thứ hai là kiểm tra trước khi chấm: nếu đã thấy bản ghi, "
        "Detection Engine trả về bản ghi đó kèm trạng thái hiện tại, không chấm lại. Tầng "
        "thứ ba là khoá lũy đẳng trên các hành động bảo vệ: nếu hành động đã có hiệu lực, "
        "phản hồi trả về trạng thái đã áp dụng thay vì thực hiện lại.",
    ),
    (
        "P",
        "Lợi ích thực tế: nếu một yêu cầu bị giao lại do lỗi mạng, hoặc hành động bảo vệ "
        "được gửi lại sau thời gian chờ quá hạn, hệ thống không sinh cảnh báo trùng và "
        "không thu hồi phiên hai lần. Nhờ vậy có thể an toàn thử giao lại thay vì phải "
        "suy nghĩ xem lần trước đã tới đích chưa.",
    ),
    ("H4", "2.14 Dữ liệu được tạo hoặc cập nhật"),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [2.5, 2.0, 3.9],
            "header": ["Bảng", "Thao tác", "Điều kiện"],
            "rows": [
                ["login_attempts", "Cập nhật trạng thái, mức rủi ro, quyết định, trỏ cảnh báo",
                 "Mỗi lần chấm thành công; hoặc đánh dấu lỗi khi chấm gặp ngoại lệ"],
                ["risk_assessments", "Tạo một dòng",
                 "Mỗi lần chấm thành công; ràng buộc duy nhất theo bản ghi lần đăng nhập"],
                ["detection_logs", "Tạo nhiều dòng",
                 "Bốn nhóm giai đoạn: đánh giá quy tắc, gọi ML, chấm điểm, gửi hành động"],
                ["alerts", "Tạo một dòng ở trạng thái mở",
                 "Mức rủi ro cao hoặc nghiêm trọng"],
                ["alert_timeline", "Tạo dòng loại sự kiện tạo cảnh báo",
                 "Ngay khi tạo cảnh báo"],
                ["sessions", "Cập nhật thời điểm thu hồi cho mọi phiên đang mở",
                 "Khi thực thi bất kỳ hành động bảo vệ nào"],
                ["users", "Cập nhật cờ xác thực một lần hoặc trạng thái khoá",
                 "Tương ứng với hành động bắt xác thực lại hoặc khoá tài khoản"],
                ["audit_logs", "Tạo dòng nhật ký kiểm toán",
                 "Khi phân viên thực hiện hành động bảo vệ"],
            ],
        },
    ),
    ("CAP", "Bảng 2.16  Dữ liệu được tạo hoặc cập nhật trong quy trình phát hiện"),
    ("H4", "2.15 Nhật ký và kiểm toán"),
    (
        "P",
        "Quy trình này tạo dấu vết ở ba nơi. Nhật ký chấm điểm ghi lại dấu vết của từng "
        "giai đoạn với mã yêu cầu chung, nhờ đó có thể nối toàn bộ chuỗi xử lý của một lần "
        "đăng nhập. Bảng kết quả đánh giá lưu ba điểm, trạng thái ML, các quy tắc đã "
        "chạy kèm đóng góp, mã lý do ML và tập đặc trưng, làm căn cứ giải thích quyết "
        "định. Dòng thời gian cảnh báo ghi mọi thao tác của phân viên.",
    ),
    (
        "NOTE",
         "Vì sao lưu tập đặc trưng đã dùng cùng kết quả: đây là điều kiện tiên quyết để "
         "chứng minh kết quả chấm điểm có thể tái tạo được. Khi có khiếu nại về một cảnh "
         "báo, chỉ cần đọc lại tập đặc trưng đã lưu và chính sách đã dùng là chạy lại được "
         "kết quả. Thiết kế này cũng giúp phân biệt được lỗi do chấm điểm với lỗi do dữ "
         "liệu đầu vào sai."),
    ("H4", "2.16 Tiêu chí xác nhận quy trình thành công"),
    ("P", "Quy trình được xem là chạy đúng khi thoả mãn toàn bộ tiêu chí sau:"),
    (
        "BUL",
         "Mỗi bản ghi lần đăng nhập có trạng thái đã xử lý và đúng một dòng kết quả "
         "đánh giá tương ứng; ràng buộc duy nhất ở cấp cơ sở dữ liệu bảo đảm điều này."),
    ("BUL",
         "Nhật ký chấm điểm có đủ bốn nhóm giai đoạn cho mỗi lần chấm: đánh giá quy tắc, "
         "gọi ML, chấm điểm, gửi hành động."),
    ("BUL",
         "Tổng các đóng góp đã chuẩn hoá trong nhật ký bằng đúng điểm quy tắc trong kết "
         "quả đánh giá. Đây là cách phân viên tự kiểm chứng mà không cần biết công thức bên trong."),
    ("BUL",
         "Tồn tại cảnh báo khi và chỉ khi mức rủi ro là cao hoặc nghiêm trọng."),
    ("BUL",
         "Mỗi cảnh báo có đủ bằng chứng: ba điểm, trạng thái ML, danh sách quy tắc chạy, "
         "mã lý do, và bản ghi lần đăng nhập kèm địa chỉ IP và thiết bị."),
    ("BUL",
         "Gửi lại cùng một mã định danh sự kiện không tạo bản ghi thứ hai và không tạo "
         "cảnh báo thứ hai."),
    ("BUL",
         "Khi ML không phản hồi: trường trạng thái ML là không sẵn sàng hoặc lỗi, điểm ML "
         "là trống, điểm gộp bằng đúng điểm quy tắc, và có dòng nhật ký ghi lý do."),
    ("BUL",
         "Khi hành động bảo vệ được áp dụng: mọi phiên đang mở của tài khoản có thời điểm "
         "thu hồi khác trống, và phản hồi trả về số lượng phiên đã thu hồi."),
    ("BUL",
         "Gọi lại hành động đã áp dụng trả về trạng thái đã áp dụng và số phiên thu hồi "
         "bằng không."),
    ("BUL",
         "Mỗi lần phân viên chuyển trạng thái cảnh báo đều có một dòng dòng thời gian tương "
         "ứng với giá trị cũ và giá trị mới."),
    ("BUL",
         "Khi chấm điểm gặp lỗi ngoài dự kiến: bản ghi lần đăng nhập ở trạng thái lỗi, có "
         "dòng nhật ký, và không có cảnh báo nào được tạo."),

    # ================================================================ II.3
    ("H2", "Yêu cầu chức năng nghiệp vụ"),
    (
        "P",
        "Mục này phân tích yêu cầu theo từng đối tượng sử dụng. Trước bảng chức năng "
        "của mỗi đối tượng, báo cáo trình bày rõ đối tượng đó là ai, vì sao hệ thống cần "
        "họ, và nếu thiếu họ thì nghiệp vụ nào không thực hiện được.",
    ),
    # ------------------------------------------------ Người dùng
    ("H3", "Chức năng của đối tượng Người dùng hệ thống"),
    (
        "P",
        "Người dùng hệ thống là chủ tài khoản đăng nhập vào ứng dụng. Đây là đối tượng "
        "duy nhất có mối quan hệ trực tiếp với hệ thống bị bảo vệ.",
    ),
    ("P",
        "Lý do cần đối tượng này: hệ thống không thể xác thực nếu không có bên cung cấp "
        "thông tin đăng nhập. Nếu thiếu đối tượng này thì toàn bộ chuỗi phát hiện không có "
        "đầu vào, vì mọi lần đăng nhập đều do người dùng thực hiện.",
    ),
    ("P",
        "Trách nhiệm: đăng nhập bằng thông tin do hệ thống cấp, hoàn thành bước xác thực "
        "đa yếu tố khi được yêu cầu, tự quản lý phiên của mình, và báo lại khi phát hiện "
        "đăng nhập lạ."),
    ("P",
        "Dữ liệu được phép truy cập: hồ sơ tài khoản của chính mình, danh sách phiên đang "
        "mở của chính mình, danh sách thiết bị tin cậy của chính mình, và thông báo "
        "trong ứng dụng dành cho chính mình. Không được truy cập bất kỳ dữ liệu lần đăng "
        "nhập, cảnh báo, hay nhật ký chấm điểm nào của người khác.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 1.9, 1.2, 2.3, 1.3, 0.8],
            "header": ["STT", "Công việc", "Loại công việc", "Quy định liên quan",
                       "Giao diện", "Ghi chú"],
            "rows": [
                ["1", "Đăng nhập", "Tra cứu",
                 "- Tên đăng nhập từ 3 đến 50 ký tự, chỉ chữ, số và gạch dưới\n"
                 "- Mật khẩu tối thiểu 8 ký tự khi đăng ký\n"
                 "- Giới hạn 5 lần trên mỗi địa chỉ IP trong 60 giây\n"
                 "- Thông báo chung khi sai tên đăng nhập hoặc sai mật khẩu\n"
                 "- Mức rủi ro cao hoặc nghiêm trọng thì bắt xác thực thêm trước khi cấp token",
                 "Màn hình đăng nhập", "Điểm cuối đăng nhập"],
                ["2", "Xác thực đa yếu tố", "Cập nhật",
                 "- Thử thách hết hạn sau 5 phút\n"
                 "- Tối đa 3 lần thử; đạt ngưỡng thì giao dịch thất bại\n"
                 "- Mã dùng một lần, không tái sử dụng\n"
                 "- Chỉ xoá cờ xác thực một lần sau khi xác thực thành công",
                 "Màn hình nhập mã", "Điểm cuối xác nhận mã"],
                ["3", "Xem danh sách phiên", "Trích xuất",
                 "- Chỉ hiển thị phiên chưa hết hạn và chưa bị thu hồi\n"
                 "- Mỗi phiên hiển thị địa chỉ IP, thiết bị, thời hạn, thời điểm hoạt động gần nhất\n"
                 "- Đánh dấu phiên hiện tại",
                 "Màn hình quản lý phiên", "Không có thao tác ghi"],
                ["4", "Thu hồi phiên của chính mình", "Cập nhật",
                 "- Chỉ được thu hồi phiên thuộc về chính mình\n"
                 "- Thu hồi phiên của người khác bị từ chối với mã 403\n"
                 "- Ghi nhật ký kiểm toán với thông tin thu hồi",
                 "Màn hình quản lý phiên", "Có ghi audit"],
                ["5", "Làm mới token", "Cập nhật",
                 "- Token làm mới phải khớp bản băm đang lưu và phiên chưa bị thu hồi\n"
                 "- Phiên đã hết hạn thì từ chối\n"
                 "- Xoay mã định danh token sau mỗi lần làm mới",
                 "Không có giao diện riêng", "Tự động theo phía máy chủ"],
                ["6", "Đăng xuất", "Cập nhật",
                 "- Xác thực bằng access token hiện tại\n"
                 "- Đặt thời điểm thu hồi, không xoá dòng phiên",
                 "Nút đăng xuất", "Có ghi audit"],
                ["7", "Quản lý thiết bị tin cậy", "Cập nhạt",
                 "- Ràng buộc duy nhất theo cặp tài khoản và vân tay thiết bị\n"
                 "- Thiết bị hết hạn không còn tác dụng\n"
                 "- Chỉ xem được thiết bị của chính mình",
                 "Màn hình thiết bị", "Điểm cuối thiết bị"],
                ["8", "Xem thông báo trong ứng dụng", "Trích xuất",
                 "- Chỉ thông báo dành cho chính mình\n"
                 "- Đánh dấu đã đọc kèm thời điểm đọc\n"
                 "- Thông báo hết hạn không hiển thị",
                 "Hộp thông báo", "Không có thao tác ghi"],
            ],
        },
    ),
    ("CAP", "Bảng 2.17  Yêu cầu chức năng nghiệp vụ của Người dùng hệ thống"),
    # ------------------------------------------------ SOC Analyst
    ("H3", "Chức năng của đối tượng SOC Analyst"),
    (
        "P",
        "SOC Analyst là phân viên trực trong Trung tâm Giám sát An ninh, làm việc theo "
        "ca và xử lý hàng đợi cảnh báo. Trong hệ thống này, họ là đối tượng sử dụng nhiều "
        "thời gian nhất.",
    ),
    (
        "P",
        "Lý do cần đối tượng này: cảnh báo mức cao cần con người xem ngữ cảnh, đánh giá "
        "bằng chứng, và quyết định giữa ba khả năng là hợp lệ, báo nhầm, hay là tấn công "
        "thật. Detection Engine chỉ đưa ra một mức rủi ro kèm điểm số; nó không biết "
        "rằng nhân viên đó đang đi công tác nước ngoài, rằng ca đêm hệ thống chạy tác vụ "
        "định kỳ, hay rằng thiết bị vừa được thay thế sau sự cố hỏng hóc. Việc quyết định "
        "này cần tri thức ngữ cảnh mà phần mềm không có.",
    ),
    (
        "P",
        "Nếu thiếu đối tượng này: mọi cảnh báo mức cao sẽ phải xử lý bằng phán đoán của "
        "quản trị viên, hoặc tệ hơn là bị bỏ qua. Hệ thống sẽ tạo ra khối lượng cảnh báo "
        "mà không ai tiêu thụ, và tín hiệu thật sẽ chìm trong nhiễu.",
    ),
    (
        "P",
        "Trách nhiệm: theo dõi hàng đợi cảnh báo, thu thập bằng chứng, tiếp nhận cảnh báo "
        "trước khi xử lý để không trùng công, ghi chú kết quả điều tra, yêu cầu hành động "
        "bảo vệ khi cần, và kết luận hoặc đánh dấu báo nhầm. Trong hệ thống, họ là người "
        "duy nhất thực hiện được nhóm hành động bảo vệ thủ công.",
    ),
    (
        "P",
        "Dữ liệu được phép truy cập: toàn bộ cảnh báo theo quyền được giao, hồ sơ điều "
        "tra đầy đủ của cảnh báo đó gồm lần đăng nhập, kết quả đánh giá và nhật ký chấm "
        "điểm, và dòng thời gian cảnh báo. Họ không được truy cập trực tiếp bảng kết quả "
        "đánh giá rủi ro để sửa, không được sửa chính sách, và không được quản lý tài "
        "khoản.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 1.9, 1.2, 2.3, 1.3, 0.8],
            "header": ["STT", "Công việc", "Loại công việc", "Quy định liên quan",
                       "Giao diện", "Ghi chú"],
            "rows": [
                ["1", "Xem danh sách cảnh báo", "Trích xuất",
                 "- Lọc theo trạng thái, mức rủi ro, người được giao và khoảng thời gian\n"
                 "- Sắp xếp theo thời điểm tạo giảm dần\n"
                 "- Có phân trang\n"
                 "- Chỉ trả về cảnh báo theo phạm vi quyền",
                 "Danh sách cảnh báo", "Không có thao tác ghi"],
                ["2", "Xem hồ sơ điều tra", "Trích xuất",
                 "- Gộp bốn nguồn: cảnh báo, lần đăng nhập, kết quả đánh giá, nhật ký chấm điểm\n"
                 "- Phải hiển thị trạng thái ML để biết chấm điểm có đầy đủ không\n"
                 "- Xác minh danh tính người bị nghi ngờ qua điểm cuối nội bộ của Core App",
                 "Chi tiết cảnh báo", "Không có thao tác ghi"],
                ["3", "Tiếp nhận cảnh báo", "Cập nhật",
                 "- Chỉ được khi cảnh báo chưa có người nhận\n"
                 "- Nếu đã có người nhận thì trả mã 409 chứ không ghi đè\n"
                 "- Bắt buộc ghi dòng thời gian với giá trị cũ và giá trị mới\n"
                 "- Ghi người thực hiện và thời điểm",
                 "Chi tiết cảnh báo", "Có ghi audit"],
                ["4", "Ghi chú điều tra", "Lưu trữ",
                 "- Ghi vào dòng thời gian với loại sự kiện ghi chú\n"
                 "- Không thay đổi trạng thái cảnh báo\n"
                 "- Ghi người thực hiện và thời điểm",
                 "Chi tiết cảnh báo", "Có ghi audit"],
                ["5", "Đánh dấu báo nhầm", "Cập nhật",
                 "- Bắt buộc lưu người thực hiện và thời điểm\n"
                 "- Ghi vào dòng thời gian để phân tích nguyên nhân báo nhầm\n"
                 "- Đây là nguồn dữ liệu để hiệu chỉnh chính sách về sau",
                 "Chi tiết cảnh báo", "Có ghi audit"],
                ["6", "Kết luận cảnh báo", "Cập nhật",
                 "- Bắt buộc có nội dung kết luận\n"
                 "- Ghi người kết luận và thời điểm kết luận\n"
                 "- Chuyển trạng thái sang đã kết luận và ghi dòng thời gian",
                 "Chi tiết cảnh báo", "Có ghi audit"],
                ["7", "Leo thang cảnh báo", "Cập nhật",
                 "- Theo quyền được cấp\n"
                 "- Không đóng cảnh báo, chỉ ghi dòng thời gian loại leo thang\n"
                 "- Chuyển quyết định phê duyệt lên quản lý bảo mật\n"
                 "- Có thể ghi kèm ghi chú lý do leo thang",
                 "Chi tiết cảnh báo", "Có ghi audit"],
                ["8", "Yêu cầu hành động bảo vệ", "Cập nhật",
                 "- Bắt buộc có lý do\n"
                 "- Kiểm tra hành động hợp lệ, trả mã 400 nếu không\n"
                 "- Phản hồi trả về số phiên đã thu hồi\n"
                 "- Ghi dòng thời gian và nhật ký kiểm toán\n"
                 "- Nếu hành động đã có hiệu lực thì trả trạng thái đã áp dụng",
                 "Chi tiết cảnh báo", "Có ghi audit"],
                ["9", "Xem dòng thời gian cảnh báo", "Trích xuất",
                 "- Trả về toàn bộ sự kiện theo thứ tự thời gian\n"
                 "- Mỗi sự kiện có loại, người thực hiện, giá trị cũ, giá trị mới và ghi chú",
                 "Chi tiết cảnh báo", "Không có thao tác ghi"],
                ["10", "Xem bảng điều khiển", "Trích xuất",
                 "- Tổng số cảnh báo theo trạng thái\n"
                 "- Cảnh báo theo mức rủi ro\n"
                 "- Lý do vi phạm phổ biến\n"
                 "- Khối lượng công việc của từng phân viên",
                 "Bảng điều khiển", "Không có thao tác ghi"],
            ],
        },
    ),
    ("CAP", "Bảng 2.18  Yêu cầu chức năng nghiệp vụ của SOC Analyst"),
    # ------------------------------------------------ Security Admin
    ("H3", "Chức năng của đối tượng Security Administrator"),
    (
        "P",
        "Security Administrator là quản trị viên bảo mật, phụ trách cấu hình và bảo trì hệ "
        "thống phát hiện. Đây là đối tượng có quyền thay đổi tham số mà người dùng và "
        "phân viên SOC không được phép.",
    ),
    (
        "P",
        "Lý do cần đối tượng này: hệ thống chấm điểm dựa trên chính sách, và chính sách "
        "phải được ai đó điều chỉnh theo thực tế vận hành. Khi một mô hình báo nhầm nhiều "
        "trong một tình huống cụ thể, cần tăng trọng số quy tắc liên quan hoặc điều chỉnh "
        "ngưỡng. Việc này không thể giao cho phân viên SOC vì họ tập trung vào xử lý cảnh "
        "báo, và cũng không giao cho người dùng. Nếu thiếu đối tượng này, chính sách sẽ "
        "phải sửa trong mã nguồn và triển khai lại, không phản hồi được với thực tế vận hành.",
    ),
    (
        "P",
        "Trách nhiệm: quản lý chính sách chấm điểm, quản lý tài khoản và gán vai trò, cấu "
        "hình ngưỡng và trọng số, thu hồi phiên của người dùng khác khi có yêu cầu bảo vệ, "
        "và theo dõi nhật ký kiểm toán.",
    ),
    (
        "P",
        "Dữ liệu được phép truy cập: toàn bộ chính sách và lịch sử kích hoạt, danh sách "
        "tài khoản và vai trò, toàn bộ cảnh báo, và toàn bộ nhật ký kiểm toán. Quyền truy "
        "cập rộng hơn phân viên SOC ở chỗ được đọc chính sách và sửa tài khoản, nhưng vẫn "
        "không có quyền phê duyệt leo thang, vì đó là vai trò của quản lý bảo mật.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 1.9, 1.2, 2.3, 1.3, 0.8],
            "header": ["STT", "Công việc", "Loại công việc", "Quy định liên quan",
                       "Giao diện", "Ghi chú"],
            "rows": [
                ["1", "Xem danh sách chính sách", "Trích xuất",
                 "- Trả về phiên bản, tên, mô tả, số quy tắc và trạng thái kích hoạt\n"
                 "- Sắp xếp theo thời điểm tạo giảm dần",
                 "Danh sách chính sách", "Không có thao tác ghi"],
                ["2", "Kiểm tra chính sách trước khi kích hoạt", "Kiểm tra",
                 "- Kiểm tra cấu hình trọng số và ngưỡng có hợp lệ không\n"
                 "- Kiểm tra từng quy tắc có đủ bảy trường, trường hợp lệ, toán tử hỗ trợ, "
                 "trọng số và điểm trong khoảng không vượt quá 1\n"
                 "- Nếu có vấn đề thì từ chối kích hoạt và trả về danh sách vấn đề, "
                 "không dùng chính sách có lỗi",
                 "Chi tiết chính sách", "Trả về 400 nếu sai"],
                ["3", "Kích hoạt chính sách", "Cập nhật",
                 "- Ràng buộc chỉ có tối đa một chính sách kích hoạt tại một thời điểm\n"
                 "- Khi kích hoạt chính sách mới, chính sách cũ bị vô hiệu hoá và ghi "
                 "thời điểm vô hiệu hoá\n"
                 "- Chỉ đặt được khi chính sách đã qua kiểm tra ở trên",
                 "Chi tiết chính sách", "Có ghi audit"],
                ["4", "Quản lý tài khoản", "Cập nhật",
                 "- Không được có hai tài khoản trùng tên đăng nhập hoặc trùng thư điện tử\n"
                 "- Không được tự động gán vai trò đặc biệt khi đăng ký\n"
                 "- Mọi thay đổi trạng thái tài khoản phải có lý do",
                 "Danh sách tài khoản", "Có ghi audit"],
                ["5", "Gán và thu hồi vai trò", "Cập nhật",
                 "- Không được gán trùng cặp tài khoản và vai trò\n"
                 "- Ghi lại ai gán và thời điểm gán\n"
                 "- Xoá tài khoản làm các bản ghi phụ thuộc bị xoá theo",
                 "Chi tiết tài khoản", "Có ghi audit"],
                ["6", "Đặt cờ bắt buộc xác thực đa yếu tố", "Cập nhật",
                 "- Cờ bền vững: áp dụng cho mọi lần đăng nhập, khác với cờ do phát hiện "
                 "đặt chỉ áp dụng một lần\n"
                 "- Mỗi lần đổi cờ phải ghi lý do",
                 "Chi tiết tài khoản", "Có ghi audit"],
                ["7", "Thu hồi phiên của người dùng khác", "Cập nhật",
                 "- Khác với người dùng, quản trị viên được thu hồi phiên của người khác\n"
                 "- Bắt buộc có lý do\n"
                 "- Ghi nhật ký kiểm toán với trạng thái trước và sau\n"
                 "- Phản hồi trả về số phiên đã thu hồi",
                 "Danh sách tài khoản", "Có ghi audit"],
                ["8", "Xem nhật ký kiểm toán", "Trích xuất",
                 "- Lọc theo người thực hiện, loại người thực hiện, hành động, tài nguyên và thời gian\n"
                 "- Hiển thị trạng thái trước và sau để thấy rõ thay đổi",
                 "Tra cứu nhật ký", "Không có thao tác ghi"],
                ["9", "Xem và điều tra cảnh báo", "Trích xuất",
                 "- Có đầy đủ quyền như phân viên SOC về mặt đọc\n"
                 "- Có thể gán lại cảnh báo cho phân viên khác\n"
                 "- Không có quyền phê duyệt leo thang",
                 "Danh sách và chi tiết cảnh báo", "Có ghi audit khi gán"],
                ["10", "Điều chỉnh tham số hệ thống", "Cập nhật",
                 "- Giá trị phải khớp kiểu dữ liệu khai báo\n"
                 "- Ghi lại người cập nhật và thời điểm\n"
                 "- Tham số liên quan xác thực, xác thực đa yếu tố, giới hạn tần suất, "
                 "phát hiện và thông báo được nhóm theo danh mục",
                 "Tham số hệ thống", "Có ghi audit"],
            ],
        },
    ),
    ("CAP", "Bảng 2.19  Yêu cầu chức năng nghiệp vụ của Security Administrator"),
    # ------------------------------------------------ Security Manager
    ("H3", "Chức năng của đối tượng Security Manager"),
    (
        "P",
        "Security Manager là quản lý bảo mật, chịu trách nhiệm về mức độ an toàn tổng thể "
        "và về quyết định khi có tranh chấp về mức độ nghiêm trọng.",
    ),
    (
        "P",
        "Lý do cần đối tượng này: có những quyết định vượt ra ngoài phạm vi kỹ thuật của "
        "một phân viên, ví dụ một cảnh báo có thể gây gián đoạn công việc của cả một phòng "
        "ban nhưng bằng chứng thì chưa đủ chắc chắn. Khi đó cần một cấp quyết định cao hơn. "
        "Đồng thời, quản lý là người duy nhất nhìn được toàn cảnh xu hướng, nên cần một "
        "vai trò chỉ đọc được số liệu tổng hợp mà không cần can thiệp kỹ thuật. Nếu thiếu "
        "đối tượng này, việc leo thang sẽ dừng ở phân viên, và không ai chịu trách nhiệm "
        "đánh giá xu hướng dài hạn.",
    ),
    (
        "P",
        "Trách nhiệm: theo dõi chỉ số tổng hợp, xem các cảnh báo quan trọng, phê duyệt hoặc "
        "bác bỏ các trường hợp leo thang, và xuất báo cáo cho ban quản lý. Họ không thực hiện "
        "thao tác kỹ thuật trên từng cảnh báo.",
    ),
    (
        "P",
        "Dữ liệu được phép truy cập: bảng điều khiển tổng hợp, danh sách cảnh báo ở mức "
        "đọc, và nhật ký kiểm toán. Họ không có quyền sửa chính sách, quản lý tài khoản, "
        "hay ghi vào bất kỳ bảng nào; mọi thao tác của họ đều là thao tác đọc hoặc phê duyệt "
        "và đều được ghi nhận ký.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.5, 1.9, 1.2, 2.3, 1.3, 0.8],
            "header": ["STT", "Công việc", "Loại công việc", "Quy định liên quan",
                       "Giao diện", "Ghi chú"],
            "rows": [
                ["1", "Xem bảng điều khiển tổng hợp", "Trích xuất",
                 "- Tổng số cảnh báo theo trạng thái và theo mức rủi ro\n"
                 "- Xu hướng cảnh báo theo thời gian\n"
                 "- Các lý do vi phạm phổ biến nhất\n"
                 "- Khối lượng công việc và thời gian xử lý của từng phân viên",
                 "Bảng điều khiển", "Không có thao tác ghi"],
                ["2", "Xem cảnh báo mức cao", "Trích xuất",
                 "- Xem theo mức rủi ro nghiêm trọng và cao\n"
                 "- Xem hồ sơ điều tra như phân viên SOC\n"
                 "- Không được ghi chú hay đổi trạng thái",
                 "Danh sách và chi tiết cảnh báo", "Không có thao tác ghi"],
                ["3", "Phê duyệt trường hợp leo thang", "Cập nhật",
                 "- Chỉ phê duyệt trường hợp đã được leo thang và đã có đánh giá của phân viên\n"
                 "- Quyết định gồm phê duyệt hoặc bác bỏ và lý do\n"
                 "- Kết quả quyết định ghi vào dòng thời gian cảnh báo\n"
                 "- Không phê duyệt được trường hợp do chính mình leo thang",
                 "Chi tiết cảnh báo", "Có ghi audit"],
                ["4", "Theo dõi tỉ lệ báo nhầm", "Trích xuất",
                 "- Tỉ lệ cảnh báo báo nhầm trên tổng số cảnh báo đã kết luận\n"
                 "- So sánh theo từng quy tắc đã chạy để biết quy tắc nào gây báo nhầm nhiều nhất\n"
                 "- Đây là căn cứ khách quan để điều chỉnh chính sách",
                 "Báo cáo tổng hợp", "Không có thao tác ghi"],
                ["5", "Xem nhật ký kiểm toán", "Trích xuất",
                 "- Xem toàn bộ nhật ký để kiểm tra tính tuân thủ\n"
                 "- Lọc theo thời gian và hành động",
                 "Tra cứu nhật ký", "Không có thao tác ghi"],
                ["6", "Xuất báo cáo tổng hợp", "Trích xuất",
                 "- Theo khoảng thời gian và phạm vi được yêu cầu\n"
                 "- Nội dung gồm số lượng cảnh báo, tỉ lệ theo mức, tỉ lệ báo nhầm, hành động đã áp dụng\n"
                 "- Đánh dấu thời điểm xuất báo cáo",
                 "Màn hình báo cáo", "Chưa có chức năng xuất tệp"],
            ],
        },
    ),
    ("CAP", "Bảng 2.20  Yêu cầu chức năng nghiệp vụ của Security Manager"),

    # ================================================================ II.4
    ("H2", "Yêu cầu chức năng hệ thống và yêu cầu chất lượng"),
    ("H3", "A. Yêu cầu chức năng hệ thống"),
    (
        "P",
        "Bảng dưới liệt kê các yêu cầu chức năng ở mức hệ thống, tức là các chức năng "
        "không gắn với một đối tượng cụ thể mà phục vụ toàn bộ hệ thống.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [0.8, 1.9, 2.6, 1.6, 0.5, 1.0],
            "header": ["Mã", "Chức năng", "Mô tả, đầu vào và đầu ra", "Điều kiện", "Actor", "Dữ liệu liên quan"],
            "rows": [
                ["FR-01", "Xác thực người dùng",
                 "Vào: tên đăng nhập, mật khẩu, địa chỉ IP, thiết bị.\nRa: cặp token và mã phiên, hoặc thử thách xác thực, hoặc mã từ chối.\n"
                 "Quy tắc: giới hạn tần suất, thông báo chung, kiểm tra trạng thái tài khoản.",
                 "Tài khoản tồn tại, chưa bị khoá, chưa vượt ngưỡng tần suất",
                 "Người dùng", "users, sessions, rate_limits, login_attempts"],
                ["FR-02", "Xác thực đa yếu tố",
                 "Vào: mã định danh giao dịch xác thực, mã xác thực.\nRa: cặp token, hoặc mã lỗi.\n"
                 "Quy tắc: hạn 5 phút, tối đa 3 lần, mã dùng một lần.",
                 "Giao dịch xác thực ở trạng thái chờ và chưa hết hạn",
                 "Người dùng", "mfa_transactions, mfa_notifications"],
                ["FR-03", "Quản lý phiên",
                 "Vào: token hiện tại, mã định danh phiên.\nRa: danh sách phiên, hoặc xác nhận thu hồi.\n"
                 "Quy tắc: chỉ chủ sở hữu được thu hồi phiên của mình; hạn 1 giờ.",
                 "Access token còn hiệu lực",
                 "Người dùng, quản trị viên", "sessions, ip_addresses"],
                ["FR-04", "Làm mới token",
                 "Vào: refresh token.\nRa: cặp token mới.\nQuy tắc: xoay mã định danh token; từ chối nếu phiên đã thu hồi hoặc hết hạn.",
                 "Bản băm refresh token tồn tại và khớp",
                 "Người dùng", "sessions"],
                ["FR-05", "Cổng kiểm duyệt trước khi cấp token",
                 "Vào: tên đăng nhập, mã người dùng, địa chỉ IP, thiết bị.\nRa: mức rủi ro, quyết định, cờ yêu cầu xác thực, cờ suy giảm.\n"
                 "Quy tắc: chỉ chặn ở mức cao và nghiêm trọng; hạn chờ 3 giây; lỗi thì mở cửa.",
                 "Mật khẩu đã đúng; cổng không bị tắt bằng tham số môi trường",
                 "Hệ thống", "login_attempts, risk_assessments"],
                ["FR-06", "Ghi nhận sự kiện đăng nhập",
                 "Vào: mã định danh sự kiện, kết quả, địa chỉ IP, thiết bị, thời điểm.\n"
                 "Ra: mã bản ghi và trạng thái xử lý.\nQuy tắc: lũy đẳng theo mã định danh sự kiện.",
                 "Khoá dùng chung đúng",
                 "Hệ thống", "login_attempts, detection_logs"],
                ["FR-07", "Xây dựng đặc trưng",
                 "Vào: bản ghi lần đăng nhập.\nRa: sáu đặc trưng.\n"
                 "Quy tắc: khoảng cách lọc 24 giờ, 7 ngày và 30 ngày; giá trị mặc định khi chưa đủ dữ liệu.",
                 "Có mã người dùng trong bản ghi lần đăng nhập",
                 "Hệ thống", "login_attempts"],
                ["FR-08", "Đánh giá quy tắc",
                 "Vào: tập quy tắc và tập đặc trưng.\nRa: điểm quy tắc và danh sách quy tắc chạy.\n"
                 "Quy tắc: chia cho tổng trọng số quy tắc đang bật; quy tắc sai bị bỏ qua và ghi nhật ký.",
                 "Có chính sách đang kích hoạt",
                 "Hệ thống", "policies, detection_logs"],
                ["FR-09", "Suy luận mức bất thường",
                 "Vào: sáu đặc trưng.\nRa: điểm bất thường chuẩn hoá, cờ bất thường, phiên bản mô hình, mã lý do.\n"
                 "Quy tắc: điểm nằm trong khoảng không vượt quá 1.",
                 "Khoá dùng chung đúng; đặc trưng đủ sáu trường",
                 "Hệ thống", "inference_logs, model_versions"],
                ["FR-10", "Gộp điểm và xếp mức",
                 "Vào: điểm quy tắc, điểm ML, cấu hình chính sách.\nRa: điểm gộp, mức rủi ro, quyết định.\n"
                 "Quy tắc: trọng số 0,4 và 0,6; ngưỡng 0,25, 0,50, 0,75.",
                 "Đã có kết quả chấm quy tắc và kết quả suy luận hoặc trạng thái lỗi",
                 "Hệ thống", "risk_assessments"],
                ["FR-11", "Tạo cảnh báo",
                 "Vào: kết quả đánh giá.\nRa: cảnh báo ở trạng thái mở kèm lý do và cụm điểm.\n"
                 "Quy tắc: chỉ tạo ở mức cao và nghiêm trọng.",
                 "Mức rủi ro là cao hoặc nghiêm trọng",
                 "Hệ thống", "alerts, alert_timeline"],
                ["FR-12", "Quản lý vòng đời cảnh báo",
                 "Vào: mã định danh cảnh báo, hành động, lý do.\n"
                 "Ra: cảnh báo cập nhật kèm dòng thời gian.\n"
                 "Quy tắc: không tiếp nhận được cảnh báo đã có người nhận; kết luận bắt buộc có nội dung.",
                 "Cảnh báo tồn tại; kết luận cần nội dung kết luận",
                 "Phân viên SOC, quản trị viên", "alerts, alert_timeline"],
                ["FR-13", "Thực thi hành động bảo vệ",
                 "Vào: loại hành động, mã tài khoản đích, lý do, mã cảnh báo, khoá lũy đẳng.\n"
                 "Ra: trạng thái áp dụng và số phiên đã thu hồi.\nQuy tắc: hạn chờ 3 giây; nuốt lỗi.",
                 "Khoá dùng chung đúng; tài khoản đích tồn tại",
                 "Hệ thống, phân viên SOC", "sessions, users, audit_logs"],
                ["FR-14", "Quản lý chính sách",
                 "Vào: tập quy tắc và cấu hình.\nRa: danh sách chính sách, hoặc kết quả kích hoạt.\n"
                 "Quy tắc: chỉ một chính sách kích hoạt; từ chối kích hoạt chính sách sai.",
                 "Chính sách hợp lệ về cấu trúc và cấu hình",
                 "Quản trị viên", "policies"],
                ["FR-15", "Truy vấn người dùng nội bộ",
                 "Vào: mã người dùng.\nRa: thông tin cơ bản và danh sách vai trò.\n"
                 "Quy tắc: thay thế khóa ngoại xuyên cơ sở dữ liệu ở tầng ứng dụng.",
                 "Khoá dùng chung đúng",
                 "Hệ thống", "users, roles, user_roles"],
                ["FR-16", "Phục hồi bản ghi chấm lỗi",
                 "Vào: danh sách bản ghi lần đăng nhập ở trạng thái lỗi.\n"
                 "Ra: số bản ghi đã chấm lại thành công.\n"
                 "Quy tắc: một bản ghi lỗi không được dừng cả đợt quét.",
                 "Có bản ghi ở trạng thái lỗi",
                 "Hệ thống", "login_attempts, risk_assessments"],
                ["FR-17", "Bảng điều khiển SOC",
                 "Vào: khoảng thời gian và bộ lọc.\nRa: số cảnh báo theo trạng thái, mức rủi ro, lý do, khối lượng phân viên.",
                 "Không có",
                 "Phân viên SOC, quản lý bảo mật", "alerts, soc_analysts"],
                ["FR-18", "Quản lý thiết bị tin cậy",
                 "Vào: vân tay thiết bị, tên thiết bị.\nRa: danh sách thiết bị, kết quả kiểm tra thiết bị đã tin cậy.\n"
                 "Quy tắc: ràng buộc duy nhất theo cặp tài khoản và vân tay thiết bị.",
                 "Người dùng đã xác thực",
                 "Người dùng", "user_trusted_devices"],
                ["FR-19", "Nhật ký kiểm toán",
                 "Vào: thông tin hành động và tài nguyên.\nRa: dòng nhật ký có trạng thái trước và sau.\n"
                 "Quy tắc: bất biến; khi xoá tài khoản thì đặt trống người thực hiện thay vì xoá dòng.",
                 "Có thao tác nhạy cảm",
                 "Hệ thống", "audit_logs"],
                ["FR-20", "Thông báo trong ứng dụng",
                 "Vào: loại thông báo, tiêu đề, nội dung.\nRa: danh sách thông báo chưa đọc.\n"
                 "Quy tắc: tám loại thông báo được phép; bốn mức ưu tiên.",
                 "Có sự kiện phù hợp với loại thông báo",
                 "Hệ thống", "user_notifications"],
            ],
        },
    ),
    ("CAP", "Bảng 2.21  Bảng yêu cầu chức năng hệ thống"),
    ("H3", "B. Yêu cầu chất lượng và yêu cầu phi chức năng"),
    (
        "P",
        "Bảng sau trình bày các yêu cầu phi chức năng. Với những tiêu chí định lượng, báo "
        "cáo ghi rõ mức độ hiện có bằng chứng hay chưa.",
    ),
    (
        "TABLE",
        {
            "caption": None,
            "widths": [1.2, 2.9, 3.3],
            "header": ["Nhóm", "Yêu cầu", "Mức độ đáp ứng hiện tại"],
            "rows": [
                [
                    "Bảo mật",
                    "Mật khẩu và mã xác thực phải được băm bằng thuật toán chậm có muối; "
                    "token lưu ở dạng băm; địa chỉ IP trong giao dịch xác thực lưu ở dạng băm.",
                    "Đáp ứng. Ba điểm này đều có trong mã nguồn.",
                ],
                [
                    "Bảo mật",
                    "Giao tiếp giữa các dịch vụ nội bộ phải có xác thực, không để lộ điểm cuối chưa kiểm soát.",
                    "Đáp ứng một phần. Các điểm cuối nội bộ dùng khoá dùng chung. "
                    "Khoá mặc định trong mã nguồn là giá trị thay thế, cần thay khi triển khai thật.",
                ],
                [
                    "Phân quyền",
                    "Mỗi điểm cuối phải kiểm tra vai trò người gọi trước khi thao tác dữ liệu.",
                    "Chưa đáp ứng. Nhóm đã xác định đây là nợ kỹ thuật: phần lớn điểm cuối "
                    "quản lý cảnh báo mới chỉ kiểm tra khoá dịch vụ nội bộ. Xem Chương VI.",
                ],
                [
                    "Sẵn sàng",
                    "Sự cố của một thành phần không được chặn đứng chức năng chính.",
                    "Đáp ứng. Ba cơ chế: cổng kiểm duyệt mở cửa khi lỗi, suy giảm về điểm "
                    "quy tắc khi ML lỗi, nuốt lỗi khi gửi hành động bảo vệ.",
                ],
                [
                    "Sẵn sàng",
                    "Bản ghi lần đăng nhập đã ghi nhưng chấm lỗi phải được xử lý lại.",
                    "Đáp ứng một phần. Hàm quét lại đã hiện thực và có kiểm thử, nhưng chưa "
                    "được nối vào bộ lập lịch nào.",
                ],
                [
                    "Hiệu năng",
                    "Thời gian chờ của cổng kiểm duyệt không được làm người dùng chờ lâu.",
                    "Đáp ứng về thiết kế: hạn chờ ba giây, chỉ áp dụng với mức rủi ro cao và "
                    "nghiêm trọng, và mở cửa khi lỗi. Chưa có số đo thực tế.",
                ],
                [
                    "Hiệu năng",
                    "Thời gian chờ gọi ML Service và gửi hành động bảo vệ có giới hạn.",
                    "Đáp ứng: lần lượt là năm giây và ba giây, cả hai đều nuốt lỗi khi quá hạn.",
                ],
                [
                    "Độ tin cậy",
                    "Xử lý lặp lại sự kiện không được tạo bản ghi trùng.",
                    "Đáp ứng. Có ba tầng: ràng buộc duy nhất ở cơ sở dữ liệu, kiểm tra trước "
                    "khi chấm, và khoá lũy đẳng trên hành động bảo vệ.",
                ],
                [
                    "Độ tin cậy",
                    "Cấu hình sai không được làm sập quy trình chấm điểm.",
                    "Đáp ứng. Cấu hình sai và quy tắc sai đều bị bỏ qua kèm ghi nhật ký, "
                    "hệ thống dùng giá trị mặc định để tiếp tục.",
                ],
                [
                    "Khả năng kiểm toán",
                    "Mọi thao tác nhạy cảm phải truy vết được người thực hiện và thời điểm.",
                    "Đáp ứng một phần. Ba bảng nhật ký tồn tại và có chỉ mục; phần điền dữ "
                    "liệu cho hành động thu hồi phiên từ phía người dùng chưa bao phủ hết.",
                ],
                [
                    "Toàn vẹn dữ liệu",
                    "Ràng buộc toàn vẹn phải được thực thi ở cơ sở dữ liệu khi có thể.",
                    "Đáp ứng trong phạm vi một cơ sở dữ liệu. Giữa các cơ sở dữ liệu thì "
                    "không thể, và hệ thống bù bằng điểm cuối nội bộ tra cứu người dùng.",
                ],
                [
                    "Toàn vẹn dữ liệu",
                    "Tập giá trị của các cột trạng thái phải được ràng buộc.",
                    "Đáp ứng. Lược đồ dùng ràng buộc kiểm tra cho trạng thái tài khoản, trạng "
                    "thái giao dịch xác thực, kênh thông báo, kết quả lần đăng nhập, trạng "
                    "thái chấm điểm, mức rủi ro, quyết định, trạng thái cảnh báo và loại sự kiện.",
                ],
                [
                    "Khả năng bảo trì",
                    "Tham số vận hành phải đổi được mà không sửa mã nguồn.",
                    "Đáp ứng một phần. Chính sách chấm điểm đổi được qua giao diện quản lý; "
                    "thời gian chờ và địa chỉ dịch vụ vẫn nằm trong mã nguồn.",
                ],
                [
                    "Khả năng mở rộng",
                    "Thiết kế phải chịu được tải tăng dần.",
                    "Chưa đánh giá. Thiết kế có chỉ mục theo truy vấn và phân tách dữ liệu "
                    "theo dịch vụ, nhưng chưa có số đo tải. Xem Chương VI.",
                ],
            ],
        },
    ),
    ("CAP", "Bảng 2.22  Yêu cầu chất lượng và mức độ đáp ứng hiện tại"),
    ("NOTE",
     "[CẦN XÁC NHẬN TIÊU CHÍ ĐỊNH LƯỢNG] — Nhóm chưa xác lập được các ngưỡng định lượng "
     "cụ thể cho: thời gian phản hồi của điểm cuối đăng nhập, số lần đăng nhập đồng thời "
     "chịu được, tỉ lệ cảnh báo báo nhầm chấp nhận được, thời gian tối đa để một cảnh báo "
     "được phân viên tiếp nhận, và thời gian lưu giữ dữ liệu chấm điểm và nhật ký kiểm "
     "toán. Các ngưỡng này cần được chốt cùng giảng viên hướng dẫn và ghi bổ sung vào báo cáo."),
]
