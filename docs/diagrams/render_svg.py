#!/usr/bin/env python3
"""Render draw.io XML → SVG. Minimal custom implementation."""
import xml.etree.ElementTree as ET
import os, sys, math

# ── Constants ────────────────────────────────────────────────────────────────
GRID = 10
ARROW_W, ARROW_H = 10, 6
ROUND = 4

# ── Color palettes (draw.io style) ─────────────────────────────────────────
FILL = {
    'rounded=1': '#DAE8FC',
    'rounded=0': '#FFF2CC',
    'ellipse': '#FFE6CC',
    'rhombus': '#FFE6CC',
    'cylinder3': '#F5F5F5',
    'umlActor': 'none',
    'text': 'none',
    'default': '#FFFFFF',
}
STROKE = {
    'default': '#333333',
    'DAE8FC': '#6C8EBF',
    'FFF2CC': '#D6A656',
    'FFE6CC': '#D79B00',
    'D5E8D4': '#82B366',
    'E1D5E7': '#9673A6',
    'CCE5FF': '#17A2B8',
    'F5F5F5': '#666666',
}

# ── Geometry helpers ─────────────────────────────────────────────────────────
def get_xy(cell, parent_w=0, parent_h=0):
    """Get absolute (x, y) of a cell."""
    x = float(cell.get('x', '0'))
    y = float(cell.get('y', '0'))
    parent = cell.get('parent', '1')
    # In practice, most cells are relative to parent=1 (root) so x/y is absolute
    return x, y

def get_geo(cell):
    """Return (x, y, w, h) from geometry element."""
    geo = cell.find('mxGeometry')
    if geo is None:
        # Try attributes directly
        x = float(cell.get('x', '0'))
        y = float(cell.get('y', '0'))
        w = float(cell.get('width', '80'))
        h = float(cell.get('height', '30'))
        return x, y, w, h
    x = float(geo.get('x', '0'))
    y = float(geo.get('y', '0'))
    w = float(geo.get('width', '80'))
    h = float(geo.get('height', '30'))
    return x, y, w, h

def escape(s):
    if s is None: return ''
    return (str(s)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;'))

# ── Shape renderers ──────────────────────────────────────────────────────────
def shape_rect(x, y, w, h, style, value, edge):
    fill = style.get('fillColor', '#FFFFFF')
    stroke = style.get('strokeColor', '#333333')
    sw = float(style.get('strokeWidth', '1'))
    r = style.get('rounded', '0')
    font_size = style.get('fontSize', '11')

    if r == '1':
        rx = ry = '5'
    else:
        rx = ry = '0'

    lines = value.split('\n') if value else []
    # Estimate text block height
    fs = float(font_size)
    line_h = fs * 1.3
    text_h = len(lines) * line_h
    text_y = y + (h - text_h) / 2 + fs * 0.8

    parts = []
    # Background rect
    if fill != 'none' and not edge:
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{rx}" ry="{ry}" fill="{fill}" stroke="{stroke}" stroke-width="{sw:.1f}"/>'
        )

    # Text
    if lines and not edge:
        text_parts = []
        for i, line in enumerate(lines):
            ty = text_y + i * line_h
            text_parts.append(
                f'<text x="{(x + w/2):.1f}" y="{ty:.1f}" '
                f'text-anchor="middle" font-size="{font_size}" '
                f'fill="{style.get("fontColor","#000000")}" '
                f'font-family="Arial,sans-serif">'
                f'{escape(line)}</text>'
            )
        parts.extend(text_parts)

    return '\n'.join(parts)

def shape_ellipse(x, y, w, h, style, value):
    fill = style.get('fillColor', '#FFE6CC')
    stroke = style.get('strokeColor', '#D79B00')
    sw = float(style.get('strokeWidth', '1'))
    font_size = style.get('fontSize', '11')
    fs = float(font_size)

    lines = value.split('\n') if value else []
    text_parts = []
    if lines:
        line_h = fs * 1.3
        text_h = len(lines) * line_h
        text_y = y + (h - text_h) / 2 + fs * 0.8
        for i, line in enumerate(lines):
            text_parts.append(
                f'<text x="{(x + w/2):.1f}" y="{text_y + i*line_h:.1f}" '
                f'text-anchor="middle" font-size="{font_size}" '
                f'fill="{style.get("fontColor","#000000")}" '
                f'font-family="Arial,sans-serif">'
                f'{escape(line)}</text>'
            )

    return (
        f'<ellipse cx="{(x+w/2):.1f}" cy="{(y+h/2):.1f}" '
        f'rx="{(w/2):.1f}" ry="{(h/2):.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw:.1f}"/>\n'
        + '\n'.join(text_parts)
    )

