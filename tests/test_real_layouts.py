"""Regression tests for the 14005 Gibson Dunn FM layout (bugs seen on the user's screenshots, Oct 2026)."""
import random

import pymupdf
import pytest

from glassx import ocr, pdfdoc, pipeline, synth
from glassx.extract import dim_value, extract_page, find_titles, merge_value_tokens
from glassx.pdfdoc import Token

GREEN, RED = (0.15, 0.6, 0.2), (0.89, 0.1, 0.1)


def run_gd(tmp_path, pages, **kw):
    path = str(tmp_path / "gd.pdf")
    synth.build_fm_pdf_gd(path, pages, **kw)
    return pipeline.process_pdf(path, use_cache=False)


def glass(r):
    return {(e["elev"], p["tag"]): (p["L"]["u"], p["L"]["l"], p["R"]["u"], p["R"]["l"], p["kind"])
            for e in r["elevations"] for p in e["panels"] if p["kind"] != "No tag"}


def T(text, x, y=100, rgb=(227, 26, 26), size=7):
    return Token(text, [x, y - size, x + len(text) * size * 0.55, y], rgb, size)


# ------------------------------------------------------------------------------------------ values
@pytest.mark.parametrize("text,strict,expect", [
    ("66", False, 66), ("66", True, None),            # bare number: only in mark-up colour
    ("66'", True, 66), ("47' 15/16", True, 47.9375),  # apostrophe = inches on FM sheets
    ("48FT", True, 48), ("BM 48FT", True, 48), ("BM65'1/4", True, 65.25),
    ("5'-6 1/2\"", True, 66.5),                        # real feet-inches still work
    ("90°", False, None), ("123 1/2", False, None), ("3184", False, None),
])
def test_value_notations(text, strict, expect):
    assert dim_value(text, strict) == expect


def test_split_fraction_is_rejoined():
    toks = merge_value_tokens([T("65'", 100), T("13/16", 117), T("66", 300), T("1/16", 312), T("48", 500), T("FT", 510)])
    assert sorted(t.t for t in toks) == ["48 FT", "65' 13/16", "66 1/16"]


def test_far_fraction_is_not_joined():
    toks = merge_value_tokens([T("65'", 100), T("5/8", 160)])
    assert sorted(t.t for t in toks) == ["5/8", "65'"]


def test_lowercase_note_is_not_a_title():
    lines = [{"t": "ELEVATION / NOOK 3144", "bbox": [235, 645, 380, 655]},
             {"t": "Elevation 1 it is wood floor 5/8", "bbox": [200, 690, 380, 700]}]
    titles = find_titles(lines, [Token("1", [220, 644, 226, 655])])
    assert [(t["elev"], t["room"]) for t in titles] == [("1", "3144")]


def test_dashed_line_made_of_segments_is_one_line():
    doc = pymupdf.open(); p = doc.new_page(width=1224, height=792)
    for x in range(25, 1195, 9):
        p.draw_line((x, 510), (x + 5, 510), width=0.5)
    lines = pdfdoc.horizontal_lines(p)
    assert len(lines) == 1 and lines[0][3] and lines[0][2] - lines[0][1] > 1100


# ------------------------------------------------------------------------------------------ whole sheets
def test_gibson_dunn_screenshot_page(tmp_path):
    """Page 4 of 14005: side view (3) + corridor view (4) with a door and a vertical tag."""
    s3 = synth.random_spec_gd(random.Random(1), 3, "3100A", 1, single=True)
    s3.uppers, s3.lowers = [(48, "")], [(65, "13/16")]
    s4 = synth.random_spec_gd(random.Random(2), 4, "3110A", 4, door=True)
    s4.tags = [("OLIGL-12", "3110A-B"), ("OLIGL-12", "3110A-C"), ("FPD-OLIGL", "3110A"), ("OLIGL-12", "3110A-D")]
    s4.uppers = [(47, "15/16"), (48, ""), (48, ""), (48, ""), (48, "")]
    s4.lowers = [(65, "13/16"), (65, "9/16"), (65, "3/8"), (65, "1/4"), (65, "1/4")]
    s4.bm_edge, s4.lead, s4.vertical_first, s4.note = 4, False, False, True
    pages = [[s3, s4]]
    r = run_gd(tmp_path, pages)
    assert glass(r) == synth.expected(pages)
    e3 = next(e for e in r["elevations"] if e["elev"] == "3")
    assert any("side view" in n for n in e3["notes"])
    assert {p["kind"] for e in r["elevations"] for p in e["panels"] if p["tag"] == "3110A"} == {"Door"}


