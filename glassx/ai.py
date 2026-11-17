"""AI reading of raster FM pages with Claude (Anthropic API).

Why: scanned / pasted-picture FM sheets have no text layer, and OCR mis-reads hand-written mark-ups, one-glyph
fractions and small tags. Claude reads the drawing the way an estimator does.

How (two calls per elevation, all results checked by code):
  1. the page, sized to the model's high-resolution limit  -> where each elevation is (title + drawing box)
  2. each elevation, cropped and sized to the same limit  -> every edge's upper / lower, the glass / door tags,
     door type, hinge side and the 45 / 90 deg door-swing readings, each with its box on the drawing
Claude only READS what is written (strings + boxes). The team rules (one upper for every edge, blank edge = average
of its neighbours, totals, judgement, door A / B / C1 / C2) stay in this code, so they never depend on the model.
Each AI value is cross-checked with OCR of the same spot; a disagreement is flagged for human review.

The API key lives only on the PC running the app (glass_data/ai_settings.json or the ANTHROPIC_API_KEY variable);
it is never sent to the browser. Drawings are sent to the Anthropic API only when AI reading is switched on.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config

log = logging.getLogger("glassx.ai")

MODELS = [("claude-sonnet-5-5", "Claude Sonnet 5.5 - recommended (accurate, fast)"),
          ("claude-opus-5-5", "Claude Opus 5.5 - most accurate, slower / dearer"),
          ("claude-haiku-5-5", "Claude Haiku 5.5 - fastest / cheapest")]
MODES = {"pictures": "Picture & scanned pages automatically",
         "button": "Only when I click AI read",
         "off": "Off"}
DEFAULTS = {"model": "claude-sonnet-5-5", "mode": "pictures", "api_key": ""}
MAX_EDGE, MAX_TOKENS = 2576, 4784          # high-resolution image tier (Claude 4.7 and later models)
PROMPT_VERSION = "1"
_LOCK = threading.Lock()
_USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "pages": 0, "errors": 0}
CLIENT_FACTORY = None                     # tests inject a fake client here


# ------------------------------------------------------------------------------------------------ settings
def _file():
    return os.path.join(config.DATA_DIR, "ai_settings.json")


KEY_FILES = ("key.txt", "key.text", "api_key.txt", "anthropic_key.txt", "anthropic.txt")


def key_file():
    """The key file dropped in the app folder (next to run_app.bat) -> (path, key) or (None, "").
    Accepts the bare key, or a line such as  ANTHROPIC_API_KEY=sk-ant-...  ; '#' lines are comments."""
    folders = [config.BASE_DIR] + ([config.DATA_DIR] if config.DATA_DIR != config.BASE_DIR else [])
    for folder in folders:
        try:
            names = {n.lower(): n for n in os.listdir(folder)}
        except OSError:
            continue
        for want in KEY_FILES:
            if want in names:
                path = os.path.join(folder, names[want])
                try:
                    with open(path, encoding="utf-8-sig") as fh:
                        for line in fh:
                            t = line.strip().strip('"').strip("'")
                            if not t or t.startswith("#"):
                                continue
                            if "=" in t and not t.startswith("sk-"):
                                t = t.split("=", 1)[1].strip().strip('"').strip("'")
                            if len(t) >= 20:
                                return path, t
                except OSError:
                    pass
    return None, ""


def load() -> dict:
    s = dict(DEFAULTS)
    try:
        with open(_file(), encoding="utf-8") as fh:
            s.update({k: v for k, v in json.load(fh).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    s["key_source"] = "settings" if s["api_key"] else ""
    kf, kk = key_file()
    if kk:                                   # key.txt in the app folder wins: drop the file in -> AI is on
        s["api_key"], s["key_source"] = kk, os.path.basename(kf)
    elif os.environ.get("ANTHROPIC_API_KEY") and not s["api_key"]:
        s["api_key"] = os.environ["ANTHROPIC_API_KEY"].strip()
        s["key_source"] = "environment"
    if s["model"] not in [m for m, _ in MODELS]:
        s["model"] = DEFAULTS["model"]
    if s["mode"] not in MODES:
        s["mode"] = DEFAULTS["mode"]
    return s


def save(model=None, mode=None, api_key=None) -> dict:
    with _LOCK:
        cur = {}
        try:
            with open(_file(), encoding="utf-8") as fh:
                cur = json.load(fh)
        except (OSError, ValueError):
            pass
        if model in [m for m, _ in MODELS]:
            cur["model"] = model
        if mode in MODES:
            cur["mode"] = mode
        if api_key is not None:
            cur["api_key"] = api_key.strip()
        os.makedirs(config.DATA_DIR, exist_ok=True)
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cur, fh)
        os.replace(tmp, _file())
    return status()


def configured() -> bool:
    s = load()
    return bool(s["api_key"]) and s["mode"] != "off" and _sdk_ok()


def auto_on() -> bool:
    return configured() and load()["mode"] == "pictures"


def _sdk_ok() -> bool:
    if CLIENT_FACTORY is not None:
        return True
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def status() -> dict:
    """Safe for the browser: never the key itself, only its last 4 characters."""
    s = load()
    k = s["api_key"]
    return {"configured": bool(k) and _sdk_ok(), "key_hint": ("…" + k[-4:]) if len(k) >= 8 else ("set" if k else ""),
            "key_source": s.get("key_source", ""), "key_file": s.get("key_source", "").lower().endswith((".txt", ".text")),
            "sdk": _sdk_ok(), "model": s["model"], "mode": s["mode"],
            "models": [{"id": m, "label": lab} for m, lab in MODELS],
            "modes": [{"id": m, "label": lab} for m, lab in MODES.items()], "usage": dict(_USAGE),
            "on": bool(k) and s["mode"] != "off" and _sdk_ok()}


def _client():
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY()
    import anthropic
    return anthropic.Anthropic(api_key=load()["api_key"], timeout=180.0, max_retries=3)


# ------------------------------------------------------------------------------------------------ images
def fit_size(width, height, max_edge=MAX_EDGE, max_tokens=MAX_TOKENS):
    """Largest size Claude will NOT resize (so the boxes it returns map 1:1 onto our image).
    Same rule as the Anthropic vision docs: ceil(w/28)*28 <= max_edge, same for h, ceil(w/28)*ceil(h/28) <= tokens."""
    def fits(w, h):
        return (math.ceil(w / 28) * 28 <= max_edge and math.ceil(h / 28) * 28 <= max_edge
                and math.ceil(w / 28) * math.ceil(h / 28) <= max_tokens)
    if fits(width, height):
        return width, height
    if height > width:
        h, w = fit_size(height, width, max_edge, max_tokens)
        return w, h
    aspect = width / height
    lo, hi = 1, width
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if fits(mid, max(round(mid / aspect), 1)):
            lo = mid
        else:
            hi = mid
    return lo, max(round(lo / aspect), 1)


def render(page, rect, cap=8.0):
    """Display-coordinate rect of the page -> (png bytes, zoom, x0, y0). Sized to fit the image tier exactly."""
    import pymupdf
    from .pdfdoc import PDF_LOCK
    x0, y0, x1, y1 = rect
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)
    fw, _ = fit_size(int(w * cap), int(h * cap))
    z = fw / w
    with PDF_LOCK:
        clip = pymupdf.Rect(x0, y0, x1, y1) * page.derotation_matrix
        clip.normalize()
        for _ in range(6):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=clip, alpha=False)
            if fit_size(pix.width, pix.height) == (pix.width, pix.height):
                break
            z *= 0.98
        return pix.tobytes("png"), z, x0, y0


# ------------------------------------------------------------------------------------------------ prompts
SYSTEM = """You read Muraflex Field Measurement (FM) sheets for the glass estimating team. You report exactly what is \
written on the drawing; the estimating software does every calculation itself.

