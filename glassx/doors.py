"""Door module: builds the DOOR sheet entries from a page's extraction result.

Every door is measured at named points (team DOOR sheet):

  PIVOT door   (FPD, GPD, GHD ... - code ends in PD / HD / DO / GO, MFD)
      A  = hinge (pivot) side edge           upper / lower from the elevation
      B  = latch side edge                   upper / lower from the elevation
      C1 = door-swing plan reading at 45 deg open           upper = B's upper
      C2 = door-swing plan reading at 90 deg open (leaf tip) upper = A's upper
      The swing plan is a quarter arc around the pivot: the end on the wall line is the closed door (its reading
      repeats the latch-side lower), the other end is the open leaf (C2) and the middle of the arc is 45 deg (C1).
      Hinge side, in order of trust: the 'V' drawn on the door in elevation (apex on the hinge side), the pivot of the
      swing plan (above the hinge edge), the closed-door reading (= latch lower).

  SLIDING door (GSD, FSD, GPSD, GFSD, QSD, GSTD ... - code ends in SD / STD)
      A  = edge at the wall / end of the run (where the door closes)
      B  = inner edge (towards the panel the door slides over)
      C1 = far edge of that panel (end of travel)

  Diff  = TOTAL(A) - TOTAL(B)         FINAL = same judgement as the GLASS sheet on A and B

Checked against the team's DOOR example: 14075 MCC Washington sliding doors (elev 1: 54 / 54 1/8 / 54 1/8,
elev 2: 54 3/8 / 54 9/16 / 54 3/4) and 14002 Westbend pivot door 63 (A 50 / 57 3/8, B 49 15/16 / 57 3/8).
"""
from __future__ import annotations

import math
import re
from statistics import median

from .units import parse_length, to_fraction_str

SLIDING_RE = re.compile(r"^[A-Z]{0,3}(?:SD|STD)(?:[-‐‑]|$)")
POINTS = {"Pivot": ("A", "B", "C1", "C2"), "Sliding": ("A", "B", "C1")}


def door_type(code: str) -> str:
    return "Sliding" if SLIDING_RE.match((code or "").upper()) else "Pivot"


def _v(s):
    if s is None or str(s).strip() == "":
        return None
    return parse_length(str(s)).get("value")


def _same(a, b):
    return a and b and abs(a[0] - b[0]) < 0.5 and abs(a[1] - b[1]) < 0.5


def _pt(p, u=None):
    if not p:
        return {"u": u or "", "l": "", "ubox": None, "lbox": None}
    return {"u": p.get("u", "") if u is None else u, "l": p.get("l", ""), "ubox": p.get("ubox"), "lbox": p.get("lbox")}


