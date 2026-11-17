"""Inch / fraction parsing for Muraflex FM notation.

Handles 57"1/4, 49"15/16, 52 5/16, 52-5/16, unicode fractions (½ ¼ ¾ ⅛ …), feet-inches (8'-6 1/2"),
FM misreads (57'5/16 -> 57 5/16) and OCR-flattened stacked fractions (3614 -> 36 1/4, 524 -> 52 1/4).
Every parse returns the chosen value plus the alternative readings, so callers never have to guess silently.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction

RULES = {"ROUND_DEN": 16}
EPS = 1e-6

VALID_DEN = (2, 4, 8, 16, 32, 64)
_UNI_FRAC = {"\u00bd": " 1/2", "\u00bc": " 1/4", "\u00be": " 3/4", "\u215b": " 1/8", "\u215c": " 3/8",
             "\u215d": " 5/8", "\u215e": " 7/8", "\u2153": " 1/3", "\u2154": " 2/3", "\u2155": " 1/5"}
_SUPSUB = {}
for _i, (_sup, _sub) in enumerate(zip("\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079",
                                      "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089")):
    _SUPSUB[ord(_sup)] = str(_i)
    _SUPSUB[ord(_sub)] = str(_i)
_SUPSUB[ord("\u2044")] = "/"   # fraction slash
_SUPSUB[ord("\u2215")] = "/"   # division slash
_SUPSUB[ord("\u2212")] = "-"   # minus
_SUPSUB[ord("\u2013")] = "-"
_SUPSUB[ord("\u2014")] = "-"
_SUPSUB[ord("\u2010")] = "-"
_SUPSUB[ord("\u2011")] = "-"
_SUPSUB[ord("\u2032")] = "'"
_SUPSUB[ord("\u2033")] = '"'
_SUPSUB[ord("\u201c")] = '"'
_SUPSUB[ord("\u201d")] = '"'
_SUPSUB[ord("\u2019")] = "'"


def _valid_frac(n: int, d: int) -> bool:
    return d in VALID_DEN and 0 < n < d and n % 2 == 1


_SUP = "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"


def _base_clean(s: str) -> str:
    s = re.sub(f"(?<=[0-9])(?=[{_SUP}])", " ", s or "")          # 36¹⁄₁₆ -> 36 ¹⁄₁₆ (stacked fraction glyphs)
    s = s.translate(_SUPSUB)
    for k, v in _UNI_FRAC.items():
        s = s.replace(k, v)
    return s


def norm_len_text(s: str) -> str:
    """Strip words/symbols around a dimension, keep digits / . - ' and spaces."""
    s = _base_clean(s).upper()
    s = s.replace("''", '"')
    # O -> 0 / l,I -> 1 only when glued to digits (common OCR confusion)
    s = re.sub(r"(?<=\d)[O](?=\d|\b)", "0", s)
    s = re.sub(r"(?<=\d)[lI](?=\d)", "1", s)
    s = re.sub(r"(\d)\s*-\s*(\d+\s*/\s*\d+)", r"\1 \2", s)       # 52-5/16 -> 52 5/16
    s = re.sub(r"(?<![\d\s])'|(?<=\s)'", " ", s)                  # apostrophe = feet only right after digits
    s = re.sub(r"(\d)\s*'(?=\s*[A-Z])", r"\1 ", s)                 # 36' F.O -> stray tick, not feet
    s = re.sub(r"[^0-9./'\- ]", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)                       # stray dots (F.O., CONF.)
    s = re.sub(r"(?<=\d)\s*/\s*(?=\d)", "/", s)
    s = re.sub(r"(?<!\d)/|/(?!\d)", " ", s)
    s = re.sub(r"-(?![\d\s])", " ", s)
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def to_fraction_str(x: float | None, den: int = 64) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return ""
    neg = x < 0
    f = Fraction(abs(x)).limit_denominator(den)
    whole = f.numerator // f.denominator
    rem = f - whole
    if rem == 0:
        out = f"{whole}"
    elif whole == 0:
        out = f"{rem.numerator}/{rem.denominator}"
    else:
        out = f"{whole} {rem.numerator}/{rem.denominator}"
    return ("-" if neg and f != 0 else "") + out


