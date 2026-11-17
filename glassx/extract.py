"""Elevation extraction: FM page tokens -> elevations -> benchmark points -> glass panels.

The rules are layout-independent so one engine serves every project family:

  1. tokens      split fractions are re-joined ("65'" + "13/16" -> 65 13/16, "48" + "FT" -> 48)
  2. values      inch / fraction / FT readings in the BM range; bare whole numbers ("48", "66") when written
                 in mark-up colour; numbers that belong to a word label ('42" HOLD TO', 'FAL - FAL 123 1/2')
                 are not measurements
  3. titles      upper-case 'ELEVATION / NAME' lines + circled number -> elevation slots (sentences in notes,
                 e.g. 'Elevation 1 it is wood floor', are not titles)
  4. ownership   every token goes to the elevation whose title sits below it (column-aware, multi-row,
                 column split refined with the glass codes)
  5. colour      mark-up values of any colour (green uppers + red lowers is fine); black drawing dims are
                 used only when the elevation has no coloured values
  6. BM line     the horizontal line (dashed segments are merged) or stand-alone 'BM' label that splits the
                 values into an upper and a lower band; 'BM 48FT' / 'BM 65' 1/4' value labels are values,
                 never the line; last resort: largest vertical gap
  7. window      values between the edge-label row (DW / FAL / CL) and the title; door-swing plans above
                 the edge row are ignored
  8. pair        optimal sequence alignment of uppers and lowers by x (tolerates a missing value)
  9. recover     an edge still missing a value takes the nearest unused reading in the right band (flagged)
 10. tags        glass code + tag ('OLIGL-12' / '3110A-B', also rotated) assigned to the span between points;
                 one-point side views; spans without a tag are listed but not exported
"""
from __future__ import annotations

import colorsys
import math
from types import SimpleNamespace
import re
from statistics import median

from .config import BM_RANGE, DOOR_PREFIX, EDGE_WORDS
from .pdfdoc import PageData, Token
from .units import _base_clean, parse_length, to_fraction_str

# Muraflex system codes, written generically: any glass family (…GL…: GL, OGL, DGL, LIGL, OLIGL, CLIGL, OGLI …)
# or door family (…PD / …SD / …HD / …TD / …DO / MFD / QSD …), optionally followed by '-12', '-OGL', …
CODE_RE = re.compile(r"^(?:[A-Z]{0,4}GL[A-Z]?|[A-Z]{0,2}(?:PD|SD|HD|TD|DO|GO)|MFD|QSD)(?:[-‐‑][A-Z0-9]{1,6})*$")
BARE_CODES = {"GL", "OGL", "DGL", "LIGL", "OLIGL", "OGLI", "CLIGL", "MFD", "QSD", "FPD", "FSD", "GSD", "GPD", "GHD",
              "TD", "GPSD", "GFSD", "GSTD"}
DOOR_RE = re.compile(r"^(?:[A-Z]{0,2}(?:PD|SD|HD|TD|DO|GO)|MFD|QSD)(?:[-‐‑]|$)")
TAG_RE = re.compile(r"^\d{1,5}[A-Z]{0,2}(?:[-.]\d{1,3})?(?:-[A-Z0-9]{1,3})?$")
DIM_RE = re.compile(r"^\d{1,3}\s*(?:[\"'”″′]\s*(?:\d{1,2}\s*/\s*\d{1,2}[\"']?)?|\s\d{1,2}/\d{1,2}[\"']?)$")
TITLE_RE = re.compile(r"(?<![A-Za-z])(?:ELEVATION(?![A-Za-z])|ELEV\.?(?=\s*[/#:]))")
_MK = "[\"'”“″′’‴]"          # inch marks as CAD / Bluebeam write them - sometimes 2 or 3 in a row (59 11/16"")
WHOLE_RE = re.compile(r"^\d{1,3}" + _MK + r"{0,3}-?$")
FRAC_RE = re.compile(r"^\d{1,2}/\d{1,2}\s?" + _MK + r"{0,3}$")
UNIT_RE = re.compile(r"^(FT|IN|INCH|" + _MK + r"{1,3})\.?$", re.I)
WORD_RE = re.compile(r"^[A-Za-z]{2,}[.:]?$")
VALUE_WORDS = {"BM", "FT", "IN", "TYP", "APPROX", "MIN", "MAX"}


# ---------------------------------------------------------------------------------------------- values
def _clean_value_text(text: str) -> str:
    s = _base_clean(text).strip().upper().replace("–", "-").replace("—", "-")
    s = re.sub(r"^B\.?M\.?\s*[:.]?\s*", "", s)                    # 'BM65'1/4' / 'B.M. 48' (glued label)
    s = re.sub(r"(\d)\s*(?:FT|IN|INCH)\.?$", r'\1"', s)            # '48FT' / '48 FT' written for inches
    s = s.replace("’", "'").replace("′", "'")
    for ch in ("‴", "″", "”", "“"):                              # triple / double primes, smart quotes = inch mark
        s = s.replace(ch, '"')
    s = re.sub(r"(?<=\d)\s*[\"']{2,}", '"', s)                    # repeated marks (2-3 in a row) = one inch mark
    s = re.sub(r"(?<=\d)\s+\"$", '"', s)                           # 59 11/16 " (space before the mark)
    m = re.fullmatch(r"(\d)\s*'\s*-\s*(\d{1,2})(?:\s+(\d{1,2}/\d{1,2}))?\s*\"?", s)
    if m:                                                          # real feet-inches: 5'-6 1/2"
        inch = int(m.group(1)) * 12 + int(m.group(2))
        return f'{inch}" {m.group(3)}' if m.group(3) else f'{inch}"'
    s = re.sub(r"^(\d{1,3})\s*[\"']?\s*-\s*(\d{1,2}/\d{1,2})", r"\1 \2", s)   # 42-1/16, 60-5/8"
    return s.replace("'", '"')                                     # FM sheets write inches as 66' / 65' 13/16


VULGAR_DEN = (2, 4, 8, 16)


def _glued_fraction(s: str):
    """OCR of a one-glyph fraction (54¼, 49⅝", 50⅛") glues it to the whole number: '541/4', '501/4"', and when the
    fraction bar is lost '5414', '4958"', '5018' -> 54 1/4, 49 5/8, 50 1/8. Only odd numerators over 2/4/8/16."""
    m = re.fullmatch(r'(\d{2})\s?(\d{1,2})/(\d{1,2})"?', s) or re.fullmatch(r'(\d{2})(\d)(\d{1,2})"?', s)
    if not m:
        return None
    w, n, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if d not in VULGAR_DEN or not 0 < n < d or n % 2 == 0:
        return None
    v = w + n / d
    return v if BM_RANGE[0] <= v <= BM_RANGE[1] else None