def test_existing_condition_span_not_exported(tmp_path):
    s = synth.random_spec_gd(random.Random(4), 10, "3184", 2)
    s.lead, s.bm_edge = True, 0
    r = run_gd(tmp_path, [[s]])
    el = r["elevations"][0]
    assert [p["kind"] for p in el["panels"]] == ["No tag", "Fixed", "Fixed"]
    assert not el["panels"][0]["export"]
    assert glass(r) == synth.expected([[s]])


@pytest.mark.parametrize("annots", [False, True])
def test_gibson_dunn_fuzz(tmp_path, annots):
    """30 random 14005-style PDFs; values as page text or as Bluebeam-style mark-ups."""
    total = wrong = 0
    for seed in range(30):
        pages = synth.random_project_gd(random.Random(seed))
        path = str(tmp_path / f"g{seed}.pdf")
        synth.build_fm_pdf_gd(path, pages, seed=seed, use_annots=annots)
        got, exp = glass(pipeline.process_pdf(path, use_cache=False)), synth.expected(pages)
        total += len(exp)
        wrong += sum(1 for k in exp if got.get(k) != exp[k]) + sum(1 for k in got if k not in exp)
    assert wrong == 0, f"{wrong}/{total} panels wrong"


def test_black_value_recovered_and_flagged(tmp_path):
    """One lower written in black among red ones is still used, with a note to check it."""
    s = synth.random_spec_gd(random.Random(9), 5, "3050", 2)
    s.lead, s.vertical_first, s.note, s.bm_edge = False, False, False, 0
    s.uppers = [(48, ""), (48, "1/8"), (48, "")]
    s.lowers = [(66, ""), (66, "1/16"), (66, "")]
    path = str(tmp_path / "b.pdf")
    synth.build_fm_pdf_gd(path, [[s]], cover=False)
    doc = pymupdf.open(path); p = doc[0]
    # overwrite the middle lower with a black copy
    hit = [w for w in p.get_text("words") if w[4] in ("66", "1/16") and w[1] > 560]
    mid = sorted(hit, key=lambda w: w[0])
    for w in mid:
        if w[4] == "1/16":
            p.add_redact_annot(pymupdf.Rect(w[:4]) + (-30, -1, 1, 1))
    p.apply_redactions()
    x = [w for w in mid if w[4] == "1/16"][0][0] - 14
    p.insert_text((x, mid[0][3] - 2), "66 1/16", fontsize=7, color=(0, 0, 0))
    doc.save(str(tmp_path / "b2.pdf"))
    r = pipeline.process_pdf(str(tmp_path / "b2.pdf"), use_cache=False)
    assert glass(r) == synth.expected([[s]])
    assert any("nearby value" in n for n in r["elevations"][0]["notes"])


@pytest.mark.skipif(not ocr.available(), reason="OCR engine not installed")
def test_circle_number_drawn_as_picture_is_read_by_ocr(tmp_path):
    s = synth.random_spec_gd(random.Random(6), 7, "3144", 2)
    s.num_img, s.lead, s.note = True, False, False
    r = run_gd(tmp_path, [[s]])
    el = r["elevations"][0]
    assert el["elev"] == "7" and any("OCR" in n for n in el["notes"])


