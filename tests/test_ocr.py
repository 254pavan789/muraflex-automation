import pytest

from glassx import ocr, pipeline, synth


@pytest.mark.skipif(not ocr.available(), reason="OCR engine not installed")
def test_scanned_sheet_is_read_and_flagged(tmp_path):
    import pymupdf
    vec = tmp_path / "v.pdf"
    synth.build_fm_pdf(str(vec), [synth.reference_project()[1]], cover=False, notes=False)
    src, out = pymupdf.open(str(vec)), pymupdf.open()
    for pg in src:
        p = out.new_page(width=pg.rect.width, height=pg.rect.height)
        p.insert_image(p.rect, pixmap=pg.get_pixmap(dpi=200))
    scan = tmp_path / "scan.pdf"
    out.save(str(scan))
    r = pipeline.process_pdf(str(scan), use_cache=False)
    assert r["elevations"], "OCR found no elevations"
    assert all("OCR" in e["notes"][0] for e in r["elevations"])      # every OCR elevation is flagged for checking
    values = [v for e in r["elevations"] for p in e["panels"] for v in (p["L"]["u"], p["L"]["l"])]
    assert sum(1 for v in values if v) >= len(values) // 2


def _picture_fm_pdf(path, dpi=110):
    """14101 Sherritt style: the elevations are a PICTURE pasted on the FM template (no text for titles or values),
    and the values use one-glyph fractions 54¼ 49½" 49⅝" 50⅛" written in red."""
    import pymupdf
    helv = pymupdf.Font("helv")
    src = pymupdf.open()
    pg = src.new_page(width=1224, height=792)
    red = (0.92, 0.25, 0.25)

    def txt(x, y, s, size=9, color=(0, 0, 0), font=helv):
        tw = pymupdf.TextWriter(pg.rect, color=color)
        tw.append((x, y), s, font=font, fontsize=size)
        tw.write_text(pg)
    for x0, num, room, lows in ((150, "1", "1308", ['49½"', '49⅝"', '49⅝"', '50"']),
                                (650, "2", "1306", ['50"', '49¾"', '50⅛"', '50¼"'])):
        edges = [x0, x0 + 90, x0 + 170, x0 + 250]
        pg.draw_rect(pymupdf.Rect(x0, 300, edges[-1], 520), width=0.6)
        for ex in edges[1:-1]:
            pg.draw_line((ex, 300), (ex, 520), width=0.6)
        pg.draw_line((x0, 410), (edges[-1], 410), width=0.4, dashes="[6 3] 0")
        for i, (c, t) in enumerate((("GSD-12", room), ("OGL-12", room + "-B"), ("OGL-12", room + "-C"))):
            cx = (edges[i] + edges[i + 1]) / 2
            txt(cx - 15, 395, c, 7)
            txt(cx - 13, 404, t, 7)
        for ex, lo in zip(edges, lows):
            txt(ex - 18, 340, "54¼", 20, red)
            txt(ex - 22, 470, lo, 20, red)
        pg.draw_circle((x0 + 5, 560), 8, width=0.6)
        txt(x0 + 2, 564, num, 9)
        txt(x0 + 18, 564, "ELEVATION / PRIVATE OFFICE " + room, 10)
    pix = pg.get_pixmap(dpi=dpi, clip=pymupdf.Rect(0, 0, 1224, 640))
    doc = pymupdf.open()
    page = doc.new_page(width=1224, height=792)
    page.insert_image(pymupdf.Rect(0, 0, 1224, 640), pixmap=pix)
    page.insert_text((60, 720), "PROJECT / DRAWING NO.:  14101", fontsize=10)      # the template is real text
    page.insert_text((800, 760), "FIELD MEASUREMENT SHEET", fontsize=7)
    doc.save(path)


@pytest.mark.skipif(not ocr.available(), reason="OCR not installed")
def test_picture_page_with_one_glyph_fractions(tmp_path):
    """No elevation in the text layer -> the pasted picture is read by OCR, and 54¼ / 49⅝" (which OCR reads as
    '54%4' / '49%"') are recognised glyph by glyph."""
    from glassx import pipeline
    path = str(tmp_path / "14101_pic.pdf")
    _picture_fm_pdf(path)
    r = pipeline.process_pdf(path, use_cache=False)
    els = {e["elev"]: e for e in r["elevations"]}
    assert set(els) == {"1", "2"}
    assert [p["u"] for p in els["1"]["points"]] == ["54 1/4"] * 4
    assert [p["l"] for p in els["1"]["points"]] == ["49 1/2", "49 5/8", "49 5/8", "50"]
    assert [p["l"] for p in els["2"]["points"]] == ["50", "49 3/4", "50 1/8", "50 1/4"]
    assert "picture" in els["1"]["notes"][0]
    assert {d["tag"] for d in r["doors"]} == {"1308", "1306"} and all(d["type"] == "Sliding" for d in r["doors"])


def test_fraction_glyph_classifier_on_rendered_values():
    import pymupdf
    from glassx import fracglyph
    helv = pymupdf.Font("helv")
    doc = pymupdf.open()
    pg = doc.new_page(width=600, height=200)
    vals = ["54¼", '49½"', '49⅝"', '50⅛"', '49¾"', "48⅜", '47⅞"']
    for i, v in enumerate(vals):
        tw = pymupdf.TextWriter(pg.rect, color=(0.9, 0.2, 0.2))
        tw.append((20 + i * 80, 100), v, font=helv, fontsize=18)
        tw.write_text(pg)
    got = []
    for i, v in enumerate(vals):
        x = 20 + i * 80
        w = helv.text_length(v, 18)
        got.append(fracglyph.repair(pg, v[:2] + "%" + '"', [x, 86, x + w, 102]))
    assert got == ['54 1/4"', '49 1/2"', '49 5/8"', '50 1/8"', '49 3/4"', '48 3/8"', '47 7/8"']