def dim_value(text: str, strict: bool = True, glued: bool = False):
    """A benchmark reading in the BM range, else None.
    strict (black PDF text): needs an inch mark, FT or a fraction, so tags like '63' are never values.
    Not strict (mark-up colour or OCR): a bare 2-digit number ('48', '66') is accepted too.
    glued (mark-up colour): OCR forms of one-glyph fractions ('5414' = 54¼) are repaired."""
    s = _clean_value_text(text)
    if glued and not strict:
        g = _glued_fraction(s)
        if g is not None:
            return g
    if not DIM_RE.match(s) and (strict or not re.fullmatch(r"\d{2}(\s*\d{1,2}/\d{1,2})?", s)):
        return None
    v = parse_length(s, BM_RANGE).get("value")
    if v is None or not (BM_RANGE[0] <= v <= BM_RANGE[1]):
        return None
    return v


def _hue_bucket(rgb):
    r, g, b = (c / 255 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.35 or v < 0.25:
        return None                              # black / grey / white = drawing ink, not mark-up
    return int(h * 12) % 12                      # 30-degree hue buckets


def coloured(t) -> bool:
    return _hue_bucket(t.rgb) is not None


def _h(t) -> float:
    return max(t.bbox[3] - t.bbox[1], 3.0) if abs(t.dir[1]) < 0.5 else max(t.bbox[2] - t.bbox[0], 3.0)


def _horizontal(t) -> bool:
    return abs(t.dir[1]) < 0.5


_SUPSUB_CH = "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u2080\u2081\u2082\u2083\u2084" \
             "\u2085\u2086\u2087\u2088\u2089\u2044\u2215"
VALID_DEN = (2, 4, 8, 16, 32, 64)


def _merge_stacked(toks: list) -> list:
    """CAD stacked fractions: big whole number + small numerator (raised) + small denominator (lowered or below),
    often followed by the inch mark as its own word: '36' '1' '16' '"' -> '36 1/16"'.  Unicode forms
    ('36¹⁄₁' + '₆') are glued back together too."""
    used, out = set(), []
    hor = [i for i, t in enumerate(toks) if _horizontal(t)]
    # unicode super/subscript pieces ('49' '⁷' '⁄' '₈' '"'), chained left to right
    def ok_join(last, b):
        return ((last.t[-1] in _SUPSUB_CH or last.t[-1].isdigit()) and b.t[:1] in _SUPSUB_CH) or \
               (last.t[-1] in _SUPSUB_CH and b.t.strip()[:1] in "\"”″'")
    tails = [j for j in hor if toks[j].t and (toks[j].t[:1] in _SUPSUB_CH or toks[j].t.strip()[:1] in "\"”″'")]
    heads = [i for i in hor if toks[i].t and (toks[i].t[-1] in _SUPSUB_CH or toks[i].t[-1].isdigit())] if tails else []
    for i in sorted(heads, key=lambda k: toks[k].bbox[0]):
        a = toks[i]
        if i in used:
            continue
        chain, last = [i], a
        while True:
            nxt = [j for j in tails if j not in used and j not in chain and toks[j].t and ok_join(last, toks[j])
                   and abs(toks[j].cy - a.cy) < 0.5 * _h(a) and -0.2 * _h(a) <= toks[j].bbox[0] - last.bbox[2] < 0.6 * _h(a)]
            if not nxt:
                break
            j = min(nxt, key=lambda j: toks[j].bbox[0])
            chain.append(j)
            last = toks[j]
        if len(chain) > 1:
            used.update(chain)
            toks.append(Token("".join(toks[c].t for c in chain), _box_union([toks[c].bbox for c in chain]), a.rgb,
                              a.size, a.dir, a.conf, a.src))
            hor.append(len(toks) - 1)
    digits = lambda t: re.fullmatch(r"\d{1,2}[\"”″']?", t.t.strip())  # noqa: E731

    def split_frac(text):
        """'116' -> (1, 16), '18"' -> (1, 8), '1516' -> (15, 16): numerator and denominator glued together
        because the fraction bar is a drawn line, not a character."""
        m = re.fullmatch(r"(\d{2,4})([\"”″']?)", text.strip())
        if not m:
            return None
        ds = m.group(1)
        for k in range(1, len(ds)):
            n, d = int(ds[:k]), int(ds[k:])
            if ds[k] != "0" and d in VALID_DEN and 0 < n < d and n % 2 == 1:
                return n, d, bool(m.group(2))
        return None

    for i in hor:
        a = toks[i]
        if i in used or not re.fullmatch(r"[±]?\d{1,3}", a.t.strip()):
            continue
        ha = _h(a)
        best = None
        # (1) one small word holding both numbers ('116' / '18"') right after the whole number
        for j in hor:
            g = toks[j]
            if j in used or j == i or g.size > 0.8 * a.size or not (-0.3 * ha <= g.bbox[0] - a.bbox[2] < 0.8 * ha) \
                    or not (a.bbox[1] - 0.4 * ha <= g.cy <= a.bbox[3] + 0.2 * ha):
                continue
            sf = split_frac(g.t)
            if sf:
                best = ("one", j, sf)
                break
        # (2) numerator and denominator as separate small words (raised / lowered or stacked)
        if best is None:
            nums = [j for j in hor if j not in used and j != i and digits(toks[j]) and toks[j].size <= 0.8 * a.size
                    and -0.3 * ha <= toks[j].bbox[0] - a.bbox[2] < 0.8 * ha
                    and a.bbox[1] - 0.4 * ha <= toks[j].cy <= a.cy + 0.1 * ha]
            cand = None
            for jn in nums:
                n = toks[jn]
                hn = _h(n)
                for jd in hor:
                    d = toks[jd]
                    if jd in used or jd in (i, jn) or not digits(d) or d.size > 0.8 * a.size:
                        continue
                    if not (d.cy > n.cy + 0.25 * hn and n.bbox[0] - 0.6 * hn <= d.bbox[0] <= n.bbox[2] + 0.9 * hn
                            and d.cy <= a.bbox[3] + 0.4 * ha):
                        continue
                    nv, dv = int(re.sub(r"\D", "", n.t)), int(re.sub(r"\D", "", d.t))
                    if dv in VALID_DEN and 0 < nv < dv:
                        key = abs(d.bbox[0] - n.bbox[2])
                        if cand is None or key < cand[0]:
                            cand = (key, jn, jd, nv, dv, bool(re.search(r"[\"”″']$", d.t.strip())))
            if cand:
                best = ("two", cand)
        if best is None:
            continue
        if best[0] == "one":
            _, j, (nv, dv, mk) = best
            parts, ids = [a, toks[j]], [i, j]
        else:
            _, jn, jd, nv, dv, mk = best[1]
            parts, ids = [a, toks[jn], toks[jd]], [i, jn, jd]
        mark = '"' if mk else ""
        if not mark:                                                # inch mark written as its own word
            right = max(p_.bbox[2] for p_ in parts[1:])
            for jm in hor:
                m = toks[jm]
                if jm not in used and jm not in ids and UNIT_RE.match(m.t.strip()) and \
                        abs(m.cy - a.cy) < 0.5 * ha and -0.3 * ha <= m.bbox[0] - right < 0.8 * ha:
                    ids.append(jm)
                    parts.append(m)
                    mark = '"'
                    break
        used.update(ids)
        out.append(Token(f"{a.t.strip().lstrip('±')} {nv}/{dv}{mark}", _box_union([p_.bbox for p_ in parts]), a.rgb,
                         a.size, a.dir, a.conf, a.src))
    return [t for k, t in enumerate(toks) if k not in used] + out


def merge_value_tokens(toks: list) -> list:
    """Re-join readings the PDF stores as separate words: "65'" + "13/16", "66" + "1/16", "48" + "FT",
    CAD stacked fractions ('36' + small '1' + small '16' + '"')."""
    toks = _merge_stacked(list(toks))
    used, out = set(), []
    hor = [i for i, t in enumerate(toks) if _horizontal(t)]
    for i in hor:
        a = toks[i]
        if i in used or not WHOLE_RE.match(_base_clean(a.t).strip()):
            continue
        ha = _h(a)
        best = None
        for j in hor:
            if j == i or j in used:
                continue
            b = toks[j]
            bt = _base_clean(b.t).strip()
            if not (FRAC_RE.match(bt) or UNIT_RE.match(bt)):
                continue
            gap = b.bbox[0] - a.bbox[2]
            same_box = abs(b.bbox[0] - a.bbox[0]) < 1 and a.src == b.src == "annot"
            if abs(b.cy - a.cy) < 0.55 * ha and (-0.3 * ha <= gap < 1.6 * ha or same_box):
                if best is None or gap < best[0]:
                    best = (gap, j)
        if best:
            b = toks[best[1]]
            used.update((i, best[1]))
            out.append(Token(f"{a.t} {b.t}", [min(a.bbox[0], b.bbox[0]), min(a.bbox[1], b.bbox[1]),
                                              max(a.bbox[2], b.bbox[2]), max(a.bbox[3], b.bbox[3])],
                             a.rgb, max(a.size, b.size), a.dir, min(a.conf, b.conf), a.src))
    return [t for i, t in enumerate(toks) if i not in used] + out


def _label_value(d, words) -> bool:
    """A number that is part of a word label ('42" HOLD TO', 'DW - CL 118"'), not a measurement."""
    h = _h(d)
    for w in words:
        if _hue_bucket(w.rgb) != _hue_bucket(d.rgb) and coloured(d):
            continue                                                       # black note beside a red reading
        if abs(w.cy - d.cy) < 0.6 * h:                                     # same line, right next to it
            gap = max(w.bbox[0] - d.bbox[2], d.bbox[0] - w.bbox[2])
            if gap < (0.6 if w.edge else 1.8) * h:                         # 'FAL59"7/16' glued; '45 3/4"  DW' is not
                return True
        if w.edge and coloured(w) and 0 < d.cy - w.cy < 2.6 * h \
                and d.bbox[0] < w.bbox[2] + 25 and d.bbox[2] > w.bbox[0] - 25:  # caption under 'FAL - FAL'
            return True
    return False


# ---------------------------------------------------------------------------------------------- titles
def _title_number_ok(t: Token) -> bool:
    return bool(re.fullmatch(r"\(?\d{1,3}\)?", t.t.strip()))


def _join_title_lines(lines) -> list:
    """CAD exports often split a title into pieces ('ELEVATION /' + 'INT. ATTORNEY S.O. 3110A'): join the pieces
    that continue a title line on the same baseline."""
    used, out = set(), []
    for i, ln in enumerate(lines):
        if not TITLE_RE.search(ln["t"]):
            continue
        t, bb = ln["t"].rstrip(), list(ln["bbox"])
        h = max(bb[3] - bb[1], 4)
        while True:
            nxt = [j for j, o in enumerate(lines) if j != i and j not in used and not TITLE_RE.search(o["t"])
                   and abs(o["bbox"][3] - bb[3]) < 0.45 * h and -0.5 * h <= o["bbox"][0] - bb[2] < 2.5 * h]
            if not nxt:
                break
            j = min(nxt, key=lambda j: lines[j]["bbox"][0])
            used.add(j)
            o = lines[j]
            t = t + " " + o["t"].strip()
            bb = [bb[0], min(bb[1], o["bbox"][1]), max(bb[2], o["bbox"][2]), max(bb[3], o["bbox"][3])]
        used.add(i)
        out.append({"t": t, "bbox": bb})
    return out + [ln for k, ln in enumerate(lines) if k not in used]


def find_titles(lines, toks) -> list:
    titles = []
    for ln in _join_title_lines(lines):
        txt = ln["t"].strip()
        m0 = TITLE_RE.search(txt)
        if not m0:
            continue
        if not re.fullmatch(r"\s*\(?\d{0,3}\)?[\s.]*", txt[:m0.start()]):
            continue                                               # 'SEE ELEVATION 4' - a reference, not a title
        after = txt[m0.end():].lstrip()
        if after and not re.match(r"[/#:\-–]", after):
            continue                                               # 'ELEVATION 26 & 27 WILL ...' - a note, not a title
        if re.search(r"[a-z]{3,}", txt) and not re.search(r"ELEV(?:ATION|\.)?\s*[/#:\-]", txt):
            continue
        tu = txt.upper()
        m = re.search(r"#\s*([A-Z0-9][A-Z0-9.\-]*)", tu)
        room = m.group(1) if m else ""
        m = re.search(r"ELEV(?:ATION|\.)?\s*[/:\-]?\s*(.*?)(?:#|$)", txt)
        name = m.group(1).strip(" -/") if m else ""
        if not room:
            m = re.search(r"\b([A-Z]?\d{2,5}[A-Z]{0,2})\s*$", name.upper())
            room = m.group(1) if m else ""
        x0, y0, x1, y1 = ln["bbox"]
        h = max(y1 - y0, 5)
        elev, ebox = "", None
        lead = re.match(r"^\s*\(?(\d{1,3})\)?\s*(?=ELEV)", txt)
        if lead:                                     # circled number merged into the title line ('10ELEVATION / ...')
            elev, ebox = lead.group(1), [x0, y0, x0 + 1, y1]
            frac = m0.start() / max(len(txt), 1)
            x0 = x0 + (x1 - x0) * frac
        for t in ([] if lead else toks):
            if _title_number_ok(t) and t.bbox[2] <= x0 + 2 and x0 - t.bbox[2] < 8 * h \
                    and abs(t.cy - (y0 + y1) / 2) < 2.5 * h:
                if ebox is None or t.bbox[2] > ebox[2]:
                    elev, ebox = t.t.strip("() "), t.bbox
        titles.append({"text": re.sub(r"^\s*\(?\d{1,3}\)?\s*(?=ELEV)", "", txt), "room": room, "name": name,
                       "elev": elev, "bbox": [x0, y0, x1, y1], "xstart": (ebox[0] if ebox else x0) - 25})
    titles.sort(key=lambda t: (t["bbox"][1], t["bbox"][0]))
    out = []
    for t in titles:                              # one title split over several line objects
        if out and abs(out[-1]["bbox"][1] - t["bbox"][1]) < 4 and abs(out[-1]["bbox"][0] - t["bbox"][0]) < 20:
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------------------------------------- pairing
def align_pairs(ups, los, gap):
    """Optimal monotone alignment of two x-sorted lists (Needleman-Wunsch, cost = |dx|, gap = `gap`).
    Returns [(u|None, l|None)] in x order.  Handles a missing upper or lower without shifting the rest."""
    n, m = len(ups), len(los)
    INF = float("inf")
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    B = [[None] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if i and j:
                dx = abs(ups[i - 1].cx - los[j - 1].cx)
                c = D[i - 1][j - 1] + (dx if dx <= 2 * gap else INF)
                if c < D[i][j]:
                    D[i][j], B[i][j] = c, "m"
            if i and D[i - 1][j] + gap < D[i][j]:
                D[i][j], B[i][j] = D[i - 1][j] + gap, "u"
            if j and D[i][j - 1] + gap < D[i][j]:
                D[i][j], B[i][j] = D[i][j - 1] + gap, "l"
    out, i, j = [], n, m
    while i or j:
        mv = B[i][j]
        if mv == "m":
            out.append((ups[i - 1], los[j - 1])); i -= 1; j -= 1
        elif mv == "u":
            out.append((ups[i - 1], None)); i -= 1
        else:
            out.append((None, los[j - 1])); j -= 1
    return out[::-1]


def _box_union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _code_of(t):
    c = _base_clean(t.t).upper().strip(" .,").replace("‐", "-").replace("‑", "-")
    if not CODE_RE.match(c):
        return None
    return c if "-" in c or c in BARE_CODES else None


def is_door(code: str) -> bool:
    return bool(DOOR_RE.match(code or "")) or (code or "").startswith(DOOR_PREFIX)




# ---------------------------------------------------------------------------------------------- page
NOTE_RE = re.compile(r"^(DELETED?|N\.?I\.?C\.?|VOID|REMOVED|CANCELL?ED)$", re.I)
EDGE_SYMBOLS = {"℄", "CL", "C/L", "Ȼ"}


def _is_edge_word(t) -> bool:
    w = t.t.strip().upper().strip(".:,")
    return w in EDGE_WORDS or w in EDGE_SYMBOLS


def other_value(text: str):
    """Any readable length (widths, thicknesses) - shown for click-to-fill, never used automatically."""
    s = _clean_value_text(text)
    if not re.search(r"\d", s) or not (DIM_RE.match(s) or re.fullmatch(r"\d{2,3}(\s\d{1,2}/\d{1,2})?", s)):
        return None
    v = parse_length(s).get("value")
    return v if v is not None and 1 <= v <= 400 else None


def extract_page(pd: PageData, pno: int) -> dict:
    toks = merge_value_tokens(pd.tokens)
    words = []
    for t in toks:
        t.v = None                                                 # type: ignore[attr-defined]
        t.edge = _is_edge_word(t)                                  # type: ignore[attr-defined]
        w = t.t.strip()
        if WORD_RE.match(w) and w.upper().strip(".:") not in VALUE_WORDS:
            words.append(t)
    dims_all, others = [], []
    for t in toks:
        v = dim_value(t.t, strict=not (t.src == "ocr" or coloured(t)), glued=coloured(t))
        if v is not None and not _label_value(t, words):
            t.v = v
            dims_all.append(t)
        elif coloured(t) or t.src != "text":
            ov = other_value(t.t)
            if ov is not None:
                others.append((t, ov))
    res = {"page": pno, "method": pd.method, "elevations": [], "notes": [],
           "candidates": [{"v": to_fraction_str(d.v), "raw": d.t, "bbox": [round(c, 2) for c in d.bbox],
                           "ink": coloured(d)} for d in dims_all]
           + [{"v": to_fraction_str(v), "raw": t.t, "bbox": [round(c, 2) for c in t.bbox], "ink": False, "other": True}
              for t, v in others]}
    titles = find_titles(pd.lines, toks)
    if not titles:
        res["notes"].append("No 'ELEVATION' titles on this page")
        return res
    rows = []
    for t in sorted(titles, key=lambda t: t["bbox"][1]):
        if rows and abs(rows[-1][0]["bbox"][1] - t["bbox"][1]) < 40:
            rows[-1].append(t)
        else:
            rows.append([t])
    for r in rows:
        r.sort(key=lambda t: t["xstart"])
    row_tops = [min(t["bbox"][1] for t in r) for r in rows]

    def owner(tok):
        for ri, r in enumerate(rows):
            if tok.cy < row_tops[ri] - 1:
                if ri > 0 and tok.cy <= row_tops[ri - 1] + 25:
                    return None
                cands = [t for t in r if t["xstart"] <= tok.cx + 5]
                return cands[-1] if cands else r[0]
        return None

    groups = {id(t): [] for t in titles}
    for tk in toks:
        o = owner(tk)
        if o is not None:
            groups[id(o)].append(tk)

    def extent(t):
        """x-extent of an elevation's frame: its glass codes and edge labels (DW / FAL / CL)."""
        ks = [k for k in groups[id(t)] if _code_of(k) or (k.edge and k.cy < t["bbox"][1])]
        return (min(k.bbox[0] for k in ks), max(k.bbox[2] for k in ks)) if ks else None

    # column boundaries: middle of the gap between neighbouring elevations' glass codes
    bounds_by_row = []
    for r in rows:
        if len(r) < 2:
            bounds_by_row.append([])
            continue
        ext = []
        for t in r:
            cs = [k for k in groups[id(t)] if _code_of(k)]
            ext.append((min(k.bbox[0] for k in cs), max(k.bbox[2] for k in cs)) if cs else None)
        bounds = []
        for i in range(len(r) - 1):
            a, b = ext[i], ext[i + 1]
            bounds.append((a[1] + b[0]) / 2 if a and b and a[1] < b[0] else r[i + 1]["xstart"])
        bounds_by_row.append(bounds)
        pool = [tk for t in r for tk in groups[id(t)]]
        for t in r:
            groups[id(t)] = []
        for tk in pool:
            ci = sum(1 for bd in bounds if tk.cx >= bd)
            groups[id(r[ci])].append(tk)
        # values between two frames go to the neighbour that has no values of its own (side views often
        # have their readings written beside the frame, nearer the next elevation)
        for i in range(len(r) - 1):
            A, B = r[i], r[i + 1]
            eA, eB = extent(A), extent(B)
            if not eA or not eB:
                continue
            gap = [k for k in groups[id(A)] + groups[id(B)] if k.v is not None and eA[1] + 15 < k.cx < eB[0] - 15]
            own = lambda T: [k for k in groups[id(T)] if k.v is not None and k not in gap]  # noqa: E731
            if gap and not own(A):
                groups[id(B)] = [k for k in groups[id(B)] if k not in gap]
                groups[id(A)] = [k for k in groups[id(A)] if k not in gap] + gap
            elif gap and not own(B):
                groups[id(A)] = [k for k in groups[id(A)] if k not in gap]
                groups[id(B)] = [k for k in groups[id(B)] if k not in gap] + gap
    bm_labels = _standalone_bm(toks, dims_all)
    row_els = []
    for ri, r in enumerate(rows):
        els = []
        for ci, t in enumerate(r):
            bnd = bounds_by_row[ri]
            xa = bnd[ci - 1] if ci > 0 and bnd else (r[ci]["xstart"] if ci > 0 else 0)
            xb = bnd[ci] if ci < len(r) - 1 and bnd else pd.width
            # readings written UNDER the title (some projects put the lower benchmarks there)
            th = max(t["bbox"][3] - t["bbox"][1], 6)
            ylim = t["bbox"][3] + 9 * th
            if ri + 1 < len(rows):
                ylim = min(ylim, row_tops[ri + 1] - 60)
            for y, lx0, lx1, _d in pd.hlines:
                if t["bbox"][3] + 2 < y < ylim and lx0 <= (xa + xb) / 2 <= lx1 and lx1 - lx0 > 0.5 * pd.width:
                    ylim = y
            below = [d for d in dims_all if xa <= d.cx < xb and t["bbox"][3] - 1 < d.cy < ylim]
            el = build_elevation(t, groups[id(t)], below, bm_labels, row_tops[ri],
                                 row_tops[ri - 1] + 25 if ri else 0, pd.hlines, pd.vlines, (xa, xb), extent(t))
            el["page"] = pno
            if pd.method == "ocr" and el["panels"]:
                el["notes"].insert(0, "Scanned page read by OCR - check every value against the drawing")
            if any(NOTE_RE.match(k.t.strip()) for k in groups[id(t)]):
                el["notes"].append("'Deleted' / 'N.I.C.' is written on this elevation - check it is still in scope")
            if el["panels"]:
                els.append(el)
            else:
                res["notes"].append(f"Ignored '{t['text'][:60]}' - no benchmark values next to it")
                if any(_code_of(k) for k in groups[id(t)]):             # glass tags but no values: values are graphics?
                    res.setdefault("unread", []).append([xa, row_tops[ri - 1] + 25 if ri else 0, xb, ylim])
        row_els.append(els)
        res["elevations"] += els
    _inherit_uppers(res["elevations"])
    return res


def _inherit_uppers(els):
    """An elevation with no upper reading takes the (uniform) upper of a neighbour on the same BM line."""
    for e in els:
        if not e["points"] or any(p["u"] for p in e["points"]):
            continue
        donors = []
        for o in els:
            if o is e or o["bm_y"] is None or e["bm_y"] is None or abs(o["bm_y"] - e["bm_y"]) > 8:
                continue
            us = {p["u"] for p in o["points"] if p["u"]}
            if len(us) == 1:
                donors.append((abs(o["title_box"][0] - e["title_box"][0]), us.pop(), o["elev"]))
        if not donors:
            continue
        _, u, src = min(donors)
        for p in e["points"]:
            p["u"] = u
        for q in e["panels"]:
            q["L"]["u"] = u
            q["R"]["u"] = u
        e["notes"] = [n for n in e["notes"] if "missing a value" not in n]
        e["notes"].append(f"No upper written here - upper {u} taken from elevation {src or '?'} on the same BM line, "
                          f"check it")


def _standalone_bm(toks, dims):
    """'BM' labels that name the benchmark LINE - not the 'BM' prefix of a value label ('BM 48FT')."""
    out = []
    for t in toks:
        if t.t.upper().replace(".", "").strip(":") != "BM":
            continue
        h = _h(t)
        if any(abs(d.cy - t.cy) < 0.7 * h and -0.5 * h < d.bbox[0] - t.bbox[2] < 3 * h for d in dims):
            continue
        out.append(t)
    return out


def _choose_bm(dims, lines, labels, x0, x1, top, bottom):
    """The horizontal line / label that splits this elevation's values into an upper and a lower band."""
    cands = []
    for y, lx0, lx1, dashed in lines:
        if top < y < bottom and lx0 <= x1 and lx1 >= x0:
            near = any(abs(b.cy - y) < 14 for b in labels)
            cands.append((y, dashed, near, lx1 - lx0))
    for b in labels:
        if top < b.cy < bottom and not any(abs(c[0] - b.cy) < 14 for c in cands):
            cands.append((b.cy, False, True, 0))
    best, best_key = None, None
    for y, dashed, near, length in cands:
        up = sum(1 for d in dims if d.cy < y - 1)
        dn = sum(1 for d in dims if d.cy > y + 1)
        key = (up > 0 and dn > 0, near, dashed, min(up, dn), length)
        if best_key is None or key > best_key:
            best, best_key = y, key
    if best is not None and (best_key[0] or len(dims) < 2 or best_key[1]):
        return best, None
    if len(dims) >= 2:
        ys = sorted(d.cy for d in dims)
        gaps = [(ys[i + 1] - ys[i], (ys[i + 1] + ys[i]) / 2) for i in range(len(ys) - 1)]
        g, y = max(gaps)
        if g > 3 * median(_h(d) for d in dims):
            return y, "No benchmark line splits the values - benchmark estimated from the gap between them"
    if best is not None:
        return best, None
    return None, None


def _trim_band(vals, target, dist, gap):
    """Keep the band nearest the BM line; drop readings beyond the first big gap, never below `target`."""
    if len(vals) <= max(target, 1):
        return list(vals), []
    vs = sorted(vals, key=dist)
    ds = [dist(v) for v in vs]
    for i in range(max(target, 1), len(vs)):
        if ds[i] - ds[i - 1] > gap:
            return vs[:i], vs[i:]
    return vs, []


def _consistent(vals, tol=6.0):
    if len(vals) < 3:
        return vals, []
    med = median(d.v for d in vals)
    keep = [d for d in vals if abs(d.v - med) <= tol]
    return (keep, [d for d in vals if abs(d.v - med) > tol]) if len(keep) >= 2 else (vals, [])


def _in_sentence(c, words) -> bool:
    """A code-like word inside a note ('... RECEIVE A FPD DUE TO ...') is not a glass/door code."""
    h = _h(c)
    for w in words:
        if w is c or not _horizontal(w) or not _horizontal(c) or abs(w.cy - c.cy) > 0.5 * h:
            continue
        if max(w.bbox[0] - c.bbox[2], c.bbox[0] - w.bbox[2]) < 1.2 * h and not _code_of(w) and \
                w.t.strip().upper().strip(".:,") not in ("BY", "OTHERS"):
            return True
    return False


def _closest_band(vals, dist, gap):
    vs = sorted(vals, key=dist)
    out = vs[:1]
    for a, b in zip(vs, vs[1:]):
        if dist(b) - dist(a) > gap:
            break
        out.append(b)
    return out


def _find_tags(toks, codes, title_top, lo_lim):
    """Glass code + tag(s) ('OLIGL-12' / '3110A-B', 'FPD-DGL' / '720-A' / '720-AA', 'GL-12' / 'BY OTHERS')."""
    tags_used, tags = set(), []
    for c in codes:
        code = _code_of(c)
        near = []
        for i, t in enumerate(toks):
            tt = t.t.strip(" .,_()[]")
            if t is c or i in tags_used or _horizontal(t) != _horizontal(c):
                continue
            d = math.hypot(t.cx - c.cx, t.cy - c.cy)
            if d < 7 * max(c.size, 4):
                near.append((d, i, t, tt))
        near.sort(key=lambda n: n[0])
        tag_toks = [n for n in near if n[0] < 4.5 * max(c.size, 4) and TAG_RE.match(n[3]) and '"' not in n[2].t
                    and not (getattr(n[2], "v", None) is not None and coloured(n[2]))]
        others = any(n[3].upper() == "OTHERS" for n in near) and any(n[3].upper() == "BY" for n in near)
        picked = tag_toks[:1]
        if picked:                                                  # second lite of the same panel: 720-A / 720-AA
            f = picked[0][2]
            for n in tag_toks[1:]:
                if math.hypot(n[2].cx - f.cx, n[2].cy - f.cy) < 2.4 * max(c.size, 4) and \
                        n[3].startswith(picked[0][3].split("-")[0]):
                    picked.append(n)
                    break
        for n in picked:
            tags_used.add(n[1])
        tag = " / ".join(n[3] for n in picked)
        if is_door(code):
            kind = "Door"
        elif others:
            kind, tag = "By others", tag or "BY OTHERS"
        else:
            kind = "Fixed"
        bb = _box_union([c.bbox] + [n[2].bbox for n in picked])
        tags.append({"code": code, "tag": tag, "kind": kind, "box": bb, "x": (bb[0] + bb[2]) / 2,
                     "y": (bb[1] + bb[3]) / 2})
    tags.sort(key=lambda t: (t["x"], t["y"]))
    # stacked panels (transoms / D1-D2-D3 lites) share the same pair of edges
    stacks = []
    for t in tags:
        if stacks and abs(stacks[-1][0]["x"] - t["x"]) < 12:
            stacks[-1].append(t)
        else:
            stacks.append([t])
    for st in stacks:
        st.sort(key=lambda t: t["y"])
    return tags, stacks, {id(toks[i]) for i in tags_used}


def _frame_edges(vlines, x0, x1, bm_y, stacks, top, bottom):
    """x of every frame edge / mullion of this elevation (long vertical lines crossing the BM level, inside the
    elevation - page borders and title-block lines run past the title and are not frame edges)."""
    if not stacks:
        return []
    sx = [s[0]["x"] for s in stacks]
    lo, hi = min(sx) - 160, max(sx) + 160
    cand = [v for v in vlines if x0 - 5 <= v[0] <= x1 + 5 and lo <= v[0] <= hi and v[1] - 5 <= bm_y <= v[2] + 5
            and v[1] >= top - 5 and v[2] <= bottom + 5]
    if not cand:
        return []
    lmax = max(v[2] - v[1] for v in cand)
    xs = sorted(v[0] for v in cand if v[2] - v[1] >= 0.55 * lmax)
    edges = []
    for x in xs:
        if edges and x - edges[-1][-1] < 5:
            edges[-1].append(x)
        else:
            edges.append([x])
    return [sum(e) / len(e) for e in edges]


def _snap(values, edges, tol):
    """Each reading goes to its nearest free frame edge (within tol)."""
    pairs = sorted((abs(d.cx - e), di, ei) for di, d in enumerate(values) for ei, e in enumerate(edges))
    out, used_d = {}, set()
    for dist, di, ei in pairs:
        if dist > tol or di in used_d or ei in out:
            continue
        out[ei] = values[di]
        used_d.add(di)
    return out


def build_elevation(title, toks, below, bm_labels, title_top, lo_lim, hlines, vlines, xspan, frame=None) -> dict:
    el = {"elev": title["elev"], "room": title["room"], "name": title["name"], "title": title["text"],
          "title_box": title["bbox"], "panels": [], "points": [], "notes": [], "bbox": None, "bm_y": None}
    x0, x1 = xspan

    def pick(ds):
        return [d for d in ds if coloured(d)] or ds
    dims = pick([t for t in toks if getattr(t, "v", None) is not None and lo_lim < t.cy < title_top])
    below_d = pick([t for t in below if getattr(t, "v", None) is not None])
    if not dims and not below_d:
        return el

    # --- benchmark line -------------------------------------------------------------------
    edges_all = [t for t in toks if getattr(t, "edge", False)]
    bm_y, note = _choose_bm(dims + below_d, hlines, bm_labels, x0, x1, lo_lim, title_top)
    if bm_y is None:
        return el
    if note:
        el["notes"].append(note)
    el["bm_y"] = round(bm_y, 2)
    hmed = median(_h(d) for d in dims + below_d)

    up_c = [d for d in dims if d.cy <= bm_y + 0.25 * d.size]
    lo_c = [d for d in dims if d.cy > bm_y + 0.25 * d.size]
    below_used = False
    if not lo_c and below_d:
        lo_c, below_used = list(below_d), True

    # --- value window: below the edge-label row (DW / FAL / CL) ------------------------------
    G = max(3.5 * hmed, 28)
    edge_ab = [e for e in edges_all if e.cy < bm_y - 0.5 * _h(e) and e.cy > lo_lim]
    if edge_ab:
        top_cut = max(e.bbox[3] for e in edge_ab) + 0.5
    else:
        band = _closest_band(up_c, lambda d: bm_y - d.cy, G) if up_c else []
        top_cut = min((d.cy for d in band), default=bm_y) - 1 if band else lo_lim
    ups = [d for d in up_c if d.cy > top_cut]
    if not ups and up_c:                                            # upper written above the edge labels
        lmed = median(d.v for d in lo_c) if lo_c else None
        cand = [d for d in up_c if lmed is None or abs(d.v - lmed) > 4]   # never a door-swing / plan lower reading
        ups = _closest_band(cand, lambda d: bm_y - d.cy, G) if cand else []
    los = [d for d in lo_c if d.cy > top_cut]
    G2 = max(2.5 * hmed, 18)
    ups, cut_u = _trim_band(ups, len(los), lambda d: bm_y - d.cy, G2)
    los, cut_l = _trim_band(los, len(ups), lambda d: d.cy - bm_y, G2)
    rejected = {id(d) for d in cut_u + cut_l}
    ups.sort(key=lambda d: d.cx)
    los.sort(key=lambda d: d.cx)
    # one elevation's uppers (ceiling) and lowers (floor) agree within an inch or two: a reading far from the
    # rest of its row is a bulkhead / door height / thickness written nearby, not a benchmark
    ups, out_u = _consistent(ups)
    los, out_l = _consistent(los)
    rejected |= {id(d) for d in out_u + out_l}
    win = ups + los

    # --- tags ------------------------------------------------------------------------------
    words = [t for t in toks if WORD_RE.match(t.t.strip()) or re.fullmatch(r"[A-Za-z]", t.t.strip())]
    codes = [t for t in toks if _code_of(t) and lo_lim < t.cy < title_top and not _in_sentence(t, words)]
    tags, stacks, tag_toks = _find_tags(toks, codes, title_top, lo_lim)

    # --- points ----------------------------------------------------------------------------
    xs = sorted(d.cx for d in win)
    spacing = sorted(b - a for a, b in zip(xs, xs[1:]) if b - a > 5)
    gap = max(25.0, (spacing[len(spacing) // 2] * 0.6) if spacing else 45.0)
    single_u = len(ups) == 1 and len(los) >= 2
    edges = _frame_edges(vlines, x0, x1, bm_y, stacks, lo_lim, title_top) if (below_used or single_u) else []
    if single_u:
        el["notes"].append(f"One upper ({to_fraction_str(ups[0].v)}) written for the whole elevation - used at every edge")
    # uppers written at only some edges, all the same value (44" at both ends) -> that value at every edge
    same_u = (not single_u and not below_used and 2 <= len(ups) < len(los)
              and max(u.v for u in ups) - min(u.v for u in ups) < 1 / 64)
    extra_u = ups[1:] if same_u else []
    if same_u:
        el["notes"].append(f"Upper {to_fraction_str(ups[0].v)} written at {len(ups)} of {len(los)} edges, all the "
                           f"same - used at every edge")
    if below_used:
        el["notes"].append("Lower values are written under the title - matched to the nearest frame edges, check them")
    points = []
    if len(edges) >= 2:
        # snap the readings to the frame edges / mullions
        sp = sorted(b - a for a, b in zip(edges, edges[1:]))
        tol = max(35.0, 0.8 * sp[len(sp) // 2])
        lmap = _snap(los, edges, tol)
        umap = {i: ups[0] for i in range(len(edges))} if single_u else _snap(ups, edges, tol)
        for i in range(len(edges) - 1):                             # narrow sidelite: both edges share a reading
            if edges[i + 1] - edges[i] < 25:
                for mp in (lmap, umap):
                    if i in mp and i + 1 not in mp:
                        mp[i + 1] = mp[i]
                    elif i + 1 in mp and i not in mp:
                        mp[i] = mp[i + 1]
        filled, averaged = 0, []
        if len(stacks) == 1 and len(edges) >= 2:                   # side view: one panel, values at one edge
            for mp in (lmap, umap):
                if mp and len(mp) < len(edges):
                    src = next(iter(mp.values()))
                    for i in range(len(edges)):
                        mp.setdefault(i, src)
        else:
            # an unmarked edge BETWEEN two marked ones = average of those two, floored to 1/16 like the team's
            # judgement average (e.g. 360-C lower = (L2 + L4) / 2); an unmarked END edge takes the nearest marked one
            for name, mp in (("L", lmap), ("U", umap)):
                if not mp:
                    continue
                real = dict(mp)
                for i in range(len(edges)):
                    if i in mp:
                        continue
                    left = [k for k in real if k < i]
                    right = [k for k in real if k > i]
                    if left and right:
                        a_, b_ = real[max(left)], real[min(right)]
                        v = math.floor((a_.v + b_.v) / 2 * 16 + 1e-6) / 16
                        mp[i] = SimpleNamespace(v=v, t=f"({to_fraction_str(a_.v)} + {to_fraction_str(b_.v)}) / 2",
                                                bbox=None, cx=edges[i], avg=True)
                        averaged.append(f"{name}{i + 1} = ({to_fraction_str(a_.v)} + {to_fraction_str(b_.v)}) / 2 = "
                                        f"{to_fraction_str(v)}")
                    else:
                        j = min(real, key=lambda k: (abs(edges[k] - edges[i]), k))
                        mp[i] = real[j]
                        filled += 1
        if averaged:
            el["notes"].append(f"{len(averaged)} edge value(s) not written on the sheet - average of the edges either "
                               f"side: " + "; ".join(averaged) + " - check them")
        if filled:
            el["notes"].append(f"{filled} end edge value(s) not written on the sheet - taken from the nearest edge, "
                               "check them")
        for i, ex in enumerate(edges):
            u, l = umap.get(i), lmap.get(i)
            points.append({"x": ex, "u": to_fraction_str(u.v) if u else "", "l": to_fraction_str(l.v) if l else "",
                           "u_raw": u.t if u else "", "l_raw": l.t if l else "",
                           "ubox": u.bbox if u else None, "lbox": l.bbox if l else None,
                           "u_avg": bool(getattr(u, "avg", False)), "l_avg": bool(getattr(l, "avg", False))})
        used = {id(d) for d in list(lmap.values()) + list(umap.values())}
        mode = "edges"
    else:
        if single_u or same_u:
            pairs = [(ups[0], l) for l in los]
        else:
            pairs = align_pairs(ups, los, gap)
        for u, l in pairs:
            points.append({"x": (l or u).cx if (single_u or same_u) else (u or l).cx,
                           "u": to_fraction_str(u.v) if u else "", "l": to_fraction_str(l.v) if l else "",
                           "u_raw": u.t if u else "", "l_raw": l.t if l else "",
                           "ubox": u.bbox if u else None, "lbox": l.bbox if l else None})
        used = {id(u) for u, _ in pairs if u} | {id(l) for _, l in pairs if l} | {id(u) for u in extra_u}
        mode = "points"

    # --- recover: an edge missing a value takes the nearest unused reading in that band -----------
    if mode == "points":
        spare = []
        for t in toks:
            if id(t) in used or id(t) in tag_toks or id(t) in rejected or _code_of(t) or not (top_cut < t.cy < title_top):
                continue
            v = getattr(t, "v", None)
            if v is None:
                v = dim_value(t.t, strict=False)
                if v is None or any(math.hypot(t.cx - c.cx, t.cy - c.cy) < 4.5 * max(c.size, 4) for c in codes):
                    continue
            spare.append((t, v))
        for p in points:
            for side in ("u", "l"):
                if p[side]:
                    continue
                cand = [(abs(t.cx - p["x"]), t, v) for t, v in spare
                        if abs(t.cx - p["x"]) < 0.9 * gap and (t.cy < bm_y) == (side == "u") and id(t) not in used]
                if cand:
                    _, t, v = min(cand, key=lambda c: c[0])
                    used.add(id(t))
                    p[side], p[side + "_raw"], p[side + "box"] = to_fraction_str(v), t.t, t.bbox
                    el["notes"].append(f"{'Upper' if side == 'u' else 'Lower'} {to_fraction_str(v)} at an edge was "
                                       f"filled from a nearby value ('{t.t}') - check it")
        # uppers given at some edges only, with different values: a blank edge between two given ones = their
        # average (floored to 1/16, as for lowers), a blank end edge = the nearest given one
        given = [i for i, p in enumerate(points) if p["u"]]
        if given and len(given) < len(points) and len(ups) < len(los):
            vals = {i: parse_length(points[i]["u"]).get("value") for i in given}
            done = []
            for i, p in enumerate(points):
                if p["u"] or not p["l"]:
                    continue
                lft = [k for k in given if k < i and vals[k] is not None]
                rgt = [k for k in given if k > i and vals[k] is not None]
                if lft and rgt:
                    a_, b_ = vals[max(lft)], vals[min(rgt)]
                    v = math.floor((a_ + b_) / 2 * 16 + 1e-6) / 16
                    p["u"], p["u_raw"] = to_fraction_str(v), f"({to_fraction_str(a_)} + {to_fraction_str(b_)}) / 2"
                    done.append(f"U{i + 1} = ({to_fraction_str(a_)} + {to_fraction_str(b_)}) / 2 = {to_fraction_str(v)}")
                elif lft or rgt:
                    k = max(lft) if lft else min(rgt)
                    p["u"], p["u_raw"] = points[k]["u"], points[k].get("u_raw", "")
                    done.append(f"U{i + 1} = {points[k]['u']} (nearest given)")
            if done:
                el["notes"].append(f"Upper not written at {len(done)} edge(s) - " + "; ".join(done) + " - check them")
        # a lone reading far from the rest of its row (thickness, bulkhead height ...) is not an edge
        for side in ("u", "l"):
            other = "l" if side == "u" else "u"
            for p in list(points):
                if p[side] and not p[other] and len(points) > 1:
                    rest = [parse_length(q[side]).get("value") for q in points if q is not p and q[side]]
                    v = parse_length(p[side]).get("value")
                    if rest and v is not None and abs(v - median(rest)) > 6:
                        points.remove(p)
        # two tags inside one span (door + narrow sidelite): split it at the mullion line between them
        if len(points) >= 2 and len(stacks) > len(points) - 1:
            for a_st, b_st in zip(stacks, stacks[1:]):
                ax = sum(t["x"] for t in a_st) / len(a_st)
                bx = sum(t["x"] for t in b_st) / len(b_st)
                xs_pts = [p["x"] for p in points]
                if any(ax < x < bx for x in xs_pts) or not (xs_pts[0] - 15 <= ax and bx <= xs_pts[-1] + 15):
                    continue
                lines = [v for v in vlines if ax + 3 < v[0] < bx - 3 and v[1] - 5 <= bm_y <= v[2] + 5
                         and v[1] >= lo_lim - 5 and v[2] <= title_top + 5]
                if not lines:
                    continue
                narrow = a_st if min(abs(ax - x) for x in xs_pts) < min(abs(bx - x) for x in xs_pts) else b_st
                nx = sum(t["x"] for t in narrow) / len(narrow)
                mx = min(lines, key=lambda v: abs(v[0] - nx))[0]          # mullion next to the narrow panel
                src = min(points, key=lambda p: abs(p["x"] - mx))
                newp = dict(src, x=mx)
                points.append(newp)
                points.sort(key=lambda p: p["x"])
                el["notes"].append(f"No reading at the mullion between {a_st[0]['tag'] or a_st[0]['code']} and "
                                   f"{b_st[0]['tag'] or b_st[0]['code']} - values taken from the nearest edge, check them")
    el["points"] = points

    # --- panels ----------------------------------------------------------------------------
    def add(t, li, ri, pl, pr):
        exp = t["kind"] == "Fixed" if t else True
        el["panels"].append({"tag": t["tag"] if t else "", "code": t["code"] if t else "",
                             "kind": t["kind"] if t else ("No tag" if tags else "Fixed"),
                             "export": exp if t else not tags, "tag_box": t["box"] if t else None,
                             "L": {"u": pl["u"], "l": pl["l"]}, "R": {"u": pr["u"], "l": pr["l"]}, "pts": [li, ri]})

    n = max(len(points) - 1, 0)
    span_stack = [None] * n
    free = []
    if len(points) == 1 and len(stacks) == 1:                     # side view: one measured edge
        for t in stacks[0]:
            add(t, 0, 0, points[0], points[0])
        el["notes"].append("One measured edge only (side view) - the same values are used for both edges")
    elif mode == "edges":
        for st in stacks:
            sx = sum(t["x"] for t in st) / len(st)
            li = max((i for i, p in enumerate(points) if p["x"] < sx), default=None)
            ri = min((i for i, p in enumerate(points) if p["x"] > sx), default=None)
            if li is None or ri is None:
                free += st
                continue
            for t in st:
                add(t, li, ri, points[li], points[ri])
        nl = sum(1 for p in points if p["l"])
        if nl < len(los):
            el["notes"].append(f"{len(los) - nl} lower value(s) could not be matched to a frame edge")
    else:
        if frame and n and stacks:                                   # readings beside the frame (arrows / notes) that
            while len(points) > 2 and points[0]["x"] < frame[0] - 25 and \
                    not any(points[0]["x"] - 15 <= t["x"] <= points[1]["x"] for t in tags):
                points.pop(0)                                         # would only create an empty end span
            while len(points) > 2 and points[-1]["x"] > frame[1] + 25 and \
                    not any(points[-2]["x"] <= t["x"] <= points[-1]["x"] + 15 for t in tags):
                points.pop()
            n = len(points) - 1
            span_stack = [None] * n
            el["points"] = points
        if n and len(stacks) == n:
            span_stack = stacks[:]
        elif n:
            opts = []
            for si, st in enumerate(stacks):
                sx = sum(t["x"] for t in st) / len(st)
                for i in range(n):
                    a, b = points[i]["x"], points[i + 1]["x"]
                    if a - 15 <= sx <= b + 15:
                        opts.append((0 if a <= sx <= b else 1, abs(sx - (a + b) / 2) / max(b - a, 1), si, i))
            taken = set()
            for _, _, si, i in sorted(opts):
                if si not in taken and span_stack[i] is None:
                    span_stack[i] = stacks[si]
                    taken.add(si)
            free = [t for si, st in enumerate(stacks) if si not in taken for t in st]
            untagged = sum(1 for s_ in span_stack if s_ is None)
            if stacks and untagged:
                el["notes"].append(f"{untagged} span(s) between measured edges have no glass tag "
                                   f"(wall / existing condition) - listed, not exported")
        for i in range(n):
            st = span_stack[i]
            for t in (st or [None]):
                add(t, i, i + 1, points[i], points[i + 1])
    if free:
        el["notes"].append(f"{len(free)} glass tag(s) without measured edges: "
                           + ", ".join(t["tag"] or t["code"] for t in free))
    stacked = [st for st in stacks if len(st) > 1]
    if stacked:
        el["notes"].append("Stacked panels share the same edges: " + "; ".join(", ".join(t["tag"] or t["code"] for t in st)
                                                                          for st in stacked))
    nu, nl = sum(1 for p in points if p["u"]), sum(1 for p in points if p["l"])
    if points and (nu != len(points) or nl != len(points)) and mode == "points":
        el["notes"].append(f"{nu} upper vs {nl} lower values on {len(points)} edges - an edge is missing a value")
    boxes = [title["bbox"]] + [d.bbox for d in win] + [t["box"] for t in tags]
    el["bbox"] = [round(v, 2) for v in _box_union(boxes)]
    el["bbox"] = [el["bbox"][0] - 6, el["bbox"][1] - 6, el["bbox"][2] + 6, el["bbox"][3] + 6]
    return el
