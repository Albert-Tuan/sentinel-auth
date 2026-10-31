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

#: Sơ đồ dùng trong báo cáo (D1.2 redesign)
#:  - Tất cả 21 figure đã được sửa lại để đạt 9pt tại A4.
#:  - Một số figure được chia thành 2-3 sub-figure; xem HINH_A, HINH_B, HINH_C.
#:  - Chapter files có thể tham chiếu thêm key phụ (usecase_a, class_b, erd_core_a, ...)
#:  - File manifest đầy đủ: docs/bao-cao/qa/figure-manifest.md
HINH = {
    # --- Use Case (3 split: A=User-Auth, B=SOC, C=Admin) ---
    # Original key: pointing to the full User-Auth view (most relevant for ch3a)
    "usecase":            IMG + "uml-use-case-user-auth-v3.png",
    "usecase_a":          IMG + "uml-use-case-user-auth-v3.png",
    "usecase_b":          IMG + "uml-use-case-soc.png",
    "usecase_c":          IMG + "uml-use-case-admin.png",
    # --- State Machine ---
    "state_alert":        IMG + "uml-state-alert-v2.png",
    "state_mfa_session":  IMG + "uml-state-mfa-tx-v2.png",
    "state_session":      IMG + "uml-state-session-v2.png",
    # --- Class Diagram (4 split: A=Auth, B=Detection, C=DTOs, D=ML+Timeline) ---
    # Original key: pointing to A (Auth) for ch3a
    "class":              IMG + "uml-class-domain-a-v2.png",
    "class_a":            IMG + "uml-class-domain-a-v2.png",
    "class_b":            IMG + "uml-class-domain-b-v2.png",
    "class_c":            IMG + "uml-class-domain-c-v4.png",
    "class_d":            IMG + "uml-class-domain-d.png",
    # --- Activity ---
    "act_login":          IMG + "uml-activity-login-mfa-v2.png",
    "act_detection":      IMG + "uml-activity-detection-v5.png",
    "act_soc":            IMG + "uml-activity-soc-v4.png",
    # --- Sequence (proper UML sequence diagrams from docs/diagrams/wf*.uml) ---
    "seq_login":          "diagrams/wf1_login.png",
    "seq_detection":      "diagrams/wf2_detection.png",
    "seq_soc":            "diagrams/wf3_soc.png",
    "seq_mfa":            "diagrams/wf4_mfa_flow.png",
    "seq_session":        "diagrams/wf5_session_management.png",
    "seq_ml":             "diagrams/wf6_ml_inference.png",
    # --- Architecture (compact D1.2 redesign) ---
    "arch":               IMG + "uml-architecture-v2.png",
    "arch_full":          "diagrams/fig_architecture_overview.png",
    # --- ERD Core (3 split: A=User, B=MFA, C=Audit) ---
    "erd_core":           IMG + "ERD_core_v3.3_a.png",   # representative (User/Session)
    "erd_core_a":         IMG + "ERD_core_v3.3_a.png",
    "erd_core_b":         IMG + "ERD_core_v3.3_b.png",
    "erd_core_c":         IMG + "ERD_core_v3.3_c.png",
    # --- ERD Detection (2 split: A=Policy+Risk, B=Log+Alert) ---
    "erd_detection":      IMG + "ERD_detection_v3.3_a.png",
    "erd_detection_a":    IMG + "ERD_detection_v3.3_a.png",
    "erd_detection_b":    IMG + "ERD_detection_v3.3_b.png",
    # --- ERD ML ---
    "erd_ml":             IMG + "ERD_ml_v3.3_v2.png",
    # --- Scenario Maps (workflow diagrams) ---
    "st01":               "diagrams/v3.3-detect/st01-login-happy-path-v2.png",
    "st03":               "diagrams/v3.3-detect/st03-login-critical-alert-v3.png",
    "st04":               "diagrams/v3.3-detect/st04-soc-handle-alert-v3.png",
    "st06":               "diagrams/v3.3-detect/st06-ml-timeout-fallback-v3.png",
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