How an FM sheet is drawn
- Each ELEVATION is a front view of a glass partition with a title under it such as "(3) ELEVATION / OFFICE 8C-28" \
(the number is in a small circle left of the title; it can also be a letter or missing).
- A dashed horizontal benchmark line labelled "BM" runs through every elevation.
- Vertical frame edges: the two wall ends, every mullion between glass panels and both edges of each door. Labels \
like DW, MW, CL / ℄, FAL above the drawing mark edges and a width dimension (e.g. 168 1/8) between them.
- The installer writes measurements in coloured ink (red, green, blue, magenta) next to the edges:
  * UPPER = from the BM line up to the ceiling / head. Written at the TOP of the edge, above the BM line, or ON \
the BM line itself. Usually 40-60.
  * LOWER = from the BM line down to the floor. Written near the FLOOR / sill at the bottom of the edge, or in a row \
under the title. Usually 45-66.
  Upper + lower of one edge is the full height (typically 95-115). An edge never has two lowers or two uppers.
  * Sometimes only one upper is written for the whole elevation, or uppers are written at the end edges only - \
report them where they are written; do not copy them to other edges.
- Inches with fractions in 1/16: 57 3/8, 57-3/8", 57"3/8, 57⅜, 65' 13/16 (an apostrophe used as the inch mark), \
48FT. Copy the text exactly as written, including the fraction. Never convert, round or compute.
- Panels between two edges carry a glass code and a tag, e.g. "OGL-12 / 8C-28-A". "BY OTHERS" under the code = glass \
by others. Door codes contain PD, HD, SD, STD, DO, MFD (FPD-OGL, GPD, GHD, GSD-12, FSD ...). A door also has a tag \
(often the room number, e.g. 8C-28). A span with a wall / existing condition and no code is "no_tag".
- Door swing plan (pivot / hinged doors): a small quarter arc drawn ABOVE the door. The pivot is the arc centre, \
above the hinge edge. Readings around it: at the TIP of the open leaf (90 deg open, above the hinge) -> swing_90; \
at the MIDDLE of the arc -> swing_45; at the closed end of the arc (on the wall line, above the latch edge) -> closed. \
These readings may carry "(S)". They are NOT uppers.
- Hinge side: the dashed "V" drawn on the door in elevation points to the hinge side; the swing plan's pivot is \
above the hinge edge.
- Sliding doors (code ends in SD / STD) have no swing plan.
- Ignore: widths and overall dimensions, glass thickness, bulkhead heights, notes and their numbers ("Taken on slab", \
"Carpet will be installed"), the title block (project number, phone, address), key plans.

