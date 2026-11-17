"""Settings (environment variables override defaults) and folder layout."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

if getattr(sys, "frozen", False):                         # PyInstaller build
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.environ.get("GLASS_DATA_DIR", os.path.join(BASE_DIR, "glass_data"))
DOC_DIR = os.path.join(DATA_DIR, "pdfs")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
EXTRACT_CACHE = os.path.join(DATA_DIR, "cache", "extract")
SESS_DIR = os.path.join(DATA_DIR, "sessions")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
LOG_DIR = os.path.join(DATA_DIR, "logs")
HOST = os.environ.get("GLASS_HOST", "0.0.0.0")      # 0.0.0.0 = reachable from other PCs on the office network
                                                   # 127.0.0.1 = this PC only
PORT = int(os.environ.get("GLASS_PORT", "8080"))
PUBLIC = os.environ.get("GLASS_PUBLIC", "").strip().lower() in ("1", "true", "yes")   # online copy, open to everyone
# online copy: the Claude API key is ignored unless the owner turns AI on for every visitor on purpose
AI_ONLINE = os.environ.get("GLASS_AI_ONLINE", "").strip().lower() in ("1", "true", "yes")
# OCR of scanned pages needs ~450 MB RAM and a real CPU core. on / off / auto (auto = off on tiny servers)
OCR_MODE = os.environ.get("GLASS_OCR", "auto").strip().lower()

# Domain constants ------------------------------------------------------------------
BM_RANGE = (15.0, 95.0)          # an upper / lower benchmark reading is always inside this range (inches)
FIXED_PREFIX = ("OLIGL", "OGLI", "LIGL", "OGL", "GL")
DOOR_PREFIX = ("FPD", "FSD", "MFD", "QSD", "GPD", "GHD", "GSD", "GPSD", "GFSD", "GSTD", "TD")
EDGE_WORDS = {"DW", "FAL", "CL", "FOM", "MW", "WALL", "COL", "EXT", "GWB"}


def set_data_dir(path: str):
    """Point every data folder at `path` (self-test, tests)."""
    global DATA_DIR, DOC_DIR, CACHE_DIR, EXTRACT_CACHE, SESS_DIR, EXPORT_DIR, LOG_DIR
    DATA_DIR = path
    DOC_DIR = os.path.join(path, "pdfs")
    CACHE_DIR = os.path.join(path, "cache")
    EXTRACT_CACHE = os.path.join(path, "cache", "extract")
    SESS_DIR = os.path.join(path, "sessions")
    EXPORT_DIR = os.path.join(path, "exports")
    LOG_DIR = os.path.join(path, "logs")
    ensure_dirs()


def ensure_dirs():
    for d in (DOC_DIR, CACHE_DIR, EXTRACT_CACHE, SESS_DIR, EXPORT_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)


def setup_logging(level=logging.INFO) -> logging.Logger:
    ensure_dirs()
    log = logging.getLogger("glassx")
    if log.handlers:
        return log
    log.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = RotatingFileHandler(os.path.join(LOG_DIR, "glassx.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    return log