def build_doors(res: dict, geo: dict | None = None) -> list:
    """Door entries for one page result (elevations + candidates from extract_page).
    geo = pdfdoc.swing_geometry() of the page (swing-plan arcs, elevation swing 'V'); optional."""
    els = res.get("elevations", [])
    used = [b for e in els for p in e.get("points", []) for b in (p.get("ubox"), p.get("lbox")) if b]
    readings = []                                   # unused BM-range values: door-swing plan readings
    for c in res.get("candidates", []):
        if c.get("other") or any(_same(c["bbox"], u) for u in used):
            continue
        v = _v(c.get("v"))
        if v is not None:
            readings.append({"v": v, "s": c["v"], "bbox": c["bbox"], "cx": (c["bbox"][0] + c["bbox"][2]) / 2,
                             "cy": (c["bbox"][1] + c["bbox"][3]) / 2})
    pivots, out = [], []
    for e in els:
        pts = e.get("points", [])
        tops = [b[1] for p in pts for b in (p.get("ubox"), p.get("lbox")) if b]
        el_top = min(tops) if tops else (e.get("bm_y") or 0) - 40
        above = [o["title_box"][3] for o in els if o is not e and o.get("title_box") and o["title_box"][3] < el_top]
        lim = max(above) + 2 if above else -1e9                    # never reach past the title row above
        panels = e.get("panels", [])
        order = sorted(range(len(panels)), key=lambda k: (panels[k].get("pts") or [0])[0])
        for k, p in enumerate(panels):
            if p.get("kind") != "Door":
                continue
            li, ri = (p.get("pts") or [None, None]) + [None, None][len(p.get("pts") or []):]
            Lp = pts[li] if li is not None and 0 <= li < len(pts) else {"u": p["L"]["u"], "l": p["L"]["l"]}
            Rp = pts[ri] if ri is not None and 0 <= ri < len(pts) else {"u": p["R"]["u"], "l": p["R"]["l"]}
            Lp = dict(Lp, u=p["L"]["u"], l=p["L"]["l"])               # values as the glass engine settled them
            Rp = dict(Rp, u=p["R"]["u"], l=p["R"]["l"])
            typ = door_type(p.get("code", ""))
            d = {"elev": e.get("elev", ""), "room": e.get("room", ""), "name": e.get("name", ""),
                 "page": e.get("page", res.get("page", 0)), "title_box": e.get("title_box"), "bbox": e.get("bbox"),
                 "tag": p.get("tag", ""), "code": p.get("code", ""), "type": typ, "export": True,
                 "tag_box": p.get("tag_box"), "notes": [], "pts": {}}
            if typ == "Sliding":
                pos = order.index(k)
                left_n = pos > 0
                right_n = pos < len(order) - 1
                def at(i):
                    return pts[i] if i is not None and 0 <= i < len(pts) else None
                if right_n and not left_n:                             # door at the left end, slides right
                    A, B, C = Lp, Rp, at(ri + 1 if ri is not None else None)
                elif left_n and not right_n:                           # door at the right end, slides left
                    A, B, C = Rp, Lp, at(li - 1 if li is not None else None)
                else:
                    A, B, C = Lp, Rp, at(ri + 1 if ri is not None else None)
                    d["notes"].append("Sliding direction not clear (door between panels) - check A / B "
                                      "(use ⇄ to swap)" if left_n else
                                      "No panel next to this sliding door - C1 (end of travel) not on the sheet")
                d["pts"] = {"A": _pt(A), "B": _pt(B), "C1": _pt(C)}
                if C is None:
                    d["pts"]["C1"]["u"] = ""
            else:
                xs = [x for x in ((Lp.get("x")), (Rp.get("x"))) if x is not None]
                xl, xr = (min(xs), max(xs)) if len(xs) == 2 else (None, None)
                if xl is not None:                     # readings sit beside the edge: use the drawn frame lines
                    tb = p.get("tag_box")
                    xl, xr = _door_edges(xl, xr, (tb[0] + tb[2]) / 2 if tb else (xl + xr) / 2,
                                         (geo or {}).get("vlines", []), e.get("bm_y"))
                    Lp, Rp = dict(Lp, x=xl), dict(Rp, x=xr)
                bottom = (e.get("title_box") or [0, 0, 0, el_top + 400])[1] + 4
                d.update(_tmp={"L": Lp, "R": Rp, "xl": xl, "xr": xr, "top": el_top, "lim": lim, "bottom": bottom})
                pivots.append(d)
            out.append(d)
    arcs = list((geo or {}).get("arcs", []))
    diag = (geo or {}).get("diag", [])
    taken = set()
    plans = {}
    # 1. swing-plan arcs: each goes to the pivot door whose edges it sits over (pivot above the hinge edge)
    pairs = []
    for di, d in enumerate(pivots):
        t = d["_tmp"]
        if t["xl"] is None:
            continue
        w = max(t["xr"] - t["xl"], 20)
        for ai, a in enumerate(arcs):
            cx, cy = a["c"]
            if not (t["xl"] - 0.6 * w <= cx <= t["xr"] + 0.6 * w) or not (t["lim"] < cy < t["top"]):
                continue
            if not 0.3 * w <= a["r"] <= 2.5 * w:
                continue
            pairs.append((min(abs(cx - t["xl"]), abs(cx - t["xr"])) + 0.05 * (t["top"] - cy), di, ai))
    used_d, used_a = set(), set()
    for _, di, ai in sorted(pairs):
        if di in used_d or ai in used_a:
            continue
        used_d.add(di); used_a.add(ai)
        plans[di] = arcs[ai]
    # 2. readings on each plan: tip -> C2, 45 deg -> C1, closed end -> latch check
    found = {}
    for di, a in plans.items():
        t = pivots[di]["_tmp"]
        lows = [v for v in (_v(t["L"].get("l")), _v(t["R"].get("l"))) if v is not None]
        dmax = 0.9 * a["r"] + 14
        cands = []
        for ri, r in enumerate(readings):
            if lows and abs(r["v"] - median(lows)) > 2.5:
                continue
            dd = {k: _box_dist(a[k], r["bbox"]) for k in ("tip", "mid", "closed")}
            if any(abs(r["v"] - x) < 1 / 64 for x in lows):
                dd["closed"] *= 0.5                            # the closed-door reading repeats an edge lower
            if min(dd.values()) <= dmax:
                cands.append((ri, dd))
        best = None
        opts = [None] + cands
        for x in opts:
            for y in opts:
                for z in opts:
                    ids = [o[0] for o in (x, y, z) if o]
                    if len(ids) != len(set(ids)):
                        continue
                    cost = sum(o[1][k] if o and o[1][k] <= dmax else (dmax if not o else 1e9)
                               for o, k in ((x, "tip"), (y, "mid"), (z, "closed")))
                    if best is None or cost < best[0]:
                        best = (cost, x, y, z)
        tip, mid, closed = (best[1:] if best else (None, None, None))
        found[di] = {"C2": readings[tip[0]] if tip else None, "C1": readings[mid[0]] if mid else None,
                     "X": readings[closed[0]] if closed else None}
        taken.update(o[0] for o in (tip, mid, closed) if o)
    # 3. doors without a drawn plan: the swing readings nearest to them (values close to the door lowers)
    claims = {}
    for ri, r in enumerate(readings):
        if ri in taken:
            continue
        best = None
        for di, d in enumerate(pivots):
            if di in plans:
                continue
            t = d["_tmp"]
            if t["xl"] is None or r["bbox"][3] > t["top"] - 2 or r["bbox"][1] < t["lim"]:
                continue
            w = max(t["xr"] - t["xl"], 30)
            if not (t["xl"] - 1.1 * w <= r["cx"] <= t["xr"] + 1.1 * w):
                continue
            lows = [v for v in (_v(t["L"].get("l")), _v(t["R"].get("l"))) if v is not None]
            if lows and abs(r["v"] - median(lows)) > 2.5:
                continue                                       # not a floor reading (upper, width ...)
            dist = abs(r["cx"] - (t["xl"] + t["xr"]) / 2) + 0.5 * abs(t["top"] - r["cy"])
            if best is None or dist < best[0]:
                best = (dist, di)
        if best:
            claims.setdefault(best[1], []).append(r)
    for di, d in enumerate(pivots):
        t = d.pop("_tmp")
        L, R = t["L"], t["R"]
        lv, rv = _v(L.get("l")), _v(R.get("l"))
        votes = {}
        if t["xl"] is not None:
            w = max(t["xr"] - t["xl"], 20)
            v = _hinge_from_v(diag, t["xl"], t["xr"], t["lim"], t["bottom"])
            if v:
                votes["elevation"] = v
            a = plans.get(di)
            if a and min(abs(a["c"][0] - t["xl"]), abs(a["c"][0] - t["xr"])) < 0.35 * w:
                votes["plan"] = "L" if abs(a["c"][0] - t["xl"]) < abs(a["c"][0] - t["xr"]) else "R"
        f = found.get(di)
        rs = claims.get(di, [])
        pre = next((votes[k] for k in ("elevation", "plan") if k in votes), None)
        X = f["X"] if f else None
        if f:
            c1, c2 = f["C1"], f["C2"]
            if not pre and X is not None and lv is not None and rv is not None and abs(lv - rv) >= 1 / 64:
                if abs(X["v"] - lv) < 1 / 64:
                    votes["closed"] = "R"                      # closed reading = left lower -> left is the latch
                elif abs(X["v"] - rv) < 1 / 64:
                    votes["closed"] = "L"
        else:                                                  # no plan drawn: fit the readings to where it would be
            fits = []
            for hg in ([pre] if pre else ["L", "R"]):
                if t["xl"] is None:
                    break
                hx, lx_, lat = (t["xl"], t["xr"], rv) if hg == "L" else (t["xr"], t["xl"], lv)
                fits.append((*_fit_plan(rs, hx, lx_, lat), hg))
            if fits:
                fits.sort(key=lambda z: z[0])
                _, c2, c1, X, hg = fits[0]
                lat = rv if hg == "L" else lv
                if not pre and X is not None and lat is not None and abs(X["v"] - lat) < 1 / 64 and \
                        lv is not None and rv is not None and abs(lv - rv) >= 1 / 64:
                    votes["closed"] = hg
                elif not pre and len(fits) > 1:                # undecided: keep the left-hinge reading of the plan
                    _, c2, c1, X, _ = next(z for z in fits if z[4] == "L")
            else:
                c1 = c2 = None
        hinge = next((votes[k] for k in ("elevation", "plan", "closed") if k in votes), None)
        A, B = (R, L) if hinge == "R" else (L, R)
        d["hinge"] = hinge or ""
        d["hinge_src"] = next((k for k in ("elevation", "plan", "closed") if k in votes), "")
        d["pts"] = {"A": _pt(A), "B": _pt(B),
                    "C1": {"u": B.get("u", ""), "l": to_fraction_str(c1["v"]) if c1 else "", "ubox": None,
                           "lbox": c1["bbox"] if c1 else None},
                    "C2": {"u": A.get("u", ""), "l": to_fraction_str(c2["v"]) if c2 else "", "ubox": None,
                           "lbox": c2["bbox"] if c2 else None}}
        d["closed"] = {"l": to_fraction_str(X["v"]), "lbox": X["bbox"]} if X else None
        if not hinge:
            d["notes"].append("Hinge side not found (no swing mark on the elevation or the plan) - A is the left "
                              "edge, check it (use ⇄ to swap)")
        elif len(set(votes.values())) > 1:
            d["notes"].append("Hinge side unclear: the swing mark on the elevation and the swing plan disagree - "
                              "used the elevation, check A / B (use ⇄ to swap)")
        elif d["hinge_src"] == "closed":
            d["notes"].append("Hinge side taken from the closed-door reading on the swing plan (no swing mark "
                              "drawn) - check A / B")
        miss = [k + (" (45°)" if k == "C1" else " (90° open)") for k, c in (("C1", c1), ("C2", c2)) if c is None]
        if miss:
            d["notes"].append(" and ".join(miss) + " door-swing reading not found on the sheet")
        bl = _v(B.get("l"))
        if X is not None and bl is not None and abs(X["v"] - bl) > 1 / 8 + 1e-9:
            d["notes"].append(f"Closed-door reading {to_fraction_str(X['v'])} on the swing plan differs from the latch "
                              f"lower {to_fraction_str(bl)} - check")
    out.sort(key=lambda d: (_elev_num(d["elev"]), d["page"], (d.get("tag_box") or [0])[0]))
    return out


