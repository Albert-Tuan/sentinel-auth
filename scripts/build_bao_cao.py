#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dựng báo cáo Đồ án từ FILE MẪU.

Nguyên tắc:
  * Mở chính file mẫu bằng python-docx để kế thừa nguyên vẹn: styles.xml,
    docDefaults (Times New Roman 13pt), numbering.xml, theme, sectPr (A4,
    lề 2,54cm), header (dòng "Báo cáo Đồ án ...") và footer (số trang).
  * Xoá toàn bộ nội dung thân tài liệu, giữ lại sectPr cuối cùng.
  * Dựng lại: trang bìa (theo đúng bố cục mẫu), MỤC LỤC, DANH SÁCH HÌNH/BẢNG,
    DANH MỤC TỪ VIẾT TẮT, rồi 6 chương + tài liệu tham khảo.

Cách dùng:
    python3 scripts/build_bao_cao.py
    python3 scripts/build_bao_cao.py --out /đường/dẫn/tới/file.docx

Sửa D3.1/D4.1 (v3.3):
  * Unicode: mọi text đi qua unicodedata.normalize("NFC", ...) trước khi
    chèn vào DOCX.
  * Font: thiết lập Times New Roman rõ ràng cho Normal + mọi Heading style,
    cả ascii/hAnsi lẫn eastAsia.
  * Hình ảnh: luôn inline + canh giữa, bề rộng tối đa A4, giữ tỉ lệ.
"""
from __future__ import annotations

import argparse
import copy
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "docs" / "bao-cao"))

import _content_ch1 as C1  # noqa: E402
import _content_ch2 as C2  # noqa: E402
import _content_ch3a as C3A  # noqa: E402
import _content_ch3b as C3B  # noqa: E402
import _content_ch4 as C4  # noqa: E402
import _content_ch5_ch6 as C5C6  # noqa: E402
import _content_head as H  # noqa: E402

TEMPLATE = Path(
    "/home/thaus/GoogleDrive/Bài Tập/Information System/"
    "Mau Cuon Bao Cao Do An PT&TKHTTT.docx"
)
DOCS = ROOT / "docs"
DEFAULT_OUT = Path(
    "/home/thaus/GoogleDrive/Bài Tập/Information System/"
    "BaoCaoPT_TKHTTT_Nhom2_Revised.docx"
)

#: Bề rộng vùng in dùng được = A4 21cm - lề trái 2,54 - lề phải 2,54
TEXT_W_CM = 21.0 - 2.54 - 2.54

#: Những mục trong file mẫu bị loại bỏ vì là ví dụ về đề tài khác (quản lý nhà trọ)
#: Danh sách heading bị loại nằm trong --drop-heading để người dùng kiểm soát.


# ---------------------------------------------------------------------------
# Tiện ích Unicode
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Chuẩn hoá Unicode về NFC trước khi chèn vào DOCX.

    NFC đảm bảo chữ tiếng Việt được ghép đúng (base + combining mark)
    thay vì tách rời, tránh hiện tượng ký tự phân mảnh trên Linux.
    """
    if not isinstance(text, str):
        return text
    return unicodedata.normalize("NFC", text)


# ---------------------------------------------------------------------------
# Tiện ích XML
# ---------------------------------------------------------------------------

def _el(tag: str, **attrs: object) -> OxmlElement:
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(f"w:{k}"), str(v))
    return e


def _hide_run(run) -> None:
    """Đánh dấu một run là văn bản ẩn (w:vanish) như in trong Word."""
    rPr = run._r.get_or_add_rPr()
    rPr.append(_el("w:vanish"))
    rPr.append(_el("w:webHidden"))


