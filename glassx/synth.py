"""Synthetic Field Measurement sheets with known answers.

Used by the test-suite, the fuzz test and `app.py --selftest`.  Layout mimics real Muraflex FM sheets:
DW/FAL edge labels, width dimension above the frame, door-swing plan values at the top, dashed BM line
with a 'BM' label, red upper/lower benchmarks next to each panel edge, code-over-tag glass labels,
circled elevation number + 'ELEVATION / NAME #ROOM' title, title block, cover and notes pages.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

try:
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore

RED = (0.89, 0.1, 0.1)
FRACS = ["", "1/16", "1/8", "3/16", "1/4", "5/16", "3/8", "7/16", "1/2"]


def fm(v_whole: int, frac: str) -> str:
    return f'{v_whole}"{frac}' if frac else f'{v_whole}"'


def val(v_whole: int, frac: str) -> str:
    return f"{v_whole} {frac}" if frac else str(v_whole)


@dataclass
class ElevSpec:
    elev: int
    room: str
    name: str
    tags: list                       # [(code, tag)] left -> right, one per panel
    uppers: list                     # [(whole, frac)] per edge (len = panels + 1)
    lowers: list
    widths: list = field(default_factory=list)
    drop: set = field(default_factory=set)      # {("u"|"l", edge_index)} values left off the sheet
    swing: list = field(default_factory=list)   # door-swing plan readings (C1 at 45 deg, C2 at 90 deg) for the first door
    hinge: str = "L"                            # hinge side of that door: "L" / "R"
    plan: str = "arc"                           # "arc" = quarter arc + leaf drawn (CAD), "text" = readings only
    vmark: bool = True                          # dashed 'V' on the door in elevation (apex = hinge side)
    stray: bool = False                         # an unrelated BM-range value near the swing plan
    rows: bool = False                          # uppers in one row at the frame head, lowers in one row at the sill


def random_spec(rng: random.Random, elev: int, room: str, n_panels: int, door_first=False) -> ElevSpec:
    tags = []
    for i in range(n_panels):
        if door_first and i == 0:
            tags.append(("FPD-LIGL", room))
        else:
            tags.append(("OLIGL-12", f"{room}-{chr(65 + i)}"))
    ups = [(rng.choice([49, 50]), rng.choice(FRACS[:4])) for _ in range(n_panels + 1)]
    los = [(rng.choice([56, 57]), rng.choice(FRACS)) for _ in range(n_panels + 1)]
    return ElevSpec(elev, room, "OFFICE " + room if not door_first else "CONFERENCE", tags, ups, los)


def stacked_text(page, x, y, s, size, color, unicode=False):
    """Write 57"1/4 the way CAD plots it: big whole number, small raised numerator, small lowered denominator."""
    import re as _re
    m = _re.fullmatch(r'(\d+)"?\s*(\d+)/(\d+)', s)
    if not m:
        page.insert_text((x, y), s, fontsize=size, color=color)
        return
    w, n, d = m.groups()
    if unicode:
        sup = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"); sub = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        tw = pymupdf.TextWriter(page.rect)
        tw.append((x, y), f"{w}{n.translate(sup)}⁄{d.translate(sub)}\"", font=pymupdf.Font("cjk"), fontsize=size)
        tw.write_text(page, color=color)
        return
    f = pymupdf.Font("helv")
    tw = pymupdf.TextWriter(page.rect)
    tw.append((x, y), w, font=f, fontsize=size)
    xn = x + f.text_length(w, size) + 0.5
    tw.append((xn, y - 0.45 * size), n, font=f, fontsize=size * 0.55)
    xd = xn + f.text_length(n, size * 0.55) + 0.8
    tw.append((xd, y + 0.15 * size), d, font=f, fontsize=size * 0.55)
    tw.append((xd + f.text_length(d, size * 0.55) + 0.5, y), '"', font=f, fontsize=size)
    tw.write_text(page, color=color)