def _fit_plan(rs, hx, lx, latch_lower):
    """Swing plan written without a drawing: pick (C2 tip, C1 45 deg, closed) from the readings rs so that they sit
    where the plan would be - tip over the hinge, 45 deg at 0.7 of the door width, closed over the latch, going down
    from tip to closed. -> (cost, tip, mid, closed)"""
    w = max(abs(lx - hx), 20)
    want = {"tip": hx, "mid": hx + 0.7 * (lx - hx), "closed": lx}
    rs = sorted(rs, key=lambda r: min(abs(r["cx"] - x) for x in want.values()))[:7]
    opts = [None] + rs
    best = (1e9, None, None, None)
    for tp in opts:
        for md in opts:
            for cl in opts:
                ch = [o for o in (tp, md, cl) if o is not None]
                if len(ch) != len({id(o) for o in ch}):
                    continue
                cost = sum(0.8 if o is None else abs(o["cx"] - want[k]) / w
                           for o, k in ((tp, "tip"), (md, "mid"), (cl, "closed")))
                for hi, lo in ((tp, md), (md, cl), (tp, cl)):
                    if hi is not None and lo is not None and hi["cy"] > lo["cy"] + 2:
                        cost += 1.0                            # tip above 45 deg above closed
                if ch and max(o["cy"] for o in ch) - min(o["cy"] for o in ch) > 1.5 * w:
                    cost += 1.0
                if cl is not None and latch_lower is not None and abs(cl["v"] - latch_lower) >= 1 / 64:
                    cost += 0.5
                if cost < best[0]:
                    best = (cost, tp, md, cl)
    return best