@pytest.mark.parametrize("rot", [90, 270])
def test_rotated_cad_plot_pages(tmp_path, rot):
    """CAD plots are often stored sideways with /Rotate - text direction must be taken as displayed."""
    pages = synth.random_project_gd(random.Random(3), 2)
    src_path = str(tmp_path / "src.pdf")
    synth.build_fm_pdf_gd(src_path, pages, seed=3)
    src, out = pymupdf.open(src_path), pymupdf.open()
    for i in range(src.page_count):
        w, h = src[i].rect.width, src[i].rect.height
        p = out.new_page(width=h, height=w)
        p.show_pdf_page(p.rect, src, i, rotate=rot)
        p.set_rotation(rot)
    out.save(str(tmp_path / "rot.pdf"))
    assert glass(pipeline.process_pdf(str(tmp_path / "rot.pdf"), use_cache=False)) == synth.expected(pages)


@pytest.mark.skipif(not ocr.available(), reason="OCR engine not installed")
def test_values_pasted_as_pictures_are_read_by_ocr(tmp_path):
    """Mark-ups that are pictures, not text: OCR fills them in; anything it cannot read stays blank (never wrong)."""
    pages = synth.random_project_gd(random.Random(2), 1)
    path = str(tmp_path / "img.pdf")
    synth.build_fm_pdf_gd(path, pages, seed=2, use_images=True, cover=False)
    r = pipeline.process_pdf(path, use_cache=False)
    got, exp = glass(r), synth.expected(pages)
    cells = [(g, e) for k in exp for g, e in zip(got.get(k, ("",) * 5), exp[k])]
    assert sum(1 for g, e in cells if g == e) >= 0.9 * len(cells)
    assert all(g in ("", e) for g, e in cells)
    assert any("OCR" in n for e in r["elevations"] for n in e["notes"])


# ------------------------------------------------------------------------------------------ v3.2 layouts
from glassx.extract import _code_of, _join_title_lines, is_door  # noqa: E402


@pytest.mark.parametrize("code,door", [("OLIGL-12", False), ("CLIGL-12", False), ("DGL-12", False), ("GL-12", False),
                                       ("OGLI", False), ("FPD-OGL", True), ("FPD-DGO", True), ("GSD-12", True)])
def test_glass_and_door_codes_are_generic(code, door):
    assert _code_of(Token(code, [0, 0, 1, 1])) == code and is_door(code) == door


@pytest.mark.parametrize("word", ["ANGLE", "OFFICE", "SINGLE", "DW", "CL", "BY"])
def test_words_are_not_codes(word):
    assert _code_of(Token(word, [0, 0, 1, 1])) is None


@pytest.mark.parametrize("text,expect", [("42-1/16", 42.0625), ("60-5/8\"", 60.625), ("42- 3/8", 42.375)])
def test_hyphen_fractions(text, expect):
    assert dim_value(text, False) == expect


def test_split_title_pieces_are_joined():
    lines = [{"t": "ELEVATION /", "bbox": [86, 404, 144, 417]}, {"t": "OFFICE VIEW", "bbox": [86, 414, 132, 424]},
             {"t": "INT. ATTORNEY S.O. 3110A", "bbox": [146, 404, 270, 416]}]
    t = find_titles(lines, [Token("3", [71, 408, 76, 421])])
    assert [(x["elev"], x["name"], x["room"]) for x in t] == [("3", "INT. ATTORNEY S.O. 3110A", "3110A")]


def fam_rows(r):
    return sorted((e["elev"], p["tag"], p["L"]["u"], p["L"]["l"], p["R"]["u"], p["R"]["l"], p["kind"])
                  for e in r["elevations"] for p in e["panels"] if p["kind"] != "No tag")


@pytest.mark.parametrize("style", ["oc", "admin"])
def test_family_fuzz(tmp_path, style):
    """14092-style (one upper, lowers under the title, BY OTHERS, 'Deleted') and ADMIN-style (hyphen fractions,
    stacked lites) sheets, upright and as rotated CAD plots."""
    total = wrong = 0
    for seed in range(24):
        pages = synth.random_project_family(random.Random(seed), style)
        path = str(tmp_path / f"{style}{seed}.pdf")
        synth.build_fm_pdf_family(path, pages, style, seed=seed, rotate=[0, 90, 270][seed % 3])
        got, exp = fam_rows(pipeline.process_pdf(path, use_cache=False)), synth.expected_family(pages, style)
        total += len(exp)
        wrong += max(sum(1 for x in exp if x not in got), sum(1 for x in got if x not in exp))
    assert wrong == 0, f"{wrong}/{total} lites wrong"