Rules for reading
- If a digit or fraction is unreadable, give your best reading AND list it in "unclear" with the reason. Never invent \
a value that is not written: use null.
- Boxes are [x1, y1, x2, y2] pixel coordinates in THIS image (origin top-left), tight around the written value.
- Work left to right. Before answering, check: every coloured value near an edge is reported once; uppers are above \
or on the BM line, lowers are below it; nothing from the title block or notes is reported."""

PAGE_TOOL = {
    "name": "report_elevations",
    "description": "Report every FM elevation drawn on this page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "elevations": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "number": {"type": ["string", "null"], "description": "number / letter in the title circle"},
                    "title": {"type": "string", "description": "title text, e.g. ELEVATION / OFFICE 8C-28"},
                    "title_box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                    "drawing_box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
                                    "description": "the whole elevation: frame, every mark-up value next to it, its "
                                                   "edge labels, width dimension, door-swing plan above it and the title"},
                },
                "required": ["number", "title", "title_box", "drawing_box"]}},
        },
        "required": ["elevations"]}}

_VAL = {"type": ["object", "null"],
        "properties": {"text": {"type": "string", "description": "exactly as written, e.g. 57 3/8"},
                       "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}},
        "required": ["text", "box"]}
ELEV_TOOL = {
    "name": "report_elevation",
    "description": "Report everything measured on the ONE elevation whose title is given (ignore neighbours).",
    "input_schema": {
        "type": "object",
        "properties": {
            "edges": {"type": "array", "description": "vertical frame edges, LEFT to RIGHT (walls, mullions, door "
                                                      "edges), including edges with no value written",
                      "items": {"type": "object",
                                "properties": {"x": {"type": "number", "description": "pixel x of the edge line"},
                                               "upper": _VAL, "lower": _VAL},
                                "required": ["x", "upper", "lower"]}},
            "panels": {"type": "array", "description": "spans between two edges, left to right",
                       "items": {"type": "object",
                                 "properties": {"left_edge": {"type": "integer"}, "right_edge": {"type": "integer"},
                                                "code": {"type": "string"}, "tag": {"type": "string"},
                                                "kind": {"type": "string",
                                                         "enum": ["glass", "door", "by_others", "no_tag"]},
                                                "tag_box": {"type": ["array", "null"], "items": {"type": "number"}}},
                                 "required": ["left_edge", "right_edge", "code", "tag", "kind"]}},
            "doors": {"type": "array",
                      "items": {"type": "object",
                                "properties": {"panel": {"type": "integer", "description": "index in panels"},
                                               "type": {"type": "string", "enum": ["pivot", "sliding"]},
                                               "hinge": {"type": "string", "enum": ["left", "right", "unknown"]},
                                               "swing_45": _VAL, "swing_90": _VAL, "closed": _VAL},
                                "required": ["panel", "type", "hinge", "swing_45", "swing_90", "closed"]}},
            "notes": {"type": "array", "items": {"type": "string"},
                      "description": "anything the estimator must know: Deleted / N.I.C., values on the wrong side, "
                                     "a second elevation drawn inside this one ..."},
            "unclear": {"type": "array", "items": {"type": "string"},
                        "description": "every value you are not sure of, with the reason"},
        },
        "required": ["edges", "panels", "doors", "notes", "unclear"]}}


def _call(png: bytes, text: str, tool: dict, model: str) -> dict:
    client = _client()
    msg = client.messages.create(
        model=model, max_tokens=8000, system=SYSTEM, tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(png).decode("ascii")}},
            {"type": "text", "text": text}]}])
    u = getattr(msg, "usage", None)
    with _LOCK:
        _USAGE["calls"] += 1
        _USAGE["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
        _USAGE["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
    for b in getattr(msg, "content", []) or []:
        if getattr(b, "type", "") == "tool_use":
            return dict(b.input)
    raise RuntimeError("the model did not return the structured answer")


def test_connection() -> dict:
    """One tiny call: is the key valid, is the model reachable?"""
    import pymupdf
    d = pymupdf.open()
    pg = d.new_page(width=200, height=60)
    pg.insert_text((10, 35), "ELEVATION / TEST 1", fontsize=12)
    png = pg.get_pixmap(dpi=96).tobytes("png")
    t0 = time.time()
    try:
        _call(png, "Report the elevations on this tiny test image.", PAGE_TOOL, load()["model"])
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "error": _friendly(e)}
    return {"ok": True, "model": load()["model"], "seconds": round(time.time() - t0, 1)}


def _friendly(e) -> str:
    s = f"{type(e).__name__}: {e}"
    low = s.lower()
    if "authentication" in low or "401" in low or "api key" in low:
        return "The API key was refused - check it in AI settings"
    if "permission" in low or "403" in low:
        return "This API key may not use this model - pick another model in AI settings"
    if "not_found" in low or "404" in low:
        return "Model not found for this API key - pick another model in AI settings"
    if "rate" in low and "limit" in low or "429" in low:
        return "Too many requests right now (rate limit) - try again in a minute"
    if "overloaded" in low or "529" in low:
        return "The AI service is busy - try again in a minute"
    if "connect" in low or "timeout" in low or "proxy" in low:
        return "Cannot reach api.anthropic.com from this PC (network / proxy / firewall)"
    return s[:300]


# ------------------------------------------------------------------------------------------------ page reading
def _to_pt(box, z, x0, y0):
    if not box or len(box) != 4:
        return None
    a, b, c, d = (float(v) for v in box)
    return [round(x0 + min(a, c) / z, 2), round(y0 + min(b, d) / z, 2),
            round(x0 + max(a, c) / z, 2), round(y0 + max(b, d) / z, 2)]


def _val(v):
    """AI text -> (fraction string, value) using the app's own reader; ('', None) when not a BM reading."""
    from .extract import dim_value
    from .units import to_fraction_str
    if not v or not str(v.get("text", "")).strip():
        return "", None
    t = str(v["text"]).replace("(S)", "").replace("(s)", "").strip()
    x = dim_value(t, strict=False, glued=True)
    return (to_fraction_str(x), x) if x is not None else ("", None)