def _door_edges(xl, xr, xc, vlines, bm_y):
    """Door frame edges: the long vertical lines nearest to the edge readings, one each side of the door tag."""
    if not vlines or bm_y is None:
        return xl, xr
    w = xr - xl
    cand = [v[0] for v in vlines if v[1] - 5 <= bm_y <= v[2] + 5 and v[2] - v[1] >= 40]
    left = [x for x in cand if x < xc - 3 and abs(x - xl) < max(0.6 * w, 45)]
    right = [x for x in cand if x > xc + 3 and abs(x - xr) < max(0.6 * w, 45)]
    nl = min(left, key=lambda x: abs(x - xl)) if left else xl
    nr = min(right, key=lambda x: abs(x - xr)) if right else xr
    return (nl, nr) if nr - nl > 10 else (xl, xr)


def _box_dist(p, b):
    """Distance from point p to box b (0 inside)."""
    dx = max(b[0] - p[0], 0, p[0] - b[2])
    dy = max(b[1] - p[1], 0, p[1] - b[3])
    return math.hypot(dx, dy)


def _hinge_from_v(diag, xl, xr, y0, y1):
    """'V' drawn on a door in elevation (two diagonals meeting at the hinge side) -> "L" / "R" / None."""
    w = xr - xl
    ls = [g for g in diag if min(g[0], g[2]) >= xl - 4 and max(g[0], g[2]) <= xr + 4 and g[1] >= y0 - 4
          and g[3] <= y1 + 4 and abs(g[2] - g[0]) >= 0.6 * w]
    votes = set()
    for a in ls:
        for b in ls:
            if a is b or math.dist((a[2], a[3]), (b[0], b[1])) > 10:
                continue
            ax = (a[2] + b[0]) / 2                                  # apex: a ends where b starts
            if abs(ax - xl) < 0.25 * w and min(a[0], b[2]) > xr - 0.25 * w:
                votes.add("L")
            elif abs(ax - xr) < 0.25 * w and max(a[0], b[2]) < xl + 0.25 * w:
                votes.add("R")
    return votes.pop() if len(votes) == 1 else None


def _elev_num(e):
    m = re.match(r"\d+", str(e or ""))
    return int(m.group(0)) if m else 10 ** 6


def totals(d):
    """{point: total or None}, diff, final for one door (A vs B)."""
    from .judgement import judge
    tots = {}
    for k, p in d["pts"].items():
        u, l = _v(p.get("u")), _v(p.get("l"))
        tots[k] = u + l if u is not None and l is not None else None
    diff, final = judge(tots.get("A"), tots.get("B"))
    return tots, diff, final
