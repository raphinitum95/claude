"""The P07 steps on the mock site (CONTRACT.md 1.3, ``tests/site/widgets.html``): the ASSERT_PAGE gate (always a hard stop), WAIT_UNTIL,
DISMISS_IF_SHOWN, PICK_DATE, CHOOSE_SUGGESTION, the CHECK_* steps, SIDE_EFFECTS steps on production, and BACKUP_LOCATORS that are reported but
never used."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus
from tests.flow_books import book

pytestmark = pytest.mark.browser

FINGERPRINTS = [["Name", "UrlContains", "Landmark", "LandmarkText", "Notes"],
                ["Payment page", "/widgets.html", "css=h1", "Payment details", ""],
                ["Confirmation page", "/confirmation", "css=h1", "", ""],
                ["Payment page, wrong words", "{PAGE_PART}", "css=h1", "Your receipt", ""]]


def envs(site: str) -> list[list]:
    return [["Variable", "Required", "Secret", "QA", "UAT", "PROD"], ["DOMAIN", "Y", "", "", site.rstrip("/"), site.rstrip("/")], ["PAGE_PART", "", "", "", "widgets", "widgets"]]


def open_page() -> tuple:
    return ("Open", "open the page", {"Page": "chrome", "Value": "{DOMAIN}/widgets.html"})


def css(selector: str, **cols) -> dict:
    return {"FindBy": "CSS_SELECTOR", "FindBy_Value": selector, "Index": 0, **cols}


async def run(make_cfg, wb: Path, tests: list[str], env: str = "UAT", **cfg):
    cfg = make_cfg(**{"timeouts.element_s": 2, "timeouts.optional_s": 1.5, "output.match_timeout_s": 1.5, **cfg})
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    result = await execute(RunOptions(workbook=wb, tests=tests, seed=1, environment=env), cfg, bus)     # (its own table: the run picks one)
    return result, events, cfg.path(cfg.runs_dir) / result.run_id


def by_name(test) -> dict:
    return {s.name: s for s in test.steps}


async def test_assert_page_passes_when_the_url_part_and_the_landmark_with_its_text_both_hold(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [open_page(), ("ASSERT_PAGE", "arrived at payment", {"Value": "payment page"}),
                                          ("CHECK_REGEX", "after the gate", css("#ref", Expected_Value=r"^REF-\d{5}$"))]},
              environments=envs(site), sheets={"_rr_fingerprints": FINGERPRINTS})
    result, events, _ = await run(make_cfg, wb, ["T"])
    (test,) = result.tests
    assert test.status == "PASSED", test.error
    gate = by_name(test)["arrived at payment"]
    assert gate.actual.endswith("/widgets.html") and any("arrived at Payment page" in n for n in gate.notes)
    (event,) = [e for e in events if e["type"] == "page_gate"]
    assert event["passed"] is True and event["landmark_found"] is True and event["fingerprint"] == "Payment page" and event["url"] == "/widgets.html"


@pytest.mark.parametrize("fingerprint,says", [("Confirmation page", "the URL does not contain '/confirmation'"),
                                              ("Payment page, wrong words", "does not say 'Your receipt'"),
                                              ("No such page", "no page fingerprint called 'No such page'")])
async def test_a_failed_page_gate_is_a_hard_stop_even_when_errors_are_ignored_and_says_which_part_failed(site, make_cfg, tmp_path, fingerprint, says):
    wb = book(tmp_path / "a.xlsx", {"T": [open_page(),
                                          ("ASSERT_PAGE", "the gate", {"Value": fingerprint, "Ignore_not_existing_object": "Y", "Timeout": 1}),
                                          ("CHECK_REGEX", "never runs", css("#ref", Expected_Value="REF"))]},
              environments=envs(site), sheets={"_rr_fingerprints": FINGERPRINTS})
    result, events, _ = await run(make_cfg, wb, ["T"])
    (test,) = result.tests
    assert test.status == "FAILED" and [s.name for s in test.steps] == ["open the page", "the gate"]
    gate = by_name(test)["the gate"]
    assert gate.status == "FAILED" and says in gate.error and not gate.ignored_error
    assert "the steps after it were not run" in test.error and test.skipped == 1
    if fingerprint != "No such page":
        (event,) = [e for e in events if e["type"] == "page_gate"]
        assert event["passed"] is False


async def test_wait_until_waits_for_an_element_to_show_to_go_and_for_its_text(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [open_page(),
                                          ("WAIT_UNTIL", "promo shows", css("#promo-close", Output_Property="SHOWN")),
                                          ("WAIT_UNTIL", "spinner gone", css("#spinner", Output_Property="GONE")),
                                          ("WAIT_UNTIL", "status ready", css("#status", Output_Property="TEXT", Expected_Value="Ready", Exact_Match="Y")),
                                          ("WAIT_UNTIL", "never says done", css("#status", Output_Property="TEXT", Expected_Value="Done", Timeout=1)),
                                          ("WAIT_UNTIL", "never shows", css("#nothing-here", Timeout=1))]},
              environments=envs(site))
    result, _, _ = await run(make_cfg, wb, ["T"])
    steps = by_name(result.tests[0])
    assert [steps[n].status for n in ("promo shows", "spinner gone", "status ready")] == ["PASSED"] * 3
    assert steps["status ready"].actual == "Ready" and steps["spinner gone"].actual == "gone"
    assert steps["never says done"].status == "FAILED" and steps["never says done"].error == "Comparison Failed"
    assert any("the text is 'Ready', not 'Done'" in n for n in steps["never says done"].notes)
    assert steps["never shows"].status == "FAILED" and "did not show" in steps["never shows"].error


async def test_dismiss_if_shown_closes_a_popup_that_appears_and_passes_logging_one_that_does_not(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [open_page(),
                                          ("DISMISS_IF_SHOWN", "close the promo", css("#promo-close")),
                                          ("WAIT_UNTIL", "promo is gone", css("#promo", Output_Property="GONE")),
                                          ("DISMISS_IF_SHOWN", "close a cookie banner", css("#cookie-banner-close", Timeout=1))]},
              environments=envs(site))
    result, events, _ = await run(make_cfg, wb, ["T"])
    (test,) = result.tests
    assert test.status == "PASSED", test.error
    steps = by_name(test)
    assert steps["close the promo"].actual == "appeared" and steps["close a cookie banner"].actual == "did not appear"
    assert any("did not appear" in n for n in steps["close a cookie banner"].notes)
    assert [e["appeared"] for e in events if e["type"] == "popup_dismissed"] == [True, False]


async def test_pick_date_sets_a_browser_date_field_types_in_the_placeholder_shape_and_clicks_through_a_calendar(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [open_page(),
                                          ("PICK_DATE", "native", css("#native", Value="15/03/2027")),
                                          ("PICK_DATE", "typed", css("#typed", Value="2027-03-15")),
                                          ("PICK_DATE", "calendar forward", css("#cal", Value="15 Mar 2027")),
                                          ("PICK_DATE", "calendar back", css("#cal", Value="2026-12-24"))]},
              environments=envs(site))
    result, _, _ = await run(make_cfg, wb, ["T"])
    (test,) = result.tests
    assert test.status == "PASSED", [(s.name, s.error) for s in test.steps]
    steps = by_name(test)
    assert steps["native"].actual == "2027-03-15" and steps["typed"].actual == "15/03/2027"
    assert steps["calendar forward"].actual == "15/03/2027" and any("2 months along" in n for n in steps["calendar forward"].notes)
    assert steps["calendar back"].actual == "24/12/2026"


async def test_choose_suggestion_types_then_clicks_the_named_suggestion_and_fails_naming_what_was_shown(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [open_page(),
                                          ("CHOOSE_SUGGESTION", "the airport", css("#city", Value="syd", Expected_Value="Sydney Airport")),
                                          ("CHECK_VALUE", "field holds it", css("#city", Expected_Value="Sydney Airport")),
                                          ("CHOOSE_SUGGESTION", "first that contains", css("#city", Value="syd")),
                                          ("CHOOSE_SUGGESTION", "not offered", css("#city", Value="mel", Expected_Value="Perth", Timeout=1))]},
              environments=envs(site))
    result, _, _ = await run(make_cfg, wb, ["T"])
    steps = by_name(result.tests[0])
    assert steps["the airport"].status == "PASSED" and steps["the airport"].actual == "Sydney Airport"
    assert steps["field holds it"].status == "PASSED"
    assert steps["first that contains"].actual == "Sydney"
    assert steps["not offered"].status == "FAILED" and "No suggestion 'Perth'" in steps["not offered"].error and "Melbourne" in steps["not offered"].error


async def test_the_check_steps_pass_and_fail_on_what_the_page_shows(site, make_cfg, tmp_path):
    checks = [
        ("CHECK_VALUE", "value exact", css("#amount", Expected_Value="1,250.00"), "PASSED"),
        ("CHECK_VALUE", "value contains", css("#amount", Expected_Value="250", Contains="Y"), "PASSED"),
        ("CHECK_VALUE", "value differs", css("#amount", Expected_Value="1,250"), "FAILED"),
        ("CHECK_REGEX", "regex", css("#ref", Expected_Value=r"^REF-\d{5}$"), "PASSED"),
        ("CHECK_REGEX", "regex misses", css("#ref", Expected_Value=r"^INV-"), "FAILED"),
        ("CHECK_COMPARE", "greater", css("#total", Output_Property="GT", Expected_Value=1000), "PASSED"),
        ("CHECK_COMPARE", "between", css("#total", Output_Property="BETWEEN", Expected_Value="1;10"), "FAILED"),
        ("CHECK_COUNT", "three items", css("li.item", Expected_Value=3), "PASSED"),
        ("CHECK_COUNT", "none at all", css(".nothing", Expected_Value=0), "PASSED"),
        ("CHECK_COUNT", "at least five", css("li.item", Output_Property=">=", Expected_Value=5), "FAILED"),
        ("CHECK_ENABLED", "aria-disabled counts", css("#buy", Expected_Value="N"), "PASSED"),
        ("CHECK_ENABLED", "ok is enabled", css("#ok", Expected_Value="Y"), "PASSED"),
        ("CHECK_CHECKED", "ticked", css("#agree", Expected_Value="Y"), "PASSED"),
        ("CHECK_CHECKED", "not ticked", css("#news", Expected_Value="Y"), "FAILED"),
        ("CHECK_SELECTED", "plan", css("#plan", Expected_Value="Max"), "PASSED"),
        ("CHECK_DATE_FORMAT", "date shape", css("#when", Expected_Value="dd/mm/yyyy"), "PASSED"),
        ("CHECK_DATE_FORMAT", "wrong shape", css("#bad-when", Expected_Value="dd/mm/yyyy"), "FAILED"),
        ("CHECK_REGEX", "missing element", css("#nope", Expected_Value="x"), "FAILED"),
        ("CHECK_REGEX", "bad pattern", css("#ref", Expected_Value="(", Ignore_not_existing_object="Y"), "FAILED"),
    ]
    wb = book(tmp_path / "a.xlsx", {"T": [open_page(), *[(m, n, c) for m, n, c, _ in checks]]}, environments=envs(site))
    result, _, _ = await run(make_cfg, wb, ["T"], **{"timeouts.element_s": 1, "output.match_timeout_s": 0.5})
    steps = by_name(result.tests[0])
    assert {n: steps[n].status for _, n, _, _ in checks} == {n: want for _, n, _, want in checks}
    assert steps["between"].error == "Comparison Failed" and any("1234.5 is not between 1 and 10" in x for x in steps["between"].notes)
    assert steps["three items"].actual == "3" and steps["none at all"].actual == "0"
    assert steps["missing element"].error == "Object was not found" and "not a valid pattern" in steps["bad pattern"].error


async def test_a_side_effect_step_is_blocked_on_production_and_stops_the_test_but_runs_in_a_normal_run(site, make_cfg, tmp_path):
    rows = [open_page(), ("CLICK", "pay", css("#pay-new", SIDE_EFFECTS="Y")),
            ("WAIT_UNTIL", "paid", css("#paid", Output_Property="TEXT", Expected_Value="paid 1", Exact_Match="Y"))]
    live = [["Variable", "Required", "Secret", "UAT", "LIVE"], ["#PRODUCTION", "", "", "", "Y"], ["DOMAIN", "Y", "", site.rstrip("/"), site.rstrip("/")]]
    prod = book(tmp_path / "prod.xlsx", {"T": rows}, environments=live, environment="LIVE")    # (production because the table says so: the mock site)
    result, events, _ = await run(make_cfg, prod, ["T"], env="LIVE")
    (test,) = result.tests
    assert test.status == "FAILED" and [s.name for s in test.steps] == ["open the page", "pay"]
    assert "Blocked" in test.steps[1].error and "production" in test.error and test.skipped == 1
    (blocked,) = [e for e in events if e["type"] == "side_effect_blocked"]
    assert blocked["environment"] == "LIVE" and blocked["name"] == "pay"
    uat = book(tmp_path / "uat.xlsx", {"T": rows}, environments=envs(site))
    result, events, _ = await run(make_cfg, uat, ["T"])
    assert result.tests[0].status == "PASSED", [(s.name, s.error, s.notes) for s in result.tests[0].steps]
    assert not [e for e in events if e["type"].startswith("side_effect")]


async def test_a_backup_locator_that_finds_the_element_is_reported_with_a_screenshot_but_the_step_still_fails_and_nothing_is_clicked(site, make_cfg, tmp_path):
    backups = json.dumps(["css=#pay-button", "css=[data-testid=pay]"])
    wb = book(tmp_path / "a.xlsx", {"T": [open_page(),
                                          ("CLICK", "pay", {"FindBy": "xpath", "FindBy_Value": "//button[@id='pay-old']", "Index": 0, "BACKUP_LOCATORS": backups}),
                                          ("Output", "nothing was paid", css("#paid", Output_Property="innertext", Exact_Match="Y"))]},
              environments=envs(site))
    result, events, run_dir = await run(make_cfg, wb, ["T"])
    steps = by_name(result.tests[0])
    pay = steps["pay"]
    assert pay.status == "FAILED" and pay.error == "Object was not found"
    assert pay.diagnosis["backup"]["locator"] == "css=[data-testid=pay]" and pay.diagnosis["backup"]["matches"] == 1
    assert pay.diagnosis["summary"][0].startswith("Backup locator css=[data-testid=pay] found 1 match")
    assert "Proposed locator: css=[data-testid=pay]" in pay.detail
    assert [t["matches"] for t in pay.diagnosis["backup"]["tried"]] == [0, 1]
    (event,) = [e for e in events if e["type"] == "backup_locator_suggestion"]
    assert event["locator"] == "css=[data-testid=pay]" and event["matches"] == 1 and (run_dir / event["screenshot"]).is_file()
    assert steps["nothing was paid"].status == "PASSED"                  # the backup was only looked at, never clicked


async def test_check_list_item_needs_the_list_to_be_showing_and_reads_the_nth_item(site, make_cfg, tmp_path):
    wb = book(tmp_path / "li.xlsx", {
        "Hidden": [open_page(), ("CHECK_LIST_ITEM", "nothing typed yet", css("#city-list", Output_Property="1", Expected_Value="Sydney"))],
        "Shown": [open_page(), ("SET", "type", css("#city", Value="syd")),
                  ("CHECK_LIST_ITEM", "second item", css("#city-list", Output_Property="2", Expected_Value="Sydney Airport")),
                  ("CHECK_LIST_ITEM", "first, wrong", css("#city-list", Output_Property="1", Expected_Value="Melbourne")),
                  ("CHECK_LIST_ITEM", "fourth", css("#city-list", Output_Property="4", Expected_Value="Sydney"))]},
        environments=envs(site))
    result, _, _ = await run(make_cfg, wb, ["Hidden", "Shown"])
    hidden, shown = result.tests
    assert hidden.status == "FAILED" and any("list is not showing" in n for n in by_name(hidden)["nothing typed yet"].notes)
    steps = by_name(shown)
    assert steps["second item"].status == "PASSED"
    assert steps["first, wrong"].status == "FAILED" and steps["fourth"].status == "FAILED"
    assert any("no item 4" in n for n in steps["fourth"].notes)
