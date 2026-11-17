import random

import pytest

from glassx import pdfdoc, pipeline, synth
from glassx.extract import align_pairs, extract_page
from glassx.pdfdoc import Token
from conftest import panels_of


def run(tmp_path, specs, **kw):
    path = str(tmp_path / "fm.pdf")
    synth.build_fm_pdf(path, specs, **kw)
    return pipeline.process_pdf(path, use_cache=False)


@pytest.mark.parametrize("kw", [{}, {"use_annots": True}, {"rows_per_page": 2}, {"width_above_frame": True},
                                {"width_above_frame": True, "rows_per_page": 2}, {"stacked": "cad"},
                                {"stacked": "unicode"}, {"stacked": "cad", "rows_per_page": 2}])
def test_reference_project_exact(tmp_path, kw):
    specs = synth.reference_project()
    r = run(tmp_path, specs, **kw)
    assert panels_of(r) == synth.expected(specs)


def test_cover_and_notes_pages_are_ignored(tmp_path):
    r = run(tmp_path, synth.reference_project())
    assert r["pages"] == 4
    assert {e["page"] for e in r["elevations"]} == {1, 2}
    assert any("KEY PLAN" in n for n in r["notes"][0])


def test_doors_listed_but_not_exported(tmp_path):
    r = run(tmp_path, synth.reference_project())
    doors = [p for e in r["elevations"] for p in e["panels"] if p["kind"] == "Door"]
    assert {p["tag"] for p in doors} == {"63", "20", "37"} and not any(p["export"] for p in doors)


def test_missing_value_does_not_shift_neighbours(tmp_path):
    rng = random.Random(3)
    s = synth.random_spec(rng, 1, "40", 3)
    s.drop = {("l", 1)}
    r = run(tmp_path, [[s]])
    assert panels_of(r) == synth.expected([[s]])
    el = r["elevations"][0]
    assert any("missing" in n for n in el["notes"])


def test_elevation_number_10_and_up(tmp_path):
    rng = random.Random(5)
    specs = [[synth.random_spec(rng, 10 + i, str(20 + i), 2) for i in range(3)]]
    assert panels_of(run(tmp_path, specs)) == synth.expected(specs)


def test_glued_text_is_split_at_gaps(tmp_path):
    import pymupdf
    doc = pymupdf.open(); p = doc.new_page(width=600, height=300)
    tw = pymupdf.TextWriter(p.rect); fnt = pymupdf.Font("helv")
    for x, t in ((50, "FAL"), (120, '59"7/16'), (300, '111"'), (400, '59"11/16')):
        tw.append((x, 100), t, font=fnt, fontsize=8)
    tw.write_text(p, color=(1, 0, 0))
    assert [t.t for t in pdfdoc.tokens_text_layer(p)] == ["FAL", '59"7/16', '111"', '59"11/16']


def test_align_pairs_handles_gap():
    T = lambda x: Token("v", [x, 0, x + 10, 5])  # noqa: E731
    ups = [T(0), T(100), T(200)]
    los = [T(2), T(203)]
    pairs = align_pairs(ups, los, 45)
    assert [(u is not None, l is not None) for u, l in pairs] == [(True, True), (True, False), (True, True)]


def test_fuzz_random_sheets(tmp_path):
    """60 random FM PDFs (1-3 pages, 2-4 elevations per page, 1-4 panels, doors, mark-ups, two-row layouts)."""
    total = wrong = 0
    for seed in range(60):
        rng = random.Random(seed)
        e, pages = 1, []
        for _ in range(rng.randint(1, 3)):
            specs = []
            for _ in range(rng.randint(2, 4)):
                specs.append(synth.random_spec(rng, e, str(rng.randint(10, 99)), rng.randint(1, 4),
                                               door_first=rng.random() < .3)); e += 1
            while sum(len(s.tags) * 62 + 110 for s in specs) > 1100:
                specs.pop()
            pages.append(specs)
        r = run(tmp_path, pages, use_annots=seed % 4 == 1, rows_per_page=2 if seed % 3 == 0 else 1, seed=seed)
        got, exp = panels_of(r), synth.expected(pages)
        total += len(exp)
        wrong += sum(1 for k in exp if got.get(k) != exp[k])
    assert wrong == 0, f"{wrong}/{total} panels wrong"


def test_page_without_text_and_no_ocr_returns_nothing(tmp_path, monkeypatch):
    import pymupdf
    from glassx import ocr
    monkeypatch.setattr(ocr, "available", lambda: False)
    doc = pymupdf.open(); doc.new_page()
    pd = pdfdoc.read_page(doc, 0)
    assert extract_page(pd, 0)["elevations"] == []
