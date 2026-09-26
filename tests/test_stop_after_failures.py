"""A test whose page is not where it expects (a login that Okta refused, a form that never opened) used to wait out every remaining step's timeout - 22 failed
steps and four minutes in the 2026-09-25 run.  It now stops after ``runner.stop_after_failed_steps`` steps in a row that could not find or use their element."""
from __future__ import annotations

import pytest

from tests.test_failure_capture import build, click, run, step_named

pytestmark = pytest.mark.browser

MISSING = lambda i: ("Click", f"missing {i}", click(f"//a[@id='nope{i}']", timeout=1))                  # noqa: E731
SEEN = ("Exist", "an element that is there", {"FindBy": "xpath", "FindBy_Value": "//h1", "Index": 0, "Timeout": 2})
WAIT = ("Wait", "a wait", {"Value": 1})


async def go(make_cfg, tmp_path, site, rows, limit):
    wb = build(tmp_path / "wb.xlsx", site, "/cover_inside.html", rows)
    result, _, _ = await run(make_cfg, wb, **{"runner.stop_after_failed_steps": limit})
    test = result.tests[0]
    return test, [s.name for s in test.steps]


async def test_a_test_stops_after_the_set_number_of_failed_element_steps_in_a_row(site, make_cfg, tmp_path):
    test, ran = await go(make_cfg, tmp_path, site, [MISSING(i) for i in range(1, 8)], 3)
    assert ran == ["Open", "missing 1", "missing 2", "missing 3"] and test.failed == 3 and test.status == "FAILED"
    assert "Stopped after 3 steps in a row could not find or use their element" in test.error and 'step 4 "missing 3"' in test.error
    assert test.skipped == 4                                                                                  # the four that were never tried


async def test_a_step_that_works_starts_the_count_again(site, make_cfg, tmp_path):
    test, ran = await go(make_cfg, tmp_path, site, [MISSING(1), MISSING(2), SEEN, MISSING(3), MISSING(4), SEEN, MISSING(5), MISSING(6)], 3)
    assert len(ran) == 9 and test.failed == 6 and "Stopped" not in test.error


async def test_waits_and_other_steps_that_touch_nothing_do_not_reset_or_count(site, make_cfg, tmp_path):
    test, ran = await go(make_cfg, tmp_path, site, [MISSING(1), WAIT, MISSING(2), WAIT, MISSING(3), MISSING(4)], 3)
    assert ran == ["Open", "missing 1", "a wait", "missing 2", "a wait", "missing 3"] and "Stopped after 3" in test.error


async def test_an_optional_element_that_is_missing_neither_counts_nor_resets(site, make_cfg, tmp_path):
    optional = ("Click", "optional banner", {"FindBy": "xpath", "FindBy_Value": "//a[@id='banner']", "Index": 0, "Ignore_not_existing_object": "Y", "Timeout": 1})
    test, ran = await go(make_cfg, tmp_path, site, [MISSING(1), MISSING(2), optional, MISSING(3), MISSING(4)], 3)
    assert ran == ["Open", "missing 1", "missing 2", "optional banner", "missing 3"] and "Stopped after 3" in test.error
    assert step_named_status(test, "optional banner") == "PASSED"


async def test_a_step_that_read_its_element_and_found_other_text_is_not_a_lost_page(site, make_cfg, tmp_path):
    differs = ("Output", "different text", {"FindBy": "xpath", "FindBy_Value": "//h1", "Index": 0, "Output_Property": "innertext", "Expected_Value": "Something else",
                                          "Exact_Match": "Y", "Timeout": 2})
    test, ran = await go(make_cfg, tmp_path, site, [MISSING(1), MISSING(2), differs, MISSING(3), MISSING(4)], 3)
    assert len(ran) == 6 and "Stopped" not in test.error and test.failed == 5


async def test_zero_never_stops(site, make_cfg, tmp_path):
    test, ran = await go(make_cfg, tmp_path, site, [MISSING(i) for i in range(1, 8)], 0)
    assert len(ran) == 8 and test.failed == 7 and "Stopped" not in test.error


def step_named_status(test, name):
    return next(s.status for s in test.steps if s.name == name)
