"""The machine, not the site: a browser that crashes (out of memory...) or disconnects is "not run" - never a pass or a fail - and the test is run
again from the start, every attempt recorded."""
from __future__ import annotations

import asyncio
import json

import pytest

from regrunner.engine import actions
from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus
from tests.workbook_factory import build_steps_workbook

pytestmark = pytest.mark.browser

TROUBLE = {"crash": 0, "kill": 0}


@actions.action("TEST_CRASH_TAB")
async def _crash_tab(ctx) -> None:
    """(tests only) The first TROUBLE["crash"] times: the tab's renderer crashes, as it does when the computer runs out of memory."""
    if TROUBLE["crash"] > 0:
        TROUBLE["crash"] -= 1
        await ctx.session.page.goto("chrome://crash")


@actions.action("TEST_KILL_BROWSER")
async def _kill_browser(ctx) -> None:
    """(tests only) The first TROUBLE["kill"] times: the whole browser goes away under the test (killed, crashed)."""
    if TROUBLE["kill"] > 0:
        TROUBLE["kill"] -= 1
        await ctx.session._browser.close()
        await ctx.session.page.title()


@pytest.fixture(autouse=True)
def calm():
    TROUBLE.update(crash=0, kill=0)
    yield
    TROUBLE.update(crash=0, kill=0)


def flow(trouble: str):
    def fill(sheet) -> None:
        sheet.add("Open", "Open", Value="DT_URL")
        sheet.add(trouble, "The machine has a problem")
        sheet.add("Output", "Heading", FindBy="xpath", FindBy_Value="//h1", Index=0, Output_Property="innertext")
        sheet.add("Quit", "Quit")
    return fill


async def run(site, make_cfg, tmp_path, trouble: str, retries: int = 1):
    wb = tmp_path / "wb.xlsx"
    build_steps_workbook(wb, {"Crashy": flow(trouble)}, params={"Crashy": {"DT_URL": site + "index.html"}})
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    cfg = make_cfg(**{"runner.stagger_s": 0, "runner.infra_retries": retries, "runner.infra_pause_s": 0.5})
    result = await asyncio.wait_for(execute(RunOptions(workbook=wb, seed=1, tests=["Crashy"], workers=1), cfg, bus), 120)
    return result, events


async def test_a_tab_that_crashes_is_not_run_and_the_test_is_run_again_from_the_start(site, make_cfg, tmp_path):
    TROUBLE["crash"] = 1
    result, events = await run(site, make_cfg, tmp_path, "TEST_CRASH_TAB")
    test = result.tests[0]
    assert test.status == "PASSED" and test.attempt == 2, (test.status, test.error)
    (first,) = test.attempts
    assert first["status"] == "NOT_RUN" and "crashed" in first["infra"]
    assert result.status == "PASSED" and result.summary["not_run"] == 0
    finished = [e["status"] for e in events if e["type"] == "test_finished"]
    assert finished == ["NOT_RUN", "PASSED"]                                  # never counted as failed
    (waiting,) = [e for e in events if e["type"] == "worker_waiting"]
    assert waiting["code"] == "infra_rerun" and "not a test result" in waiting["message"] and waiting["seconds"] == 0.5
    assert [e["wait"] for e in events if e["type"] == "worker_resumed"] == [waiting["wait"]]
    assert [e for e in events if e["type"] == "run_progress"][-1]["percent"] == 100.0


async def test_a_browser_that_goes_away_is_not_run_either(site, make_cfg, tmp_path):
    TROUBLE["kill"] = 1
    result, _ = await run(site, make_cfg, tmp_path, "TEST_KILL_BROWSER")
    test = result.tests[0]
    assert test.status == "PASSED" and test.attempt == 2 and "closed unexpectedly" in test.attempts[0]["infra"]


async def test_a_test_that_keeps_crashing_ends_not_run_and_the_run_is_incomplete_not_failed(site, make_cfg, tmp_path):
    TROUBLE["crash"] = 99
    result, events = await run(site, make_cfg, tmp_path, "TEST_CRASH_TAB", retries=1)
    test = result.tests[0]
    assert test.status == "NOT_RUN" and len(test.attempts) == 1 and "says nothing about the application" in test.error
    assert result.status == "INCOMPLETE"
    assert result.summary["not_run"] == 1 and result.summary["failed"] == 0 and result.summary["errored"] == 0
    crashed = [s for s in test.steps if s.status == "NOT_RUN"]
    assert len(crashed) == 1 and crashed[0].error.startswith("Not run:") and test.failed == 0


def test_the_shared_summary_and_the_console_say_not_run_separately(tmp_path):
    from regrunner.publish import summary_text
    data = {"run_id": "r", "status": "INCOMPLETE", "summary": {"tests": 2, "passed": 1, "failed": 0, "errored": 0, "not_run": 1},
            "tests": [{"id": "A", "status": "PASSED", "steps": []}, {"id": "B", "status": "NOT_RUN", "steps": [], "error": "Not run: The browser tab crashed"}]}
    text = summary_text(data)
    assert "1 could not be run on this computer" in text and "neither passed nor failed" in text and "did not" not in text.split("\n")[1]