def draw_elevation(page, spec: ElevSpec, x0: float, top: float, panel_w: float = 62, height: float = 200,
                   rng: random.Random | None = None, use_annots=False, width_above_frame=False, stacked=None):
    """Draw one elevation; frame from (x0, top). Returns BM y used."""
    rng = rng or random.Random(spec.elev)
    n = len(spec.tags)
    x1 = x0 + n * panel_w
    bm_y = top + height * 0.34
    page.draw_rect(pymupdf.Rect(x0, top, x1, top + height), color=(0, 0, 0), width=0.8)
    for i in range(1, n):
        page.draw_line((x0 + i * panel_w, top), (x0 + i * panel_w, top + height), color=(0, 0, 0), width=0.8)
    page.insert_text((x0 - 4, top - 62), "DW", fontsize=5)
    page.insert_text((x1 - 4, top - 62), "FAL" if spec.elev % 2 else "DW", fontsize=5)

    def red(x, y, s):
        if stacked and "/" in s:
            stacked_text(page, x, y, s, 9, RED, unicode=stacked == "unicode")
            return
        if use_annots:
            a = page.add_freetext_annot(pymupdf.Rect(x, y - 10, x + len(s) * 6 + 6, y + 3), s, fontsize=9,
                                        text_color=RED)
            a.update()
        else:
            page.insert_text((x, y), s, fontsize=9, color=RED)

    red((x0 + x1) / 2 - 18, top - 20 if width_above_frame else top - 62, fm(50 + n * 6, "11/16"))                  # width label on the edge row (in BM range!)
    doors = [i for i, (c, _t) in enumerate(spec.tags) if c.startswith("FPD")]
    if doors and spec.swing:
        # door-swing plan as CAD draws it: quarter arc around the pivot (above the hinge edge); the closed end lies on
        # the wall line (its reading repeats the latch lower), the open leaf stands square to the wall (C2 at its
        # tip), C1 is read at 45 deg
        i = doors[0]
        hi, li = (i, i + 1) if spec.hinge == "L" else (i + 1, i)
        hx, lx = x0 + hi * panel_w, x0 + li * panel_w
        sg = 1 if lx > hx else -1
        r_, py = 0.5 * panel_w, top - 88
        closed, tip = (hx + sg * r_, py), (hx, py - r_)
        mid = (hx + sg * r_ * math.cos(math.pi / 4), py - r_ * math.sin(math.pi / 4))
        if spec.plan == "arc":
            arc = [(hx + sg * r_ * math.cos(t * math.pi / 40), py - r_ * math.sin(t * math.pi / 40)) for t in range(21)]
            page.draw_polyline(arc, color=(0.4, 0.4, 0.4), width=0.4)
            page.draw_line((hx, py), tip, color=(0, 0, 0), width=0.8)                  # open leaf
            for q in (closed, mid, tip):
                page.draw_circle(q, 1.1, color=(0, 0, 0), width=0.3)
        lab = lambda q, s_: red(q[0] + (4 if sg > 0 else -34), q[1] - 2, s_)  # noqa: E731
        red(tip[0] - (12 if sg > 0 else 20), tip[1] - 5, fm(*spec.swing[1]))
        lab(mid, fm(*spec.swing[0]))
        red(closed[0] + (5 if sg > 0 else -36), closed[1] - 3, fm(*spec.lowers[li]))
        if spec.stray:
            red(hx - sg * 1.6 * r_ - 14, py - r_ * 0.9, fm(spec.lowers[li][0] + 2, "7/16"))
        if spec.vmark:
            for a, b in (((lx, top + 4), (hx, top + height / 2)), ((hx, top + height / 2), (lx, top + height - 4))):
                page.draw_line(a, b, color=(0.45, 0.45, 0.45), width=0.4, dashes="[3 2] 0")
    else:
        red(x0 + 10, top - 110, fm(57, "1/4"))                                  # door-swing plan values
    for i in range(n):
        code, tag = spec.tags[i]
        cx = x0 + (i + 0.5) * panel_w
        page.insert_text((cx - 14, bm_y - 14), code, fontsize=5.5)
        page.insert_text((cx - 7, bm_y - 7), tag, fontsize=5.5)
    for i in range(n + 1):
        ex = x0 + i * panel_w
        side = -1 if i == 0 else (1 if i == n else rng.choice([-1, 1]))
        ux = ex + (side * rng.uniform(4, 10)) - (28 if side < 0 else 0)
        lx = ex + (side * rng.uniform(4, 10)) - (28 if side < 0 else 0)
        uy = bm_y - rng.uniform(4, min(40, 0.25 * height))
        ly = bm_y + rng.uniform(0.09 * height, 0.55 * height)
        if spec.rows:                                                 # 14065 style: readings in two neat rows
            uy, ly = top + 16, top + height - 6
        if ("u", i) not in spec.drop:
            red(ux, uy, fm(*spec.uppers[i]))
        if ("l", i) not in spec.drop:
            red(lx, ly, fm(*spec.lowers[i]))
    ty = top + height + 22
    page.draw_circle((x0 + 2, ty - 3), 7, color=(0, 0, 0), width=0.6)
    page.insert_text((x0 - 1, ty), str(spec.elev), fontsize=8)
    page.insert_text((x0 + 14, ty), f"ELEVATION / {spec.name} #{spec.room}", fontsize=8)
    page.insert_text((x0 + 14, ty + 8), "CORRIDOR VIEW", fontsize=5)
    return bm_y


def title_block(page, project="14002"):
    W, H = page.rect.width, page.rect.height
    page.draw_rect(pymupdf.Rect(20, H - 120, W - 20, H - 20), color=(0, 0, 0), width=0.8)
    page.insert_text((30, H - 100), f"PROJECT / DRAWING NO.:  {project}", fontsize=10)
    page.insert_text((300, H - 100), "1) MEASUREMENTS TAKEN :   FROM: SLAB   TO: GYPROCK BULKHEAD", fontsize=8)
    page.insert_text((W - 260, H - 100), "DESCRIPTION: FIELD MEASUREMENT SHEET - ELEVATIONS", fontsize=7)


def build_fm_pdf(path: str, specs_by_page: list, use_annots=False, cover=True, notes=True, seed=7,
                 rows_per_page=1, width_above_frame=False, stacked=None):
    """specs_by_page: [[ElevSpec, ...], ...]. rows_per_page=2 stacks elevations in two rows."""
    rng = random.Random(seed)
    doc = pymupdf.open()
    if cover:
        p = doc.new_page(width=1224, height=792)
        p.insert_text((60, 70), "FIELD MEASUREMENT SHEETS - KEY PLAN", fontsize=16)
        p.insert_text((60, 100), "DESCRIPTION: ELEVATIONS", fontsize=9)
        p.insert_text((300, 420), "1", fontsize=10)
        p.insert_text((315, 420), "ELEVATION / KEY PLAN #1", fontsize=9)
        p.insert_text((300, 450), 'NOTE: 50" BM TYP.', fontsize=8)
        title_block(p)
    for specs in specs_by_page:
        p = doc.new_page(width=1224, height=792)
        per_row = (len(specs) + rows_per_page - 1) // rows_per_page
        for ri in range(rows_per_page):
            row = specs[ri * per_row:(ri + 1) * per_row]
            if not row:
                continue
            top = 150 + ri * 330 if rows_per_page > 1 else 230
            height = 150 if rows_per_page > 1 else 260
            x = 90
            bm_ys = []
            for s in row:
                bm_ys.append(draw_elevation(p, s, x, top, height=height, rng=rng, use_annots=use_annots,
                                            width_above_frame=width_above_frame, stacked=stacked))
                x += len(s.tags) * 62 + 110
            bm = bm_ys[0]
            p.draw_line((30, bm), (1190, bm), color=(0.3, 0.3, 0.3), width=0.6, dashes="[6 3] 0")
            p.insert_text((32, bm + 4), "BM", fontsize=13)
        title_block(p)
    if notes:
        p = doc.new_page(width=1224, height=792)
        p.insert_text((60, 70), "GENERAL NOTES", fontsize=14)
        p.insert_text((60, 100), "ALL DIMENSIONS IN INCHES. VERIFY ON SITE.", fontsize=9)
    doc.save(path)
    doc.close()