def _fill(points, side, notes):
    """Team rules for edges without a written value (same as the text reader):
    one value written for the elevation / all given values equal -> used at every edge;
    blank edge between two written ones -> their average floored to 1/16; blank end edge -> nearest written."""
    from .units import to_fraction_str
    key = side
    given = [i for i, p in enumerate(points) if p[key + "v"] is not None]
    if not given or len(given) == len(points):
        return
    vals = {i: points[i][key + "v"] for i in given}
    name = "Upper" if side == "u" else "Lower"
    if max(vals.values()) - min(vals.values()) < 1 / 64:
        v = vals[given[0]]
        for p in points:
            if p[key + "v"] is None:
                p[key], p[key + "v"] = to_fraction_str(v), v
        notes.append(f"{name} {to_fraction_str(v)} written at {len(given)} of {len(points)} edges - used at every edge")
        return
    done = []
    for i, p in enumerate(points):
        if p[key + "v"] is not None:
            continue
        lft = [k for k in given if k < i]
        rgt = [k for k in given if k > i]
        if lft and rgt:
            a, b = vals[max(lft)], vals[min(rgt)]
            v = math.floor((a + b) / 2 * 16 + 1e-6) / 16
            done.append(f"{side.upper()}{i + 1} = ({to_fraction_str(a)} + {to_fraction_str(b)}) / 2 = {to_fraction_str(v)}")
        else:
            v = vals[max(lft) if lft else min(rgt)]
            done.append(f"{side.upper()}{i + 1} = {to_fraction_str(v)} (nearest written)")
        p[key], p[key + "v"] = to_fraction_str(v), v
    notes.append(f"{name} not written at {len(done)} edge(s) - " + "; ".join(done) + " - check them")


