"""Regression on real project FM PDFs (14005 Gibson Dunn, 14075 MCC Washington, 14092 SSI Orange County).

The PDFs are client documents and are not shipped: copy them into tests/real_pdfs/ to run these tests.
Expected rows were checked by hand against the sheets."""
import json
import os

import pytest

from glassx import pipeline

HERE = os.path.dirname(__file__)
EXPECTED = json.load(open(os.path.join(HERE, "real_expected.json"), encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_real_pdf(name):
    path = os.path.join(HERE, "real_pdfs", name)
    if not os.path.exists(path):
        pytest.skip(f"{name} not in tests/real_pdfs")
    r = pipeline.process_pdf(path, use_cache=False)
    got = [[e["elev"], q["tag"], q["L"]["u"], q["L"]["l"], q["R"]["u"], q["R"]["l"], q["kind"]]
           for e in r["elevations"] for q in e["panels"]]
    assert got == EXPECTED[name]