def expected(specs_by_page):
    """Expected panels: {(elev, tag): (L_u, L_l, R_u, R_l, kind)}"""
    out = {}
    for specs in specs_by_page:
        for s in specs:
            U = lambda i: "" if ("u", i) in s.drop else val(*s.uppers[i])  # noqa: E731
            L = lambda i: "" if ("l", i) in s.drop else val(*s.lowers[i])  # noqa: E731
            if getattr(s, "single", False):                       # side view: one measured edge
                code, tag = s.tags[0]
                out[(str(s.elev), tag)] = (U(0), L(0), U(0), L(0), "Fixed")
                continue
            for i, (code, tag) in enumerate(s.tags):
                kind = "Door" if code.startswith("FPD") else "Fixed"
                out[(str(s.elev), tag)] = (U(i), L(i), U(i + 1), L(i + 1), kind)
    return out


# ---------------------------------------------------------------------------------------------
# Second sheet family, rebuilt from the 14005 Gibson Dunn FM screenshots:
#   green uppers / red lowers, bare whole numbers ('48', '66'), apostrophe inches with a SPACE before the
#   fraction ("47' 3/4", "65' 13/16"), 'BM 48FT' / 'BM 65' 1/4' labels with arrows at one edge, page-wide BM
#   line drawn as many short dash segments + big 'BM' label, red 'FAL - FAL 123 1/2' and '42" HOLD TO'
#   labels, door-swing plan values above, vertical (rotated) tags, untagged 'existing condition' span,
#   lowercase cloud note 'Elevation 1 it is wood floor 5/8', one-point side views (OFFICE VIEW).
GREEN = (0.15, 0.6, 0.2)


def random_spec_gd(rng: random.Random, elev: int, room: str, n_panels: int, door=False, single=False) -> ElevSpec:
    W = lambda base: (base + rng.choice([-1, 0, 0, 0]), rng.choice(["", "", "1/16", "1/8", "3/16", "1/4", "3/4", "15/16"]))  # noqa: E731
    if single:
        s = ElevSpec(elev, room, f"INT. ATTORNEY S.O. {room}", [("OLIGL-12", f"{room}-A")], [W(48)], [W(66)])
        s.single = True
        return s
    tags = []
    for i in range(n_panels):
        if door and i == 1:
            tags.append(("FPD-OLIGL", room))
        else:
            tags.append(("OLIGL-12", f"{room}-{chr(65 + i)}"))
    s = ElevSpec(elev, room, rng.choice(["NOOK", "INT. ATTORNEY S.O.", "OFFICE"]) + f" {room}", tags,
                 [W(48) for _ in range(n_panels + 1)], [W(66) for _ in range(n_panels + 1)])
    s.vertical_first = rng.random() < 0.4
    s.bm_edge = rng.choice([0, n_panels])
    s.lead = rng.random() < 0.35
    s.note = rng.random() < 0.3
    s.single = False
    return s


def _gd_value(rng, w, frac, bm=False, upper=True):
    if bm:
        return f"BM {w}FT" if not frac and rng.random() < .6 else (f"BM {w}' {frac}" if frac else f"BM {w}'")
    if not frac:
        return rng.choice([f"{w}", f"{w}'"])
    return rng.choice([f"{w}' {frac}", f"{w} {frac}"])


def gd_width(spec) -> float:
    return 120 if getattr(spec, "single", False) else len(spec.tags) * 68 + (55 if getattr(spec, "lead", False) else 0) + 70


def _digit_image(text: str) -> bytes:
    d = pymupdf.open(); p = d.new_page(width=14, height=14)
    p.insert_text((3.5 if len(text) == 1 else 1, 10.5), text, fontsize=9)
    return p.get_pixmap(dpi=600).tobytes("png")


def _text_image(text: str, color, size: float) -> tuple:
    w = len(text) * size * 0.6 + 4
    d = pymupdf.open(); p = d.new_page(width=w, height=size + 4)
    p.insert_text((2, size + 1), text, fontsize=size, color=color)
    return p.get_pixmap(dpi=500).tobytes("png"), w, size + 4


