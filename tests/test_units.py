import pytest

from glassx.units import parse_length, to_fraction_str

BM = (15, 95)


@pytest.mark.parametrize("text,expected", [
    ('57"1/4', "57 1/4"), ('49"15/16', "49 15/16"), ('50"', "50"), ("52 5/16", "52 5/16"), ("52-5/16", "52 5/16"),
    ("57'5/16", "57 5/16"),                    # FM misread of the inch mark
    ("72½", "72 1/2"), ("±72 1/2\"", "72 1/2"),
    ("8'-6 1/2\"", "102 1/2"),                 # real feet-inches
    ("525/16", "52 5/16"), ("524", "52 1/4"), ("3614\"", "36 1/4"),   # OCR-flattened stacked fractions
    ("361 4 II", "36 1/4"), ("19 16 1I", "19 1/16"),
    ('- 115" CONF.', "-115"),
])
def test_parse_length(text, expected):
    rng = {"102 1/2": None, "-115": None, "36 1/4": (1, 600), "1 9/16": (0, 60)}.get(expected, BM)
    assert to_fraction_str(parse_length(text, rng)["value"]) == expected


def test_alternatives_are_reported_not_hidden():
    p = parse_length("212", (1, 600))
    assert p["inferred"] and "2 1/2" in p["alts"]


@pytest.mark.parametrize("x,s", [(107.25, "107 1/4"), (0.0625, "1/16"), (-0.125, "-1/8"), (50, "50"), (49.9375, "49 15/16")])
def test_to_fraction_str(x, s):
    assert to_fraction_str(x) == s
