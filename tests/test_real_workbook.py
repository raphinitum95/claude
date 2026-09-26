"""Structural checks against the user's real workbook (no browser, no network)."""
from __future__ import annotations

from pathlib import Path

import pytest

from regrunner.lint import lint, summarize
from regrunner.selectors.migrate import collect
from regrunner.workbook import Workbook

REAL = Path(__file__).resolve().parents[1] / "workbooks" / "UAT_AEM_Travelex Regression_v9.1.xlsx"
pytestmark = [pytest.mark.realworkbook, pytest.mark.skipif(not REAL.exists(), reason="real workbook not present")]


@pytest.fixture(scope="module")
def wb():
    return Workbook(REAL, environment="UAT", seed=1)


def test_all_nine_tests_are_discovered_with_the_workbooks_own_selection(wb):
    cases = {c.id: c for c in wb.discover()}
    assert list(cases) == ["Owner_AZ", "Owner_CRVD", "Owner_RVD", "PostDeparture", "Preview", "Travelkore", "ANZ", "CW", "WM"]
    assert {i for i, c in cases.items() if c.enabled} == {"Owner_CRVD", "Travelkore", "CW"}
    assert cases["CW"].scenario == "TC_696157" and all(c.is_ui for c in cases.values()) and not wb.warnings


def test_plans_are_stable_and_exactly_one_open_step_runs(wb):
    counts = {}
    for case in wb.discover():
        plan = wb.runtime(case).plan()
        counts[case.id] = len(plan)
        opens = [p for p in plan if p[2] == "OPEN"]
        assert len(opens) == 1, f"{case.id}: headless/headed Open rows must be mutually exclusive"
        assert plan[-1][2] == "QUIT"
    assert counts == {"Owner_AZ": 235, "Owner_CRVD": 180, "Owner_RVD": 155, "PostDeparture": 197, "Preview": 235,
                      "Travelkore": 268, "ANZ": 179, "CW": 151, "WM": 145}


@pytest.mark.parametrize("headless,steps,first", [(True, 151, ["WAIT", "OPEN"]), (False, 150, ["OPEN"])])
def test_headless_setting_only_swaps_the_open_rows(headless, steps, first):
    """Headless adds exactly one helper row: `Wait 1` stages the URL into R3 for the "URL:=..;;HEADLESS:=TRUE" formula."""
    wb = Workbook(REAL, environment="UAT", headless=headless)
    case = next(c for c in wb.discover() if c.id == "CW")
    plan = wb.runtime(case).plan()
    assert len(plan) == steps and [p[2] for p in plan[:len(first)]] == first


@pytest.mark.parametrize("env,url", [
    ("UAT", "https://cw.uat.travelexinsurance.net/"), ("QA", "https://cw.qa.travelexinsurance.net/"),
    ("PROD", "https://cw.travelexinsurance.com")])
def test_environment_override_picks_the_right_base_url(env, url):
    w = Workbook(REAL, environment=env)
    case = next(c for c in w.discover() if c.id == "CW")
    rt = w.runtime(case)
    assert rt.params["DT_URL"] == url and rt.environment == env


def test_first_steps_of_cw_after_substitution(wb):
    case = next(c for c in wb.discover() if c.id == "CW")
    rt = wb.runtime(case)
    steps = []
    for row in range(2, rt.total_rows + 1):
        s = rt.prepare_row(row)
        if s:
            steps.append(s)
            rt.record(s, "PASSED", "", "")
        if len(steps) == 6:
            break
    assert [s.method for s in steps][:2] == ["WAIT", "OPEN"]
    from regrunner.engine.actions import parse_open_value
    assert parse_open_value(steps[1].text("VALUE"))["URL"] == "https://cw.uat.travelexinsurance.net/"   # "URL:=...;;HEADLESS:=TRUE"
    assert steps[1].page == "CHROME"
    frame = next(s for s in steps if s.method == "SWITCHTOFRAME")
    assert frame.text("VALUE") == "aemFormFrame"


def test_lint_finds_no_errors_and_flags_the_known_legacy_no_ops(wb):
    findings = lint(wb)
    counts = summarize(findings)
    assert counts["error"] == 0
    noops = [f for f in findings if "GETATTRIBUTE" in f.message]
    assert len(noops) == 8 and {f.test for f in noops} == {"Owner_RVD"}


def test_most_selector_usage_can_be_expressed_without_xpath(wb):
    uses = collect(wb)
    total = sum(u.uses for u in uses)
    converted = sum(u.uses for u in uses if u.css)
    assert total > 1200 and converted / total > 0.7
    # nothing brittle is ever auto-converted
    assert not any(u.css and ("text()" in u.value or "contains(." in u.value) for u in uses)