KIND = {"glass": "Fixed", "door": "Door", "by_others": "By others", "no_tag": "No tag"}


def convert(page_no, title, data, z, x0, y0) -> tuple:
    """One AI elevation answer -> (elevation dict in the app's format, AI door info)."""
    from .extract import is_door
    notes = [f"Read by AI ({load()['model']}) - check every value against the drawing"]
    pts = []
    for e in sorted(data.get("edges") or [], key=lambda e: float(e.get("x", 0))):
        us, uv = _val(e.get("upper"))
        ls, lv = _val(e.get("lower"))
        pts.append({"x": round(x0 + float(e.get("x", 0)) / z, 2), "u": us, "l": ls, "uv": uv, "lv": lv,
                    "u_raw": (e.get("upper") or {}).get("text", ""), "l_raw": (e.get("lower") or {}).get("text", ""),
                    "ubox": _to_pt((e.get("upper") or {}).get("box"), z, x0, y0) if us else None,
                    "lbox": _to_pt((e.get("lower") or {}).get("box"), z, x0, y0) if ls else None,
                    "u_avg": False, "l_avg": False})
    _fill(pts, "u", notes)
    _fill(pts, "l", notes)
    panels = []
    for p in data.get("panels") or []:
        li, ri = int(p.get("left_edge", 0)), int(p.get("right_edge", 0))
        if not (0 <= li < len(pts) and 0 <= ri < len(pts)):
            continue
        code = (p.get("code") or "").strip().upper()
        kind = KIND.get(p.get("kind"), "Fixed")
        if kind == "Fixed" and code and is_door(code):
            kind = "Door"
        if kind == "Fixed" and not code and not (p.get("tag") or "").strip():
            kind = "No tag"
        panels.append({"tag": (p.get("tag") or "").strip(), "code": code, "kind": kind,
                       "export": kind == "Fixed", "tag_box": _to_pt(p.get("tag_box"), z, x0, y0),
                       "L": {"u": pts[li]["u"], "l": pts[li]["l"]}, "R": {"u": pts[ri]["u"], "l": pts[ri]["l"]},
                       "pts": [li, ri]})
    for n in data.get("notes") or []:
        notes.append("AI: " + str(n))
    for n in data.get("unclear") or []:
        notes.append("REQUIRES HUMAN REVIEW (AI unsure): " + str(n))
    boxes = [b for p in pts for b in (p["ubox"], p["lbox"]) if b] + [title["box"]]
    el = {"elev": title["number"], "room": title["room"], "name": title["name"], "title": title["text"],
          "title_box": title["box"], "panels": panels,
          "points": [{k: v for k, v in p.items() if k not in ("uv", "lv")} for p in pts], "notes": notes,
          "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                   max(b[3] for b in boxes)], "bm_y": None, "page": page_no, "ai": True}
    ai_doors = []
    for dd in data.get("doors") or []:
        k = int(dd.get("panel", -1))
        if 0 <= k < len(panels):
            ai_doors.append({"panel": k, "type": dd.get("type"), "hinge": dd.get("hinge"),
                             **{n: (_val(dd.get(n)), _to_pt((dd.get(n) or {}).get("box"), z, x0, y0))
                                for n in ("swing_45", "swing_90", "closed")}})
    return el, ai_doors


def _title_parts(t):
    """Same name / room split as the text reader: 'ELEVATION / OFFICE 2 #63' -> name 'OFFICE 2', room '63'."""
    import re
    text = re.sub(r"\s+", " ", (t.get("title") or "").strip())
    tu = text.upper()
    m = re.search(r"#\s*([A-Z0-9][A-Z0-9.\-]*)", tu)
    room = m.group(1) if m else ""
    m = re.search(r"ELEV(?:ATION|\.)?\s*[/:\-]?\s*(.*?)(?:#|$)", text, re.I)
    name = m.group(1).strip(" -/") if m else text
    if not room:
        m = re.search(r"\b([A-Z]?\d{1,5}[A-Z]?(?:-\d{1,3})?[A-Z]{0,2})\s*$", name.upper())
        room = m.group(1) if m else ""
    num = str(t.get("number") or "").strip().strip("()")
    return {"number": num, "text": text, "name": name, "room": room}


def read_page(doc, pno: int, model: str | None = None) -> dict:
    """Whole page with Claude -> {"elevations": [...], "ai_doors": {id(el): [...]}, "notes": [...]}."""
    from .pdfdoc import PDF_LOCK
    model = model or load()["model"]
    with PDF_LOCK:
        page = doc[pno]
        disp = page.rect * page.rotation_matrix
        disp.normalize()
        W, H = disp.width, disp.height
    png, z, ox, oy = render(page, (0, 0, W, H))
    found = _call(png, "Find every FM elevation on this page. Give its title and a drawing_box that includes the "
                       "frame, all mark-up values around it, the door-swing plan above it and the title.",
                  PAGE_TOOL, model).get("elevations") or []
    titles = []
    for f in found:
        tb, db = _to_pt(f.get("title_box"), z, ox, oy), _to_pt(f.get("drawing_box"), z, ox, oy)
        if not tb or not db:
            continue
        tp = _title_parts(f)
        tp["box"] = tb
        titles.append((tp, db))

    def one(item):
        tp, db = item
        x0, y0, x1, y1 = db
        mx, my = 0.06 * (x1 - x0) + 10, 0.06 * (y1 - y0) + 10                 # keep a margin round the drawing
        rect = (max(0, x0 - mx), max(0, y0 - my), min(W, x1 + mx), min(H, max(y1, tp["box"][3]) + my))
        img, zz, rx, ry = render(page, rect)
        data = _call(img, f'Read the elevation titled "{tp["text"]}" (number {tp["number"] or "not given"}). '
                          "Report its edges left to right with the upper and lower written at each, its panels, "
                          "and its doors. Ignore any other elevation that shows at the border of this image.",
                     ELEV_TOOL, model)
        return convert(pno, tp, data, zz, rx, ry)
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(one, titles))
    with _LOCK:
        _USAGE["pages"] += 1
    els = [r[0] for r in results if r[0]["points"]]
    return {"elevations": els, "ai_doors": {i: r[1] for i, r in enumerate(results) if r[0]["points"]},
            "model": model}


