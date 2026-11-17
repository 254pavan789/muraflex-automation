"""GLASS sheet writer - reproduces the estimation team's template exactly.

    B ELEV | C Tag | E UPPER | G LOWER | I TOTAL | K Difference | M JUDGEMENT | O Fraction
    data from row 5 | 2 rows per panel (left edge, right edge) | 1 blank row between panels
    2 blank rows between elevations | elevations sorted by number across all pages

TOTAL / Difference / JUDGEMENT / Fraction are live formulas AND carry their computed result as the cell's
cached value, so numbers are visible in Protected View, previewers and mobile viewers (openpyxl alone writes
formulas without results, which shows as blank cells until Excel recalculates).
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .config import BM_RANGE
from .judgement import EXCEL_FORMULA, judge
from .units import parse_length

LEN_FMT = '# ??/??;-# ??/??;0'
THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HDR = {"B": "ELEV", "C": "Tag", "E": "UPPER", "G": "LOWER", "I": "TOTAL", "K": "Difference", "M": "JUDGEMENT",
       "O": "Fraction"}


def _font(bold=False):
    return Font(name="Calibri", size=11, bold=bold)


def _num(s):
    if s is None or str(s).strip() == "":
        return None
    v = parse_length(str(s), BM_RANGE)["value"]
    return v if v is not None else str(s)


def elev_sort_key(e):
    m = re.match(r"\d+", str(e.get("elev") or ""))
    return (int(m.group(0)) if m else 10 ** 6, e.get("page", 0), (e.get("title_box") or [0])[0])


def layout_rows(elevations):
    """Pure layout -> [(row, elevation, panel_index_in_elev, panel)] for exported panels."""
    out, r, first = [], 5, True
    for el in sorted(elevations, key=elev_sort_key):
        panels = [p for p in el.get("panels", []) if p.get("export") and p.get("kind") != "Door"]   # doors -> DOOR sheet
        if not panels:
            continue
        if not first:
            r += 1
        for k, p in enumerate(panels):
            if k:
                r += 1
            out.append((r, el, k, p))
            r += 2
        first = False
        r += 1
    return out


def build_workbook(elevations):
    """-> (Workbook, cache {cell: value})"""
    cache = {}
    wb = Workbook()
    wb.calculation.fullCalcOnLoad = True
    ws = wb.active
    ws.title = "GLASS"
    for c, w in {"A": 30, "B": 8.5, "C": 11, "D": 8.5, "E": 9.5, "F": 8.5, "G": 9.5, "H": 8.5, "I": 10, "J": 8.5,
                 "K": 11.5, "L": 8.5, "M": 13, "N": 8.5, "O": 10}.items():
        ws.column_dimensions[c].width = w
    yellow, black, red = (PatternFill("solid", start_color=x, end_color=x) for x in ("FFFF00", "000000", "FF0000"))
    for col in "EFGHIJKLMNO":
        ws[f"{col}1"].fill = yellow
    for col, lab in HDR.items():
        c = ws[f"{col}2"]
        c.value = lab; c.font = _font(True); c.border = BORDER; c.alignment = Alignment(horizontal="center")
        ws[f"{col}3"].fill = black
    ws["D3"].fill = black
    ws["A4"] = "START ON THIS ROW-->"; ws["A4"].fill = red
    ws["A6"] = "NOTES"
    for r, t in ((7, "skip 2 lines to start new elevation"), (8, "skip a line for double glazed"),
                 (9, "skip a line for sidelights")):
        ws[f"A{r}"] = t; ws[f"A{r}"].fill = yellow
    ws["A10"].fill = yellow
    last = 5
    for r1, el, k, p in layout_rows(elevations):
        r2 = r1 + 1
        if k == 0:
            e = str(el.get("elev") or "")
            ws[f"B{r1}"] = int(e) if e.isdigit() else (e or None)
        ws[f"C{r1}"] = p.get("tag") or None
        tots = []
        for rr, side in ((r1, "L"), (r2, "R")):
            u, l = _num(p[side].get("u")), _num(p[side].get("l"))
            ws[f"E{rr}"], ws[f"G{rr}"] = u, l
            ws[f"I{rr}"] = f'=IF(OR(E{rr}="",G{rr}=""),"",E{rr}+G{rr})'
            t = u + l if isinstance(u, (int, float)) and isinstance(l, (int, float)) else None
            cache[f"I{rr}"] = "" if t is None else t
            tots.append(t)
        d, j = judge(*tots)
        ws[f"K{r1}"] = f'=IF(OR(I{r1}="",I{r2}=""),"",I{r1}-I{r2})'
        ws[f"M{r1}"] = EXCEL_FORMULA.format(r1=r1, r2=r2)
        ws[f"O{r1}"] = f'=IF(ISNUMBER(M{r1}),M{r1},"")'
        cache[f"K{r1}"], cache[f"M{r1}"] = d, j
        cache[f"O{r1}"] = j if isinstance(j, (int, float)) else ""
        last = r2
    for rr in range(5, max(last + 10, 60) + 1):
        for col in HDR:
            c = ws[f"{col}{rr}"]
            c.border = BORDER
            c.font = _font()
            if col in "EGIKMO":
                c.number_format = LEN_FMT if col != "O" else "# ?/??"
                c.alignment = Alignment(horizontal="right")
            elif col == "B":
                c.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A5"
    ws.page_setup.orientation = "portrait"
    ws.print_title_rows = "1:3"
    return wb, cache


_CELL = re.compile(r'<c r="([A-Z]+\d+)"([^>]*)><f>(.*?)</f>(?:<v\s*/>|<v>[^<]*</v>)?</c>', re.S)


def to_bytes(wb, cache) -> bytes:
    """Save and inject cached results into formula cells.
    cache = {cell: value} for every sheet, or {sheet title: {cell: value}} for a workbook of several sheets."""
    per_sheet = bool(cache) and all(isinstance(v, dict) for v in cache.values())
    files = {f"xl/worksheets/sheet{i + 1}.xml": (cache.get(ws.title, {}) if per_sheet else cache)
             for i, ws in enumerate(wb.worksheets)}
    buf = io.BytesIO()
    wb.save(buf)
    zin = zipfile.ZipFile(io.BytesIO(buf.getvalue()))

    def fix(m, cache):
        ref, attrs, f = m.group(1), m.group(2), m.group(3)
        if ref not in cache:
            return m.group(0)
        v = cache[ref]
        attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f'<c r="{ref}"{attrs}><f>{f}</f><v>{repr(float(v))}</v></c>'
        return f'<c r="{ref}"{attrs} t="str"><f>{f}</f><v>{escape(str(v))}</v></c>'

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in files:
                c = files[item.filename]
                data = _CELL.sub(lambda m: fix(m, c), data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)
    return out.getvalue()


def build_project_workbook(elevations, doors=None):
    """One workbook per PDF, like the team file: tab GLASS (glass panels) + tab DOOR (pivot / sliding doors).
    -> (Workbook, {sheet: cache})"""
    wb, gcache = build_workbook(elevations)
    dcache = fill_door_sheet(wb.create_sheet("DOOR"), doors or [])
    wb.active = 0
    return wb, {"GLASS": gcache, "DOOR": dcache}


def export_bytes(elevations, doors=None) -> bytes:
    """<PDF name>.xlsx with both tabs (GLASS + DOOR)."""
    return to_bytes(*build_project_workbook(elevations, doors))


def xlsx_name(pdf_name: str) -> str:
    stem = os.path.splitext(os.path.basename(pdf_name or "export"))[0]
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip() or "export"
    return stem + ".xlsx"


# ---------------------------------------------------------------------------------------------- DOOR sheet
DOOR_GREY = PatternFill("solid", start_color="D9D9D9", end_color="D9D9D9")
DOOR_YELLOW = PatternFill("solid", start_color="FFFF00", end_color="FFFF00")
PIVOT_COLS = ("C", "D", "E", "F")          # A, B, C1, C2      Diff G, FINAL H, ELEV NO in A
SLIDE_COLS = ("K", "L", "M")               # A, B, C1          Diff N, FINAL O, ELEV NO in J


def _door_final_formula(d, t, ca, cb):
    """FINAL = GLASS judgement on TOTAL(A) and TOTAL(B); Diff cell d, totals row t."""
    from .judgement import CHECK, LEVEL, TYPO
    return (f'=IF(ABS({d})>5,"{TYPO}",IF(ABS({d})>1,"{CHECK}",IF(ABS({d})>=3/4,"{LEVEL}",'
            f'IF(ABS({d})>=1/4,FLOOR(({ca}{t}+{cb}{t})/2,1/16),MIN({ca}{t},{cb}{t})))))')


def build_door_workbook(doors):
    """DOOR sheet on its own.  -> (Workbook, cache)"""
    wb = Workbook()
    wb.calculation.fullCalcOnLoad = True
    ws = wb.active
    ws.title = "DOOR"
    return wb, fill_door_sheet(ws, doors)


def fill_door_sheet(ws, doors):
    """Team DOOR sheet: pivot doors in A / C-H, sliding doors in J / K-O, one 4-row block per door
    (uppers, lowers + Diff, totals + FINAL, blank).  -> cache {cell: value}"""
    from openpyxl.comments import Comment
    from .doors import totals
    cache = {}
    for c, w in {"A": 9.5, "B": 2.5, "C": 11, "D": 11, "E": 11, "F": 11, "G": 9, "H": 11.5, "I": 6, "J": 9,
                 "K": 11, "L": 11, "M": 11, "N": 9, "O": 11.5}.items():
        ws.column_dimensions[c].width = w
    bold = _font(True)
    for ref, lab, al in (("A1", "ELEV NO", "center"), ("C1", "A", "center"), ("D1", "B", "left"), ("E1", "C1", "left"),
                         ("F1", "C2", "left"), ("G1", "PIVOT DOOR", "center"), ("K1", "A", "center"), ("L1", "B", "left"),
                         ("M1", "C1", "left"), ("N1", "SLIDING DOOR", "center")):
        ws[ref] = lab
        ws[ref].font = bold if lab in ("ELEV NO", "A") else _font()
        ws[ref].alignment = Alignment(horizontal=al)
    ws.merge_cells("G1:H1")
    ws.merge_cells("N1:O1")
    for ref in ("A1", "C1", "D1", "E1", "F1", "G1", "H1", "K1", "L1", "M1", "N1", "O1"):
        ws[ref].border = BORDER
    piv = [d for d in doors if d.get("export", True) and d.get("type") != "Sliding"]
    sli = [d for d in doors if d.get("export", True) and d.get("type") == "Sliding"]
    nblocks = max(len(piv), len(sli), 12)

    def block(r, d, cols, elev_col, diff_col, fin_col):
        names = ("A", "B", "C1", "C2")[:len(cols)]
        ws[f"{diff_col}{r}"], ws[f"{fin_col}{r}"] = "Diff", "FINAL"
        tot = {}
        if d is not None:
            e = str(d.get("elev") or "")
            ws[f"{elev_col}{r}"] = int(e) if e.isdigit() else (e or None)
            ws[f"{elev_col}{r}"].alignment = Alignment(horizontal="center")
            tag = d.get("tag") or d.get("code") or ""
            if tag:
                hg = {"L": ", hinge left", "R": ", hinge right"}.get(d.get("hinge", ""), "") if cols == PIVOT_COLS else ""
                ws[f"{elev_col}{r}"].comment = Comment(f"Door {tag} ({d.get('type', '')}{hg})", "MURAFLEX AUTOMATION")
            tot, _, _ = totals(d)
        for c, k in zip(cols, names):
            p = (d or {}).get("pts", {}).get(k, {})
            u, l = _num(p.get("u")), _num(p.get("l"))
            ws[f"{c}{r}"], ws[f"{c}{r + 1}"] = u, l
            ws[f"{c}{r + 2}"] = f"={c}{r}+{c}{r + 1}"
            uu = u if isinstance(u, (int, float)) else 0
            ll = l if isinstance(l, (int, float)) else 0
            cache[f"{c}{r + 2}"] = uu + ll
            for rr in (r, r + 1, r + 2):
                ws[f"{c}{rr}"].number_format = LEN_FMT
            ws[f"{c}{r + 2}"].fill = DOOR_GREY
        ca, cb = cols[0], cols[1]
        ws[f"{diff_col}{r + 1}"] = f"={ca}{r + 2}-{cb}{r + 2}"
        ws[f"{diff_col}{r + 1}"].number_format = LEN_FMT
        ws[f"{diff_col}{r + 1}"].alignment = Alignment(horizontal="right")
        ta, tb = cache[f"{ca}{r + 2}"], cache[f"{cb}{r + 2}"]
        d_, j_ = judge(ta, tb)
        cache[f"{diff_col}{r + 1}"] = d_
        f = f"{fin_col}{r + 2}"
        ws[f] = _door_final_formula(f"{diff_col}{r + 1}", r + 2, ca, cb)
        ws[f].fill = DOOR_YELLOW
        ws[f].number_format = LEN_FMT
        ws[f].alignment = Alignment(horizontal="left")
        cache[f] = j_

    for i in range(nblocks):
        r = 2 + 4 * i
        block(r, piv[i] if i < len(piv) else None, PIVOT_COLS, "A", "G", "H")
        block(r, sli[i] if i < len(sli) else None, SLIDE_COLS, "J", "N", "O")
    ws.freeze_panes = "A2"
    ws.print_title_rows = "1:1"
    return cache


def export_doors_bytes(doors) -> bytes:
    return to_bytes(*build_door_workbook(doors))


def xlsx_door_name(pdf_name: str) -> str:
    return xlsx_name(pdf_name)[:-5] + " - DOOR.xlsx"
