"""Optional OCR for scanned pages (RapidOCR / PaddleOCR models on ONNX Runtime, fully offline).
The rest of the app works without it."""
from __future__ import annotations

import logging
import threading

_ENGINE = None
_ERR = None
_LOCK = threading.Lock()
log = logging.getLogger("glassx.ocr")


def _load():
    global _ENGINE, _ERR
    if _ENGINE is not None or _ERR is not None:
        return _ENGINE
    with _LOCK:
        if _ENGINE is None and _ERR is None:
            try:
                try:                                   # rapidocr >= 2 (newer, more accurate models)
                    from rapidocr import RapidOCR  # type: ignore
                    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                    _ENGINE = ("v2", RapidOCR())
                    for name in ("RapidOCR", "rapidocr"):
                        logging.getLogger(name).setLevel(logging.ERROR)
                except ImportError:
                    from rapidocr_onnxruntime import RapidOCR  # type: ignore
                    _ENGINE = ("v1", RapidOCR())
            except Exception as e:  # pragma: no cover
                _ERR = str(e)
                log.warning("OCR unavailable: %s", e)
    return _ENGINE


def available() -> bool:
    return _load() is not None


def read_lines(img) -> list:
    """-> [(box[[x,y]x4], text, confidence)]"""
    eng = _load()
    if not eng:
        return []
    ver, engine = eng
    with _LOCK:
        if ver == "v1":
            res, _ = engine(img, use_det=True, use_cls=True, use_rec=True)
            return [(box, txt, float(conf)) for box, txt, conf in (res or [])]
        r = engine(img, use_det=True, use_cls=True, use_rec=True)      # flags are sticky in rapidocr 2: always pass them
        if r is None or getattr(r, "txts", None) is None:
            return []
        boxes = getattr(r, "boxes", None)
        boxes = boxes if boxes is not None else [None] * len(r.txts)
        return [(b.tolist() if hasattr(b, "tolist") else b, t, float(s)) for b, t, s in zip(boxes, r.txts, r.scores)]


def read_word(img) -> tuple:
    """Recognise one short word in a tight crop (no text detection step) -> (text, confidence)."""
    eng = _load()
    if not eng:
        return "", 0.0
    ver, engine = eng
    with _LOCK:
        if ver == "v1":
            res, _ = engine(img, use_det=False, use_cls=False, use_rec=True)
            if res:
                t, c = res[0][0], res[0][1]
                return str(t), float(c)
            return "", 0.0
        r = engine(img, use_det=False, use_cls=False, use_rec=True)
        txts = getattr(r, "txts", None)
        if txts:
            return str(txts[0]), float(r.scores[0])
        return "", 0.0