def set_spacing(par, *, before: int | None = None, after: int | None = None,
                line: int | None = None) -> None:
    """Đặt khoảng cách đoạn bằng đơn vị nửa điểm và twip."""
    pPr = par._p.get_or_add_pPr()
    sp = pPr.find(qn("w:spacing"))
    if sp is None:
        sp = _el("w:spacing")
        pPr.append(sp)
    if before is not None:
        sp.set(qn("w:before"), str(before))
    if after is not None:
        sp.set(qn("w:after"), str(after))
    if line is not None:
        sp.set(qn("w:line"), str(line))
        sp.set(qn("w:lineRule"), "auto")


def set_indent(par, *, first_line: int | None = None, left: int | None = None,
               hanging: int | None = None) -> None:
    pPr = par._p.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = _el("w:ind")
        pPr.append(ind)
    if first_line is not None:
        ind.set(qn("w:firstLine"), str(first_line))
    if left is not None:
        ind.set(qn("w:left"), str(left))
    if hanging is not None:
        ind.set(qn("w:hanging"), str(hanging))


def set_keep(par, *, with_next: bool = True, together: bool = True,
             page_break_before: bool = False) -> None:
    """Chống đứt tiêu đề ở cuối trang — yêu cầu mục VIII của đề tài."""
    pPr = par._p.get_or_add_pPr()
    for tag, on in (("w:keepNext", with_next), ("w:keepLines", together),
                    ("w:pageBreakBefore", page_break_before)):
        e = pPr.find(qn(tag))
        if on and e is None:
            pPr.append(_el(tag))
        elif not on and e is not None:
            pPr.remove(e)


