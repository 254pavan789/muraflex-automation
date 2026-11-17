import pytest

from glassx.judgement import CHECK, LEVEL, TYPO, judge


@pytest.mark.parametrize("t1,t2,j", [
    (107.25, 107.375, 107.25),          # SOP example 63-A: diff 1/8 -> smallest
    (102.3125, 102.25, 102.25),         # 'Calculating Fixed Panel Heights' 1174-A
    (102.25, 102.1875, 102.1875),       # 1174-B
    (102.5, 102.75, 102.625),           # diff 1/4 -> average (102 10/16)
    (102.75, 103.0, 102.875),           # 102 14/16
    (100.0, 100.1875, 100.0),           # diff exactly 3/16 -> smallest
    (100.0, 100.0625 + 0.25, 100.15625 // (1 / 16) / 16),   # average rounded down to 1/16
    (102.3125, 103.0625, LEVEL),        # 3/4
    (102.3125, 104.0, CHECK),           # 1 11/16
    (102.3125, 120.0, TYPO),
])
def test_rules(t1, t2, j):
    assert judge(t1, t2)[1] == j


def test_missing_total():
    assert judge(None, 100) == ("", "")
