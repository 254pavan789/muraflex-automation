"""DOOR module: door points (A / B / C1 / C2), the DOOR sheet and its API."""
import io
import os
import zipfile

import openpyxl
import pytest

from glassx import doors, excel, pipeline, synth
from glassx.server import create_app

REAL = os.path.join(os.path.dirname(__file__), "real_pdfs")


def _pts(d, keys=("A", "B", "C1", "C2")):
    return tuple((d["pts"][k]["u"], d["pts"][k]["l"]) for k in keys if k in d["pts"])


def test_door_type():
    for c in ("GSD-12", "FSD", "GPSD-12", "GFSD", "QSD-12", "GSTD-12", "SD"):
        assert doors.door_type(c) == "Sliding", c
    for c in ("FPD-OLIGL", "GPD-12", "GHD", "MFD", "FPD-DGO", "", "OGL-12"):
        assert doors.door_type(c) == "Pivot", c


@pytest.mark.parametrize("kw", [{}, {"rows_per_page": 2}, {"use_annots": True}, {"stacked": "cad"},
                                 {"rows_per_page": 2, "width_above_frame": True}])
def test_reference_pivot_doors(tmp_path, kw):
    """Hinge side from the swing plan, C1 / C2 = the other swing readings with B / A uppers."""
    specs = synth.reference_project()
    path = str(tmp_path / "ref.pdf")
    synth.build_fm_pdf(path, specs, **kw)
    r = pipeline.process_pdf(path, use_cache=False)
    got = [(d["elev"], d["tag"], *_pts(d)) for d in r["doors"]]
    assert got == synth.expected_doors(specs)
    assert all(d["type"] == "Pivot" and not d["notes"] for d in r["doors"])


def test_door_totals_and_final():
    d = {"type": "Pivot", "pts": {"A": {"u": "50", "l": "57 3/8"}, "B": {"u": "49 15/16", "l": "57 3/8"},
                                  "C1": {"u": "49 15/16", "l": "57 1/4"}, "C2": {"u": "50", "l": "57 1/4"}}}
    tots, diff, final = doors.totals(d)
    assert tots == {"A": 107.375, "B": 107.3125, "C1": 107.1875, "C2": 107.25}
    assert diff == 0.0625 and final == 107.3125


def _door(elev, tag, typ, vals):
    keys = ("A", "B", "C1", "C2")[:len(vals)]
    return {"elev": elev, "tag": tag, "code": "", "type": typ, "export": True, "notes": [],
            "pts": {k: {"u": u, "l": l} for k, (u, l) in zip(keys, vals)}}


def test_door_sheet_layout():
    """Matches the team DOOR sheet: pivot blocks in A / C-H, sliding blocks in J / K-O, 4 rows per door."""
    ds = [_door("2", "63", "Pivot", [("50", "57 3/8"), ("49 15/16", "57 3/8"), ("49 15/16", "57 1/4"), ("50", "57 1/4")]),
          _door("1", "745", "Sliding", [("48", "54"), ("48", "54 1/8"), ("48", "54 1/8")]),
          _door("2", "738", "Sliding", [("48", "54 3/8"), ("48", "54 9/16"), ("48", "54 3/4")]),
          dict(_door("9", "x", "Pivot", [("1", "1"), ("1", "1")]), export=False)]
    data = excel.export_doors_bytes(ds)
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    assert wb.sheetnames == ["DOOR"]
    ws = wb["DOOR"]
    assert [ws[c].value for c in ("A1", "C1", "D1", "E1", "F1", "G1", "K1", "L1", "M1", "N1")] == \
        ["ELEV NO", "A", "B", "C1", "C2", "PIVOT DOOR", "A", "B", "C1", "SLIDING DOOR"]
    assert {str(m) for m in ws.merged_cells.ranges} >= {"G1:H1", "N1:O1"}
    # pivot block rows 2-4
    assert ws["A2"].value == 2 and [ws[f"{c}2"].value for c in "CDEF"] == [50, 49.9375, 49.9375, 50]
    assert [ws[f"{c}3"].value for c in "CDEF"] == [57.375, 57.375, 57.25, 57.25]
    assert [ws[f"{c}4"].value for c in "CDEF"] == [107.375, 107.3125, 107.1875, 107.25]
    assert (ws["G2"].value, ws["H2"].value, ws["G3"].value, ws["H4"].value) == ("Diff", "FINAL", 0.0625, 107.3125)
    # sliding blocks rows 2-4 and 6-8 (the user's 14075 example)
    assert ws["J2"].value == 1 and [ws[f"{c}4"].value for c in "KLM"] == [102, 102.125, 102.125] and ws["O4"].value == 102
    assert ws["J6"].value == 2 and ws["N7"].value == -0.1875 and ws["O8"].value == 102.375
    assert ws["A6"].value is None                       # the unticked pivot door is not exported
    assert ws["C8"].value == 0 and ws["H8"].value == 0  # empty template blocks show 0 like the team sheet
    f = openpyxl.load_workbook(io.BytesIO(data))["DOOR"]
    assert f["C4"].value == "=C2+C3" and f["G3"].value == "=C4-D4" and "FLOOR" in f["H4"].value
    assert f["N3"].value == "=K4-L4" and "MIN(K4,L4)" in f["O4"].value
    assert f["C4"].fill.start_color.rgb.endswith("D9D9D9") and f["H4"].fill.start_color.rgb.endswith("FFFF00")
    assert "745" in (f["J2"].comment.text if f["J2"].comment else "")