def shade(cell, hex_fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(_el("w:shd", val="clear", color="auto", fill=hex_fill))


def cell_valign(cell, val: str = "center") -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(_el("w:vAlign", val=val))


def repeat_header_row(row) -> None:
    """Lặp lại dòng tiêu đề khi bảng tràn sang trang sau."""
    trPr = row._tr.get_or_add_trPr()
    trPr.append(_el("w:tblHeader"))


def cant_split_row(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    trPr.append(_el("w:cantSplit"))


def add_page_number_footer(section) -> None:
    """Đặt lại footer: số trang canh giữa, khớp với mẫu."""
    footer = section.footer
    footer.is_linked_to_previous = False
    for p in list(footer.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    p = footer.paragraphs[0]
    for child in list(p._p):
        if etree_is_r(child):
            p._p.remove(child)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_spacing(p, before=0, after=0, line=240)
    run = p.add_run()
    for tag, attr in (("w:fldChar", "begin"),):
        e = _el(tag, fldCharType=attr)
        run._r.append(e)
    run2 = p.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = " PAGE "
    run2._r.append(it)
    run3 = p.add_run()
    run3._r.append(_el("w:fldChar", fldCharType="separate"))
    run4 = p.add_run("1")
    run5 = p.add_run()
    run5._r.append(_el("w:fldChar", fldCharType="end"))


def etree_is_r(child) -> bool:
    return child.tag == qn("w:r")


def set_update_fields(doc) -> None:
    """Bắt Word cập nhật mục lục và danh sách hình/bảng khi mở tệp."""
    settings = doc.settings.element
    for tag in ("w:updateFields",):
        e = settings.find(qn(tag))
        if e is None:
            settings.append(_el(tag, val="true"))


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def _set_font_on_rFonts(element, font_name: str) -> None:
    """Đặt tên font trên rFonts element cho ascii/hAnsi/eastAsia.

    element thường là style._element (pPr.rPr hoặc rPr trực tiếp).
    Đặt cả ba để đảm bảo font hiển thị đúng trên Linux/Windows/WPS.
    """
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        element.set(qn(attr), font_name)


def _apply_run_font(run, font_name: str = "Times New Roman") -> None:
    """Đặt font cho một run, bao gồm cả eastAsia."""
    run.font.name = font_name
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    _set_font_on_rFonts(rFonts, font_name)


def set_document_fonts(doc) -> None:
    """Thiết lập Times New Roman cho Normal và mọi Heading style.

    Áp dụng cho cả ascii/hAnsi lẫn eastAsia để chữ Việt hiển thị đúng
    trên mọi bộ office (Word, LibreOffice, WPS).
    """
    FONT = "Times New Roman"
    style_names = ["Normal", "Heading 1", "Heading 2", "Heading 3",
                   "Heading 4", "Heading 5", "Heading 6",
                   "List Paragraph", "Caption"]

    for name in style_names:
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        style.font.name = FONT
        # Đặt trên rPr/rFonts để python-docx không bị ghi đè
        rPr = style.element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.insert(0, rFonts)
        _set_font_on_rFonts(rFonts, FONT)

        # Kích thước mặc định
        if name == "Normal":
            style.font.size = Pt(13)

    # Cũng cập nhật docDefaults rPr (phong cách mặc định cho toàn tài liệu)
    docDefaults = doc.styles.element.find(qn("w:docDefaults"))
    if docDefaults is not None:
        rPrDefault = docDefaults.find(qn("w:rPrDefault"))
        if rPrDefault is None:
            rPrDefault = OxmlElement("w:rPrDefault")
            docDefaults.append(rPrDefault)
        rPr = rPrDefault.find(qn("w:rPr"))
        if rPr is None:
            rPr = OxmlElement("w:rPr")
            rPrDefault.append(rPr)
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.insert(0, rFonts)
        _set_font_on_rFonts(rFonts, FONT)


# ---------------------------------------------------------------------------
# Dựng các loại khối
# ---------------------------------------------------------------------------

def add_para(doc, text: str, *, style: str | None = None,
             align: str | None = None, indent_first: bool = True,
             italic: bool = False, bold: bool = False,
             size_pt: float | None = None, space_after: int = 120,
             space_before: int = 0, line: int = 300,
             keep_next: bool = False, color: str | None = None) -> object:
    p = doc.add_paragraph()
    if style:
        p.style = doc.styles[style]
    pf = p.paragraph_format
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "both":
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    elif align == "right":
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_spacing(p, before=space_before, after=space_after, line=line)
    if indent_first and not style:
        set_indent(p, first_line=709)  # 1,25 cm
    if keep_next:
        set_keep(p, with_next=True, together=True)
    if text:
        run = p.add_run(normalize(text))
        run.italic = italic
        run.bold = bold
        if size_pt:
            run.font.size = Pt(size_pt)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
        # Đảm bảo font chuẩn trên mọi run chèn text
        _apply_run_font(run)
    return p


def add_heading(doc, level: int, text: str) -> object:
    """Dùng đúng style Heading N của file mẫu, không tự định dạng tay."""
    style = f"Heading {level}"
    p = doc.add_paragraph()
    p.style = doc.styles[style]
    run = p.add_run(normalize(text))
    # Đảm bảo font chuẩn trên run tiêu đề
    _apply_run_font(run)
    # Giữ tiêu đề cùng trang với nội dung ngay sau nó
    set_keep(p, with_next=True, together=True)
    # Canh giữa: mẫu canh giữa các tiêu đề cấp 1
    if level == 1:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return p


def add_bullet(doc, text: str) -> object:
    p = doc.add_paragraph(style=doc.styles["List Paragraph"])
    run = p.add_run("•  " + normalize(text))
    _apply_run_font(run)
    pf = p.paragraph_format
    set_indent(p, left=567, hanging=283)
    set_spacing(p, before=0, after=80, line=300)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    return p


def add_caption(doc, text: str) -> object:
    """Caption hình/bảng: định dạng y hệt mẫu, kèm trường TC ẩn để Word
    dựng được Danh sách hình, bảng."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_spacing(p, before=60, after=200, line=288)
    run = p.add_run(normalize(text))
    run.bold = True
    _apply_run_font(run)

    # Trường TC ẩn: đánh dấu caption cho danh sách hình bảng
    tc = p.add_run()
    _hide_run(tc)
    tc._r.append(_el("w:fldChar", fldCharType="begin"))
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f' TC "{normalize(text)}" \\f c \\l 1 '
    tc._r.append(instr)
    tc._r.append(_el("w:fldChar", fldCharType="end"))
    return p


#: Chiều rộng vùng nội dung và chiều cao tối đa cho một hình (cm).
#: A4 khổ dọc, lề 2,54cm mỗi cạnh, trừ chỗ cho caption + một đoạn nội dung.
MAX_IMG_W_CM = 15.5
MAX_IMG_H_CM = 19.5


def insert_figure(doc, image_path: Path | str,
                  caption: str | None = None,
                  width_cm: float = MAX_IMG_W_CM) -> object:
    """Chèn hình ảnh inline, canh giữa, tự thu nhỏ nếu vượt quá khung A4.

    * Luôn canh giữa paragraph chứa ảnh.
    * Giới hạn bề rộng tối đa = ``width_cm`` (mặc định 15,5 cm cho A4 lề 2,54).
    * Giữ tỉ lệ gốc — không bóp méo.
    * Nếu ảnh quá cao cho một trang, giới hạn chiều cao = MAX_IMG_H_CM.
    * Chèn caption (tùy chọn) bên dưới ảnh, canh giữa.
    * Font chuẩn cho caption.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"thiếu hình: {path}")

    w_cm = min(width_cm, MAX_IMG_W_CM)
    with Image.open(path) as im:
        px_w, px_h = im.size
    if not px_h:
        raise ValueError(f"hình không hợp lệ: {path}")

    # Tính chiều cao tương ứng giữ nguyên tỉ lệ
    h_cm = w_cm * px_h / px_w
    if h_cm > MAX_IMG_H_CM:
        h_cm = MAX_IMG_H_CM
        w_cm = h_cm * px_w / px_h

    # Tạo paragraph chứa ảnh — luôn canh giữa
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_spacing(p, before=120, after=60, line=240)

    # Chèn ảnh inline (mặc định inline, không phải floating)
    run = p.add_run()
    run.add_picture(str(path), width=Cm(w_cm), height=Cm(h_cm))

    # Thêm caption nếu có
    if caption:
        cap_p = doc.add_paragraph()
        cap_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_spacing(cap_p, before=40, after=160, line=240)
        cap_run = cap_p.add_run(normalize(caption))
        cap_run.italic = True
        _apply_run_font(cap_run)

        # Trường TC ẩn cho danh sách hình
        tc = cap_p.add_run()
        _hide_run(tc)
        tc._r.append(_el("w:fldChar", fldCharType="begin"))
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = f' TC "{normalize(caption)}" \\f c \\l 1 '
        tc._r.append(instr)
        tc._r.append(_el("w:fldChar", fldCharType="end"))

    return p


def add_image(doc, key: str, width_cm: float,
              caption: str | None = None) -> object:
    """API cũ — giữ tương thích ngược: chèn hình theo key trong H.HINH."""
    path = DOCS / H.HINH[key]
    return insert_figure(doc, path, caption=caption, width_cm=width_cm)


def _apply_table_borders(tbl) -> None:
    """Viền mảnh màu đen, giống hệt file mẫu (sz=4)."""
    tblPr = tbl._tbl.tblPr
    for e in tblPr.findall(qn("w:tblBorders")):
        tblPr.remove(e)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        borders.append(_el(f"w:{edge}", val="single", sz="4", space="0",
                           color="000000"))
    tblPr.append(borders)


def _new_table(doc, ncols: int, widths: list[float]):
    """Tạo bảng mới theo đúng thuộc tính bảng của file mẫu."""
    t = doc.add_table(rows=0, cols=ncols)
    _ = None  # bảng của mẫu không dùng style dựng sẵn, viền đặt thủ công bên dưới
    t.autofit = False

    tblPr = t._tbl.tblPr
    for tag in ("w:tblW", "w:tblLayout", "w:tblLook", "w:tblBorders", "w:jc"):
        for e in tblPr.findall(qn(tag)):
            tblPr.remove(e)
    _apply_table_borders(t)
    tblPr.append(_el("w:tblW", w=int(sum(widths) * 567), type="dxa"))
    tblPr.append(_el("w:jc", val="center"))
    tblPr.append(_el("w:tblLayout", type="fixed"))
    tblPr.append(_el("w:tblLook", val="04A0", firstRow="1", lastRow="0",
                     firstColumn="1", lastColumn="0", noHBand="0", noVBand="1"))

    # Đặt lại lưới cột
    grid = t._tbl.find(qn("w:tblGrid"))
    for gc in list(grid):
        grid.remove(gc)
    for w in widths:
        grid.append(_el("w:gridCol", w=int(w * 567)))
    return t


def add_table(doc, spec: dict) -> object:
    """Bảng: viền mảnh, cố định bề rộng cột, lặp dòng tiêu đề, không vỡ lề."""
    header: list[str] = spec["header"]
    rows: list[list[str]] = spec["rows"]
    widths: list[float] = spec["widths"]

    ncols = len(header)
    assert all(len(r) == ncols for r in rows), "số cột của dòng không khớp tiêu đề"
    # Chuẩn hoá bề rộng cho khớp đúng vùng in
    widths = [w * TEXT_W_CM / sum(widths) for w in widths]

    t = _new_table(doc, ncols, widths)

    def fill_row(cells_vals: list[str], *, header_row: bool) -> None:
        row = t.add_row()
        cant_split_row(row)
        if header_row:
            repeat_header_row(row)
        for i, (cell, val) in enumerate(zip(row.cells, cells_vals)):
            cell.width = Cm(widths[i])
            cell_valign(cell, "center")
            p = cell.paragraphs[0]
            p.text = ""
            # canh giữa cột ngắn, giải trang cột dài
            long_col = widths[i] >= 2.6
            p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if long_col
                           else WD_ALIGN_PARAGRAPH.CENTER)
            set_spacing(p, before=40, after=40, line=264)
            run = p.add_run(normalize(str(val)))
            run.font.size = Pt(11.5)
            run.bold = header_row
            _apply_run_font(run)
            if header_row:
                shade(cell, "D9D9D9")

    fill_row(header, header_row=True)
    for r in rows:
        fill_row(r, header_row=False)

    # khoảng cách sau bảng
    tail = doc.add_paragraph()
    set_spacing(tail, before=0, after=80, line=240)
    return t


# ---------------------------------------------------------------------------
# Trang bìa — bám đúng bố cục file mẫu
# ---------------------------------------------------------------------------

def _cover_line(doc, runs: list[tuple[str, dict]], *, align: str = "center",
                before: int = 0, after: int = 0) -> object:
    p = doc.add_paragraph()
    p.alignment = (WD_ALIGN_PARAGRAPH.CENTER if align == "center"
                   else WD_ALIGN_PARAGRAPH.JUSTIFY)
    set_spacing(p, before=before, after=after, line=240)
    for text, fmt in runs:
        r = p.add_run(normalize(text))
        r.bold = fmt.get("b", False)
        if fmt.get("sz"):
            r.font.size = Pt(fmt["sz"])
        _apply_run_font(r)
    return p


def build_cover(doc) -> None:
    monhoc = H.TRANG_BIA[0][1]
    detai = H.TRANG_BIA[1][1]
    gv = H.TRANG_BIA[2][1]
    members = H.TRANG_BIA[3][1]
    dich = H.TRANG_BIA[4][1]

    # --- Đầu trang bìa ---
    _cover_line(doc, [("BỘ KHOA HỌC VÀ CÔNG NGHỆ", {"b": True, "sz": 16})], after=0)
    _cover_line(doc, [("HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG",
                       {"b": True, "sz": 16})], after=6)
    _cover_line(doc, [("-" * 29, {"sz": 16})], after=0)

    for _ in range(3):
        _cover_line(doc, [("", {})])

    # --- BÁO CÁO ĐỒ ÁN MÔN HỌC ---
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_spacing(p, before=0, after=0, line=240)
    r = p.add_run(normalize("BÁO CÁO "))
    r.bold = True
    r.font.size = Pt(36)
    r2 = p.add_run()
    r2.bold = True
    r2.font.size = Pt(36)
    r2._r.append(_el("w:br"))
    r3 = p.add_run(normalize("ĐỒ ÁN MÔN HỌC"))
    r3.bold = True
    r3.font.size = Pt(36)
    for r_ in (r, r2, r3):
        _apply_run_font(r_)

    for _ in range(3):
        _cover_line(doc, [("", {})])

    # --- MÔN HỌC / ĐỀ TÀI ---
    _cover_line(doc, [(f"MÔN HỌC: {monhoc}", {"b": True, "sz": 16})], before=6)
    _cover_line(doc, [(f"ĐỀ TÀI: {detai}", {"b": True, "sz": 16})], before=6)

    for _ in range(6):
        _cover_line(doc, [("", {})])

    # --- Giảng viên ---
    _cover_line(doc, [("Giảng viên hướng dẫn: ", {"b": True}), (gv, {})],
                align="both")

    for _ in range(1):
        _cover_line(doc, [("", {})])

    _cover_line(doc, [("Thực hiện bởi nhóm sinh viên, bao gồm: ", {"b": True})],
                align="both")

    for i, (ho_ten, mssv, lop, vai_tro) in enumerate(members, start=1):
        p = doc.add_paragraph()
        set_spacing(p, before=0, after=0, line=276)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        set_indent(p, left=720, hanging=360)
        parts = [
            f"{i}. {ho_ten}", "\t", mssv, "\t", lop, "\t\t", vai_tro
        ]
        for part in parts:
            r = p.add_run(normalize(part) if part != "\t" else part)
            _apply_run_font(r)

    for _ in range(5):
        _cover_line(doc, [("", {})])

    # --- Địa điểm, thời gian ---
    _cover_line(doc, [(dich, {"b": True, "sz": 13})])

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


# ---------------------------------------------------------------------------
# Mục lục, danh sách hình bảng, danh mục từ viết tắt
# ---------------------------------------------------------------------------

def _field_block(doc, instr: str, placeholder: str) -> None:
    """Chèn một trường Word (TOC, TOA) có nội dung tạm để mở lên cập nhật."""
    p = doc.add_paragraph()
    r = p.add_run()
    r._r.append(_el("w:fldChar", fldCharType="begin", dirty="true"))
    r2 = p.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r2._r.append(it)
    r3 = p.add_run()
    r3._r.append(_el("w:fldChar", fldCharType="separate"))
    r4 = p.add_run(normalize(placeholder))
    r4.italic = True
    _apply_run_font(r4)
    r5 = p.add_run()
    r5._r.append(_el("w:fldChar", fldCharType="end"))


def build_front_matter(doc) -> None:
    # ---- MỤC LỤC ----
    add_heading(doc, 1, "MỤC LỤC")
    _field_block(
        doc,
        ' TOC \\o "1-3" \\h \\z \\u ',
        "Mở tệp này bằng Word và nhấn Ctrl+A rồi F9 (hoặc bấm chuột phải → "
        "Cập nhật trường) để sinh mục lục từ các tiêu đề thật.",
    )
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---- DANH SÁCH HÌNH, BẢNG ----
    add_heading(doc, 1, "DANH SÁCH HÌNH, BẢNG")
    _field_block(
        doc,
        ' TOC \\h \\z \\f c ',
        "Cập nhật trường bằng Ctrl+A rồi F9 để sinh danh sách hình và bảng "
        "từ các đoạn caption trong báo cáo.",
    )
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---- DANH MỤC TỪ VIẾT TẮT ----
    add_heading(doc, 1, "DANH MỤC TỪ VIẾT TẮT")
    add_para(doc, "Danh mục chỉ gồm những thuật ngữ thực sự xuất hiện trong "
                  "nội dung báo cáo.",
             indent_first=False, italic=True, space_after=200)
    t = _new_table(doc, 2, [3.0, TEXT_W_CM - 3.0])

    for idx, (abbrev, meaning) in enumerate(H.TU_VIET_TAT):
        row = t.add_row()
        cant_split_row(row)
        if idx == 0:
            repeat_header_row(row)
        for i, (cell, val) in enumerate(
                zip(row.cells, [abbrev, meaning])):
            cell.width = Cm(3.0 if i == 0 else TEXT_W_CM - 3.0)
            cell_valign(cell, "center")
            p = cell.paragraphs[0]
            p.text = ""
            p.alignment = (WD_ALIGN_PARAGRAPH.CENTER if i == 0
                           else WD_ALIGN_PARAGRAPH.LEFT)
            set_spacing(p, before=40, after=40, line=264)
            run = p.add_run(normalize(val))
            run.font.size = Pt(11.5)
            run.bold = idx == 0
            _apply_run_font(run)
            if idx == 0:
                shade(cell, "D9D9D9")
    _ = None
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


# ---------------------------------------------------------------------------
# Render danh sách khối
# ---------------------------------------------------------------------------

def render_blocks(doc, blocks: list[tuple[str, object]]) -> None:
    for kind, payload in blocks:
        if kind == "H1":
            add_heading(doc, 1, payload)
        elif kind == "H2":
            add_heading(doc, 2, payload)
        elif kind == "H3":
            add_heading(doc, 3, payload)
        elif kind == "H4":
            add_heading(doc, 4, payload)
        elif kind == "H5":
            add_heading(doc, 5, payload)
        elif kind == "P":
            add_para(doc, payload, align="both")
        elif kind == "PB":
            add_para(doc, payload, align="both", space_before=160)
        elif kind == "BUL":
            add_bullet(doc, payload)
        elif kind == "NOTE":
            add_para(doc, payload, align="both", indent_first=False,
                     italic=True, size_pt=12, space_before=100,
                     space_after=140)
        elif kind == "CAP":
            add_caption(doc, payload)
        elif kind == "EQ":
            add_para(doc, payload, align="center", indent_first=False,
                     italic=True, space_before=100, space_after=140)
        elif kind == "CODE":
            add_para(doc, payload, align="left", indent_first=False,
                     size_pt=11, space_after=80, line=240)
        elif kind == "IMG":
            add_image(doc, payload["key"], payload["width_cm"],
                      caption=payload.get("caption"))
        elif kind == "TABLE":
            add_table(doc, payload)
        elif kind == "PAGEBREAK":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        else:
            raise ValueError(f"không rõ loại khối: {kind!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--template", default=str(TEMPLATE))
    ap.add_argument("--smoke-test", action="store_true",
                    help="Tạo smoke-test DOCX thu nhỏ để kiểm tra Vietnamese")
    args = ap.parse_args()

    tpl = Path(args.template)
    if not tpl.exists():
        print(f"Không tìm thấy file mẫu: {tpl}", file=sys.stderr)
        return 1

    doc = Document(str(tpl))

    # 1) Bỏ sạch thân tài liệu, giữ sectPr cuối cùng (khổ A4 + lề của mẫu)
    body = doc.element.body
    sectPr = body.find(qn("w:sectPr"))
    for child in list(body):
        if child is not sectPr:
            body.remove(child)

    # 2) Chuẩn hoá lại tên style để tránh xung đột với style của Google Docs
    for sec in doc.sections:
        add_page_number_footer(sec)
        hdr = sec.header
        hdr.is_linked_to_previous = False
        if hdr.paragraphs:
            hp = hdr.paragraphs[0]
            for r in list(hp.runs):
                r._r.getparent().remove(r._r)
            run = hp.add_run(normalize(
                "Báo cáo Đồ án Phân tích thiết kế hệ thống thông tin"
            ))
            _apply_run_font(run)

    set_update_fields(doc)

    # 3) Áp dụng font chuẩn toàn tài liệu
    set_document_fonts(doc)

    if args.smoke_test:
        # Smoke-test: tạo DOCX nhỏ kiểm tra Vietnamese rendering
        add_heading(doc, 1, "SMOKE TEST — Vietnamese Rendering")
        add_para(doc, "Đoạn văn tiếng Việt: Các ký tự có dấu phải hiển thị đúng: "
                     "ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÛĀĒĪŌŪăēīōūđẠẮẦẬẬẺẼỀỀỂỈỌỎỒỒỔỖỜỞỢỤỦỨỪửỰỲỴÝỹ",
                     align="both")
        add_heading(doc, 2, "Tiêu đề cấp 2 — Kiểm tra dấu")
        add_para(doc, "Tiêu đề cấp 3 với chữ Việt: Mục tiêu nghiệp vụ", align="both",
                 italic=True)
        add_para(doc, "Đây là đoạn bullet tiếng Việt:", align="both")
        add_bullet(doc, "Ghi nhận đầy đủ mọi lần đăng nhập")
        add_bullet(doc, "Đánh giá rủi ro của mỗi lần đăng nhập dựa trên hành vi")
        add_bullet(doc, "Tạo cảnh báo có đủ bằng chứng khi rủi ro vượt ngưỡng")
        add_para(doc, "Đoạn ghi chú: Mô hình học máy dùng để suy luận mức bất thường "
                     "của lần đăng nhập dựa trên lịch sử hành vi người dùng.",
                 align="both", italic=True, space_after=200)
        add_heading(doc, 3, "Bảng minh họa")
        add_table(doc, {
            "header": ["Cột 1", "Cột 2 — Tiếng Việt", "Cột 3"],
            "rows": [
                ["Hàng 1", "Giá trị minh họa", "Số liệu"],
                ["Hàng 2", "Bảo mật thông tin", "123"],
                ["Hàng 3", "Xác thực đa yếu tố", "456"],
            ],
            "widths": [3.0, 8.0, 4.0],
        })
        add_para(doc, "Kết thúc smoke test.", align="both", space_after=200)

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out))
        n_img = sum(1 for r in doc.part.rels.values() if "image" in r.reltype)
        print(f"Smoke-test DOCX: {out}")
        print(f"  đoạn văn: {len(doc.paragraphs)}")
        print(f"  bảng    : {len(doc.tables)}")
        print(f"  hình    : {n_img}")
        print(f"  dung lượng: {out.stat().st_size / 1024:.0f} KiB")
        return 0

    # 4) Dựng nội dung đầy đủ
    build_cover(doc)
    build_front_matter(doc)

    render_blocks(doc, C1.CHUONG_I)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    render_blocks(doc, C2.CHUONG_II)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    render_blocks(doc, C3A.CHUONG_III_A)
    render_blocks(doc, C3B.CHUONG_III_B)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    render_blocks(doc, C4.CHUONG_IV)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    render_blocks(doc, C5C6.CHUONG_V)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    render_blocks(doc, C5C6.CHUONG_VI)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    render_blocks(doc, C5C6.TAI_LIEU_THAM_KHAO)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))

    # 5) In báo cáo kết quả
    n_tbl = len(doc.tables)
    n_img = sum(1 for r in doc.part.rels.values() if "image" in r.reltype)
    n_par = len(doc.paragraphs)
    print(f"Đã tạo: {out}")
    print(f"  đoạn văn : {n_par}")
    print(f"  bảng     : {n_tbl}")
    print(f"  hình     : {n_img}")
    print(f"  dung lượng: {out.stat().st_size / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
