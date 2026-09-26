"""Truth table for pass/fail - each row is a rule read from the legacy validateresults()."""
from __future__ import annotations

import pytest

from regrunner.engine.outcome import FAILED, PASSED, StepOut, evaluate
from regrunner.workbook.model import PreparedStep


def step(**cells) -> PreparedStep:
    return PreparedStep(row=2, values={k.upper(): v for k, v in cells.items()})


CASES = [
    # id,                 cells,                                             out kwargs,                 element, actual, status,  error
    ("clean pass",        {},                                                {},                         True,  "",     PASSED, ""),
    ("error fails",       {},                                                {"error": "boom"},          True,  "",     FAILED, "boom"),
    ("ignore swallows",   {"ignore_not_existing_object": "Y"},               {"error": "boom"},          True,  "",     PASSED, ""),
    ("missing fails",     {},                                                {"obj_exists": False},      True,  "",     FAILED, "Object was not found"),
    ("missing ignored",   {"ignore_not_existing_object": "Y"},               {"obj_exists": False},      True,  "",     PASSED, ""),
    ("missing non-elem",  {},                                                {"obj_exists": False},      False, "",     PASSED, ""),
    ("exact equal",       {"exact_match": "Y", "expected_value": "abc"},     {},                         True,  "abc",  PASSED, ""),
    ("exact differs",     {"exact_match": "Y", "expected_value": "abc"},     {},                         True,  "abd",  FAILED, "Comparison Failed"),
    ("exact no trim",     {"exact_match": "Y", "expected_value": "abc"},     {},                         True,  "abc ", FAILED, "Comparison Failed"),
    ("exact both blank",  {"exact_match": "Y"},                              {},                         True,  "",     PASSED, ""),
    ("exact exp blank",   {"exact_match": "Y"},                              {},                         True,  "x",    FAILED, "Comparison Failed"),
    ("exact case",        {"exact_match": "Y", "expected_value": "ABC"},     {},                         True,  "abc",  FAILED, "Comparison Failed"),
    ("no flag: no compare", {"expected_value": "abc"},                       {},                         True,  "zzz",  PASSED, ""),
    ("contains ci",       {"contains": "Y", "expected_value": " ABC "},      {},                         True,  "xxabcxx", PASSED, ""),
    ("contains miss",     {"contains": "Y", "expected_value": "abc"},        {},                         True,  "xyz",  FAILED, "Comparison Failed"),
    ("ignore still fails on mismatch", {"ignore_not_existing_object": "Y", "exact_match": "Y", "expected_value": "a"},
                                                                             {},                         True,  "b",    FAILED, "Comparison Failed"),
    ("numeric expected",  {"exact_match": "Y", "expected_value": 0},         {},                         True,  "0",    PASSED, ""),
    ("crlf normalised",   {"exact_match": "Y", "expected_value": "a\r\nb"},  {},                         True,  "a\nb", PASSED, ""),
]


@pytest.mark.parametrize("name,cells,out_kwargs,element,actual,status,error", CASES, ids=[c[0] for c in CASES])
def test_truth_table(name, cells, out_kwargs, element, actual, status, error):
    verdict = evaluate(step(**cells), StepOut(**out_kwargs), element_action=element, actual=actual)
    assert (verdict.status, verdict.error) == (status, error)


def test_ignored_errors_are_kept_for_the_report():
    v = evaluate(step(ignore_not_existing_object="Y"), StepOut(error="Timeout 1000ms exceeded"), element_action=True, actual="")
    assert v.status == PASSED and v.ignored_error == "Timeout 1000ms exceeded" and v.error == ""