# ------------------------------------------------------------------------------------------------ QC
def cross_check(els: list, tokens: list):
    """AI value vs OCR / text of the same spot. Agreement = fine; a different reading = REQUIRES HUMAN REVIEW."""
    from .extract import dim_value
    from .units import to_fraction_str
    readings = []
    for t in tokens or []:
        v = dim_value(t.t, strict=False, glued=True)
        if v is not None:
            readings.append((t.bbox, v, t.src))
    for e in els:
        bad = []
        for i, p in enumerate(e["points"]):
            for side in ("u", "l"):
                box, s = p.get(side + "box"), p.get(side)
                if not box or not s:
                    continue
                from .units import parse_length
                av = parse_length(s).get("value")
                pad = max(4.0, 0.3 * (box[3] - box[1]))
                near = [(v, src) for b, v, src in readings
                        if b[0] < box[2] + pad and b[2] > box[0] - pad and b[1] < box[3] + pad and b[3] > box[1] - pad]
                if not near or av is None:
                    continue
                if any(abs(v - av) < 1 / 64 for v, _ in near):
                    continue
                other = near[0]
                bad.append(f"{side.upper()}{i + 1}: AI {s} / {'text' if other[1] == 'text' else 'OCR'} "
                           f"{to_fraction_str(other[0])}")
        if bad:
            e["notes"].append("REQUIRES HUMAN REVIEW - AI and OCR read differently: " + "; ".join(bad))
        else:
            e["notes"].append("AI values agree with OCR where OCR could read them")