def test_door_sheet_matches_recalculation(tmp_path):
    import shutil
    import subprocess
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        pytest.skip("LibreOffice not installed")
    specs = synth.reference_project()
    path = str(tmp_path / "ref.pdf")
    synth.build_fm_pdf(path, specs)
    r = pipeline.process_pdf(path, use_cache=False)
    extra = [_door("1", "745", "Sliding", [("48", "54"), ("48", "54 1/8"), ("48", "54 1/8")]),
             _door("3", "z", "Sliding", [("48", "54"), ("48", "55 1/2"), ("48", "54")])]
    src = tmp_path / "in.xlsx"
    src.write_bytes(excel.export_bytes(r["elevations"], r["doors"] + extra))      # the real one-workbook export
    out = tmp_path / "out"
    subprocess.run([soffice, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(out), str(src)],
                   check=True, capture_output=True, timeout=120)
    a = openpyxl.load_workbook(src, data_only=True)["DOOR"]
    b = openpyxl.load_workbook(out / "in.xlsx", data_only=True)["DOOR"]
    n = 0
    for row in a.iter_rows(min_row=2, max_row=50):
        for c in row:
            if c.value not in (None, "") and c.column_letter in "CDEFGHKLMNO":
                n += 1
                assert b[c.coordinate].value == c.value, c.coordinate
    assert n > 100


def test_glass_sheet_never_has_doors():
    el = {"elev": "1", "panels": [{"export": True, "kind": "Fixed", "tag": "1-A", "L": {}, "R": {}},
                                  {"export": True, "kind": "Door", "tag": "1", "L": {}, "R": {}}]}
    assert [p["tag"] for *_, p in excel.layout_rows([el])] == ["1-A"]


def test_door_names():
    assert excel.xlsx_door_name("14075_MCC Washington_FMs-[VRF KC-07 OCT 2026].pdf") == \
        "14075_MCC Washington_FMs-[VRF KC-07 OCT 2026] - DOOR.xlsx"