def floor_den(x: float, den: int | None = None) -> float:
    den = den or RULES["ROUND_DEN"]
    return math.floor(x * den + EPS) / den


def _in(rng, v):
    return rng is None or (rng[0] - EPS <= v <= rng[1] + EPS)


def _stack_candidates(digits: str, den: int | None = None):
    """'3614' -> [(36.25,'36 1/4')], '525' + den 16 -> [(52+5/16, ...)]"""
    out = []
    if den is not None:
        for nlen in (1, 2):
            if len(digits) > nlen:
                w, n = digits[:-nlen], digits[-nlen:]
                if n.startswith("0"):
                    continue
                if _valid_frac(int(n), den):
                    out.append(int(w) + int(n) / den)
        return out
    for d in VALID_DEN:
        ds = str(d)
        for n in range(1, d, 2):
            suf = f"{n}{ds}"
            if digits.endswith(suf) and len(digits) > len(suf):
                out.append(int(digits[: -len(suf)]) + n / d)
    return out


def parse_length(text, rng=None) -> dict:
    """Parse a dimension in inches.  Returns {value, alts[], inferred, error, clean}."""
    res = {"value": None, "alts": [], "inferred": False, "error": None, "clean": ""}
    if text is None or str(text).strip() == "":
        res["error"] = "empty"
        return res
    if isinstance(text, (int, float)):
        res["value"] = float(text)
        return res
    s = norm_len_text(str(text))
    res["clean"] = s
    if not re.search(r"\d", s):
        res["error"] = "no number found"
        return res

    # candidate = (value, inferred, priority)  -> lower priority number wins inside the expected range
    def pick(cands):
        seen, uniq = set(), []
        for v, inf, pr in cands:
            key = round(v, 6)
            if key not in seen:
                seen.add(key)
                uniq.append((v, inf, pr))
        inr = [c for c in uniq if _in(rng, c[0])]
        pool = sorted(inr or uniq, key=lambda c: (c[2], c[1]))
        best = pool[0]
        res["value"] = best[0]
        res["inferred"] = bool(best[1] or len(inr) > 1)
        res["alts"] = [to_fraction_str(v) for v, _, _ in sorted(uniq, key=lambda c: (not _in(rng, c[0]), c[2]))
                       if abs(v - best[0]) > EPS][:6]
        if not inr and rng:
            res["error"] = f"outside expected range {rng[0]:g}-{rng[1]:g} in"
        return res

    def digit_cands(digits, pr_base=1):
        """Fraction glyphs that OCR flattened into plain digits."""
        out = [(int(digits), False, pr_base)]
        if len(digits) >= 3:
            for v in _stack_candidates(digits):                    # 3614 -> 36 1/4
                out.append((v, True, pr_base))
        for d in (2, 4, 8, 16):                                    # 524 -> 52 1/4 (the '1' read as fraction bar)
            ds = str(d)
            if digits.endswith(ds) and len(digits) > len(ds) + 1:
                out.append((int(digits[:-len(ds)]) + 1 / d, True, pr_base + 1))
        return out

    # feet-inches  8'-6 1/2"
    m = re.fullmatch(r"(-?)(\d+)'(\d+/\d+)", s.replace(" ", ""))
    if m and _valid_frac(*map(int, m.group(3).split("/"))):     # 57'5/16 on FM sheets = misread 57"5/16
        n_, d_ = map(int, m.group(3).split("/"))
        inch_v, feet_v = int(m.group(2)) + n_ / d_, int(m.group(2)) * 12 + n_ / d_
        sg = -1 if m.group(1) else 1
        return pick([(sg * inch_v, True, 0 if _in(rng, inch_v) or not _in(rng, feet_v) else 1),
                     (sg * feet_v, True, 1 if _in(rng, inch_v) or not _in(rng, feet_v) else 0)])
    m = re.fullmatch(r"(-?)(\d+)\s*'\s*-?\s*(.*?)\s*\"?", s)
    if m:
        rest = m.group(3).replace('"', "").strip()
        inch = parse_length(rest).get("value") if rest else 0.0
        if inch is None:
            inch = 0.0
        v = int(m.group(2)) * 12 + inch
        res["value"] = -v if m.group(1) else v
        return res
    s = s.replace("'", " ").strip()
    sign = -1 if s.startswith("-") else 1
    s = s.lstrip("-").strip()
    S_ = lambda cl: [(sign * v, inf, pr) for v, inf, pr in cl]

    m = re.fullmatch(r"(\d+) (\d+)/(\d+)", s)                    # 52 5/16
    if m:
        w, n, d = map(int, m.groups())
        if d == 0:
            res["error"] = "zero denominator"
            return res
        if n < d:
            return pick(S_([(w + n / d, not _valid_frac(n, d), 0)]))
        cands = []
        ns = m.group(2)                                            # 102 25/16 -> 102 5/16 (stray digit)
        for k in (1, 2):
            if len(ns) > k and _valid_frac(int(ns[-k:]), d):
                cands.append((w + int(ns[-k:]) / d, True, 0))
                cands.append((int(str(w) + ns[:-k]) + int(ns[-k:]) / d, True, 1))
        if not cands:
            res["error"] = f"fraction {n}/{d} >= 1"
            return res
        return pick(S_(cands))
    m = re.fullmatch(r"(\d+)/(\d+)", s)                          # 3/4  or  525/16
    if m:
        n, d = int(m.group(1)), int(m.group(2))
        if d == 0:
            res["error"] = "zero denominator"
            return res
        cands = []
        if n < d:
            cands.append((n / d, False, 0))
        stacks = _stack_candidates(m.group(1), d)
        cands += [(v, True, 0) for v in stacks]
        if n >= d and d in (2, 4, 8, 16) and not stacks:          # 72/2 -> 72 1/2 (OCR dropped the 1 of the glyph)
            cands.append((n + 1 / d, True, 1))
        if not cands:
            res["error"] = f"cannot read fraction '{s}'"
            return res
        return pick(S_(cands))
    m = re.fullmatch(r"(\d+) (\d+) (\d+)", s)                    # stacked CAD tokens 36 1 4
    if m:
        w, n, d = map(int, m.groups())
        if _valid_frac(n, d):
            return pick(S_([(w + n / d, False, 0)]))
    m = re.fullmatch(r"\d+\.\d+", s)                              # 102.25
    if m:
        return pick(S_([(float(s), False, 0)]))
    m = re.fullmatch(r"\d+", s)                                    # 102  /  3614  /  524
    if m:
        return pick(S_(digit_cands(s, 0)))
    # Several tokens in the box: individual numbers + glued readings (stacked fraction split by OCR)
    toks = re.findall(r"\d+ \d+/\d+|\d+/\d+|\d+(?:\.\d+)?", s)
    if toks:
        cands = []
        for x in toks:
            px = parse_length(x, rng)
            if px.get("value") is not None:
                cands.append((px["value"], True, 2))
                cands += [(v, True, 3) for v in (parse_length(a).get("value") for a in px["alts"]) if v is not None]
        digit_toks = [t for t in toks if re.fullmatch(r"\d+", t)]
        if len(digit_toks) >= 2:
            joined = [("".join(digit_toks[:2]), 0), ("".join(digit_toks), 1)]
            for js, pr in joined:
                for v, inf, _ in digit_cands(js):
                    if v != int(v):                                  # only the fractional readings
                        cands.append((v, True, pr))
            if len(digit_toks) >= 3 and _valid_frac(int(digit_toks[1]), int(digit_toks[2])):
                cands.append((int(digit_toks[0]) + int(digit_toks[1]) / int(digit_toks[2]), True, 0))
        if cands:
            r = pick(S_(cands))
            r["inferred"] = True
            r["error"] = r["error"] or ("several numbers in box" if len(toks) > 1 else None)
            return r
    res["error"] = f"cannot read '{s}'"
    return res