def shape_rhombus(x, y, w, h, style, value):
    fill = style.get('fillColor', '#FFE6CC')
    stroke = style.get('strokeColor', '#D79B00')
    sw = float(style.get('strokeWidth', '1'))
    font_size = style.get('fontSize', '11')
    fs = float(font_size)

    cx, cy = x + w/2, y + h/2
    pts = f'{cx:.1f},{y:.1f} {x+w:.1f},{cy:.1f} {cx:.1f},{y+h:.1f} {x:.1f},{cy:.1f}'

    lines = value.split('\n') if value else []
    text_parts = []
    if lines:
        line_h = fs * 1.3
        text_h = len(lines) * line_h
        text_y = cy - text_h/2 + fs * 0.8
        for i, line in enumerate(lines):
            text_parts.append(
                f'<text x="{cx:.1f}" y="{text_y + i*line_h:.1f}" '
                f'text-anchor="middle" font-size="{font_size}" '
                f'fill="{style.get("fontColor","#000000")}" '
                f'font-family="Arial,sans-serif">'
                f'{escape(line)}</text>'
            )

    return (
        f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw:.1f}"/>\n'
        + '\n'.join(text_parts)
    )

def shape_cylinder(x, y, w, h, style, value):
    fill = style.get('fillColor', '#F5F5F5')
    stroke = style.get('strokeColor', '#666666')
    sw = float(style.get('strokeWidth', '1'))
    font_size = style.get('fontSize', '10')
    fs = float(font_size)

    arc = 15
    body_top = y + arc
    parts = [
        # Body bottom
        f'<rect x="{x:.1f}" y="{body_top:.1f}" width="{w:.1f}" height="{h-arc:.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw:.1f}"/>',
        # Bottom ellipse
        f'<ellipse cx="{(x+w/2):.1f}" cy="{(y+h-arc):.1f}" rx="{(w/2):.1f}" ry="{arc:.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw:.1f}"/>',
        # Top ellipse
        f'<ellipse cx="{(x+w/2):.1f}" cy="{body_top:.1f}" rx="{(w/2):.1f}" ry="{arc:.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw:.1f}"/>',
    ]

    lines = value.split('\n') if value else []
    if lines:
        line_h = fs * 1.3
        text_h = len(lines) * line_h
        text_y = y + (h - text_h)/2 + fs * 0.8
        for i, line in enumerate(lines):
            parts.append(
                f'<text x="{(x+w/2):.1f}" y="{text_y+i*line_h:.1f}" '
                f'text-anchor="middle" font-size="{font_size}" '
                f'fill="{style.get("fontColor","#000000")}" '
                f'font-family="Arial,sans-serif">{escape(line)}</text>'
            )
    return '\n'.join(parts)

def shape_actor(x, y, w, h, style, value):
    """Simple stick figure."""
    fill = 'none'
    stroke = '#333333'
    sw = float(style.get('strokeWidth', '1'))

    cx, cy = x + w/2, y + h/2
    head_r = min(w, h) * 0.2
    head_cy = y + head_r + 2
    body_top = head_cy + head_r
    body_bot = y + h * 0.75
    arm_y = (body_top + body_bot) / 2

    parts = [
        # Head
        f'<circle cx="{cx:.1f}" cy="{head_cy:.1f}" r="{head_r:.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw:.1f}"/>',
        # Body
        f'<line x1="{cx:.1f}" y1="{body_top:.1f}" x2="{cx:.1f}" y2="{body_bot:.1f}" '
        f'stroke="{stroke}" stroke-width="{sw:.1f}"/>',
        # Arms
        f'<line x1="{x:.1f}" y1="{arm_y:.1f}" x2="{x+w:.1f}" y2="{arm_y:.1f}" '
        f'stroke="{stroke}" stroke-width="{sw:.1f}"/>',
        # Legs
        f'<line x1="{cx:.1f}" y1="{body_bot:.1f}" x2="{x:.1f}" y2="{y+h:.1f}" '
        f'stroke="{stroke}" stroke-width="{sw:.1f}"/>',
        f'<line x1="{cx:.1f}" y1="{body_bot:.1f}" x2="{x+w:.1f}" y2="{y+h:.1f}" '
        f'stroke="{stroke}" stroke-width="{sw:.1f}"/>',
    ]
    return '\n'.join(parts)

# ── Main renderer ────────────────────────────────────────────────────────────
def parse_style(style_str):
    """Parse draw.io style string into dict."""
    d = {}
    if not style_str:
        return d
    for part in style_str.split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            d[k.strip()] = v.strip()
    return d

