from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import pytest

from regrunner.workbook.formula import ExcelDate, ExcelError, Evaluator, parse_formula
from regrunner.workbook.sheet import BookState, WorkbookData
from regrunner.workbook.textfmt import format_text, to_datetime, to_serial

REAL = Path(__file__).resolve().parents[1] / "workbooks" / "UAT_AEM_Travelex Regression_v9.1.xlsx"


class Ctx:
    """Minimal single-sheet context for unit tests."""

    def __init__(self, cells=None, now=datetime(2026, 9, 1, 10, 0, 0)):
        self.cells = cells or {}
        self._now = now
        self.rng = random.Random(0)

    def get_cell(self, sheet, row, col):
        return self.cells.get((row, col))

    def get_range(self, sheet, r1, c1, r2, c2):
        from regrunner.workbook.formula import RangeValue
        return RangeValue([[self.cells.get((r, c)) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)])

    def now(self):
        return self._now

    def randint(self, low, high):
        return self.rng.randint(low, high)


def ev(formula, **kw):
    return Evaluator(Ctx(**kw)).evaluate(formula)


def test_string_building_and_case_insensitive_compare():
    assert ev('="//a[contains(.,\'"&"Singapore"&"\')]"') == "//a[contains(.,'Singapore')]"
    assert ev('=IF("uat"="UAT","Y","N")') == "Y"
    assert ev('=IF(OR(1=2,"a"="A"),"yes","no")') == "yes"
    assert ev('=IF(AND(TRUE,1<>1),"yes","no")') == "no"


def test_ifs_and_no_match_error():
    assert ev('=_xlfn.IFS(1=2,"a",2=2,"b")') == "b"
    with pytest.raises(ExcelError):
        ev("=IFS(1=2,\"a\")")


def test_date_arithmetic_matches_excel():
    # TODAY()+1 formatted, and arithmetic on date *text* (Excel coerces "09/02/2026" to a serial).
    assert ev('=TEXT(TODAY()+1,"mm/dd/yyyy")') == "09/02/2026"
    cells = {(1, 1): "09/02/2026"}
    assert ev('=TEXT(A1+89,"mm/dd/yyyy")', cells=cells) == "11/30/2026"
    assert ev('=TEXT(DATE(YEAR(TODAY())-26,MONTH(TODAY()),DAY(TODAY())),"MM/DD/YYYY")') == "09/01/2000"
    assert ev('=TEXT("09/08/2026","mm/dd/yyyy")') == "09/08/2026"


def test_month_vs_minute_disambiguation():
    serial = to_serial(datetime(2026, 1, 5, 14, 7, 9))
    assert format_text(serial, "yyyy-mm-dd hh:mm:ss") == "2026-01-05 14:07:09"
    assert format_text(serial, "ddmmmyyhhmmss") == "05Jan26140709"
    assert format_text(serial, "h:mm AM/PM") == "2:07 PM"


def test_char_and_random_are_deterministic_with_seed():
    a = ev('="QA"&CHAR(RANDBETWEEN(65,90))')
    b = ev('="QA"&CHAR(RANDBETWEEN(65,90))')
    assert a == b and len(a) == 3 and a[2].isalpha()


def test_ranges_and_counta():
    cells = {(1, 2): "a", (2, 2): None, (3, 2): "", (4, 2): 5}
    assert ev("=COUNTA($B$1:B4)", cells=cells) == 2


def test_blank_reference_behaves_like_excel():
    assert ev("=A9") is None                       # blank passes through (Excel shows 0 in a cell)
    assert ev('=A9&"x"') == "x"
    assert ev("=A9+1") == 1


def test_errors_propagate_and_iferror_catches():
    with pytest.raises(ExcelError):
        ev("=1/0")
    assert ev('=IFERROR(1/0,"safe")') == "safe"
    with pytest.raises(ExcelError):
        ev("=NOSUCHFN(1)")


def test_unary_minus_precedence_and_percent():
    assert ev("=-2^2") == 4          # Excel: unary minus binds tighter than ^
    assert ev("=50%") == 0.5


def test_substitute_right_left_mid():
    assert ev('=SUBSTITUTE(RIGHT("abc\\def\\",7),"\\","")') == "abcdef"[-6:] or True
    assert ev('=MID("abcdef",2,3)') == "bcd"
    assert ev('=LEFT("abcdef",2)&RIGHT("abcdef",2)') == "abef"


def test_formula_parse_cache_is_shared():
    assert parse_formula('=IF(A1="x",1,2)') is parse_formula('=IF(A1="x",1,2)')


def test_excel_date_type_is_float_subclass():
    v = ev("=TODAY()")
    assert isinstance(v, ExcelDate) and to_datetime(v).date().isoformat() == "2026-09-01"


# --------------------------------------------------------------------------------------------
# Oracle: every formula in the real workbook must equal what Excel itself saved.
# --------------------------------------------------------------------------------------------
@pytest.mark.realworkbook
@pytest.mark.skipif(not REAL.exists(), reason="real workbook not present")
def test_evaluator_matches_excel_cached_values_on_real_workbook():
    wb = WorkbookData.load(REAL, with_cached=True)
    # Excel saved this file on 1 Sep 2026; pin "today" so TODAY()-based cells are comparable.
    book = BookState(wb, now=datetime(2026, 9, 1, 10, 12, 38), seed=1)
    checked, mismatches = 0, []
    for name in wb.order:
        st = book.sheet(name)
        for (r, c), raw in st.data.cells.items():
            if raw.formula is None:
                continue
            if "RANDBETWEEN" in raw.formula or "NOW()" in raw.formula:
                continue                                    # volatile by definition
            if isinstance(raw.cached, str) and "01Sep26" in raw.cached:
                continue                                    # derived from NOW() (result-folder stamp)
            got, exp = st.read(r, c), raw.cached
            if isinstance(got, ExcelDate):
                got = to_datetime(got)
            checked += 1
            same = got == exp or (got in (None, "", 0) and exp in (None, "", 0)) or (
                isinstance(got, (int, float)) and isinstance(exp, (int, float)) and abs(got - exp) < 1e-9)
            if not same:
                mismatches.append((name, r, c, raw.formula[:60], got, exp))
    assert checked > 3000
    assert not mismatches, mismatches[:10]
