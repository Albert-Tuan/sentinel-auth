#!/usr/bin/env python3
"""Generate two DOCX reports for Sentinel Auth project matching the HVCS template format."""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

# ─── Helpers ────────────────────────────────────────────────────────────────

BASE = "/run/media/thaus/Lab/1_Project/sentinel-auth/sentinel-auth"

def set_cell_bg(cell, hex_color):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)

def set_cell_border(cell, **kwargs):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        val = kwargs.get(edge)
        if val:
            tag = OxmlElement(f'w:{edge}')
            tag.set(qn('w:val'), val.get('val', 'single'))
            tag.set(qn('w:sz'), str(val.get('sz', 4)))
            tag.set(qn('w:space'), '0')
            tag.set(qn('w:color'), val.get('color', '000000'))
            tcBorders.append(tag)
    tcPr.append(tcBorders)

def cell_text(cell, text, bold=False, size=10, align=WD_ALIGN_PARAGRAPH.CENTER, color=None):
    cell.text = ''
    p = cell.paragraphs[0]
    p.alignment = align
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor(*bytes.fromhex(color))
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

def add_heading(doc, text, level=1, color='2C3E50'):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        run.font.color.rgb = RGBColor(*bytes.fromhex(color))
        if level == 1:
            run.font.size = Pt(14)
        elif level == 2:
            run.font.size = Pt(12)
        else:
            run.font.size = Pt(11)
    return p

def add_para(doc, text, bold=False, size=10, indent=False):
    p = doc.add_paragraph()
    if indent:
        p.paragraph_format.left_indent = Cm(1)
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    return p

def add_bullet(doc, text, size=10):
    p = doc.add_paragraph(style='List Bullet')
    run = p.add_run(text)
    run.font.size = Pt(size)
    return p

def add_bold_bullet(doc, bold_part, normal_part, size=10):
    p = doc.add_paragraph(style='List Bullet')
    r1 = p.add_run(bold_part)
    r1.bold = True
    r1.font.size = Pt(size)
    r2 = p.add_run(normal_part)
    r2.font.size = Pt(size)
    return p

def make_table_header_row(table, headers, bg='C0D0E0', bold=True, size=10):
    row = table.rows[0]
    for i, h in enumerate(headers):
        cell = row.cells[i]
        set_cell_bg(cell, bg)
        cell_text(cell, h, bold=bold, size=size, color='000000')

def add_image(doc, path, width=None):
    if os.path.exists(path):
        run = doc.add_picture(path, width=width or Cm(14))
        last_para = doc.paragraphs[-1]
        last_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        return run

# ─── REPORT 1 ────────────────────────────────────────────────────────────────

