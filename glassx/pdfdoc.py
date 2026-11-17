"""PDF access layer: every piece of text on a page as a token (text, box, colour, size, direction),
text lines for titles, and long horizontal vector lines (benchmark-line candidates).

All coordinates returned are DISPLAYED page coordinates (rotation applied), in PDF points.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import numpy as np

try:
    import pymupdf  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore

from . import fracglyph, ocr

PDF_LOCK = threading.RLock()       # MuPDF documents are not thread-safe


@dataclass
class Token:
    t: str
    bbox: list
    rgb: tuple = (0, 0, 0)
    size: float = 8.0
    dir: tuple = (1.0, 0.0)
    conf: float = 1.0
    src: str = "text"              # text | annot | ocr

    @property
    def cx(self):
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def cy(self):
        return (self.bbox[1] + self.bbox[3]) / 2


@dataclass
class PageData:
    width: float
    height: float
    method: str                     # text | ocr
    tokens: list = field(default_factory=list)
    lines: list = field(default_factory=list)        # [{"t", "bbox"}]
    hlines: list = field(default_factory=list)       # [(y, x0, x1, dashed)]
    vlines: list = field(default_factory=list)       # [(x, y0, y1)]  frame edges / mullions
    swing: dict = field(default_factory=dict)        # {"arcs": [...], "diag": [...]}  door-swing geometry


def _rgb(c: int):
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


def _disp(page, bb):
    r = pymupdf.Rect(bb) * page.rotation_matrix
    r.normalize()
    return [r.x0, r.y0, r.x1, r.y1]


def _along(bb, dx, dy):
    vals = [x * dx + y * dy for x in (bb[0], bb[2]) for y in (bb[1], bb[3])]
    return min(vals), max(vals)


def overlap(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _tokens_from_raw(page, raw, src="text", displayed=False) -> list:
    """rawdict -> tokens, split at whitespace AND at visible gaps between characters.
    displayed=True: coordinates are already in displayed (rotated) space - true for annotation appearances."""
    toks = []
    m = pymupdf.Matrix(1, 0, 0, 1, 0, 0) if displayed else page.rotation_matrix
    for b in raw.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            dx, dy = ln.get("dir", (1, 0))
            ddx, ddy = dx * m.a + dy * m.c, dx * m.b + dy * m.d          # writing direction as displayed
            for sp in ln.get("spans", []):
                size = sp.get("size", 8) or 8
                rgb = _rgb(sp.get("color", 0))
                if sp.get("alpha", 255) == 0 or min(rgb) > 245:      # invisible / white text: not on the sheet
                    continue
                cur, prev_end, prev_perp = [], None, None

                def flush():
                    if cur:
                        x0 = min(c[1][0] for c in cur); y0 = min(c[1][1] for c in cur)
                        x1 = max(c[1][2] for c in cur); y1 = max(c[1][3] for c in cur)
                        bb = [x0, y0, x1, y1] if displayed else _disp(page, (x0, y0, x1, y1))
                        toks.append(Token("".join(c[0] for c in cur), bb, rgb, size,
                                          (round(ddx, 2), round(ddy, 2)), 1.0, src))
                for ch in sp.get("chars", []):
                    c, bb = ch.get("c", ""), ch.get("bbox")
                    if not c or c.isspace():
                        flush(); cur = []; prev_end = None; prev_perp = None
                        continue
                    a0, a1 = _along(bb, dx, dy)
                    perp = ((bb[0] + bb[2]) * -dy + (bb[1] + bb[3]) * dx) / 2       # position across the line
                    if prev_end is not None and (a0 - prev_end > 0.33 * size or a0 - prev_end < -1.5 * size
                                                 or (abs(perp - prev_perp) > 0.3 * size and c.isdigit()
                                                     and cur and cur[-1][0].isdigit())):
                        flush(); cur = []
                    cur.append((c, bb))
                    prev_end, prev_perp = a1, perp
                flush()
    return toks


def tokens_text_layer(page) -> list:
    """Split text at whitespace AND at visible gaps between characters.
    FM sheets often store far-apart labels in one span with no spaces ('FAL59"7/16111"')."""
    toks = _tokens_from_raw(page, page.get_text("rawdict"))
    toks += annotation_tokens(page, toks)
    return toks


def annotation_tokens(page, existing) -> list:
    """Mark-ups (FreeText / Text / Callout - e.g. Bluebeam values) that are not already page text.
    The annotation's own appearance is read glyph by glyph, so every word keeps its real position and colour;
    if that is not possible the note text is spread over the annotation box."""
    out = []
    try:
        annots = list(page.annots() or [])
    except Exception:
        return out
    for a in annots:
        try:
            if a.type[0] not in (pymupdf.PDF_ANNOT_FREE_TEXT, pymupdf.PDF_ANNOT_TEXT):
                continue
            got = []
            if a.type[0] == pymupdf.PDF_ANNOT_FREE_TEXT:
                try:
                    got = _tokens_from_raw(page, a.get_textpage().extractRAWDICT(), "annot", displayed=True)
                except Exception:
                    got = []
            if not got:
                txt = (a.info.get("content") or "").strip()
                if not txt:
                    continue
                bb = _disp(page, a.rect)
                col = a.colors.get("stroke") or a.colors.get("fill") or (1, 0, 0)
                rgb = tuple(int(v * 255) for v in col[:3])
                lines = [ln for ln in txt.splitlines() if ln.strip()] or [txt]
                lh = (bb[3] - bb[1]) / len(lines)
                for li, ln in enumerate(lines):
                    words = ln.split()
                    total = max(sum(len(w) for w in words) + len(words) - 1, 1)
                    cw = (bb[2] - bb[0]) / total
                    x = bb[0]
                    for w in words:
                        got.append(Token(w, [x, bb[1] + li * lh, x + len(w) * cw, bb[1] + (li + 1) * lh], rgb,
                                         min(lh, 12), (1.0, 0.0), 1.0, "annot"))
                        x += (len(w) + 1) * cw
            for t in got:
                if not any(e.t == t.t and overlap(e.bbox, t.bbox) for e in existing):
                    out.append(t)
        except Exception:
            continue
    return out


def tokens_ocr(page, regions=None) -> list:
    """OCR words, colour sampled from the image under each word (to find red mark-ups).
    regions: only read these areas (display coordinates) - much faster than the whole sheet."""
    zoom = min(3.0, 6000 / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    toks = []
    zr = [[c * zoom for c in r] for r in regions] if regions else None
    for box, txt, conf in ocr_tiled(img, regions=zr):
        if box is None:
            continue
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        parts = txt.split()
        total = sum(len(p) for p in parts) + max(len(parts) - 1, 0)
        cx = x0
        for p in parts:
            w = (x1 - x0) * len(p) / max(total, 1)
            bx = (int(cx), int(y0), int(cx + w) + 1, int(y1) + 1)
            patch = img[max(bx[1], 0):bx[3], max(bx[0], 0):bx[2]].reshape(-1, 3)
            dark = patch[patch.astype(int).sum(axis=1) < 600] if len(patch) else patch
            rgb = tuple(int(v) for v in dark.mean(axis=0)) if len(dark) else (0, 0, 0)
            box_pt = [bx[0] / zoom, bx[1] / zoom, bx[2] / zoom, bx[3] / zoom]
            word = p
            if max(rgb) - min(rgb) > 35:                       # mark-up colour: a one-glyph fraction (54¼) is lost by
                fixed = fracglyph.repair(page, p, box_pt)      # OCR ('54%4', '544') - recognise the glyph itself
                if fixed:
                    word = fixed
            toks.append(Token(word, box_pt, rgb, (y1 - y0) / zoom, (1.0, 0.0), float(conf), "ocr"))
            cx += w + (x1 - x0) / max(total, 1)
    return toks


def ocr_tiled(img, tile=800, overlap=260, regions=None) -> list:
    """OCR engines shrink large images before detection, so small FM labels on a full sheet disappear.
    Reading overlapping tiles at full resolution keeps them; duplicates in the overlaps are merged.
    800 px tiles: the detector never upscales them (it does below ~736 px) and peak memory is ~25% lower than 1100."""
    H, W = img.shape[:2]
    found = []
    ys = list(range(0, max(H - overlap, 1), tile - overlap)) or [0]
    xs = list(range(0, max(W - overlap, 1), tile - overlap)) or [0]
    for y0 in ys:
        for x0 in xs:
            if regions and not any(r[0] < x0 + tile and r[2] > x0 and r[1] < y0 + tile and r[3] > y0 for r in regions):
                continue
            sub = img[y0:min(y0 + tile, H), x0:min(x0 + tile, W)]
            if sub.size == 0 or sub.min() > 200:          # blank tile
                continue
            th, tw = sub.shape[:2]
            for box, txt, conf in ocr.read_lines(np.ascontiguousarray(sub)):
                if box is None:
                    continue
                bx = [p[0] for p in box]; by = [p[1] for p in box]
                # a word touching an inner tile border is cut in two: the neighbour tile (overlap) has it whole
                cut = (x0 > 0 and min(bx) < 3) or (y0 > 0 and min(by) < 3) or \
                      (x0 + tw < W and max(bx) > tw - 3) or (y0 + th < H and max(by) > th - 3)
                found.append(([[p[0] + x0, p[1] + y0] for p in box], txt, conf, cut))

    def bb(b):
        xs_ = [p[0] for p in b]; ys_ = [p[1] for p in b]
        return min(xs_), min(ys_), max(xs_), max(ys_)
    def inter(a, b):
        return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))

    # a line longer than the tile overlap (an elevation title) is cut in BOTH tiles: join the two halves on their
    # common text  ('ELEVATION/PRIVATE OFFICE' + 'PRIVATE OFFICE 1308' -> 'ELEVATION/PRIVATE OFFICE 1308')
    def join(fa, fb):
        a, b = bb(fa[0]), bb(fb[0])
        if a[0] > b[0]:
            fa, fb, a, b = fb, fa, b, a
        hy = min(a[3], b[3]) - max(a[1], b[1])
        if hy < 0.6 * min(a[3] - a[1], b[3] - b[1]) or not (b[0] < a[2] < b[2]):
            return None
        ta, tb = fa[1], fb[1]
        for k in range(min(len(ta), len(tb)), 2, -1):
            if ta.endswith(tb[:k]):
                box = [[a[0], min(a[1], b[1])], [b[2], min(a[1], b[1])], [b[2], max(a[3], b[3])], [a[0], max(a[3], b[3])]]
                return (box, ta + tb[k:], min(fa[2], fb[2]), False)
        return None
    merged = True
    while merged:
        merged = False
        for i in range(len(found)):
            for j in range(i + 1, len(found)):
                if not (found[i][3] or found[j][3]):
                    continue
                m = join(found[i], found[j])
                if m:
                    found = [f for k, f in enumerate(found) if k not in (i, j)] + [m]
                    merged = True
                    break
            if merged:
                break
    whole = [bb(f[0]) for f in found if not f[3]]

    def covered(f):                                        # a cut word whose text other tiles read whole
        a = bb(f[0])
        return sum(inter(a, w) for w in whole) > 0.5 * max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    found = [f[:3] for f in found if not (f[3] and covered(f))]
    found.sort(key=lambda f: -f[2])
    keep = []
    for f in found:
        a = bb(f[0])
        area_a = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
        replace, dup = None, False
        for gi, g in enumerate(keep):
            b = bb(g[0])
            area_b = max((b[2] - b[0]) * (b[3] - b[1]), 1e-6)
            ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
            inter = ix * iy
            if not inter:
                continue
            if inter / max(area_a, area_b) > 0.5:                 # same word read twice (tile overlap)
                dup = True
                break
            if inter / min(area_a, area_b) > 0.7:                 # one reading is part of the other: keep the longer
                if len(f[1].replace(" ", "")) > len(g[1].replace(" ", "")) and area_a > area_b:
                    replace = gi
                else:
                    dup = True
                break
        if replace is not None:
            keep[replace] = f
        elif not dup:
            keep.append(f)
    return keep


def text_lines(page) -> list:
    out = []
    d = page.get_text("dict")
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln.get("spans", [])).strip()
            if t:
                out.append({"t": t, "bbox": _disp(page, ln["bbox"])})
    return out


def lines_from_tokens(toks) -> list:
    """OCR words -> text lines: same baseline band AND no big horizontal gap (several titles share a row)."""
    rows = {}
    for t in toks:
        rows.setdefault(round(t.cy / 6), []).append(t)
    out = []
    for arr in rows.values():
        arr.sort(key=lambda t: t.bbox[0])
        cur = [arr[0]]
        for t in arr[1:]:
            h = max(t.bbox[3] - t.bbox[1], cur[-1].bbox[3] - cur[-1].bbox[1], 4)
            if t.bbox[0] - cur[-1].bbox[2] > 3 * h:
                out.append(cur); cur = [t]
            else:
                cur.append(t)
        out.append(cur)
    return [{"t": " ".join(t.t for t in a),
             "bbox": [a[0].bbox[0], min(t.bbox[1] for t in a), a[-1].bbox[2], max(t.bbox[3] for t in a)]}
            for a in out if isinstance(a, list)]


def horizontal_lines(page, drawings=None) -> list:
    """Long horizontal lines -> [(y, x0, x1, dashed)] (benchmark-line candidates).
    CAD exports often draw a dashed line as hundreds of separate short segments, so collinear segments are
    merged first; a line made of many pieces with gaps counts as dashed."""
    segs = []
    try:
        W = page.rect.width
        rot = page.rotation_matrix
        for dr in (page.get_drawings() if drawings is None else drawings):
            dashed = bool(dr.get("dashes")) and dr.get("dashes") not in ("[] 0", "[] 0.0", "[] 0 d")
            for it in dr.get("items", []):
                if it[0] != "l":
                    continue
                r = pymupdf.Rect(it[1], it[2]) * rot
                r.normalize()
                if r.height < 1.0 and r.width > 0.5:
                    segs.append(((r.y0 + r.y1) / 2, r.x0, r.x1, dashed))
    except Exception:
        return []
    segs.sort(key=lambda s: (round(s[0] * 2), s[1]))
    out, i = [], 0
    while i < len(segs):                                    # group by y (within 0.8 pt)
        j = i
        while j + 1 < len(segs) and abs(segs[j + 1][0] - segs[i][0]) < 0.8:
            j += 1
        grp = sorted(segs[i:j + 1], key=lambda s: s[1])
        cur = list(grp[0]) + [1, 0.0]                        # y, x0, x1, dashed, pieces, gap length
        for s in grp[1:]:
            if s[1] - cur[2] < 18:                           # same line, next dash
                if s[1] > cur[2]:
                    cur[5] += s[1] - cur[2]
                cur[2] = max(cur[2], s[2]); cur[3] = cur[3] or s[3]; cur[4] += 1
            else:
                out.append(cur); cur = list(s) + [1, 0.0]
        out.append(cur)
        i = j + 1
    return [(c[0], c[1], c[2], bool(c[3] or (c[4] >= 6 and c[5] > 0.15 * (c[2] - c[1]))))
            for c in out if c[2] - c[1] > 0.25 * W]


def vertical_lines(page, drawings=None) -> list:
    """Vertical lines -> [(x, y0, y1)], collinear pieces merged (frame edges and mullions)."""
    segs = []
    try:
        rot = page.rotation_matrix
        for dr in (page.get_drawings() if drawings is None else drawings):
            for it in dr.get("items", []):
                if it[0] == "l":
                    pts = [(it[1], it[2])]
                elif it[0] == "re":
                    r = it[1]
                    pts = [(r.tl, r.bl), (r.tr, r.br), (r.tl, r.tr), (r.bl, r.br)]
                elif it[0] == "qu":
                    q = it[1]
                    pts = [(q.ul, q.ll), (q.ur, q.lr), (q.ul, q.ur), (q.ll, q.lr)]
                else:
                    continue
                for a, b in pts:
                    r = pymupdf.Rect(a, b) * rot
                    r.normalize()
                    if r.width < 1.0 and r.height > 4:
                        segs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
    except Exception:
        return []
    segs.sort(key=lambda s: (round(s[0] * 2), s[1]))
    out, i = [], 0
    while i < len(segs):
        j = i
        while j + 1 < len(segs) and abs(segs[j + 1][0] - segs[i][0]) < 0.8:
            j += 1
        grp = sorted(segs[i:j + 1], key=lambda s: s[1])
        cur = list(grp[0])
        for s_ in grp[1:]:
            if s_[1] - cur[2] < 6:
                cur[2] = max(cur[2], s_[2])
            else:
                out.append(tuple(cur)); cur = list(s_)
        out.append(tuple(cur))
        i = j + 1
    return [o for o in out if o[2] - o[1] > 30]


def _bez(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _circumcenter(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy


def swing_geometry(page, drawings=None) -> dict:
    """Door-swing drawing on the page (display coordinates):
      arcs - quarter circles of a door-swing plan: {"c": pivot, "r", "closed": end on the wall line, "tip": end of
             the open leaf (90 deg), "mid": the 45 deg point}. Drawn as Bezier curves or as a polyline.
      diag - long straight diagonal lines (dashed pieces merged): the 'V' drawn on a door in elevation, whose apex
             points to the hinge side. [(x0, y0, x1, y1)]"""
    arcs, pieces = [], []
    try:
        m = page.rotation_matrix
        ma, mb, mc, md, me, mf = m.a, m.b, m.c, m.d, m.e, m.f

        def tr(p):
            return (p[0] * ma + p[1] * mc + me, p[0] * mb + p[1] * md + mf)

        for dr in (page.get_drawings() if drawings is None else drawings):
            rr = dr.get("rect")
            big = rr is not None and max(rr.width, rr.height) >= 8
            chains, cur = [], []
            for it in dr.get("items", []):
                k = it[0]
                if k == "l":
                    p0, p1 = it[1], it[2]
                    dx, dy = abs(p1.x - p0.x), abs(p1.y - p0.y)
                    if dx > 0.3 and dy > 0.3 and 0.12 < dy / dx < 9 and len(pieces) < 40000:
                        q0, q1 = tr(p0), tr(p1)
                        pieces.append((q0[0], q0[1], q1[0], q1[1]))
                    if not big:
                        continue
                    pts = [tr(p0), tr(p1)]
                elif k == "c" and big:
                    pts = [tr(_bez(it[1], it[2], it[3], it[4], t / 6)) for t in range(7)]
                else:
                    if cur:
                        chains.append(cur)
                    cur = []
                    continue
                if cur and abs(cur[-1][0] - pts[0][0]) < 0.3 and abs(cur[-1][1] - pts[0][1]) < 0.3:
                    cur += pts[1:]
                else:
                    if cur:
                        chains.append(cur)
                    cur = list(pts)
            if cur:
                chains.append(cur)
            for ch in chains:
                if len(ch) < 4:
                    continue
                xs, ys = [p[0] for p in ch], [p[1] for p in ch]
                if max(max(xs) - min(xs), max(ys) - min(ys)) < 8:
                    continue
                c = _circumcenter(ch[0], ch[len(ch) // 2], ch[-1])
                if not c:
                    continue
                r = math.dist(c, ch[0])
                if not 10 <= r <= 250 or any(abs(math.dist(c, p) - r) > max(0.8, 0.06 * r) for p in ch):
                    continue
                a0 = math.atan2(ch[0][1] - c[1], ch[0][0] - c[0])
                a1 = math.atan2(ch[-1][1] - c[1], ch[-1][0] - c[0])
                span = abs(math.degrees(math.atan2(math.sin(a1 - a0), math.cos(a1 - a0))))
                if not 55 <= span <= 125:
                    continue
                e1, e2 = ch[0], ch[-1]
                # the closed position lies along the wall (horizontal from the pivot), the open leaf is square to it
                closed, tip = (e1, e2) if abs(e1[0] - c[0]) - abs(e1[1] - c[1]) > abs(e2[0] - c[0]) - abs(e2[1] - c[1]) \
                    else (e2, e1)
                ux, uy = closed[0] - c[0] + tip[0] - c[0], closed[1] - c[1] + tip[1] - c[1]
                n = math.hypot(ux, uy) or 1
                mid = (c[0] + r * ux / n, c[1] + r * uy / n)
                if any(math.dist(c, a["c"]) < 2 and abs(r - a["r"]) < 2 for a in arcs):
                    continue                                            # same arc drawn twice
                arcs.append({"c": c, "r": r, "closed": closed, "tip": tip, "mid": mid})
    except Exception:
        return {"arcs": [], "diag": []}
    return {"arcs": arcs, "diag": _merge_diagonals(pieces)}


def _merge_diagonals(pieces):
    """Collinear diagonal pieces (CAD dashes) -> long lines [(x0, y0, x1, y1)], top end first."""
    groups = {}
    for x0, y0, x1, y1 in pieces:
        th = math.atan2(y1 - y0, x1 - x0) % math.pi
        rho = x0 * math.sin(th) - y0 * math.cos(th)                    # signed distance of the line from the origin
        key = (round(math.degrees(th) / 1.5), round(rho / 1.5))
        groups.setdefault(key, []).append((x0, y0, x1, y1, th))
    out = []
    for g in groups.values():
        th = g[0][4]
        ux, uy = math.cos(th), math.sin(th)
        ts = sorted(t for x0, y0, x1, y1, _ in g for t in (x0 * ux + y0 * uy, x1 * ux + y1 * uy))
        if ts[-1] - ts[0] < 25:
            continue
        x0, y0, x1, y1, _ = g[0]
        rho_x, rho_y = x0 - (x0 * ux + y0 * uy) * ux, y0 - (x0 * ux + y0 * uy) * uy
        a = (rho_x + ts[0] * ux, rho_y + ts[0] * uy)
        b = (rho_x + ts[-1] * ux, rho_y + ts[-1] * uy)
        out.append((a[0], a[1], b[0], b[1]) if a[1] <= b[1] else (b[0], b[1], a[0], a[1]))
    return out


def graphic_regions(doc, pno: int) -> list:
    """Parts of a page whose drawing is NOT text: pasted pictures (a scanned or screenshot elevation placed on the FM
    template) and, when the page is mostly vector outlines with almost no text, the whole page.
    -> [[x0, y0, x1, y1]] display coordinates, worth reading with OCR when the text layer gave no elevations."""
    with PDF_LOCK:
        page = doc[pno]
        disp = page.rect * page.rotation_matrix
        disp.normalize()
        W, H = disp.width, disp.height
        regions = []
        try:
            for info in page.get_image_info():
                r = pymupdf.Rect(info["bbox"]) * page.rotation_matrix
                r.normalize()
                r &= disp
                if r.width * r.height >= 0.04 * W * H:
                    regions.append([r.x0, r.y0, r.x1, r.y1])
        except Exception:
            pass
        if regions:
            return regions
        try:
            words = page.get_text("words")
            drs = page.get_drawings()
        except Exception:
            return []
        small = sum(1 for d in drs if d.get("rect") is not None and max(d["rect"].width, d["rect"].height) < 14)
        upper = [w for w in words if (pymupdf.Rect(w[:4]) * page.rotation_matrix).normalize().y1 < 0.78 * H]
        if small > 1500 and len(upper) < 40:                     # CAD text exported as outlines (title block aside)
            return [[0, 0, W, H]]
        return []


def read_page(doc, pno: int, allow_ocr: bool = True, hybrid=False) -> PageData:
    """hybrid=True: keep the text layer AND add OCR words for everything drawn as graphics
    (mark-ups pasted as pictures, CAD text exported as vector outlines)."""
    with PDF_LOCK:
        page = doc[pno]
        toks = tokens_text_layer(page)
        method = "text"
        if sum(len(t.t) for t in toks) < 10 and allow_ocr and ocr.available():   # no text layer -> scan
            toks = tokens_ocr(page)
            method = "ocr"
        elif hybrid and allow_ocr and ocr.available():
            regions = hybrid if isinstance(hybrid, list) else None
            extra = [o for o in tokens_ocr(page, regions) if not any(overlap(o.bbox, t.bbox) for t in toks if t.t.strip())]
            if regions:
                extra = [o for o in extra if any(overlap(o.bbox, r) for r in regions)]
            if extra:
                toks = toks + extra
                method = "text+ocr"
        if method == "text":
            lines = text_lines(page)
        elif method == "ocr":
            lines = lines_from_tokens(toks)
        else:
            lines = text_lines(page) + lines_from_tokens([t for t in toks if t.src == "ocr"])
        try:
            drs = page.get_drawings()
        except Exception:
            drs = []
        return PageData(page.rect.width, page.rect.height, method, toks, lines, horizontal_lines(page, drs),
                        vertical_lines(page, drs), swing_geometry(page, drs))


def render_png(doc, pno: int, width_px: int, path: str):
    with PDF_LOCK:
        pg = doc[pno]
        z = width_px / pg.rect.width
        pg.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False).save(path)


def open_pdf(path: str):
    return pymupdf.open(path)