def test_door_api(tmp_path):
    path = tmp_path / "14002 FM.pdf"
    synth.build_fm_pdf(str(path), synth.reference_project())
    c = create_app().test_client()
    html = c.get("/").data
    assert b"cardGlass" in html and b"cardDoor" in html and b">GLASS<" in html and b">DOOR<" in html
    r = c.post("/api/open", data={"file": (open(path, "rb"), "14002 FM.pdf")}, content_type="multipart/form-data").json
    ds = []
    for p in range(4):
        ds += c.post("/api/extract", json={"doc_id": r["doc_id"], "page": p}).json["doors"]
    assert len(ds) == 3
    x = c.post("/api/export", json={"pdf_name": "14002 FM.pdf", "elevations": [], "doors": ds})
    assert x.status_code == 200 and "14002 FM.xlsx" in x.headers["Content-Disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(x.data), data_only=True)
    assert wb.sheetnames == ["GLASS", "DOOR"] and wb["DOOR"]["H4"].value == 107.3125
    z = c.post("/api/export_zip", json={"files": [{"pdf_name": "a.pdf", "doors": ds}, {"pdf_name": "b.pdf", "doors": []}]})
    assert sorted(zipfile.ZipFile(io.BytesIO(z.data)).namelist()) == ["a.xlsx", "b.xlsx"]
    x = c.post("/api/export_doors", json={"pdf_name": "14002 FM.pdf", "doors": ds})       # old route: same workbook
    assert "14002 FM.xlsx" in x.headers["Content-Disposition"]
    assert c.post(f"/api/session/{r['doc_id']}", json={"els": [], "doors": ds}).json["ok"]
    assert len(c.get(f"/api/session/{r['doc_id']}").json["doors"]) == 3


def _real(prefix):
    if not os.path.isdir(REAL):
        return None
    for f in os.listdir(REAL):
        if f.startswith(prefix) and f.lower().endswith(".pdf"):
            return os.path.join(REAL, f)
    return None


def test_real_14075_sliding_doors_match_team_example():
    p = _real("14075")
    if not p:
        pytest.skip("real PDF not present")
    r = pipeline.process_pdf(p, use_cache=False)
    got = [(d["elev"], d["type"], _pts(d), doors.totals(d)[2]) for d in r["doors"]]
    assert got == [("1", "Sliding", (("48", "54"), ("48", "54 1/8"), ("48", "54 1/8")), 102),
                   ("2", "Sliding", (("48", "54 3/8"), ("48", "54 9/16"), ("48", "54 3/4")), 102.375)]


def test_real_14005_pivot_doors_have_swing_readings():
    p = _real("14005")
    if not p:
        pytest.skip("real PDF not present")
    r = pipeline.process_pdf(p, use_cache=False)
    assert [d["elev"] for d in r["doors"]] == ["2", "4", "5", "7", "9"]
    for d in r["doors"]:
        assert d["type"] == "Pivot" and not d["notes"], d
        assert all(d["pts"][k]["l"] for k in ("A", "B", "C1", "C2"))
        assert d["pts"]["C1"]["u"] == d["pts"]["B"]["u"] and d["pts"]["C2"]["u"] == d["pts"]["A"]["u"]
        assert d["hinge_src"] == "elevation"
    # the team's screenshot of ELEV 5: C2 = 65 13/16 at the open leaf tip, C1 = 65 15/16 at 45 deg, closed = 65 3/4
    e5 = r["doors"][2]
    assert (e5["hinge"], e5["pts"]["A"]["l"], e5["pts"]["B"]["l"]) == ("L", "65 5/8", "65 3/4")
    assert (e5["pts"]["C1"]["l"], e5["pts"]["C2"]["l"], e5["closed"]["l"]) == ("65 15/16", "65 13/16", "65 3/4")
    assert [d["hinge"] for d in r["doors"]] == ["L", "R", "L", "R", "R"]


def test_real_14092_hinge_and_swing():
    p = _real("14092")
    if not p:
        pytest.skip("real PDF not present")
    r = pipeline.process_pdf(p, use_cache=False)
    got = [(d["elev"], d["hinge"], d["pts"]["A"]["l"], d["pts"]["B"]["l"], d["pts"]["C1"]["l"], d["pts"]["C2"]["l"])
           for d in r["doors"]]
    assert got == [("1", "R", "60 7/16", "60 3/16", "60 1/16", "60 9/16"),
                   ("3", "L", "60 5/8", "60 5/8", "60 11/16", "60 9/16"),
                   ("5", "R", "60 11/16", "60 3/4", "60 7/8", "60 7/8"),
                   ("6", "R", "60 13/16", "60 3/4", "60 15/16", "60 15/16")]


@pytest.mark.parametrize("seed", range(8))
def test_door_fuzz(tmp_path, seed):
    """Random hinge side, plan drawn as an arc or only written, with / without the elevation 'V', stray values."""
    import random
    specs = synth.random_door_project(random.Random(seed), 2)
    path = str(tmp_path / "f.pdf")
    synth.build_fm_pdf(path, specs, seed=seed, rows_per_page=1 + seed % 2, use_annots=seed % 3 == 2)
    r = pipeline.process_pdf(path, use_cache=False)
    got = {(d["elev"], d["tag"]): _pts(d) for d in r["doors"]}
    flat = [s for pg in specs for s in pg]
    for ex, sp in zip(synth.expected_doors(specs), flat):
        if synth.door_determinable(sp):
            assert got.get((ex[0], ex[1])) == tuple(ex[2:]), (sp.hinge, sp.plan, sp.vmark, sp.stray)


def test_swing_geometry_reads_arc_and_v(tmp_path):
    import pymupdf
    from glassx import pdfdoc
    path = str(tmp_path / "ref.pdf")
    synth.build_fm_pdf(path, synth.reference_project())
    doc = pymupdf.open(path)
    g = pdfdoc.swing_geometry(doc[1])
    assert len(g["arcs"]) == 2                       # doors 63 (hinge left) and 20 (hinge right)
    a = sorted(g["arcs"], key=lambda a: a["c"][0])
    assert a[0]["closed"][0] > a[0]["c"][0] and a[1]["closed"][0] < a[1]["c"][0]
    assert abs(a[0]["tip"][0] - a[0]["c"][0]) < 1 and a[0]["tip"][1] < a[0]["c"][1]
    assert len([d for d in g["diag"] if d[3] - d[1] > 50]) == 4    # two V marks