def apply_doors(res: dict, ai_doors_by_el: dict):
    """Door A / B / C1 / C2 from the AI reading (hinge + 45 / 90 deg swing readings); sliding doors keep the app's
    own rule (A = closed end of the run)."""
    for d in res.get("doors", []):
        el = next((e for e in res["elevations"] if e.get("ai") and e["page"] == d["page"] and e["title_box"] ==
                   d.get("title_box")), None)
        if el is None:
            continue
        idx = res["elevations"].index(el)
        k = next((i for i, p in enumerate(el["panels"]) if p.get("tag_box") == d.get("tag_box") and
                  p.get("tag") == d.get("tag")), None)
        info = next((a for a in ai_doors_by_el.get(idx, []) if a["panel"] == k), None)
        if info is None:
            continue
        if info["type"] in ("pivot", "sliding"):
            d["type"] = "Sliding" if info["type"] == "sliding" else "Pivot"
        if d["type"] != "Pivot":
            continue
        li, ri = el["panels"][k]["pts"]
        L, R = el["points"][li], el["points"][ri]
        A, B = (R, L) if info["hinge"] == "right" else (L, R)
        c45, c90 = info["swing_45"], info["swing_90"]
        d["pts"] = {"A": {"u": A["u"], "l": A["l"], "ubox": A.get("ubox"), "lbox": A.get("lbox")},
                    "B": {"u": B["u"], "l": B["l"], "ubox": B.get("ubox"), "lbox": B.get("lbox")},
                    "C1": {"u": B["u"], "l": c45[0][0], "ubox": None, "lbox": c45[1] if c45[0][0] else None},
                    "C2": {"u": A["u"], "l": c90[0][0], "ubox": None, "lbox": c90[1] if c90[0][0] else None}}
        cl = info["closed"]
        d["closed"] = {"l": cl[0][0], "lbox": cl[1]} if cl[0][0] else None
        d["hinge"] = {"left": "L", "right": "R"}.get(info["hinge"], "")
        d["hinge_src"] = "ai" if d["hinge"] else ""
        d["notes"] = ["Read by AI - check A / B / C1 / C2 against the drawing"]
        if not d["hinge"]:
            d["notes"].append("Hinge side not clear on the drawing (AI) - A is the left edge, check it (use ⇄)")
        miss = [n for n, c in (("C1 (45°)", c45), ("C2 (90° open)", c90)) if not c[0][0]]
        if miss:
            d["notes"].append(" and ".join(miss) + " door-swing reading not found on the sheet")