def test_oc_rules_and_notes(tmp_path):
    rng = random.Random(5)
    a = synth.random_spec_oc(rng, 1, "717", 3)
    a.panels = [("GL-12", "BY OTHERS", "By others", False), ("FPD-OGL", "717", "Door", False),
                ("GL-12", "717-C", "Fixed", False)]
    b = synth.random_spec_oc(rng, 2, "720", 1, deleted=True)
    b.panels = [("DGL-12", "BY OTHERS", "By others", True)]
    pages = [[a, b]]
    b.uppers = [a.uppers[0]] * 2
    path = str(tmp_path / "oc.pdf")
    synth.build_fm_pdf_family(path, pages, "oc")
    r = pipeline.process_pdf(path, use_cache=False)
    assert fam_rows(r) == synth.expected_family(pages, "oc")
    e1, e2 = r["elevations"]
    assert {p["kind"]: p["export"] for p in e1["panels"]} == {"By others": False, "Door": False, "Fixed": True}
    assert any("under the title" in n for n in e1["notes"]) and any("One upper" in n for n in e1["notes"])
    assert any("taken from elevation 1" in n for n in e2["notes"]) and any("Deleted" in n for n in e2["notes"])


def test_admin_stacked_lites_share_edges(tmp_path):
    s = synth.random_spec_admin(random.Random(2), 19, "1917", 3)
    path = str(tmp_path / "ad.pdf")
    synth.build_fm_pdf_family(path, [[s]], "admin")
    r = pipeline.process_pdf(path, use_cache=False)
    el = r["elevations"][0]
    assert len(el["panels"]) == 9 and el["panels"][0]["tag"] == "1917-D1 / 1917-DD1"
    assert any("Stacked panels" in n for n in el["notes"])


# ------------------------------------------------------------------------------------------ v3.3 (13871 style)
@pytest.mark.parametrize("line", ["ELEVATION 26 & 27 WILL", "ELEVATION 24 & 25.", "ELEVATION 3 FOR DETAILS",
                                  "ELEVATIONS 28, 29 & 30."])
def test_note_lines_are_not_titles(line):
    assert find_titles([{"t": line, "bbox": [100, 100, 220, 108]}], []) == []


@pytest.mark.parametrize("line", ["ELEVATION / FOCUS ROOM #1127", "ELEVATION /", "ELEVATION:  OFFICE 3", "ELEVATION"])
def test_real_titles_still_found(line):
    assert len(find_titles([{"t": line, "bbox": [100, 100, 220, 108]}], [])) == 1


def test_astrazeneca_style_fuzz(tmp_path):
    """Uppers = lowers magnitude, notes naming elevations, FPD inside a note, bulkhead height above a door,
    narrow sidelite with readings only on its outer edge, side views with a thickness in the BM range."""
    total = wrong = fakes = 0
    for seed in range(24):
        pages = synth.random_project_az(random.Random(seed))
        path = str(tmp_path / f"az{seed}.pdf")
        synth.build_fm_pdf_az(path, pages, seed=seed, rotate=[0, 90, 270][seed % 3])
        r = pipeline.process_pdf(path, use_cache=False)
        got, exp = fam_rows(r), synth.expected_az(pages)
        fakes += sum(1 for e in r["elevations"] if not e["elev"])
        total += len(exp)
        wrong += max(sum(1 for x in exp if x not in got), sum(1 for x in got if x not in exp))
    assert wrong == 0 and fakes == 0, f"{wrong}/{total} wrong, {fakes} fake elevations"