def draw_elevation_gd(page, spec: ElevSpec, x0: float, bm_y: float, rng: random.Random, use_annots=False,
                      use_images=False):
    edge_y, top_y, floor_y, title_y = bm_y - 155, bm_y - 75, bm_y + 130, bm_y + 145
    up_y, lo_y = bm_y - 78, bm_y + 82

    def txt(x, y, s, color=(0, 0, 0), size=8, rotate=0):
        if use_images and color in (RED, GREEN) and rotate == 0 and any(ch.isdigit() for ch in s):
            png, w, h = _text_image(s, color, size)                 # mark-up pasted as a picture
            page.insert_image(pymupdf.Rect(x - 2, y - size - 1, x - 2 + w, y - size - 1 + h), stream=png)
        elif use_annots and color in (RED, GREEN) and rotate == 0:   # Bluebeam-style mark-up
            a = page.add_freetext_annot(pymupdf.Rect(x - 1, y - size - 1, x + len(s) * size * 0.62 + 4, y + 3), s,
                                        fontsize=size, text_color=color)
            a.update()
        else:
            page.insert_text((x, y), s, fontsize=size, color=color, rotate=rotate)

    def title(xc):
        page.draw_circle((xc, title_y - 3), 8, color=(0, 0, 0), width=0.6)
        if getattr(spec, "num_img", False):                       # circled number drawn as a picture
            page.insert_image(pymupdf.Rect(xc - 7, title_y - 10, xc + 7, title_y + 4), stream=_digit_image(str(spec.elev)))
        else:
            txt(xc - 3, title_y, str(spec.elev), size=8)
        txt(xc + 14, title_y, f"ELEVATION / {spec.name}", size=8)
        txt(xc + 14, title_y + 8, rng.choice(["CORRIDOR VIEW", "OFFICE VIEW"]), size=5)

    if getattr(spec, "single", False):                            # side view, one measured edge
        ex = x0 + 30
        page.draw_rect(pymupdf.Rect(x0 + 15, top_y, x0 + 45, floor_y), color=(0, 0, 0), width=0.7)
        txt(x0 + 10, edge_y, "DW", size=5); txt(x0 + 42, edge_y, "FAL", size=5)
        txt(x0 + 12, edge_y + 35, '11 5/8"', RED, 6)               # thickness: outside the BM range
        txt(x0 + 27, bm_y - 10, "OLIGL-12", size=5, rotate=90)
        txt(x0 + 33, bm_y - 10, spec.tags[0][1], size=5, rotate=90)
        page.draw_line((ex + 35, bm_y), (ex + 35, up_y + 6), color=GREEN, width=0.8)
        txt(ex + 25, up_y, _gd_value(rng, *spec.uppers[0], bm=True), GREEN, 6)
        txt(ex - 10, lo_y + 8, _gd_value(rng, *spec.lowers[0]), RED, 7)
        title(x0 + 10)
        return
    n = len(spec.tags)
    pw = 68
    gx0 = x0 + (55 if spec.lead else 0)
    edges = [gx0 + i * pw for i in range(n + 1)]
    fx0 = x0
    page.draw_rect(pymupdf.Rect(fx0, top_y, edges[-1], floor_y), color=(0, 0, 0), width=0.7)
    for ex in edges:
        page.draw_line((ex, top_y), (ex, floor_y), color=(0, 0, 0), width=0.7)
    txt(fx0 - 4, edge_y, rng.choice(["DW", "FAL"]), size=5)
    txt(edges[-1] - 4, edge_y, rng.choice(["DW", "FAL"]), size=5)
    mid = (fx0 + edges[-1]) / 2
    txt(mid - 20, edge_y + 25, rng.choice(["FAL - FAL", "DW - CL"]), RED, 7)
    txt(mid - 15, edge_y + 37, f'{100 + n * 9}" 1/2', RED, 7)
    if rng.random() < .5:
        txt(fx0 + 20, edge_y + 2, '42" HOLD TO', (0.8, 0.5, 0.1), 5)
    # door-swing plan above the edge row (must be ignored)
    txt(mid, edge_y - 120, "66'", RED, 6); txt(mid + 30, edge_y - 95, "66' 1/8", RED, 6); txt(mid - 30, edge_y - 70, "90°", RED, 6)
    txt(mid - 60, edge_y - 90, "OFFICE", size=4)
    if spec.lead:                                                  # existing-condition span: values, no tag
        txt(fx0 + 6, up_y + 4, f"{48}'", GREEN, 7)
        txt(fx0 + 4, lo_y, "66 1/16", RED, 7)
        txt(fx0 - 40, bm_y - 2, "EXISTING", size=4); txt(fx0 - 40, bm_y + 4, "L-CONDITION", size=4)
    for i, (code, tag) in enumerate(spec.tags):
        cx = edges[i] + pw / 2
        if i == 0 and spec.vertical_first:
            txt(cx - 2, bm_y - 8, code, size=5, rotate=90)
            txt(cx + 5, bm_y - 8, tag, size=5, rotate=90)
        else:
            txt(cx - 15, bm_y - 30, code, size=5.5)
            txt(cx - 12, bm_y - 23, tag, size=5.5)
    for i, ex in enumerate(edges):
        right = i == n
        bm = i == spec.bm_edge
        ux = ex + (6 if right else -2) + rng.uniform(-3, 3)
        if ("u", i) not in spec.drop:
            if bm:
                page.draw_line((ex + 8, bm_y), (ex + 8, up_y + 8), color=GREEN, width=0.8)
            txt(ux, up_y + rng.uniform(-3, 3), _gd_value(rng, *spec.uppers[i], bm=bm), GREEN, 7)
        if ("l", i) not in spec.drop:
            if bm:
                page.draw_line((ex + 8, bm_y), (ex + 8, lo_y - 8), color=RED, width=0.8)
            txt(ux - 4, lo_y + rng.uniform(-4, 4), _gd_value(rng, *spec.lowers[i], bm=bm), RED, 7)
    title(fx0 + 4)
    if spec.note:
        txt(fx0, title_y + 40, f"Elevation {spec.elev} it is wood floor 5/8", RED, 6)


def build_fm_pdf_gd(path: str, specs_by_page: list, seed=7, cover=True, use_annots=False, use_images=False):
    rng = random.Random(seed)
    doc = pymupdf.open()
    if cover:
        p = doc.new_page(width=1224, height=792)
        p.insert_text((60, 70), "GIBSON DUNN RECONFIGURATION - FIELD MEASUREMENTS", fontsize=14)
        p.insert_text((60, 100), "KEY PLAN", fontsize=9)
        title_block(p, "14005")
    for specs in specs_by_page:
        p = doc.new_page(width=1224, height=792)
        bm = 510
        x = 140
        for s in specs:
            draw_elevation_gd(p, s, x, bm, rng, use_annots=use_annots, use_images=use_images)
            x += gd_width(s) + 80
        for xs in range(25, 1195, 9):                              # dashed BM line as separate short segments
            p.draw_line((xs, bm), (xs + 5, bm), color=(0.35, 0.35, 0.35), width=0.5)
        p.insert_text((30, bm + 7), "BM", fontsize=18)
        title_block(p, "14005")
    doc.save(path)
    doc.close()


def random_project_gd(rng: random.Random, n_pages=None):
    pages, e = [], 1
    for _ in range(n_pages or rng.randint(1, 3)):
        specs, width = [], 0
        for _ in range(rng.randint(1, 3)):
            if rng.random() < .2:
                s = random_spec_gd(rng, e, f"{rng.randint(3000, 3200)}A", 1, single=True)
            else:
                s = random_spec_gd(rng, e, f"{rng.randint(3000, 3200)}{rng.choice(['', 'A', 'B'])}",
                                   rng.randint(1, 4), door=rng.random() < .3)
            if width + gd_width(s) + 80 > 1020:
                break
            specs.append(s); width += gd_width(s) + 80; e += 1
        pages.append(specs)
    return pages


def random_door_project(rng: random.Random, n_pages: int = 2) -> list:
    """14002-style pages where every elevation starts with a pivot door: random hinge side, swing plan drawn as an arc
    or as plain readings, with / without the elevation 'V', sometimes a stray value next to the plan."""
    pages, e = [], 1
    for _ in range(n_pages):
        specs = []
        for _j in range(4):
            sp = random_spec(rng, e, str(rng.randint(10, 99)), rng.randint(1, 3), door_first=True)
            sp.hinge = rng.choice("LR")
            sp.plan = "arc" if rng.random() < 0.7 else "text"
            sp.vmark = rng.random() < 0.7
            sp.stray = rng.random() < 0.3
            hl = sp.lowers[0 if sp.hinge == "L" else 1]
            sp.swing = [(hl[0], rng.choice(FRACS)), (hl[0], rng.choice(FRACS))]
            specs.append(sp)
            e += 1
        pages.append(specs)
    return pages