def get_shape(style):
    shape = style.get('shape', '')
    if shape == 'ellipse': return 'ellipse'
    if shape == 'rhombus': return 'rhombus'
    if shape == 'cylinder3': return 'cylinder3'
    if shape == 'umlActor': return 'actor'
    return 'rect'

def render(xml_path):
    # Pre-process: decode XML numeric entities that are invalid in attributes
    with open(xml_path, 'r', encoding='utf-8') as f:
        raw = f.read()
    # draw.io uses &#x...; (hex) inside attribute values which is invalid XML.
    # Convert to literal newlines so ET can parse.
    import re
    raw = re.sub(r'&#x([^;]+);', lambda m: chr(int(m.group(1), 16)), raw)

    root = ET.fromstring(raw)
    ns = {'mx': 'http://graphdraw.mxgraph.com/mxfile'}

    # Get page dimensions from mxGraphModel
    model = root.find('.//mxGraphModel')
    page_w = float(model.get('pageWidth', '1000'))
    page_h = float(model.get('pageHeight', '800'))
    dx = float(model.get('dx', '0'))
    dy = float(model.get('dy', '0'))

    # Build cells dict
    cells = {}
    all_cells = []
    for cell in model.findall('.//mxCell'):
        cid = cell.get('id', '')
        cells[cid] = cell
        all_cells.append(cell)

    # Build geometry lookup for ALL cells (shapes + edges with mxGeometry)
    all_geo = {}
    for cell in all_cells:
        cid = cell.get('id', '')
        if cid in ('0', '1'): continue
        try:
            x, y, w, h = get_geo(cell)
            all_geo[cid] = (x, y, w, h)
        except (ValueError, TypeError):
            pass

    shapes = []
    edges = []

    for cell in all_cells:
        cid = cell.get('id', '')
        if cid in ('0', '1'): continue
        style_str = cell.get('style', '')
        style = parse_style(style_str)
        value_el = cell.find('mxGeometry')
        value = cell.get('value', '')
        if value_el is not None:
            v = value_el.get('value', '')
            if v: value = v

        edge = style_str.startswith('endArrow') or 'edgeStyle' in style_str
        if edge:
            edges.append((cid, cell, style, value))
        else:
            try:
                x, y, w, h = get_geo(cell)
            except (ValueError, TypeError):
                continue
            shapes.append((cid, cell, style, value, x, y, w, h))

    # Calculate content bounds for viewBox
    if shapes:
        min_x = min(x for _, _, _, _, x, y, w, h in shapes)
        min_y = min(y for _, _, _, _, x, y, w, h in shapes)
        max_x = max(x + w for _, _, _, _, x, y, w, h in shapes)
        max_y = max(y + h for _, _, _, _, x, y, w, h in shapes)
        pad = 40
        vx = min_x - pad
        vy = min_y - pad
        vw = max(1000, max_x - min_x + pad * 2)
        vh = max(600, max_y - min_y + pad * 2)
    else:
        vx, vy, vw, vh = 0, 0, 1000, 800

    svg_parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{vw:.0f}" height="{vh:.0f}" viewBox="{vx:.0f} {vy:.0f} {vw:.0f} {vh:.0f}">',
        f'  <defs>',
        f'    <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">',
        f'      <path d="M0,0 L0,6 L9,3 z" fill="#333333"/>',
        f'    </marker>',
        f'    <marker id="arrow-green" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">',
        f'      <path d="M0,0 L0,6 L9,3 z" fill="#82B366"/>',
        f'    </marker>',
        f'    <marker id="arrow-purple" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">',
        f'      <path d="M0,0 L0,6 L9,3 z" fill="#9673A6"/>',
        f'    </marker>',
        f'    <marker id="arrow-orange" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">',
        f'      <path d="M0,0 L0,6 L9,3 z" fill="#D6A656"/>',
        f'    </marker>',
        f'    <marker id="arrow-red" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">',
        f'      <path d="M0,0 L0,6 L9,3 z" fill="#CC0000"/>',
        f'    </marker>',
        f'    <marker id="arrow-cyan" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">',
        f'      <path d="M0,0 L0,6 L9,3 z" fill="#17A2B8"/>',
        f'    </marker>',
        f'  </defs>',
        f'  <rect width="100%" height="100%" fill="white"/>',
    ]

    # Draw edges first (behind shapes)
    for cid, cell, style, value in edges:
        sw = float(style.get('strokeWidth', '1.5'))
        scolor = style.get('strokeColor', '#333333')
        dashed = '1' if style.get('dashed', '0') == '1' else None

        geo = cell.find('mxGeometry')
        sx = sy = tx = ty = 0.0

        # draw.io uses mxPoint for edge endpoints
        # sourcePoint/targetPoint = absolute coords (used by lifelines)
        # OR source/target = parent cell id (used by regular edges)
        if geo is not None:
            pts = {p.get('as'): p for p in geo.findall('mxPoint') if p.get('as')}
            if 'sourcePoint' in pts:
                sx = float(pts['sourcePoint'].get('x', '0'))
                sy = float(pts['sourcePoint'].get('y', '0'))
            if 'targetPoint' in pts:
                tx = float(pts['targetPoint'].get('x', '0'))
                ty = float(pts['targetPoint'].get('y', '0'))

        # Fallback: use source/target cell centers
        if sx == 0 and sy == 0:
            src = cell.get('source', '')
            tgt = cell.get('target', '')
            if src and src in all_geo:
                _sx, _sy, _sw, _sh = all_geo[src]
                sx, sy = _sx + _sw/2, _sy + _sh/2
            if tgt and tgt in all_geo:
                _tx, _ty, _tw, _th = all_geo[tgt]
                tx, ty = _tx + _tw/2, _ty + _th/2

        # Build path (simple straight line)
        path = f'M {sx:.1f},{sy:.1f} L {tx:.1f},{ty:.1f}'

        # Pick arrow marker
        end_marker = 'url(#arrow)'
        if scolor == '#82B366': end_marker = 'url(#arrow-green)'
        elif scolor == '#9673A6': end_marker = 'url(#arrow-purple)'
        elif scolor == '#D6A656': end_marker = 'url(#arrow-orange)'
        elif scolor == '#CC0000': end_marker = 'url(#arrow-red)'
        elif scolor == '#17A2B8': end_marker = 'url(#arrow-cyan)'

        attrs = [f'stroke="{scolor}"', f'stroke-width="{sw:.1f}"',
                 f'fill="none"', f'marker-end="{end_marker}"']
        if dashed:
            attrs.append('stroke-dasharray="4,3"')
        if style.get('endArrow', '') == 'none':
            attrs[-1] = ''  # no marker
        attrs = [a for a in attrs if a]

        svg_parts.append(f'  <path d="{path}" {" ".join(attrs)}/>')

        # Edge label
        if value:
            mid_x = (sx + tx) / 2
            mid_y = (sy + ty) / 2
            fs = style.get('fontSize', '10')
            svg_parts.append(
                f'  <text x="{mid_x:.1f}" y="{mid_y:.1f}" '
                f'text-anchor="middle" font-size="{fs}" '
                f'font-family="Arial,sans-serif" '
                f'fill="{style.get("fontColor","#333333")}">'
                f'{escape(value)}</text>'
            )

    # Draw shapes
    for cid, cell, style, value, x, y, w, h in shapes:
        shape_type = get_shape(style)

        if shape_type == 'ellipse':
            svg_parts.append(shape_ellipse(x, y, w, h, style, value))
        elif shape_type == 'rhombus':
            svg_parts.append(shape_rhombus(x, y, w, h, style, value))
        elif shape_type == 'cylinder3':
            svg_parts.append(shape_cylinder(x, y, w, h, style, value))
        elif shape_type == 'actor':
            svg_parts.append(shape_actor(x, y, w, h, style, value))
        else:
            svg_parts.append(shape_rect(x, y, w, h, style, value, False))

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    diagrams = [
        ('fig_wf1_login.drawio', 'WF-1: Đăng nhập'),
        ('fig_wf2_detection.drawio', 'WF-2: Detection'),
        ('fig_wf3_soc_alerts.drawio', 'WF-3: SOC Alerts'),
        ('fig_architecture_overview.drawio', 'Architecture Overview'),
    ]

    for fname, label in diagrams:
        xml_path = os.path.join(base, fname)
        svg_path = xml_path.replace('.drawio', '.svg')
        pdf_path = xml_path.replace('.drawio', '.pdf')

        try:
            svg = render(xml_path)
            with open(svg_path, 'w', encoding='utf-8') as f:
                f.write(svg)
            print(f'  ✓ SVG: {svg_path} ({len(svg):,} bytes)')

            # Convert SVG → PDF with inkscape
            result = os.system(f'inkscape --export-filename="{pdf_path}" --export-area-drawing "{svg_path}" 2>/dev/null')
            if result == 0 and os.path.exists(pdf_path):
                print(f'  ✓ PDF: {pdf_path} ({os.path.getsize(pdf_path):,} bytes)')
            else:
                print(f'  ✗ PDF: inkscape failed (SVG OK, can open in browser)')
        except Exception as e:
            print(f'  ✗ Error: {e}', file=sys.stderr)

if __name__ == '__main__':
    main()
