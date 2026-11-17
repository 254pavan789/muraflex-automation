"""One-glyph fractions read by OCR (54¼, 49⅝", 50⅛").

OCR engines do not know the vulgar-fraction glyphs: 54¼ comes back as '54%4', '544' or '5414', and 49⅝" as '49%"' -
the fraction is lost. When a mark-up value was read by OCR, the glyph after the whole number is cut out of a sharp
render of the page and compared with the seven fractions FM sheets use (½ ¼ ¾ ⅛ ⅜ ⅝ ⅞), drawn in a Helvetica-like
font (the font CAD and Bluebeam use for these notes). The best match replaces the OCR guess:  '54%4' -> '54 1/4"'.
"""
from __future__ import annotations

import re
import threading

import numpy as np
import pymupdf

FRACS = {"¼": (1, 4), "½": (1, 2), "¾": (3, 4), "⅛": (1, 8), "⅜": (3, 8), "⅝": (5, 8), "⅞": (7, 8)}
GRID = (20, 24)
MIN_SCORE = 0.30
_TPL = None
_LOCK = threading.Lock()
_CLEAN = re.compile(r"^\d{2}(?:\s*\d{1,2}/\d{1,2})?\s*[\"”″']?$")      # already a clean whole / fraction reading


def _norm(mask):
    """Binary glyph -> fixed-size, zero-mean, unit-length vector (scale and stroke-weight tolerant)."""
    ys, xs = np.where(mask)
    if not len(ys):
        return None
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
    from PIL import Image
    a = np.asarray(Image.fromarray(m).resize(GRID, Image.BILINEAR), float) / 255
    a -= a.mean()
    n = np.linalg.norm(a)
    return a / n if n else None


def _templates():
    global _TPL
    with _LOCK:
        if _TPL is None:
            tpl = {}
            for fname in ("helv", "cjk"):                       # Nimbus Sans (Helvetica / Arial look) + a fallback
                try:
                    font = pymupdf.Font(fname)
                except Exception:
                    continue
                for ch in FRACS:
                    doc = pymupdf.open()
                    pg = doc.new_page(width=200, height=200)
                    tw = pymupdf.TextWriter(pg.rect)
                    tw.append((20, 150), ch, font=font, fontsize=120)
                    tw.write_text(pg)
                    pix = pg.get_pixmap(alpha=False)
                    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
                    v = _norm(a.min(axis=2) < 128)
                    if v is not None:
                        tpl.setdefault(ch, []).append(v)
            _TPL = tpl
        return _TPL


def needs_check(text: str) -> bool:
    """OCR text of a value that may hide a one-glyph fraction: starts with a 2-digit whole number (BM range) and is not
    already a clean reading ('50"' / '54 1/4"' stay as they are)."""
    t = text.strip()
    m = re.match(r"\d{2}", t)
    if re.search(r"\d\s*/\s*\d", t):              # '57"1/4' / '541/4': OCR already saw a written fraction
        return False
    return bool(m) and 15 <= int(m.group(0)) <= 95 and not _CLEAN.match(t) and len(t) <= 8


def classify(page, bbox) -> tuple:
    """Look at the value in bbox (display coordinates) -> (fraction glyph or '', score)."""
    x0, y0, x1, y1 = bbox
    h = max(y1 - y0, 4)
    clip = pymupdf.Rect(x0 - 0.3 * h, y0 - 0.2 * h, x1 + 0.5 * h, y1 + 0.2 * h) * page.derotation_matrix
    clip.normalize()
    z = 80 / h
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=clip, alpha=False)   # rendered upright, as displayed
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).astype(int)
    mask = ((img.max(axis=2) - img.min(axis=2)) > 35) & (img.min(axis=2) < 215)   # mark-up ink, not black / white
    cols = mask.any(axis=0)
    blobs, i = [], 0
    while i < len(cols):
        if cols[i]:
            j = i
            while j < len(cols) and cols[j]:
                j += 1
            ys = np.where(mask[:, i:j].any(axis=1))[0]
            blobs.append((i, j, ys.min(), ys.max()))
            i = j
        else:
            i += 1
    if not blobs:
        return "", 0.0
    top, bot = min(b[2] for b in blobs), max(b[3] for b in blobs)
    ht = max(bot - top, 1)
    body = [b for b in blobs if b[3] - b[2] > 0.6 * ht]          # digits + fraction (inch marks are short, at the top)
    if len(body) < 2:
        return "", 0.0
    digits_w = body[-2][1] - body[0][0]
    fw = body[-1][1] - body[-1][0]
    if not 0.25 * digits_w <= fw <= 0.95 * digits_w:               # the last glyph is about one digit wide
        return "", 0.0
    v = _norm(mask[:, body[-1][0]:body[-1][1]])
    if v is None:
        return "", 0.0
    scores = sorted(((float((v * t).sum()), ch) for ch, ts in _templates().items() for t in ts), reverse=True)
    return (scores[0][1], scores[0][0]) if scores and scores[0][0] >= MIN_SCORE else ("", 0.0)


def repair(page, text: str, bbox):
    """'54%4' / '544' / '49%"' -> '54 1/4"' / '49 5/8"' when the glyph is recognised, else None."""
    if not needs_check(text):
        return None
    try:
        ch, _ = classify(page, bbox)
    except Exception:
        return None
    if not ch:
        return None
    n, d = FRACS[ch]
    return f'{text.strip()[:2]} {n}/{d}"'