def gen_requirement_report(out_path):
    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # ── COVER / HEADER ──────────────────────────────────────────────────────
    add_heading(doc, 'XÁC ĐỊNH YÊU CẦU', level=1, color='1A5276')
    add_heading(doc, 'Hệ thống Sentinel Auth', level=2, color='2C3E50')
    add_para(doc, 'Hệ thống giám sát bất thường đăng nhập — phát hiện rủi ro bằng ML', size=10)

    # ── I. KHẢO SÁT HIỆN TRẠNG ─────────────────────────────────────────────
    add_heading(doc, 'I. KHẢO SÁT HIỆN TRẠNG', level=2, color='1A5276')

    add_para(doc,
        'Hệ thống Sentinel Auth được xây dựng nhằm số hóa và tự động hóa việc giám sát '
        'đăng nhập, phát hiện các hành vi bất thường dựa trên Isolation Forest và quy tắc '
        'rủi ro, thay thế việc theo dõi thủ công dễ sai sót và thiếu minh bạch.')

    add_heading(doc, '1. Quy mô hoạt động', level=3, color='2C3E50')
    add_bullet(doc, 'Hệ thống phục vụ toàn bộ người dùng của tổ chức (sinh viên, nhân viên).')
    add_bullet(doc, 'SOC Analyst giám sát và xử lý các cảnh báo rủi ro cao.')
    add_bullet(doc, 'Quản trị viên quản lý cấu hình hệ thống, tài khoản và theo dõi nhật ký.')

    add_heading(doc, '2. Cơ cấu tổ chức', level=3, color='2C3E50')
    add_para(doc, 'Hệ thống bao gồm 3 nhóm người dùng chính với các trách nhiệm và quyền hạn riêng biệt:')
    add_bullet(doc, 'User: đăng nhập, xem thông tin tài khoản, quản lý MFA.')
    add_bullet(doc, 'SOC Analyst: giám sát alerts, điều tra và xử lý cảnh báo rủi ro.')
    add_bullet(doc, 'System Administrator: quản lý tài khoản, cấu hình hệ thống, theo dõi nhật ký.')

    add_heading(doc, '3. Hiện trạng nghiệp vụ', level=3, color='2C3E50')
    add_para(doc, 'Quy trình chính hiện tại gồm:')
    add_bullet(doc, 'User đăng nhập → hệ thống kiểm tra credentials (username/password).')
    add_bullet(doc, 'Hệ thống đánh giá rủi ro: trích features (IP, tần suất thất bại, thiết bị…) '
                     'và gọi ML scoring (Isolation Forest).')
    add_bullet(doc, 'Nếu risk cao → tạo alert cho SOC.')
    add_bullet(doc, 'SOC xem, acknowledge hoặc resolve alert.')
    add_bullet(doc, 'Quản trị giám sát toàn bộ nhật ký và cấu hình hệ thống.')

    # ── II. YÊU CẦU CHỨC NĂNG NGHIỆP VỤ ──────────────────────────────────
    add_heading(doc, 'II. XÁC ĐỊNH YÊU CẦU CHỨC NĂNG NGHIỆP VỤ', level=2, color='1A5276')

    # ── USER ────────────────────────────────────────────────────────────────
    add_heading(doc, 'Bộ phận: User (Người dùng)   Mã số: USER', level=3, color='1A5276')
    add_para(doc, 'Vai trò: Người dùng hệ thống — thực hiện đăng nhập có xác thực và quản lý MFA.', size=10)

    headers = ['STT', 'Công việc', 'Loại công việc', 'Quy định liên quan', 'Ghi chú']
    col_widths = [Cm(1), Cm(5.5), Cm(2.5), Cm(4), Cm(4)]

    tbl = doc.add_table(rows=1, cols=5)
    tbl.style = 'Table Grid'
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, w in enumerate(col_widths):
        tbl.columns[i].width = w
    make_table_header_row(tbl, headers, bg='D5E8D4', size=10)

    rows_data = [
        ('1', 'Đăng nhập hệ thống', 'Xác thực', 'AUTH_QĐ_1', 'Trả về ALLOW / MFA_REQUIRED / DENY. Lỗi generic — không leak username.'),
        ('2', 'Xác thực MFA (TOTP/Email OTP)', 'Xác thực', 'AUTH_QĐ_2', 'Chỉ khi mfa_required=true. Gửi mã 6 chữ số. Hết hạn 5 phút.'),
        ('3', 'Xem thông tin tài khoản cá nhân', 'Tra cứu', '—', 'Hiển thị username, email, trạng thái tài khoản.'),
        ('4', 'Đăng xuất', 'Lưu trữ', '—', 'Thu hồi session, xóa token.'),
        ('5', 'Nhận thông báo từ hệ thống', 'Tra cứu', '—', 'Thông báo dạng JSON response — không push notification.'),
    ]
    for r in rows_data:
        row = tbl.add_row()
        for i, val in enumerate(r):
            cell = row.cells[i]
            cell_text(cell, val, size=9,
                      align=WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT)

    doc.add_paragraph()

    # USER regulations table
    add_para(doc, 'Bảng Quy định liên quan — User', bold=True, size=11)
    headers2 = ['STT', 'Mã số', 'Tên Quy định', 'Mô tả chi tiết']
    col_widths2 = [Cm(1), Cm(2.5), Cm(4), Cm(9)]

    tbl2 = doc.add_table(rows=1, cols=4)
    tbl2.style = 'Table Grid'
    for i, w in enumerate(col_widths2):
        tbl2.columns[i].width = w
    make_table_header_row(tbl2, headers2, bg='FFF2CC', size=10)

    regs = [
        ('1', 'AUTH_QĐ_1', 'Quy định đăng nhập hợp lệ',
         'Username tồn tại trong hệ thống.\n'
         'Password đúng (Argon2id verify).\n'
         'Tài khoản không bị khóa (status ≠ locked/suspended).\n'
         'Nếu thỏa mãn: trả ALLOW hoặc MFA_REQUIRED.\n'
         'Nếu sai: trả generic error "Invalid credentials".'),
        ('2', 'AUTH_QĐ_2', 'Quy định xác thực MFA',
         'Mã OTP 6 chữ số, có hiệu lực trong 5 phút.\n'
         'Chỉ 3 lần thử, sau đó hết hạn.\n'
         'Mã được gửi qua email.\n'
         'Kiểm tra bound_ip_hash: nếu IP khác → từ chối.'),
    ]
    for r in regs:
        row = tbl2.add_row()
        for i, val in enumerate(r):
            cell = row.cells[i]
            cell_text(cell, val, size=9,
                      align=WD_ALIGN_PARAGRAPH.CENTER if i in (0, 1) else WD_ALIGN_PARAGRAPH.LEFT)

    doc.add_paragraph()

    # ── SOC ANALYST ──────────────────────────────────────────────────────────
    add_heading(doc, 'Bộ phận: SOC Analyst (Nhân viên giám sát an ninh)   Mã số: SOC', level=3, color='1A5276')
    add_para(doc, 'Vai trò: Giám sát các cảnh báo rủi ro, điều tra và xử lý các đăng nhập bất thường.', size=10)

    tbl3 = doc.add_table(rows=1, cols=5)
    tbl3.style = 'Table Grid'
    for i, w in enumerate(col_widths):
        tbl3.columns[i].width = w
    make_table_header_row(tbl3, headers, bg='CCE5FF', size=10)

    soc_rows = [
        ('1', 'Xem danh sách alerts', 'Tra cứu', '—', 'Lọc theo status (open/acknowledged/resolved) và risk_level (low/medium/high/critical).'),
        ('2', 'Xem chi tiết alert', 'Tra cứu', '—', 'Hiển thị đầy đủ thông tin: login_attempt, user, risk scores, thời gian.'),
        ('3', 'Acknowledge alert', 'Lưu trữ', 'SOC_QĐ_1', 'Chuyển trạng thái open → acknowledged. Ghi assigned_to và notes.'),
        ('4', 'Resolve alert', 'Lưu trữ', 'SOC_QĐ_2', 'Chuyển acknowledged → resolved hoặc false_positive. Ghi resolved_by, resolved_at.'),
        ('5', 'Lọc và tìm kiếm alerts', 'Tra cứu', '—', 'Lọc theo: status, risk_level, user_id, khoảng thời gian.'),
        ('6', 'Xem lịch sử đăng nhập', 'Tra cứu', '—', 'Xem toàn bộ login_attempts của một user để hỗ trợ điều tra.'),
    ]
    for r in soc_rows:
        row = tbl3.add_row()
        for i, val in enumerate(r):
            cell = row.cells[i]
            cell_text(cell, val, size=9,
                      align=WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT)

    doc.add_paragraph()

    add_para(doc, 'Bảng Quy định liên quan — SOC Analyst', bold=True, size=11)
    tbl4 = doc.add_table(rows=1, cols=4)
    tbl4.style = 'Table Grid'
    for i, w in enumerate(col_widths2):
        tbl4.columns[i].width = w
    make_table_header_row(tbl4, headers2, bg='FFF2CC', size=10)

    soc_regs = [
        ('1', 'SOC_QĐ_1', 'Quy định Acknowledge alert',
         'Alert ở trạng thái open.\n'
         'SOC ghi nhận đã xem xét.\n'
         'Gán assigned_to = mã SOC, ghi notes.\n'
         'Trạng thái chuyển: open → acknowledged.'),
        ('2', 'SOC_QĐ_2', 'Quy định Resolve alert',
         'Alert ở trạng thái acknowledged.\n'
         'SOC xác nhận đã xử lý xong.\n'
         'Ghi resolved_by, resolved_at, notes.\n'
         'Trạng thái chuyển: acknowledged → resolved hoặc false_positive.'),
    ]
    for r in soc_regs:
        row = tbl4.add_row()
        for i, val in enumerate(r):
            cell = row.cells[i]
            cell_text(cell, val, size=9,
                      align=WD_ALIGN_PARAGRAPH.CENTER if i in (0, 1) else WD_ALIGN_PARAGRAPH.LEFT)

    doc.add_paragraph()

    # ── SYSTEM ADMIN ────────────────────────────────────────────────────────
    add_heading(doc, 'Bộ phận: System Administrator   Mã số: SYSADM', level=3, color='1A5276')
    add_para(doc, 'Vai trò: Quản lý tài khoản, cấu hình hệ thống, theo dõi nhật ký và bảo trì kỹ thuật.', size=10)

    tbl5 = doc.add_table(rows=1, cols=5)
    tbl5.style = 'Table Grid'
    for i, w in enumerate(col_widths):
        tbl5.columns[i].width = w
    make_table_header_row(tbl5, headers, bg='E1D5E7', size=10)

    adm_rows = [
        ('1', 'Tạo và quản lý tài khoản', 'Lưu trữ', 'SYSADM_QĐ_1', 'Tạo, cập nhật, khóa tài khoản user và SOC. Mật khẩu được hash Argon2id.'),
        ('2', 'Phân quyền người dùng', 'Lưu trữ', 'SYSADM_QĐ_2', 'Gán vai trò: user, soc. Mỗi tài khoản 1 vai trò chính. Thay đổi áp dụng ngay.'),
        ('3', 'Quản lý cấu hình hệ thống', 'Lưu trữ', '—', 'Cấu hình ngưỡng risk (low/medium/high/critical), thời gian hết hạn session, thời gian OTP.'),
        ('4', 'Theo dõi nhật ký detection', 'Tra cứu', '—', 'Xem detection_logs: rule_score, anomaly_score, ml_status, risk_level của mỗi lần đăng nhập.'),
        ('5', 'Thống kê hệ thống', 'Tổng hợp', '—', 'Tổng số user, số alerts theo risk_level, tỉ lệ ML degradation.'),
    ]
    for r in adm_rows:
        row = tbl5.add_row()
        for i, val in enumerate(r):
            cell = row.cells[i]
            cell_text(cell, val, size=9,
                      align=WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT)

    doc.add_paragraph()

    # ── III. YÊU CẦU CHỨC NĂNG HỆ THỐNG ──────────────────────────────────
    add_heading(doc, 'III. XÁC ĐỊNH YÊU CẦU CHỨC NĂNG HỆ THỐNG', level=2, color='1A5276')

    tbl6 = doc.add_table(rows=1, cols=3)
    tbl6.style = 'Table Grid'
    h3 = ['STT', 'Nội dung', 'Mô tả chi tiết']
    w3 = [Cm(1), Cm(5), Cm(11)]
    for i, h in enumerate(h3):
        tbl6.columns[i].width = w3[i]
    make_table_header_row(tbl6, h3, bg='DAE8FC', size=10)

    sys_reqs = [
        ('1', 'Xác thực và phân quyền đăng nhập',
         'User đăng nhập bằng username/password. Hệ thống dùng Argon2id hash. '
         'Phân biệt phiên theo vai trò (user/soc/sysadm). '
         'MFA qua OTP email khi cần.'),
        ('2', 'Phát hiện rủi ro tự động (Inline Detection)',
         'Sau mỗi đăng nhập, hệ thống tự động trích features và gọi ML scoring (Isolation Forest) '
         'trong cùng request. Tính rule_score + anomaly_score → risk_level.'),
        ('3', 'Cảnh báo rủi ro tự động (Automatic Alert)',
         'Nếu risk_level = HIGH hoặc CRITICAL → tự động tạo alert trong bảng alerts '
         '(status=open). Không cần SOC can thiệp.'),
        ('4', 'SOC Dashboard — tra cứu và xử lý alerts',
         'SOC xem danh sách alerts, lọc theo status/risk_level, xem chi tiết, '
         'acknowledge hoặc resolve. Tất cả thao tác được ghi nhận.'),
        ('5', 'Nhật ký Detection (Detection Logs)',
         'Mỗi lần detection chạy đều ghi: login_attempt_id, rule_score, anomaly_score, '
         'ml_status, risk_level, decision, thời gian. Phục vụ hậu kiểm và replay.'),
        ('6', 'Sao lưu dữ liệu',
         'Dữ liệu PostgreSQL được lưu trong Docker volume. Chỉ SYSADM có quyền '
         'sao lưu và phục hồi. Không cần can thiệp mã nguồn.'),
    ]
    for r in sys_reqs:
        row = tbl6.add_row()
        for i, val in enumerate(r):
            cell = row.cells[i]
            cell_text(cell, val, size=9,
                      align=WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT)

    doc.add_paragraph()

    # ── IV. YÊU CẦU CHẤT LƯỢNG ────────────────────────────────────────────
    add_heading(doc, 'IV. XÁC ĐỊNH YÊU CẦU VỀ CHẤT LƯỢNG', level=2, color='1A5276')

    tbl7 = doc.add_table(rows=1, cols=4)
    tbl7.style = 'Table Grid'
    h4 = ['STT', 'Nội dung', 'Tiêu chuẩn', 'Mô tả chi tiết']
    w4 = [Cm(1), Cm(4), Cm(2.5), Cm(9)]
    for i, h in enumerate(h4):
        tbl7.columns[i].width = w4[i]
    make_table_header_row(tbl7, h4, bg='FFE6CC', size=10)

    qual_reqs = [
        ('1', 'Tốc độ phản hồi đăng nhập', 'Hiệu quả',
         'Thời gian phản hồi login endpoint ≤ 500ms (chưa tính ML timeout). '
         'ML scoring có timeout 500ms — nếu quá → ml_status=error, risk_level fallback medium.'),
        ('2', 'Xử lý MFA tức thì', 'Hiệu quả',
         'MFA verify phản hồi ≤ 300ms. Pre-auth transaction hết hạn sau 5 phút.'),
        ('3', 'Giao diện trực quan, dễ sử dụng', 'Tiện dụng',
         'SOC dashboard hiển thị alerts rõ ràng theo risk_level (màu sắc). '
         'Lọc nhanh theo status và risk. Thông báo lỗi cụ thể, không generic khi không cần.'),
        ('4', 'Cho phép thay đổi cấu hình ngưỡng rủi ro', 'Tiến hóa',
         'SYSADM có thể thay đổi ngưỡng risk (low/medium/high/critical) '
         'mà không cần can thiệp mã nguồn — qua cấu hình hoặc DB.'),
        ('5', 'Tương thích đa nền tảng', 'Tương thích',
         'Hệ thống chạy trên Docker (Linux/macOS/Windows). '
         'API RESTful tương thích mọi client HTTP (web browser, curl, Postman).'),
        ('6', 'Bảo mật dữ liệu đăng nhập', 'Bảo mật',
         'Password hash Argon2id. Không lưu token thô — chỉ hash. '
         'Generic login error không leak username tồn tại. '
         'MFA bound IP để chống relay.'),
    ]
    for r in qual_reqs:
        row = tbl7.add_row()
        for i, val in enumerate(r):
            cell = row.cells[i]
            cell_text(cell, val, size=9,
                      align=WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT)

    doc.add_paragraph()

    # ── WORKFLOW DIAGRAMS ───────────────────────────────────────────────────
    add_heading(doc, 'V. SƠ ĐỒ LUỒNG HOẠT ĐỘNG CHÍNH', level=2, color='1A5276')

    add_para(doc, '5.1 Luồng WF-1: Đăng nhập (Login Flow)', bold=True, size=11)
    add_para(doc,
        'Mô tả: User gửi username/password → kiểm tra credentials → ALLOW/MFA_REQUIRED/DENY. '
        'Nếu MFA_REQUIRED → tạo pre-auth transaction → user gửi OTP → verify → tạo session → trả access_token.',
        size=10)
    img_path = os.path.join(BASE, 'docs/diagrams/fig_wf1_login.png')
    add_image(doc, img_path, width=Cm(14))

    doc.add_paragraph()
    add_para(doc, '5.2 Luồng WF-2: Detection Inline (Risk Assessment)', bold=True, size=11)
    add_para(doc,
        'Mô tả: Sau khi login thành công → gọi /internal/v1/detect → trích features (IP, fail_count, '
        'device, time…) → gọi ML scoring (Isolation Forest) → lưu risk_assessment → '
        'nếu risk_level HIGH/CRITICAL → tạo alert.',
        size=10)
    img_path2 = os.path.join(BASE, 'docs/diagrams/fig_wf2_detection.png')
    add_image(doc, img_path2, width=Cm(14))

    doc.add_paragraph()
    add_para(doc, '5.3 Luồng WF-3: SOC — Xem và xử lý Alert', bold=True, size=11)
    add_para(doc,
        'Mô tả: SOC xem danh sách alerts (lọc theo status, risk_level) → xem chi tiết → '
        'acknowledge (chuyển open → acknowledged) hoặc resolve '
        '(chuyển acknowledged → resolved / false_positive).',
        size=10)
    img_path3 = os.path.join(BASE, 'docs/diagrams/fig_wf3_soc_alerts.png')
    add_image(doc, img_path3, width=Cm(14))

    doc.add_paragraph()
    add_para(doc, '5.4 Tổng quan kiến trúc hệ thống', bold=True, size=11)
    add_para(doc,
        'Mô tả: Kiến trúc tổng quan 3 workflow. FastAPI xử lý tất cả (auth + detection + ML) '
        'trong 1 process. PostgreSQL lưu trữ (1 schema public). Không Redis. Không background worker.',
        size=10)
    img_path4 = os.path.join(BASE, 'docs/diagrams/fig_architecture_overview.png')
    add_image(doc, img_path4, width=Cm(15))

    doc.save(out_path)
    print(f'✓ Saved: {out_path}')