def door_determinable(s) -> bool:
    """Can the hinge side be told from the sheet? ('V' mark, drawn plan, or a closed reading that differs)."""
    i = 0
    return s.vmark or s.plan == "arc" or val(*s.lowers[i]) != val(*s.lowers[i + 1])


def reference_project():
    """The 14002 Westbend sample (values as read from the user's screenshots)."""
    U = lambda a, b="": (a, b)  # noqa: E731
    p1 = [ElevSpec(1, "63", "OFFICE 2", [("OLIGL-12", "63-A"), ("OLIGL-12", "63-B")],
                   [U(50), U(50, "1/16"), U(50, "1/16")], [U(57, "1/4"), U(57, "5/16"), U(57, "1/4")]),
          ElevSpec(2, "63", "OFFICE 2", [("FPD-LIGL", "63"), ("OLIGL-12", "63-C")],
                   [U(50), U(49, "15/16"), U(49, "15/16")], [U(57, "3/8"), U(57, "3/8"), U(57, "3/8")]),
          ElevSpec(3, "20", "OFFICE 1", [("FPD-LIGL", "20"), ("OLIGL-12", "20-A"), ("OLIGL-12", "20-B")],
                   [U(50), U(50), U(50), U(49, "15/16")], [U(57, "5/16"), U(57, "1/4"), U(57, "3/16"), U(57, "5/16")])]
    p2 = [ElevSpec(4, "20", "OFFICE 1", [("OLIGL-12", "20-C"), ("OLIGL-12", "20-D"), ("OLIGL-12", "20-E")],
                   [U(49, "15/16"), U(49, "15/16"), U(50), U(50, "1/16")],
                   [U(57, "5/16"), U(57, "3/16"), U(57, "3/16"), U(57, "3/16")]),
          ElevSpec(5, "37", "CONFERENCE", [("FPD-LIGL", "37"), ("OLIGL-12", "37-A")],
                   [U(50), U(49, "7/8"), U(49, "15/16")], [U(57, "3/16"), U(56, "15/16"), U(57)]),
          ElevSpec(6, "37", "CONFERENCE", [("OLIGL-12", "37-B"), ("OLIGL-12", "37-C")],
                   [U(49, "15/16"), U(49, "7/8"), U(49, "7/8")], [U(57), U(57), U(57, "1/2")])]
    p1[1].swing = [U(57, "1/4"), U(57, "1/4")]
    p1[2].swing = [U(57, "3/16"), U(57, "1/8")]
    p2[1].swing = [U(57, "1/16"), U(57)]
    p1[2].hinge = "R"                                   # door 20 hinged on the right, door 37 drawn without an arc
    p2[1].plan = "text"
    return [p1, p2]


def expected_doors(specs_by_page):
    """Pivot doors of the 14002-style sheets: [(elev, tag, (A_u, A_l), (B_u, B_l), (C1_u, C1_l), (C2_u, C2_l))].
    A = hinge edge, B = latch edge, C1 = 45 deg reading with B's upper, C2 = 90 deg reading with A's upper."""
    out = []
    for specs in specs_by_page:
        for s in specs:
            for i, (code, tag) in enumerate(s.tags):
                if not code.startswith("FPD"):
                    continue
                hi, li = (i, i + 1) if s.hinge == "L" else (i + 1, i)
                A = (val(*s.uppers[hi]), val(*s.lowers[hi]))                    # A = hinge side, B = latch side
                B = (val(*s.uppers[li]), val(*s.lowers[li]))
                c1 = val(*s.swing[0]) if s.swing else ""
                c2 = val(*s.swing[1]) if s.swing else ""
                out.append((str(s.elev), tag, A, B, (B[0], c1), (A[0], c2)))
    return out


# ---------------------------------------------------------------------------------------------
# Family 3 - 14092 SSI Orange County style: ONE upper per elevation written near the edge-label row, lowers
# written UNDER the title (one per frame edge), 'GL-12 / BY OTHERS' glass, door-swing plan values above that
# repeat the lower magnitude, rotated narrow sidelites, an elevation marked 'Deleted' with no upper of its own.
# Family 4 - 'ADMIN' style (user screenshots): blue values with hyphen fractions (42-1/16, 60-5/8), uppers in a
# row above the frame, lowers in a row at the bottom, stacked lites (3 per column) tagged DGL-12 / 1917-D1 / 1917-DD1.
BLUE = (0.05, 0.1, 0.95)


@dataclass
class FamSpec:
    elev: int
    room: str
    name: str
    panels: list                 # [(code, tag, kind, vertical)]  (one per column; ADMIN: tag is the column letter)
    uppers: list                 # per edge (OC: one value repeated)
    lowers: list                 # per edge
    stack: int = 1               # ADMIN: lites per column
    deleted: bool = False        # OC: no upper written ('Deleted'), upper comes from the neighbour
    skip: set = field(default_factory=set)   # OC: edges whose lower is NOT written under the title


def _w(rng, base, fr=("", "1/16", "1/8", "3/16", "1/4", "3/8", "1/2", "5/8", "3/4", "13/16", "15/16")):
    return (base + rng.choice([0, 0, 1, -1]), rng.choice(fr))


def random_spec_oc(rng, elev, room, n, deleted=False):
    panels = []
    for i in range(n):
        r = rng.random()
        if r < .2 and n > 1:
            panels.append(("FPD-OGL", room, "Door", False))
        elif r < .55:
            panels.append(("GL-12", "BY OTHERS", "By others", rng.random() < .3))
        else:
            panels.append(("GL-12", f"{room}-{chr(65 + i)}", "Fixed", False))
    up = _w(rng, 45)
    sp = FamSpec(elev, room, f"OFFICE {room}", panels, [up] * (n + 1), [_w(rng, 60) for _ in range(n + 1)],
                 deleted=deleted)
    for i in range(1, n):                     # an inner edge left blank by the field man (between two full panels)
        if not panels[i - 1][3] and not panels[i][3] and i - 1 not in sp.skip and rng.random() < 0.18:
            sp.skip.add(i)
    return sp


