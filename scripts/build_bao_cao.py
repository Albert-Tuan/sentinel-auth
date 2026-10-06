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
"""
from __future__ import annotations

import argparse
import copy
import re
import shutil
import sys
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
        run = p.add_run(text)
        run.italic = italic
        run.bold = bold
        if size_pt:
            run.font.size = Pt(size_pt)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
    return p


def add_heading(doc, level: int, text: str) -> object:
    """Dùng đúng style Heading N của file mẫu, không tự định dạng tay."""
    style = f"Heading {level}"
    p = doc.add_paragraph()
    p.style = doc.styles[style]
    p.add_run(text)
    # Giữ tiêu đề cùng trang với nội dung ngay sau nó
    set_keep(p, with_next=True, together=True)
    # Canh giữa: mẫu canh giữa các tiêu đề cấp 1
    if level == 1:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return p


def add_bullet(doc, text: str) -> object:
    p = doc.add_paragraph(style=doc.styles["List Paragraph"])
    p.add_run("•  " + text)
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
    run = p.add_run(text)
    run.bold = True

    # Trường TC ẩn: đánh dấu caption cho danh sách hình bảng
    tc = p.add_run()
    _hide_run(tc)
    tc._r.append(_el("w:fldChar", fldCharType="begin"))
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f' TC "{text}" \\f c \\l 1 '
    tc._r.append(instr)
    tc._r.append(_el("w:fldChar", fldCharType="end"))
    return p


#: Chiều rộng vùng nội dung và chiều cao tối đa cho một hình (cm).
#: A4 khổ dọc, lề 2,54cm mỗi cạnh, trừ chỗ cho caption + một đoạn nội dung.
MAX_IMG_W_CM = 15.5
MAX_IMG_H_CM = 19.5


def add_image(doc, key: str, width_cm: float) -> object:
    """Chèn hình, tự thu nhỏ nếu vượt quá khung trang của file mẫu.

    Một số sơ đồ sinh bằng PlantUML có tỉ lệ rất dài, nếu chỉ giới hạn theo
    bề rộng thì chiều cao vượt quá một trang và Word sẽ cắt hình. Vì vậy ta
    lấy kích thước gốc, giới hạn theo cả bề rộng lẫn chiều cao, rồi mới đặt
    vào tài liệu.
    """
    path = DOCS / H.HINH[key]
    if not path.exists():
        raise FileNotFoundError(f"thiếu hình: {key} -> {path}")

    w_cm = min(width_cm, MAX_IMG_W_CM)
    with Image.open(path) as im:
        px_w, px_h = im.size
    if not px_h:
        raise ValueError(f"hình không hợp lệ: {key}")
    h_cm = w_cm * px_h / px_w
    if h_cm > MAX_IMG_H_CM:
        h_cm = MAX_IMG_H_CM
        w_cm = h_cm * px_w / px_h

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_spacing(p, before=120, after=60, line=240)
    p.add_run().add_picture(str(path), width=Cm(w_cm), height=Cm(h_cm))
    return p


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
            run = p.add_run(str(val))
            run.font.size = Pt(11.5)
            run.bold = header_row
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
        r = p.add_run(text)
        r.bold = fmt.get("b", False)
        if fmt.get("sz"):
            r.font.size = Pt(fmt["sz"])
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
    r = p.add_run("BÁO CÁO ")
    r.bold = True
    r.font.size = Pt(36)
    r2 = p.add_run()
    r2.bold = True
    r2.font.size = Pt(36)
    r2._r.append(_el("w:br"))
    r3 = p.add_run("ĐỒ ÁN MÔN HỌC")
    r3.bold = True
    r3.font.size = Pt(36)

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
        p.add_run(f"{i}. {ho_ten}")
        p.add_run("\t")
        p.add_run(mssv)
        p.add_run("\t")
        p.add_run(lop)
        p.add_run("\t\t")
        p.add_run(vai_tro)

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
    r4 = p.add_run(placeholder)
    r4.italic = True
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
            run = p.add_run(val)
            run.font.size = Pt(11.5)
            run.bold = idx == 0
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
            add_image(doc, payload["key"], payload["width_cm"])
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
            hp.add_run("Báo cáo Đồ án Phân tích thiết kế hệ thống thông tin")

    set_update_fields(doc)

    # 3) Dựng nội dung
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

    # 4) In báo cáo kết quả
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
