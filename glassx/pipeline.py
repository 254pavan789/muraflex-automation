"""Service layer shared by the web app and the command line: document store, cached page extraction,
whole-PDF processing and export."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from collections import OrderedDict

from . import ENGINE_VERSION, ai, config, doors, excel, pdfdoc
from .extract import extract_page
from .pdfdoc import PDF_LOCK

log = logging.getLogger("glassx.pipeline")
_DOCS: "OrderedDict[str, object]" = OrderedDict()
_DOCS_LOCK = threading.Lock()


def doc_id_for(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]


def valid_id(doc_id: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{16}", doc_id or ""))


def store_pdf(data: bytes, name: str) -> str:
    config.ensure_dirs()
    did = doc_id_for(data)
    path = os.path.join(config.DOC_DIR, did + ".pdf")
    if not os.path.exists(path):                     # several people may open the same PDF at once
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    with open(os.path.join(config.DOC_DIR, did + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"name": name, "opened": time.time()}, fh)
    return did


def pdf_path(doc_id: str) -> str:
    return os.path.join(config.DOC_DIR, doc_id + ".pdf")


def get_doc(doc_id: str):
    with _DOCS_LOCK:
        d = _DOCS.get(doc_id)
        if d is None:
            p = pdf_path(doc_id)
            if not os.path.exists(p):
                raise FileNotFoundError("PDF not found - open it again")
            d = pdfdoc.open_pdf(p)
            _DOCS[doc_id] = d
            while len(_DOCS) > 8:
                _, old = _DOCS.popitem(last=False)
                with PDF_LOCK:
                    old.close()
        else:
            _DOCS.move_to_end(doc_id)
        return d


def page_sizes(doc_id: str) -> list:
    d = get_doc(doc_id)
    with PDF_LOCK:
        return [{"w": round(p.rect.width, 2), "h": round(p.rect.height, 2)} for p in d]


def extract(doc_id: str, pno: int, use_cache: bool = True, ai_mode: str | None = None) -> dict:
    """Extract one page, cached on disk per engine version (re-opening a PDF is instant).
    ai_mode: None = AI settings decide (picture / scanned pages when AI is on), "force" = read with AI now (the
    AI read button), "off" = never."""
    cp = os.path.join(config.EXTRACT_CACHE, f"{doc_id}_{pno}_v{ENGINE_VERSION}.json")
    if use_cache and os.path.exists(cp):
        try:
            with open(cp, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    t0 = time.perf_counter()
    d = get_doc(doc_id)
    pd = pdfdoc.read_page(d, pno)
    res = extract_page(pd, pno)
    raster = pd.method == "ocr"
    regions = _needs_hybrid(res, pd) if pd.method == "text" else []
    if regions:
        # elevations found but values missing: they are probably drawn as graphics -> read those areas with OCR too
        pd2 = pdfdoc.read_page(d, pno, hybrid=regions)
        if pd2.method == "text+ocr":
            res2 = extract_page(pd2, pno)
            if _score(res2) > _score(res):
                for el in res2["elevations"]:
                    el["notes"].insert(0, "Some values on this page are drawings, not text - read by OCR, check them")
                res = res2
    if pd.method == "text" and not res["elevations"]:
        # nothing in the text layer: the elevations may be a pasted picture (scan / screenshot placed on the FM
        # template) or CAD text exported as outlines -> read those parts of the page with OCR
        pics = pdfdoc.graphic_regions(d, pno)
        if pics:
            pd2 = pdfdoc.read_page(d, pno, hybrid=pics)
            if pd2.method == "text+ocr":
                res2 = extract_page(pd2, pno)
                raster = True
                if res2["elevations"]:
                    for el in res2["elevations"]:
                        el["notes"].insert(0, "This drawing is a picture, not text - read by OCR, check every value")
                    res, pd = res2, pd2
    if not res["elevations"] and pd.method == "text" and sum(len(t.t) for t in pd.tokens) < 10:
        from . import ocr
        why = ocr.disabled_reason()
        with pdfdoc.PDF_LOCK:
            has_pic = bool(d[pno].get_images())
        if why and has_pic:                                          # scanned / picture page and this server cannot OCR it
            raster = True
            res["ocr_off"] = why
            res["notes"] = list(res.get("notes") or []) + [
                f"Scanned / picture page - not read: {why}. Use the office version (run_app.bat) for scanned PDFs."]
    _ocr_missing_numbers(d, pno, res)
    res["doors"] = doors.build_doors(res, dict(getattr(pd, "swing", None) or {}, vlines=pd.vlines))
    res["raster"] = raster
    if ai_mode == "force" or (ai_mode is None and raster and ai.auto_on()):
        res = _ai_read(d, pno, res, pd, forced=ai_mode == "force")
    elif ai_mode is None and not raster and res["elevations"] and ai.auto_on() and ai.weak(res):
        # vector page with gaps (outlined / pictured values): AI fills only what the exact text read is missing
        try:
            n = ai.fill_gaps(res, ai.read_page(d, pno))
            if n:
                res["method"] = res.get("method", "text") + "+ai"
                res["doors"] = doors.build_doors(res, dict(getattr(pd, "swing", None) or {}, vlines=pd.vlines))
        except Exception as e:                                                # noqa: BLE001
            res["notes"].append("AI could not fill the missing values: " + ai._friendly(e))
    res["ms"] = int((time.perf_counter() - t0) * 1000)
    try:
        with open(cp, "w", encoding="utf-8") as fh:
            json.dump(res, fh)
    except Exception:
        pass
    log.info("doc %s page %d: %d elevation(s), %s, %d ms", doc_id, pno, len(res["elevations"]), res["method"], res["ms"])
    return res


def _ai_read(d, pno, res, pd, forced=False):
    """Read the page with Claude; keep the OCR / text result when AI is off, fails or finds nothing."""
    if not ai.configured():
        if forced:
            res["notes"].append("AI reading is not set up - add the API key in AI settings (host PC)")
            res["ai_error"] = "AI reading is not set up"
        return res
    try:
        out = ai.read_page(d, pno)
    except Exception as e:                                                    # noqa: BLE001
        msg = ai._friendly(e)
        log.warning("AI read failed on page %d: %s", pno, msg)
        res["notes"].append("AI read failed - showing the OCR / text read: " + msg)
        res["ai_error"] = msg
        return res
    if not out["elevations"]:
        res["notes"].append("AI found no elevation on this page - showing the OCR / text read")
        return res
    ai.cross_check(out["elevations"], pd.tokens)
    new = {"page": pno, "method": "ai", "ai_model": out["model"], "raster": res.get("raster", False),
           "elevations": out["elevations"], "notes": [], "candidates": res.get("candidates", [])}
    new["doors"] = doors.build_doors(new, None)
    ai.apply_doors(new, out["ai_doors"])
    return new


def _score(res: dict) -> int:
    return sum(1 for e in res["elevations"] for p in e["panels"] for s in ("L", "R") for k in ("u", "l") if p[s][k])


def _needs_hybrid(res: dict, pd) -> list:
    """Areas worth a second read with OCR: elevations with glass tags but no readable values, and elevations where
    more than a quarter of the exported cells are blank. Empty list = nothing to retry."""
    regions = [list(r) for r in res.get("unread", [])]
    for e in res["elevations"]:
        cells = [p[s][k] for p in e["panels"] if p["export"] for s in ("L", "R") for k in ("u", "l")]
        if cells and sum(1 for c in cells if not c) > 0.25 * len(cells) and e.get("bbox"):
            x0, y0, x1, y1 = e["bbox"]
            regions.append([x0 - 40, y0 - 60, x1 + 40, max(y1, e["title_box"][3]) + 60])
    return regions if len(pd.tokens) < 6000 else []


def _ocr_missing_numbers(doc, pno: int, res: dict):
    """Circled elevation numbers drawn as graphics (not text) are read by OCR from the circle left of the title."""
    missing = [e for e in res["elevations"] if not e["elev"]]
    if not missing:
        return
    try:
        from . import ocr
        if not ocr.available():
            return
        import numpy as np
        import pymupdf
        with PDF_LOCK:
            page = doc[pno]
            for e in missing:
                x0, y0, x1, y1 = e["title_box"]
                h = max(y1 - y0, 6)
                clip = pymupdf.Rect(x0 - 5 * h, y0 - 1.6 * h, x0 + 0.5, y1 + 1.6 * h) * page.derotation_matrix
                clip.normalize()
                pix = page.get_pixmap(matrix=pymupdf.Matrix(8, 8), clip=clip, alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                found = _circle_digits(img, ocr)
                if found:
                    num = found
                    e["elev"] = num
                    e["notes"].append(f"Elevation number {num} read from the circle by OCR - check it")
    except Exception as ex:  # pragma: no cover - OCR is optional
        log.warning("OCR of elevation number failed: %s", ex)


def _circle_digits(img, ocr) -> str:
    """Find the ring left of the title, crop inside it and recognise the digits (no detection step:
    detectors miss a lone digit inside a circle)."""
    import cv2
    import numpy as np
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    ink = (gray < 150).astype(np.uint8)
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, 120), np.uint8)) | \
        cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((120, 1), np.uint8))      # frame lines, not the ring
    ink = ink & (1 - lines)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    H, W = ink.shape
    comps = sorted((tuple(stats[i][:4]) for i in range(1, n) if stats[i][4] > 15), key=lambda c: c[0])
    groups = []                                       # marks that touch / nearly touch = one symbol (ring + digit)
    for x, y, w, h in comps:
        for g in groups:
            if x <= g[2] + 25 and x + w >= g[0] - 25 and y <= g[3] + 25 and y + h >= g[1] - 25:
                g[0], g[1], g[2], g[3] = min(g[0], x), min(g[1], y), max(g[2], x + w), max(g[3], y + h)
                break
        else:
            groups.append([x, y, x + w, y + h])
    crops = []
    for gx0, gy0, gx1, gy1 in sorted(groups, key=lambda g: -g[2]):   # right-most first (next to the title)
        w, h = gx1 - gx0, gy1 - gy0
        if h < 40:
            continue
        ring = 0.7 < w / max(h, 1) < 1.4
        m = 0.17 if ring else 0.0
        crops.append(img[int(gy0 + m * h):int(gy1 - m * h), int(gx0 + m * w):int(gx1 - m * w)])
        break
    for crop in crops:
        if crop.size == 0:
            continue
        pad = np.full((crop.shape[0] + 40, crop.shape[1] + 40, 3), 255, dtype=np.uint8)
        pad[20:-20, 20:-20] = crop
        t, c = ocr.read_word(pad)
        t = t.strip("() .")
        if re.fullmatch(r"\d{1,3}", t) and c > 0.5:
            return t
    return ""


def process_pdf(path: str, use_cache: bool = True) -> dict:
    """Whole PDF -> {"name", "pages", "elevations", "notes"} (used by CLI batch and self-test)."""
    with open(path, "rb") as fh:
        data = fh.read()
    did = store_pdf(data, os.path.basename(path))
    n = len(page_sizes(did))
    els, notes, drs = [], {}, []
    for p in range(n):
        r = extract(did, p, use_cache)
        els += r["elevations"]
        drs += r.get("doors", [])
        if r["notes"]:
            notes[p] = r["notes"]
    return {"doc_id": did, "name": os.path.basename(path), "pages": n, "elevations": els, "notes": notes, "doors": drs}


def export_to(elevations: list, pdf_name: str, out_dir: str | None = None, doors: list | None = None) -> str:
    """<PDF name>.xlsx with tabs GLASS and DOOR."""
    out_dir = out_dir or config.EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, excel.xlsx_name(pdf_name))
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(excel.export_bytes(elevations, doors))
    os.replace(tmp, path)
    return path


def export_doors_to(door_list: list, pdf_name: str, out_dir: str | None = None) -> str:
    out_dir = out_dir or config.EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, excel.xlsx_door_name(pdf_name))
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(excel.export_doors_bytes(door_list))
    os.replace(tmp, path)
    return path


def clear_cache():
    shutil.rmtree(config.EXTRACT_CACHE, ignore_errors=True)
    config.ensure_dirs()
