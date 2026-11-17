import io

import openpyxl

from glassx import excel, pipeline, synth


def _export(tmp_path):
    path = str(tmp_path / "fm.pdf")
    synth.build_fm_pdf(path, synth.reference_project())
    r = pipeline.process_pdf(path, use_cache=False)
    return r, excel.export_bytes(r["elevations"])


def test_template_layout_and_cached_values(tmp_path):
    r, data = _export(tmp_path)
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)     # cached values only
    assert wb.sheetnames == ["GLASS", "DOOR"]                          # one workbook, both tabs
    ws = wb["GLASS"]
    assert [ws[c + "2"].value for c in "BCEGIKMO"] == ["ELEV", "Tag", "UPPER", "LOWER", "TOTAL", "Difference",
                                                      "JUDGEMENT", "Fraction"]
    assert ws["A4"].value == "START ON THIS ROW-->"
    # elevation 1: 63-A rows 5-6, 63-B rows 8-9 ; elevation 2 (63-C, door skipped) starts at row 12
    assert (ws["B5"].value, ws["C5"].value, ws["C8"].value, ws["B12"].value, ws["C12"].value) == (1, "63-A", "63-B", 2, "63-C")
    assert ws["I5"].value == 107.25 and ws["I6"].value == 107.375
    assert ws["K5"].value == -0.125 and ws["M5"].value == 107.25 and ws["O5"].value == 107.25
    assert ws["C6"].value is None and ws["B8"].value is None


def test_formulas_present(tmp_path):
    _, data = _export(tmp_path)
    ws = openpyxl.load_workbook(io.BytesIO(data))["GLASS"]
    assert ws["I5"].value.startswith("=IF(") and "FLOOR" in ws["M5"].value and ws["O5"].value.startswith("=IF(ISNUMBER")


def test_layout_rows_spacing():
    mk = lambda e, n: {"elev": str(e), "panels": [{"export": True, "tag": f"{e}-{i}", "L": {}, "R": {}} for i in range(n)]}  # noqa
    rows = [r for r, *_ in excel.layout_rows([mk(2, 1), mk(1, 2)])]
    assert rows == [5, 8, 12]          # elev 1: 5,8  | 2 blank rows | elev 2: 12


def test_xlsx_name():
    assert excel.xlsx_name("14002_Westbend South Multi-Family_FMs REVISED-[VRF KC-10 JUL 2026].pdf") == \
        "14002_Westbend South Multi-Family_FMs REVISED-[VRF KC-10 JUL 2026].xlsx"
    assert excel.xlsx_name('a:b*c?.pdf') == "a_b_c_.xlsx"


def test_cached_values_match_excel_recalculation(tmp_path):
    """The stored results must equal what a spreadsheet engine computes from the formulas."""
    import shutil
    import subprocess
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        import pytest
        pytest.skip("LibreOffice not installed")
    _, data = _export(tmp_path)
    src = tmp_path / "in.xlsx"
    src.write_bytes(data)
    out = tmp_path / "out"
    subprocess.run([soffice, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(out), str(src)],
                   check=True, capture_output=True, timeout=120)
    a = openpyxl.load_workbook(io.BytesIO(data), data_only=True)["GLASS"]
    b = openpyxl.load_workbook(out / "in.xlsx", data_only=True)["GLASS"]
    checked = 0
    for row in a.iter_rows(min_row=5, max_row=60):
        for c in row:
            if c.column_letter in "IKMO" and c.value not in (None, ""):
                checked += 1
                assert b[c.coordinate].value == c.value, c.coordinate
    assert checked > 30


def test_one_workbook_glass_and_door_tabs(tmp_path):
    """Both tabs carry their own cached results (same cell names on both sheets must not mix)."""
    path = str(tmp_path / "fm.pdf")
    synth.build_fm_pdf(path, synth.reference_project())
    r = pipeline.process_pdf(path, use_cache=False)
    wb = openpyxl.load_workbook(io.BytesIO(excel.export_bytes(r["elevations"], r["doors"])), data_only=True)
    assert wb.sheetnames == ["GLASS", "DOOR"] and wb.active.title == "GLASS"
    g, d = wb["GLASS"], wb["DOOR"]
    assert g["I5"].value == 107.25 and g["M5"].value == 107.25
    # door 63 (team DOOR sheet): totals 107 3/8 | 107 5/16 | 107 3/16 | 107 1/4, Diff 1/16, FINAL 107 5/16
    assert [d[f"{c}4"].value for c in "CDEF"] == [107.375, 107.3125, 107.1875, 107.25]
    assert d["G3"].value == 0.0625 and d["H4"].value == 107.3125
    f = openpyxl.load_workbook(io.BytesIO(excel.export_bytes(r["elevations"], r["doors"])))
    assert f["GLASS"]["I5"].value.startswith("=IF(") and f["DOOR"]["C4"].value == "=C2+C3"
    assert excel.export_bytes(r["elevations"])[:2] == b"PK"           # no doors -> empty DOOR template tab