# ------------------------------------------------------------------------------------------ v3.4 stacked fractions
def test_cad_stacked_fraction_tokens_are_joined():
    big, small = (0, 0, 0), (0, 0, 0)
    toks = [Token("36", [50, 85, 66, 104], big, 14), Token("1", [66, 84, 70, 95], small, 8),
            Token("16", [71, 94, 80, 105], small, 8), Token('"', [81, 85, 86, 104], big, 14),
            Token("40", [350, 85, 366, 104], big, 14), Token("9", [367, 84, 371, 94], small, 7),
            Token('16"', [366, 94, 376, 104], small, 7)]
    got = sorted(t.t for t in merge_value_tokens(toks))
    assert got == ['36 1/16"', '40 9/16"'] and dim_value('36 1/16"') == 36.0625


@pytest.mark.parametrize("text,expect", [("36¹⁄₁₆\"", 36.0625), ("40⁹⁄₁₆\"", 40.5625), ("57¼\"", 57.25)])
def test_unicode_fractions(text, expect):
    assert dim_value(text, True) == expect


def test_stacked_fractions_do_not_join_unrelated_numbers():
    toks = [Token("36", [50, 85, 66, 104], (0, 0, 0), 14), Token("3", [66, 84, 70, 95], (0, 0, 0), 8),
            Token("17", [71, 94, 80, 105], (0, 0, 0), 8)]                       # 3/17 is not a fraction
    assert sorted(t.t for t in merge_value_tokens(toks)) == ["17", "3", "36"]


# ------------------------------------------------------------------------------------------ v3.5 (13869 Sanofi)
@pytest.mark.parametrize("parts,expect", [
    ([("36", 14, 0), ("116", 7, -2), ('"', 14, 0)], '36 1/16"'),        # fraction bar drawn as a line
    ([("±72", 14, 0), ('18"', 7, -2)], '72 1/8"'),
    ([("40", 14, 0), ("916", 7, -2), ('"', 14, 0)], '40 9/16"'),
    ([("40", 14, 0), ("1516", 7, -2), ('"', 14, 0)], '40 15/16"'),
])
def test_glued_small_fraction_words(parts, expect):
    toks, x = [], 50
    for text, size, dy in parts:
        w = len(text) * size * 0.55
        toks.append(Token(text, [x, 100 - size + dy, x + w, 100 + dy], (0, 0, 0), size))
        x += w + 1
    got = [t.t for t in merge_value_tokens(toks)]
    assert got == [expect]


def test_small_word_that_is_not_a_fraction_stays():
    toks = [Token("36", [50, 86, 66, 100], (0, 0, 0), 14), Token("10", [67, 91, 74, 98], (0, 0, 0), 7)]
    assert sorted(t.t for t in merge_value_tokens(toks)) == ["10", "36"]         # 1/0 is not a fraction


def test_cl_symbol_letters_are_not_split():
    import pymupdf
    doc = pymupdf.open(); p = doc.new_page()
    tw = pymupdf.TextWriter(p.rect); f = pymupdf.Font("helv")
    tw.append((100, 100), "C", font=f, fontsize=6); tw.append((101.5, 102), "L", font=f, fontsize=6)
    tw.write_text(p)
    assert "".join(t.t for t in pdfdoc.tokens_text_layer(p)) in ("CL", "C" + "L")