# ------------------------------------------------------------------------------------------------ vector pages with gaps
def weak(res: dict) -> bool:
    """A text (vector) page whose read left real gaps: an elevation with no values at all, or at least 2 edges (and a
    fifth of them) still without an upper or a lower. Only such pages are worth an AI call - full text pages are exact."""
    pts = [p for e in res.get("elevations", []) for p in e.get("points", [])]
    if any(not e.get("points") for e in res.get("elevations", [])):
        return True
    miss = sum(1 for p in pts if not p.get("u") or not p.get("l"))
    return miss >= 2 and miss >= 0.2 * max(len(pts), 1)


def _overlap(a, b):
    return a and b and min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def fill_gaps(res: dict, out: dict) -> int:
    """Fill ONLY the values the text read could not find, from the AI read of the same elevation and edge.
    Text values are exact and are never replaced. -> number of values filled."""
    filled = 0
    for e in res.get("elevations", []):
        a = next((x for x in out.get("elevations", []) if (e.get("elev") and x.get("elev") == e.get("elev"))
                  or _overlap(e.get("title_box"), x.get("title_box"))), None)
        if a is None or not a.get("points"):
            continue
        xs = sorted(p["x"] for p in e.get("points", []) if p.get("x") is not None)
        gap = min((b - c for c, b in zip(xs, xs[1:])), default=60)
        tol = max(14.0, 0.3 * gap)
        done = []
        for i, p in enumerate(e.get("points", [])):
            if p.get("x") is None:
                continue
            q = min(a["points"], key=lambda q: abs(q["x"] - p["x"]))
            if abs(q["x"] - p["x"]) > tol:
                continue
            for side in ("u", "l"):
                if not p.get(side) and q.get(side):
                    p[side], p[side + "box"] = q[side], q.get(side + "box")
                    p[side + "_raw"] = "AI: " + str(q.get(side + "_raw") or q[side])
                    done.append(f"{side.upper()}{i + 1} {q[side]}")
        for pn in e.get("panels", []):
            ij = pn.get("pts") or []
            if len(ij) == 2:
                for key, k in (("L", ij[0]), ("R", ij[1])):
                    if 0 <= k < len(e["points"]):
                        for side in ("u", "l"):
                            if not pn[key].get(side) and e["points"][k].get(side):
                                pn[key][side] = e["points"][k][side]
        if done:
            filled += len(done)
            e["notes"].append(f"Read by AI where the text had no value ({len(done)}): " + ", ".join(done) +
                              " - check them")
    return filled