def random_spec_admin(rng, elev, room, ncols, door=False):
    panels = []
    for i in range(ncols):
        if door and i == 0:
            panels.append(("FPD-DGL", f"{room}-A", "Door", False))
        else:
            panels.append(("DGL-12", chr(68 + i), "Fixed", False))            # D, E, F ...
    return FamSpec(elev, room, f"ADMIN - {room}", panels, [_w(rng, 42, ("", "1/16", "1/8", "3/16", "3/8", "7/16"))
                                                        for _ in range(ncols + 1)],
                   [_w(rng, 60) for _ in range(ncols + 1)], stack=3)


def _fam_val(rng, w, f, style):
    if style == "admin":
        return f"{w}-{f}" if f else str(w)
    return f'{w} {f}"' if f else f'{w}"'


def _fam_width(s):
    return len(s.panels) * (70 if s.stack > 1 else 62) + 60


def draw_elevation_fam(page, s: FamSpec, x0, bm_y, rng, style):
    col = BLUE if style == "admin" else RED
    n = len(s.panels)
    edges, x = [x0], x0
    for code, tag, kind, vert in s.panels:
        x += (18 if vert else (70 if s.stack > 1 else 62))
        edges.append(x)
    top, bot = bm_y - 95, bm_y + 130
    title_y = bot + 28 if style == "oc" else bot + 22
    for ex in edges:                                                # frame edges (double lines like CAD)
        page.draw_line((ex - 1.2, top), (ex - 1.2, bot), width=0.5)
        page.draw_line((ex + 1.2, top), (ex + 1.2, bot), width=0.5)
    page.draw_line((x0, top), (edges[-1], top), width=0.5)
    page.draw_line((x0, bot), (edges[-1], bot), width=0.5)
    page.insert_text((x0 - 4, top - 70), rng.choice(["DW", "FAL"]), fontsize=5)
    page.insert_text((edges[-1] - 4, top - 70), rng.choice(["DW", "FAL", "CL"]), fontsize=5)
    page.insert_text(((x0 + edges[-1]) / 2 - 12, top - 62), _fam_val(rng, 100 + n * 20, "5/16", style), fontsize=8,
                     color=col)                                     # width: out of the BM range
    if style == "oc":
        page.insert_text((x0 + 20, top - 150), _fam_val(rng, *s.lowers[0], style), fontsize=8, color=RED)  # swing plan
        page.insert_text((x0 + 60, top - 130), _fam_val(rng, *s.lowers[1], style), fontsize=8, color=RED)
        if not s.deleted:
            page.insert_text(((x0 + edges[-1]) / 2 - 10, top - 52), _fam_val(rng, *s.uppers[0], style), fontsize=8,
                             color=RED)
        else:
            page.insert_text((x0 + 4, top - 50), "Deleted", fontsize=8, color=RED)
        for i, ex in enumerate(edges):                               # lowers UNDER the title, near each edge
            if i > 0 and edges[i] - edges[i - 1] < 25:
                continue                                             # narrow sidelite: one value for both edges
            if i in s.skip:
                continue                                             # field man left this edge blank
            page.insert_text((ex - 12, title_y + 26 + rng.uniform(-3, 3)), _fam_val(rng, *s.lowers[i], style),
                             fontsize=8, color=RED)
    else:
        for i, ex in enumerate(edges):
            page.insert_text((ex - 12, top - 14), _fam_val(rng, *s.uppers[i], style), fontsize=8, color=col)
            page.insert_text((ex - 12, bot + 12), _fam_val(rng, *s.lowers[i], style), fontsize=8, color=col)
    for i, (code, tag, kind, vert) in enumerate(s.panels):
        cx = (edges[i] + edges[i + 1]) / 2
        if vert:
            page.insert_text((cx - 1, bm_y + 10), f"{code}", fontsize=4.5, rotate=90)
            page.insert_text((cx + 5, bm_y + 10), tag, fontsize=4.5, rotate=90)
        elif s.stack > 1 and kind != "Door":
            for r in range(s.stack):
                cy = top + (r + 0.5) * (bot - top) / s.stack - 8
                if r:
                    page.draw_line((edges[i], top + r * (bot - top) / s.stack), (edges[i + 1], top + r * (bot - top) / s.stack), width=0.5)
                page.insert_text((cx - 12, cy), code, fontsize=4.5)
                page.insert_text((cx - 14, cy + 6), f"{s.room}-{tag}{r + 1}", fontsize=4.5)
                page.insert_text((cx - 15, cy + 12), f"{s.room}-{tag}{tag}{r + 1}", fontsize=4.5)
        else:
            page.insert_text((cx - 12, bm_y - 12), code, fontsize=4.5)
            if kind == "By others":
                page.insert_text((cx - 14, bm_y - 6), "BY OTHERS", fontsize=4.5)
            else:
                page.insert_text((cx - 10, bm_y - 6), tag, fontsize=4.5)
                if s.stack > 1:
                    page.insert_text((cx - 11, bm_y), tag + "A", fontsize=4.5)
    page.draw_circle((x0 + 8, title_y - 3), 8, width=0.6)
    page.insert_text((x0 + 5 - (3 if s.elev > 9 else 0), title_y), str(s.elev), fontsize=8)
    page.insert_text((x0 + 20, title_y), "ELEVATION /", fontsize=8)              # title split in two text pieces
    page.insert_text((x0 + 70, title_y), s.name, fontsize=8)
    page.insert_text((x0 + 20, title_y + 7), "CORRIDOR VIEW - PHASE 1", fontsize=4.5)