def test_missing_lower_between_two_edges_is_their_average(tmp_path):
    """14090 CONFERENCE 360 (user mark-up): lowers under the title, edges 3 and 6 left blank.
    360-C lower = (L2 + L4) / 2, 360-E / 360-F shared edge = (L5 + L7) / 2 - not a copy of the previous edge."""
    from glassx import synth
    U = lambda a, b="": (a, b)  # noqa: E731
    tags = [("OLGL-12", f"360-{c}", "Fixed", False) for c in "ABCDEF"]
    s = synth.FamSpec(1, "360", "CONFERENCE 360", tags, [U(48)] * 7,
                      [U(60, "9/16"), U(60, "11/16"), U(60), U(60, "13/16"), U(60, "3/4"), U(60), U(60, "5/8")],
                      skip={2, 5})
    path = str(tmp_path / "c360.pdf")
    synth.build_fm_pdf_family(path, [[s]], "oc")
    r = pipeline.process_pdf(path, use_cache=False)
    rows = {p["tag"]: (p["L"]["l"], p["R"]["l"]) for e in r["elevations"] for p in e["panels"]}
    assert rows["360-B"] == ("60 11/16", "60 3/4") and rows["360-C"] == ("60 3/4", "60 13/16")
    assert rows["360-E"] == ("60 3/4", "60 11/16") and rows["360-F"] == ("60 11/16", "60 5/8")
    note = " ".join(r["elevations"][0]["notes"])
    assert "average of the edges either side" in note and "(60 11/16 + 60 13/16) / 2 = 60 3/4" in note
    assert sorted(synth.expected_family([[s]], "oc")) == sorted(
        (e["elev"], p["tag"], p["L"]["u"], p["L"]["l"], p["R"]["u"], p["R"]["l"], p["kind"])
        for e in r["elevations"] for p in e["panels"])


@pytest.mark.parametrize("annots", [False, True])
def test_14065_upper_at_ends_and_triple_inch_marks(tmp_path, monkeypatch, annots):
    """14065 UBS Boca Raton: 44" written only at the two end edges (same value -> every edge), and lowers written
    with repeated inch marks  59 11/16\"\"\"  (the fraction used to be lost: 59 instead of 59 11/16)."""
    monkeypatch.setattr(synth, "fm", lambda w, f: f'{w} {f}"""' if f else f'{w}"""')
    U = lambda a, b="": (a, b)  # noqa: E731
    s = synth.ElevSpec(17, "04-015", "PRIVATE OFFICE", [("OGL-12", "04-015-A"), ("OGL-12", "04-015-B")],
                       [U(44)] * 3, [U(59, "11/16"), U(59, "7/8"), U(59, "11/16")], drop={("u", 1)}, rows=True)
    s2 = synth.ElevSpec(18, "04-017", "PRIVATE OFFICE", [("OGL-12", "04-017-A"), ("OGL-12", "04-017-B"),
                                                         ("OGL-12", "04-017-C")],
                        [U(44)] * 4, [U(59, "11/16"), U(59, "7/8"), U(59, "7/8"), U(59, "7/8")],
                        drop={("u", 1), ("u", 2)}, rows=True)
    path = str(tmp_path / "14065.pdf")
    synth.build_fm_pdf(path, [[s, s2]], use_annots=annots)
    r = pipeline.process_pdf(path, use_cache=False)
    rows = {p["tag"]: (p["L"]["u"], p["L"]["l"], p["R"]["u"], p["R"]["l"]) for e in r["elevations"] for p in e["panels"]}
    assert rows["04-015-A"] == ("44", "59 11/16", "44", "59 7/8")
    assert rows["04-015-B"] == ("44", "59 7/8", "44", "59 11/16")
    assert rows["04-017-B"] == ("44", "59 7/8", "44", "59 7/8") and rows["04-017-C"][2] == "44"
    assert any("used at every edge" in n for e in r["elevations"] for n in e["notes"])


def test_uppers_given_at_some_edges_with_different_values(tmp_path):
    """Different uppers at the ends: a blank edge in between = their average (floored to 1/16), flagged."""
    U = lambda a, b="": (a, b)  # noqa: E731
    s = synth.ElevSpec(1, "05", "OFFICE", [("OGL-12", "05-A"), ("OGL-12", "05-B")],
                       [U(44), U(44), U(44, "1/4")], [U(59, "1/2"), U(59, "5/8"), U(59, "3/4")], drop={("u", 1)},
                       rows=True)
    path = str(tmp_path / "u.pdf")
    synth.build_fm_pdf(path, [[s]])
    r = pipeline.process_pdf(path, use_cache=False)
    e = r["elevations"][0]
    assert [p["u"] for p in e["points"]] == ["44", "44 1/8", "44 1/4"]
    assert any("U2 = (44 + 44 1/4) / 2 = 44 1/8" in n for n in e["notes"])