# ─── REPORT 2 ────────────────────────────────────────────────────────────────

def gen_object_analysis_report(out_path):
    doc = Document()

    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # ── HEADER ─────────────────────────────────────────────────────────────
    add_heading(doc, 'ĐỀ TÀI: HỆ THỐNG SENTINEL AUTH', level=1, color='1A5276')
    add_para(doc, 'Hệ thống giám sát bất thường đăng nhập — phát hiện rủi ro bằng ML', size=10, bold=False)
    doc.add_paragraph()

    # ── USER ROLES & FUNCTIONS ──────────────────────────────────────────────
    add_heading(doc, '1) CÁC ĐỐI TƯỢNG SỬ DỤNG (User Roles) VÀ CHỨC NĂNG', level=2, color='1A5276')

    # User
    add_heading(doc, 'a. User (Người dùng)', level=3, color='2C3E50')
    add_para(doc, 'Vai trò: Người dùng hệ thống — đăng nhập có xác thực và quản lý MFA.', size=10)

    add_bold_bullet(doc, 'Chức năng đăng nhập (Tài khoản, mật khẩu, MFA OTP):', '')
    add_bullet(doc, 'Gửi username + password → nhận ALLOW / MFA_REQUIRED / DENY.')
    add_bullet(doc, 'Nếu MFA_REQUIRED → nhập mã OTP (6 chữ số, email) → xác thực → nhận access_token.')
    add_bullet(doc, 'Đăng xuất → thu hồi session.')

    add_bold_bullet(doc, 'Xem thông tin cá nhân:', '')
    add_bullet(doc, 'Xem username, email, trạng thái tài khoản.')

    add_bold_bullet(doc, 'Nhận thông báo:', '')
    add_bullet(doc, 'Nhận phản hồi từ hệ thống về kết quả đăng nhập và MFA.')

    doc.add_paragraph()

    # SOC
    add_heading(doc, 'b. SOC Analyst (Nhân viên giám sát an ninh)', level=3, color='2C3E50')
    add_para(doc, 'Vai trò: Giám sát các cảnh báo rủi ro, điều tra và xử lý các đăng nhập bất thường.', size=10)

    add_bold_bullet(doc, 'Chức năng đăng nhập (Tài khoản, mật khẩu, MFA OTP):', '')
    add_bullet(doc, 'Giống User — SOC có tài khoản riêng với vai trò soc.')

    add_bold_bullet(doc, 'Giám sát Alerts:', '')
    add_bullet(doc, 'Xem danh sách alerts với bộ lọc: status (open/acknowledged/resolved), risk_level (low/medium/high/critical).')
    add_bullet(doc, 'Xem chi tiết alert: thông tin user, IP, risk scores, thời gian, rule hit, reason codes.')
    add_bullet(doc, 'Acknowledge alert: ghi nhận đã xem xét, gán assigned_to và notes.')
    add_bullet(doc, 'Resolve alert: xác nhận đã xử lý xong, ghi resolved_by và resolved_at.')

    add_bold_bullet(doc, 'Tra cứu lịch sử đăng nhập:', '')
    add_bullet(doc, 'Xem toàn bộ login_attempts của một user để hỗ trợ điều tra.')

    add_bold_bullet(doc, 'Thống kê:', '')
    add_bullet(doc, 'Tổng số alerts theo risk_level, tỉ lệ ML degradation, số alerts chưa xử lý.')

    doc.add_paragraph()

    # System Admin
    add_heading(doc, 'c. System Administrator (Quản trị hệ thống)', level=3, color='2C3E50')
    add_para(doc, 'Vai trò: Quản lý tài khoản, cấu hình hệ thống, theo dõi nhật ký và bảo trì kỹ thuật.', size=10)

    add_bold_bullet(doc, 'Quản lý tài khoản:', '')
    add_bullet(doc, 'Tạo tài khoản user và SOC. Cập nhật thông tin. Khóa/mở khóa tài khoản.')
    add_bullet(doc, 'Mật khẩu được hash bằng Argon2id — không lưu dạng plain text.')

    add_bold_bullet(doc, 'Phân quyền người dùng:', '')
    add_bullet(doc, 'Gán vai trò: user hoặc soc. Mỗi tài khoản 1 vai trò chính.')
    add_bullet(doc, 'Thay đổi vai trò áp dụng ngay lập tức.')

    add_bold_bullet(doc, 'Quản lý cấu hình hệ thống:', '')
    add_bullet(doc, 'Ngưỡng risk: low/medium/high/critical (thay đổi được mà không cần code).')
    add_bullet(doc, 'Thời gian hết hạn session và OTP.')
    add_bullet(doc, 'Cấu hình ML timeout (mặc định 500ms).')

    add_bold_bullet(doc, 'Theo dõi nhật ký hệ thống:', '')
    add_bullet(doc, 'Xem detection_logs: mỗi detection ghi: login_attempt_id, rule_score, anomaly_score, ml_status, risk_level, decision, thời gian.')
    add_bullet(doc, 'Xem alerts: theo dõi trạng thái alerts toàn hệ thống.')

    add_bold_bullet(doc, 'Thống kê hệ thống:', '')
    add_bullet(doc, 'Tổng số user, số alerts theo risk_level, tỉ lệ ML degradation, số login attempts.')

    add_bold_bullet(doc, 'Sao lưu và phục hồi:', '')
    add_bullet(doc, 'Sao lưu Docker volume PostgreSQL định kỳ.')
    add_bullet(doc, 'Phục hồi khi có sự cố.')

    doc.add_paragraph()

    # ── WORKFLOW DIAGRAMS ───────────────────────────────────────────────────
    add_heading(doc, '2) SƠ ĐỒ LUỒNG HOẠT ĐỘNG CHÍNH', level=2, color='1A5276')

    add_para(doc, '2.1 Luồng WF-1: Đăng nhập (Login Flow)', bold=True, size=11)
    add_para(doc,
        'Mô tả: User gửi username/password → kiểm tra credentials → ALLOW/MFA_REQUIRED/DENY. '
        'Nếu MFA_REQUIRED → tạo pre_auth_transaction → user gửi OTP → verify → tạo session → trả access_token.',
        size=10)
    add_image(doc, os.path.join(BASE, 'docs/diagrams/fig_wf1_login.png'), width=Cm(14))

    doc.add_paragraph()
    add_para(doc, '2.2 Luồng WF-2: Detection Inline (Risk Assessment)', bold=True, size=11)
    add_para(doc,
        'Mô tả: Sau login thành công → gọi /internal/v1/detect → trích features → '
        'gọi ML scoring (Isolation Forest) → lưu risk_assessment → tạo alert nếu risk HIGH/CRITICAL.',
        size=10)
    add_image(doc, os.path.join(BASE, 'docs/diagrams/fig_wf2_detection.png'), width=Cm(14))

    doc.add_paragraph()
    add_para(doc, '2.3 Luồng WF-3: SOC — Xem và xử lý Alert', bold=True, size=11)
    add_para(doc,
        'Mô tả: SOC xem danh sách alerts → xem chi tiết → acknowledge hoặc resolve. '
        'Alert state machine: open → acknowledged → resolved / false_positive.',
        size=10)
    add_image(doc, os.path.join(BASE, 'docs/diagrams/fig_wf3_soc_alerts.png'), width=Cm(14))

    doc.add_paragraph()
    add_para(doc, '2.4 Tổng quan kiến trúc hệ thống', bold=True, size=11)
    add_para(doc,
        'Mô tả: FastAPI xử lý 3 workflow trong 1 process. PostgreSQL lưu trữ (1 schema public). '
        'Không Redis, không background worker. Detection chạy inline trong request.',
        size=10)
    add_image(doc, os.path.join(BASE, 'docs/diagrams/fig_architecture_overview.png'), width=Cm(15))

    doc.add_paragraph()

    # ── TECHNICAL SUMMARY ───────────────────────────────────────────────────
    add_heading(doc, '3) TÓM TẮT KỸ THUẬT', level=2, color='1A5276')

    add_para(doc, 'Công nghệ sử dụng:', bold=True, size=11)
    add_bullet(doc, 'Backend: FastAPI (Python 3.11) — 1 process duy nhất.')
    add_bullet(doc, 'Database: PostgreSQL (1 schema public) — lưu users, sessions, login_attempts, risk_assessments, alerts, detection_logs.')
    add_bullet(doc, 'ML: Isolation Forest (scikit-learn) — chạy inline trong request.')
    add_bullet(doc, 'Password hashing: Argon2id.')
    add_bullet(doc, 'MFA: OTP 6 chữ số qua email.')
    add_bullet(doc, 'Container: Docker Compose (app + postgres).')

    doc.add_paragraph()
    add_para(doc, 'Không sử dụng:', bold=True, size=11)
    add_bullet(doc, 'Không Redis — detection chạy inline, không cần background worker.')
    add_bullet(doc, 'Không multi-package/multi-schema — 1 schema public duy nhất.')
    add_bullet(doc, 'Không notification worker — alerts trả về JSON trực tiếp.')
    add_bullet(doc, 'Không RBAC phức tạp — 2 vai trò: user, soc.')

    doc.save(out_path)
    print(f'✓ Saved: {out_path}')


# ─── MAIN ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    out1 = os.path.join(BASE, 'docs/01_BangYeuCau_ChucNangNghiepVu_SentinelAuth.docx')
    out2 = os.path.join(BASE, 'docs/02_PhanTichDoiTuong_SentinelAuth.docx')

    gen_requirement_report(out1)
    gen_object_analysis_report(out2)

    print('\nDone.')