def build_fm_pdf_family(path, specs_by_page, style="oc", seed=7, rotate=0):
    rng = random.Random(seed)
    doc = pymupdf.open()
    for specs in specs_by_page:
        p = doc.new_page(width=1224, height=792)
        bm = 330
        x = 120
        for s in specs:
            draw_elevation_fam(p, s, x, bm, rng, style)
            x += _fam_width(s) + 110
        for xs in range(25, 1195, 9):
            p.draw_line((xs, bm), (xs + 5, bm), color=(0.35, 0.35, 0.35), width=0.5)
        p.insert_text((30, bm + 7), "BM", fontsize=18)
        p.draw_line((20, 640), (1204, 640), width=0.8)                # title block top
        p.insert_text((30, 660), "PROJECT / DRAWING NO.:  14092", fontsize=10)
        p.insert_text((400, 660), "3) FINISH FLOOR THICKNESS :", fontsize=8)
        p.insert_text((560, 660), '1/4"', fontsize=8, color=RED)
    doc.save(path)
    doc.close()
    if rotate:                                                       # CAD plot stored sideways
        src, out = pymupdf.open(path), pymupdf.open()
        for i in range(src.page_count):
            w, h = src[i].rect.width, src[i].rect.height
            q = out.new_page(width=h, height=w)
            q.show_pdf_page(q.rect, src, i, rotate=rotate)
            q.set_rotation(rotate)
        src.close()
        out.save(path)
        out.close()


def _fill_skipped(low, skip):
    """Edge left blank: between two written edges = their average floored to 1/16, at the end = nearest written."""
    if not skip:
        return low
    from .units import parse_length, to_fraction_str
    num = [parse_length(val(*w))["value"] for w in low]
    out = list(low)
    real = [i for i in range(len(low)) if i not in skip]
    for i in skip:
        lft = [k for k in real if k < i]
        rgt = [k for k in real if k > i]
        if lft and rgt:
            v = math.floor((num[max(lft)] + num[min(rgt)]) / 2 * 16 + 1e-6) / 16
            w, _, f = to_fraction_str(v).partition(" ")
            out[i] = (int(w), f) if "/" in f else (int(v), "")
        else:
            out[i] = low[min(real, key=lambda k: (abs(k - i), k))]
    return out


def expected_family(specs_by_page, style="oc"):
    """Sorted list of (elev, tag, L_u, L_l, R_u, R_l, kind) - one row per glass lite."""
    out = []
    for specs in specs_by_page:
        up_line = next((s.uppers[0] for s in specs if not s.deleted), None)
        for s in specs:
            n = len(s.panels)
            low = list(s.lowers)
            widths = [(18 if v else 62) for _, _, _, v in s.panels]
            if style == "oc":                                         # narrow sidelite shares one written value
                x, edges = 0, [0]
                for w_ in widths:
                    x += w_
                    edges.append(x)
                for i in range(1, n + 1):
                    if edges[i] - edges[i - 1] < 25:
                        low[i] = low[i - 1]
                low = _fill_skipped(low, s.skip)
            ups = [up_line] * (n + 1) if (style == "oc" and s.deleted) else s.uppers
            for i, (code, tag, kind, vert) in enumerate(s.panels):
                vals = (val(*ups[i]), val(*low[i]), val(*ups[i + 1]), val(*low[i + 1]))
                if s.stack > 1 and kind != "Door":
                    for r in range(s.stack):
                        out.append((str(s.elev), f"{s.room}-{tag}{r + 1} / {s.room}-{tag}{tag}{r + 1}") + vals + (kind,))
                elif s.stack > 1:
                    out.append((str(s.elev), f"{tag} / {tag}A") + vals + (kind,))
                else:
                    out.append((str(s.elev), tag) + vals + (kind,))
    return sorted(out)


def random_project_family(rng, style="oc", n_pages=None):
    pages, e = [], 1
    for _ in range(n_pages or rng.randint(1, 2)):
        specs, width = [], 0
        for k in range(rng.randint(1, 3)):
            room = str(rng.randint(700, 1999))
            if style == "oc":
                s = random_spec_oc(rng, e, room, rng.randint(1, 4), deleted=k > 0 and rng.random() < .3)
            else:
                s = random_spec_admin(rng, e, room, rng.randint(1, 3), door=rng.random() < .3)
            if width + _fam_width(s) + 110 > 1000:
                break
            specs.append(s); width += _fam_width(s) + 110; e += 1
        if style == "oc" and specs:                                  # one ceiling per BM line (as on real sheets)
            for s in specs[1:]:
                s.uppers = [specs[0].uppers[0]] * len(s.uppers)
        pages.append(specs)
    return pages


# ---------------------------------------------------------------------------------------------
# Family 5 - 13871 AstraZeneca style: uppers and lowers of the SAME magnitude (48 / 48 3/8), notes inside the
# drawing that mention 'ELEVATION 26 & 27 WILL ... A FPD ...', a bulkhead height (69 3/4) written above a door,
# narrow rotated sidelite next to the door with readings only on its outer edge, side views with a thickness
# (15 1/4) in the BM range, door-swing plans with 48-ish values above the edge labels.
GREEN2 = (0.05, 0.55, 0.15)


def random_spec_az(rng, elev, room, n, sidelite=False, single=False):
    if single:
        return {"elev": elev, "room": room, "single": True, "panels": [("OGL-12", f"{room}-A", "Fixed", True)],
                "u": [_w(rng, 48, ("", "1/8", "1/4"))], "l": [_w(rng, 48, ("", "1/8", "3/16", "1/4", "3/8"))]}
    panels = []
    for i in range(n):
        panels.append(("FPD-DGL", f"{room}-A", "Door", False) if i == 0 and n > 1 and rng.random() < .5 else
                      ("OGL-12", f"{room}-{chr(65 + i)}", "Fixed", False))
    if sidelite:
        panels.append(("OGL-12", f"{room}-{chr(65 + n)}", "Fixed", True))
    k = len(panels) + 1 - (1 if sidelite else 0)                 # measured edges (not the sidelite mullion)
    return {"elev": elev, "room": room, "single": False, "panels": panels, "sidelite": sidelite,
            "u": [(48, rng.choice(["", "", "1/8", "1/4"])) for _ in range(k)],
            "l": [_w(rng, 48, ("", "1/16", "3/16", "1/4", "3/8", "1/2")) for _ in range(k)],
            "bulkhead": rng.random() < .5}


