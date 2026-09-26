"""A slow computer or a slow site must never turn into a failure, and the verdict must not depend on how many tests run at once.

Waits end on evidence (engine/patience.py): while the page is visibly working they go on; a page that has finished (or is stuck) still fails
in bounded time, with the reason.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus
from tests.workbook_factory import build_steps_workbook

pytestmark = pytest.mark.browser


def quote_flow(sheet) -> None:
    """Open the page, wait for the plan (the site's slow answer), click through, check the result."""
    sheet.add("Open", "Open", Value="DT_URL")
    sheet.add("Output", "Plan shown", FindBy="xpath", FindBy_Value="//p[@id='plan']", Index=0, Output_Property="innertext",
              Expected_Value="Plan ready", Exact_Match="Y")
    sheet.add("Click", "Get quote", FindBy="xpath", FindBy_Value="//button[@id='go']", Index=0)
    sheet.add("Output", "Result", FindBy="xpath", FindBy_Value="//span[@id='result']", Index=0, Output_Property="innertext",
              Expected_Value="Done", Exact_Match="Y")
    sheet.add("Quit", "Quit")


def busy_flow(sheet) -> None:
    sheet.add("Open", "Open", Value="DT_URL")
    sheet.add("Output", "Plan shown", FindBy="xpath", FindBy_Value="//p[@id='plan']", Index=0, Output_Property="innertext",
              Expected_Value="Plan ready", Exact_Match="Y")
    sheet.add("Quit", "Quit")


def workbook(tmp_path, site, flows: dict, urls: dict):
    wb = tmp_path / "wb.xlsx"
    build_steps_workbook(wb, flows, params={name: {"DT_URL": url} for name, url in urls.items()})
    return wb


async def run(wb, cfg, tests, workers):
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    started = time.monotonic()
    result = await execute(RunOptions(workbook=wb, seed=1, tests=tests, workers=workers), cfg, bus)
    return result, events, time.monotonic() - started


def verdicts(result) -> dict:
    """What a person compares between two runs: each test's status and, step by step, its status and what it read."""
    return {t.id: (t.status, [(s.seq, s.status, s.actual) for s in t.steps]) for t in result.tests}


async def test_the_same_workbook_gives_the_same_verdicts_at_one_worker_and_at_three_even_when_the_site_answers_after_25_s(site, make_cfg, tmp_path):
    """Acceptance 1: a page whose server answers after 25 s, a tab whose computer is too busy to answer for 15 s, and a quick page - identical
    results with 1 worker and with 3 (and every test passes, where the old fixed limits failed the slow ones: see the next test)."""
    flows = {"Slow": quote_flow, "Busy": busy_flow, "Quick": quote_flow}
    urls = {"Slow": site + "slow.html?ms=25000", "Busy": site + "cpu.html?ms=15000", "Quick": site + "slow.html?ms=300"}
    wb = workbook(tmp_path, site, flows, urls)
    cfg = make_cfg(**{"runner.stagger_s": 0.5, "runner.min_page_load_gap_s": 0})
    alone, events_alone, _ = await run(wb, cfg, list(flows), 1)
    together, events_together, _ = await run(wb, make_cfg(**{"runner.stagger_s": 0.5, "runner.min_page_load_gap_s": 0}), list(flows), 3)
    assert {t.id: t.status for t in alone.tests} == {"Slow": "PASSED", "Busy": "PASSED", "Quick": "PASSED"}, [(t.id, t.error, [(s.name, s.error, s.notes) for s in t.steps if s.status != "PASSED"]) for t in alone.tests]
    assert verdicts(alone) == verdicts(together)
    for events in (events_alone, events_together):
        slow = [e for e in events if e["type"] == "worker_waiting" and e["code"] == "slow_page"]
        assert {e["test"] for e in slow} >= {"Slow", "Busy"}               # the long waits were shown on the run screen, with the reason
        assert any("has not answered yet" in e["message"] for e in slow if e["test"] == "Slow")
        assert any("computer is very busy" in e["message"] for e in slow if e["test"] == "Busy")
        waiting = {e["wait"] for e in slow}
        assert waiting == {e["wait"] for e in events if e["type"] == "worker_resumed" and e["code"] == "slow_page"}      # ...and taken down after
    slow_steps = {s.name: s for s in next(t for t in alone.tests if t.id == "Slow").steps}
    assert any("waited" in n and "the page was slow" in n for s in slow_steps.values() for n in s.notes)     # the report says it too


async def test_with_the_old_fixed_limits_the_slow_site_failed(site, make_cfg, tmp_path):
    """The control: the same slow page with patience off (element_s = 6 s here) fails - which is what used to happen on a busy machine."""
    wb = workbook(tmp_path, site, {"Slow": quote_flow}, {"Slow": site + "slow.html?ms=20000"})
    result, _, _ = await run(wb, make_cfg(**{"patience.enabled": False, "runner.stagger_s": 0}), ["Slow"], 1)
    assert result.tests[0].status == "FAILED"


def absent_flow(sheet) -> None:
    sheet.add("Open", "Open", Value="DT_URL")
    sheet.add("Click", "A button this page does not have", FindBy="xpath", FindBy_Value="//button[@id='nope']", Index=0)
    sheet.add("Quit", "Quit")


async def test_a_wrong_page_or_a_stuck_page_still_fails_in_bounded_time_with_the_reason(site, make_cfg, tmp_path):
    """Acceptance 2: slow is not the same as wrong.  A missing element on a finished page fails in the step's normal time; a page whose request
    never answers, and a page that never finishes loading, fail once nothing has moved for patience.stall_s."""
    flows = {"Absent": absent_flow, "Hung": busy_flow, "NeverLoads": busy_flow}
    urls = {"Absent": site + "index.html", "Hung": site + "slow.html?path=/bin/forever", "NeverLoads": site + "never_load.html"}
    wb = workbook(tmp_path, site, flows, urls)
    cfg = make_cfg(**{"runner.stagger_s": 0, "runner.min_page_load_gap_s": 0, "patience.stall_s": 4, "patience.tell_after_s": 2})
    result, events, took = await asyncio.wait_for(run(wb, cfg, list(flows), 3), 120)
    by = {t.id: t for t in result.tests}
    assert took < 60

    absent = next(s for s in by["Absent"].steps if s.action == "CLICK")
    assert by["Absent"].status == "FAILED" and "Object was not found" in absent.error
    assert any("had finished loading" in n and "did not appear within 6 s" in n for n in absent.notes), absent.notes
    assert 5 < absent.duration_ms / 1000 < 15                                   # the step's normal time on a quiet page, not minutes

    hung = next(s for s in by["Hung"].steps if s.action == "OUTPUT")
    assert by["Hung"].status == "FAILED" and hung.status == "FAILED"            # (an Output with Exact_Match reports "Comparison Failed", as ever)
    assert any("nothing on the page moved for 4 s" in n and "/bin/forever" in n for n in hung.notes), hung.notes
    assert hung.duration_ms / 1000 < 20

    opened = by["NeverLoads"].steps[0]
    assert opened.status == "FAILED" and "never finished loading" in opened.error and "nothing on the page moved for 4 s" in opened.error
    assert by["NeverLoads"].status == "ERROR"                                   # nothing loaded: the rest was not run
    assert all(t.status != "NOT_RUN" for t in result.tests)                     # a site problem, not the machine's


def dialog_flow(sheet) -> None:
    sheet.add("Open", "Open", Value="DT_URL")
    sheet.add("Click", "Show the alert", FindBy="xpath", FindBy_Value="//button[@id='al']", Index=0)
    sheet.add("Wait", "A slow computer gets to the next step late", Value=3)
    sheet.add("ALERT_TEXT_OUT", "Read the alert", Expected_Value="Hello from the site", Exact_Match="Y")
    sheet.add("Quit", "Quit")


async def test_an_alert_waits_for_its_step_however_late_that_step_comes(site, make_cfg, tmp_path):
    """A dialog nobody answers is dismissed after 1.5 s - so an ALERT step that a slow computer reached later found nothing.  When the next step
    (past Wait rows) is the ALERT step, the dialog is answered as it opens, the way that step says, and the step reads what it said."""
    wb = workbook(tmp_path, site, {"Dialog": dialog_flow}, {"Dialog": site + "alert.html"})
    result, _, _ = await asyncio.wait_for(run(wb, make_cfg(**{"runner.stagger_s": 0, "waits.mode": "legacy"}), ["Dialog"], 1), 90)
    test = result.tests[0]
    assert test.status == "PASSED", [(s.name, s.error) for s in test.steps]
    assert next(s for s in test.steps if s.action == "ALERT_TEXT_OUT").actual == "Hello from the site"


async def test_an_optional_element_on_a_page_still_loading_is_waited_for_not_called_absent(site, make_cfg, tmp_path):
    """Ignore_not_existing_object=Y used to mean 'absent after 3 s', even while the page was still loading it: on a slow computer the step then
    skipped what it was for (a cookie banner that appeared a moment later still covered the page)."""
    def flow(sheet) -> None:
        sheet.add("Open", "Open", Value="DT_URL")
        sheet.add("Output", "Plan (optional)", FindBy="xpath", FindBy_Value="//p[@id='plan']", Index=0, Output_Property="innertext",
                  Ignore_not_existing_object="Y")
        sheet.add("Quit", "Quit")
    wb = workbook(tmp_path, site, {"Optional": flow}, {"Optional": site + "slow.html?ms=5000"})
    result, _, _ = await run(wb, make_cfg(**{"runner.stagger_s": 0}), ["Optional"], 1)
    step = next(s for s in result.tests[0].steps if s.action == "OUTPUT")
    assert step.actual == "Plan ready" and not step.ignored_error


async def test_the_login_code_wait_is_announced_before_it_starts_and_never_names_the_code(site, make_cfg, tmp_path):
    """The TOTP wait used to be silent (a note after the sleep): the run screen must say it before, with a countdown."""
    from regrunner import totp
    from tests.test_totp_reuse import SECRET
    totp._taken[totp.fingerprint(SECRET)] = int(time.time() // totp.STEP_S)    # another login just used this window's code: this one has to wait

    def flow(sheet) -> None:
        sheet.add("GET_GOOGLE_TOKEN", "Get code", Value="DT_Key")
        sheet.add("Quit", "Quit")
    wb = tmp_path / "wb.xlsx"
    build_steps_workbook(wb, {"Login": flow}, params={"Login": {"DT_Key": SECRET}})
    events: list[dict] = []
    bus = EventBus()
    order: list[str] = []
    bus.subscribe(lambda e: (events.append(e), order.append(e["type"])))
    result = await execute(RunOptions(workbook=wb, seed=1, tests=["Login"], workers=1), make_cfg(**{"runner.stagger_s": 0}), bus)
    assert result.tests[0].status == "PASSED"
    (waiting,) = [e for e in events if e["type"] == "worker_waiting"]
    (resumed,) = [e for e in events if e["type"] == "worker_resumed"]
    assert waiting["code"] == "login_code" and 0 < waiting["seconds"] <= 30.5 and "next login code" in waiting["message"]
    assert "another test has just used this account's current code" in waiting["message"]
    assert resumed["wait"] == waiting["wait"] and resumed["waited_s"] >= waiting["seconds"] - 0.5
    step = result.tests[0].steps[0]
    code = totp.code_at(SECRET, (int(time.time()) // 30) * 30)
    text = json.dumps(events)
    assert step.actual == "••••••" and SECRET not in text
    assert all(totp.code_at(SECRET, w * 30) not in text for w in range(int(time.time()) // 30 - 3, int(time.time()) // 30 + 2)), code
