"""Nội dung báo cáo, được render vào DOCX dựa trên file mẫu.

Cấu trúc module:
  * `Blocks` là một danh sách lệnh (tuples) mà `build_docx.py` dịch sang
    đối tượng python-docx.
  * Mỗi khối nội dung bắt đầu bằng một marker rõ ràng để dễ đối chiếu với
    mẫu báo cáo và checklist.

Quy ước marker:
  ("H1", text)              -> Heading 1   (CHƯƠNG ..., DANH MỤC ...)
  ("H2", text)              -> Heading 2   (mục cấp 2)
  ("H3", text)              -> Heading 3   (mục cấp 3)
  ("H4", text)              -> Heading 4   (mục cấp 4)
  ("P",  text)              -> Normal      (đoạn thường)
  ("PB", text)              -> Normal      (đoạn đệm trước)
  ("BUL", text)             -> List Paragraph
  ("NOTE", text)            -> Normal in nghiêng, dùng cho lưu ý/ghi chú
  ("CAP", text)             -> Normal canh giữa, dùng cho caption hình/bảng
  ("EQ",  text)             -> Normal canh giữa, dùng cho công thức
  ("CODE", text)            -> Normal đơn cách, dùng cho khối dữ liệu/ký hiệu
  ("PAGEBREAK", "")         -> ngắt trang
  ("TABLE", spec)           -> bảng, spec = dict(xem file con)
  ("IMG", spec)             -> hình, spec = dict(key, width_cm, caption=str|None)
  ("TOC", kind)             -> trường TOC / TOA / danh mục từ viết tắt
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Đường dẫn hình ảnh (tương đối tới thư mục docs/)
# ---------------------------------------------------------------------------

IMG = "bao-cao/"

#: Sơ đồ dùng trong báo cáo
HINH = {
    "usecase": IMG + "uml-use-case-tong-quat.png",
    "state_alert": IMG + "uml-state-alert.png",
    "state_mfa_session": IMG + "uml-state-mfa-session.png",
    "class": IMG + "uml-class-domain.png",
    "act_login": IMG + "uml-activity-login-mfa.png",
    "act_detection": IMG + "uml-activity-detection.png",
    "act_soc": IMG + "uml-activity-soc.png",
    "seq_login": "WF-1_Login.png",
    "seq_detection": "WF-2_Detection.png",
    "seq_soc": "WF-3_SOC.png",
    "seq_mfa": "WF-4_MFA.png",
    "seq_session": "WF-5_Sessions.png",
    "seq_ml": "WF-6_ML.png",
    "arch": "diagrams/fig_architecture_overview.png",
    "erd_core": IMG + "ERD_core_v3.3.png",
    "erd_detection": IMG + "ERD_detection_v3.3.png",
    "erd_ml": IMG + "ERD_ml_v3.3.png",
    "st01": "diagrams/v3.3-detect/st01-login-happy-path.png",
    "st03": "diagrams/v3.3-detect/st03-login-critical-alert.png",
    "st04": "diagrams/v3.3-detect/st04-soc-handle-alert.png",
    "st06": "diagrams/v3.3-detect/st06-ml-timeout-fallback.png",
}

# ---------------------------------------------------------------------------
# Trang bìa
# ---------------------------------------------------------------------------

TRANG_BIA: list[tuple[str, Any]] = [
    ("COVER_MONHOC", "Phân tích thiết kế hệ thống thông tin"),
    ("COVER_DETAI", "Hệ thống cảnh báo đăng nhập bất thường"),
    ("COVER_GV", "ths. Nguyễn Thị Bích Nguyên"),
    (
        "COVER_MEMBER",
        [
            ("Đặng Tuấn Anh", "N23DCAT003", "D23CQAT01-N", "Trưởng nhóm"),
            ("Nguyễn Trần Sony", "N23DCAT059", "D23CQAT01-N", "Thành viên"),
            ("Lê Bảo Khang", "N23DCAT032", "D23CQAT01-N", "Thành viên"),
        ],
    ),
    ("COVER_DICH", "TP. Hồ Chí Minh, tháng 10 / 2026"),
]

# ---------------------------------------------------------------------------
# Danh mục từ viết tắt — chỉ gồm thuật ngữ THỰC SỰ xuất hiện trong báo cáo
# ---------------------------------------------------------------------------

TU_VIET_TAT: list[tuple[str, str]] = [
    ("API", "Application Programming Interface - giao diện lập trình ứng dụng"),
    ("DBMS", "Database Management System - hệ quản trị cơ sở dữ liệu"),
    ("ERD", "Entity Relationship Diagram - sơ đồ thực thể quan hệ"),
    ("FK", "Foreign Key - khoá ngoại"),
    ("HTTP", "Hypertext Transfer Protocol - giao thức truyền tải siêu văn bản"),
    ("IP", "Internet Protocol - giao thức mạng, dùng ở đây để chỉ địa chỉ nguồn"),
    ("JSONB", "JSON Binary - kiểu dữ liệu JSON của PostgreSQL"),
    ("JWT", "JSON Web Token - định dạng token có chữ ký số"),
    ("MFA", "Multi-Factor Authentication - xác thực đa yếu tố"),
    ("ML", "Machine Learning - học máy"),
    ("OTP", "One-Time Password - mật khẩu dùng một lần"),
    ("PK", "Primary Key - khoá chính"),
    ("RBAC", "Role-Based Access Control - phân quyền theo vai trò"),
    ("SOC", "Security Operations Center - Trung tâm Giám sát An ninh"),
    ("SQL", "Structured Query Language - ngôn ngữ truy vấn có cấu trúc"),
    ("TOTP", "Time-Based One-Time Password - mật khẩu dùng một lần theo thời gian"),
    ("TTL", "Time To Live - thời gian sống của phiên hoặc token"),
    ("UML", "Unified Modeling Language - ngôn ngữ mô hình hoá thống nhất"),
    ("UUID", "Universally Unique Identifier - định danh duy nhất phổ quát"),
]