def draw_elevation_az(page, s, x0, bm, rng, note_no):
    top, bot = bm - 80, bm + 160
    title_y = bot + 28
    widths = [(20 if p[3] else 85) for p in s["panels"]]
    edges = [x0]
    for w in widths:
        edges.append(edges[-1] + w)
    for ex in edges:
        page.draw_line((ex - 1, top), (ex - 1, bot), width=0.5)
        page.draw_line((ex + 1, top), (ex + 1, bot), width=0.5)
    page.draw_line((x0, top), (edges[-1], top), width=0.5)
    page.draw_line((x0, bot), (edges[-1], bot), width=0.5)
    page.insert_text((x0 - 4, top - 90), "DW", fontsize=5)
    page.insert_text((edges[-1] - 4, top - 90), rng.choice(["DW", "FAL"]), fontsize=5)
    page.insert_text((x0 + 20, top - 200), f"{48} 1/4", fontsize=9, color=BLUE)       # swing plan above labels
    page.insert_text((x0 + 70, top - 170), f"{48} 3/8", fontsize=9, color=BLUE)
    for i, (code, tag, kind, vert) in enumerate(s["panels"]):
        cx = (edges[i] + edges[i + 1]) / 2
        if vert:
            page.insert_text((cx - 1, bm + 10), code, fontsize=4.5, rotate=90)
            page.insert_text((cx + 5, bm + 10), tag, fontsize=4.5, rotate=90)
        else:
            page.insert_text((cx - 12, bm - 12), code, fontsize=4.5)
            page.insert_text((cx - 10, bm - 6), tag, fontsize=4.5)
            if kind == "Door":
                page.insert_text((cx - 11, bm), tag + "A", fontsize=4.5)
    if s["single"]:
        ex = x0 + 25
        page.insert_text((x0 + 10, top - 40), '15 1/4', fontsize=6, color=RED)          # thickness, in BM range
        page.insert_text((ex, bm - 30), val(*s["u"][0]), fontsize=5, color=RED)
        page.insert_text((ex, bm + 40), val(*s["l"][0]), fontsize=5, color=GREEN2)
    else:
        meas = list(range(len(edges)))
        if s.get("sidelite"):
            meas.remove(len(edges) - 2)                            # mullion between door/panel and sidelite
        for k, ei in enumerate(meas):
            ex = edges[ei]
            page.insert_text((ex - 8, bm - 45 + rng.uniform(-6, 6)), val(*s["u"][k]), fontsize=10, color=RED)
            page.insert_text((ex - 14, bm + 95 + rng.uniform(-3, 3)), val(*s["l"][k]), fontsize=10, color=GREEN2)
        if s.get("bulkhead"):
            page.insert_text((x0 + 40, top - 30), "69 3/4", fontsize=8, color=GREEN2)   # bulkhead height
        y = bm - 20
        for ln in ["NOTE TO ARCHITECT:", f"ELEVATION {note_no} & {note_no + 1} WILL", "RECEIVE A FPD DUE TO",
                   "SWING. CONFIRMED"]:
            page.insert_text((x0 - 105, y), ln, fontsize=5)
            y += 7
    page.draw_circle((x0 + 8, title_y - 3), 8, width=0.6)
    page.insert_text((x0 + 4, title_y), str(s["elev"]), fontsize=8)
    page.insert_text((x0 + 20, title_y), f"ELEVATION / FOCUS ROOM #{s['room']}", fontsize=8)
    page.insert_text((x0 + 20, title_y + 7), "CORRIDOR VIEW", fontsize=4.5)
    return edges


def build_fm_pdf_az(path, specs_by_page, seed=7, rotate=0):
    rng = random.Random(seed)
    doc = pymupdf.open()
    for specs in specs_by_page:
        p = doc.new_page(width=1224, height=792)
        bm, x = 360, 230
        for s in specs:
            draw_elevation_az(p, s, x, bm, rng, s["elev"] - 1)
            x += sum(20 if q[3] else 85 for q in s["panels"]) + 190
        for xs in range(25, 1195, 9):
            p.draw_line((xs, bm), (xs + 5, bm), color=(0.35, 0.35, 0.35), width=0.5)
        p.insert_text((30, bm + 7), "BM", fontsize=18)
        p.draw_line((20, 680), (1204, 680), width=0.8)
        p.insert_text((30, 700), "PROJECT / DRAWING NO.:  13871", fontsize=10)
    doc.save(path)
    doc.close()
    if rotate:
        src, out = pymupdf.open(path), pymupdf.open()
        for i in range(src.page_count):
            w, h = src[i].rect.width, src[i].rect.height
            q = out.new_page(width=h, height=w)
            q.show_pdf_page(q.rect, src, i, rotate=rotate)
            q.set_rotation(rotate)
        src.close(); out.save(path); out.close()


def expected_az(specs_by_page):
    out = []
    for specs in specs_by_page:
        for s in specs:
            if s["single"]:
                code, tag, kind, _ = s["panels"][0]
                out.append((str(s["elev"]), tag, val(*s["u"][0]), val(*s["l"][0]), val(*s["u"][0]), val(*s["l"][0]), kind))
                continue
            u, l = [val(*x) for x in s["u"]], [val(*x) for x in s["l"]]
            if s.get("sidelite"):                                  # mullion takes the nearest (outer) edge
                u.insert(len(u) - 1, u[-1]); l.insert(len(l) - 1, l[-1])
            for i, (code, tag, kind, _) in enumerate(s["panels"]):
                t = f"{tag} / {tag}A" if kind == "Door" else tag
                out.append((str(s["elev"]), t, u[i], l[i], u[i + 1], l[i + 1], kind))
    return sorted(out)


def random_project_az(rng, n_pages=None):
    pages, e = [], 24
    for _ in range(n_pages or rng.randint(1, 2)):
        specs, width = [], 0
        for _ in range(rng.randint(1, 3)):
            s = random_spec_az(rng, e, str(1120 + e), rng.randint(1, 3), sidelite=rng.random() < .4,
                               single=rng.random() < .2)
            w = sum(20 if q[3] else 85 for q in s["panels"]) + 190
            if width + w > 950:
                break
            specs.append(s); width += w; e += 1
        pages.append(specs)
    return pages
