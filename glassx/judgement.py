"""Height judgement rules (Muraflex 'Calculating Fixed Panel Heights' + team height-judgement tool).

    diff = TOTAL(left) - TOTAL(right)
    |diff| > 5"            -> "DEFINITELY A TYPO"
    1" < |diff| <= 5"      -> "CHECK VALUE ENTERED"
    3/4" <= |diff| <= 1"   -> "LEVEL FLOOR or CEILING"
    1/4" <= |diff| < 3/4"  -> average of the two totals, rounded DOWN to 1/16"
    |diff| < 1/4"          -> the smaller total   (SOP: < 3/16" smallest; 3/16" uses smallest too)

The same rules are written into the Excel JUDGEMENT formula; this module provides the stored result.
"""
from __future__ import annotations

import math

EPS = 1e-9
TYPO, CHECK, LEVEL = "DEFINITELY A TYPO", "CHECK VALUE ENTERED", "LEVEL FLOOR or CEILING"


def judge(t1, t2):
    """-> (difference or '', judgement number/text or '')"""
    if t1 is None or t2 is None:
        return "", ""
    d = t1 - t2
    a = abs(d)
    if a > 5 + EPS:
        return d, TYPO
    if a > 1 + EPS:
        return d, CHECK
    if a >= 0.75 - EPS:
        return d, LEVEL
    if a >= 0.25 - EPS:
        return d, math.floor((t1 + t2) / 2 * 16 + 1e-6) / 16
    return d, min(t1, t2)


EXCEL_FORMULA = ('=IF(K{r1}="","",IF(ABS(K{r1})>5,"' + TYPO + '",IF(ABS(K{r1})>1,"' + CHECK + '",'
                 'IF(ABS(K{r1})>=3/4,"' + LEVEL + '",IF(ABS(K{r1})>=1/4,FLOOR((I{r1}+I{r2})/2,1/16),'
                 'MIN(I{r1},I{r2}))))))')
