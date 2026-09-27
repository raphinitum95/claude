"""The build window (build/session.py, P08) on the mock site: the overlay in every page, frame and window; picking without the site noticing;
locators, "which one?", words as variables; run up to here / this step / next with the runner's own actions; the side-effect pause; the
"earlier steps changed" warning.  Headless: ``build.headless`` is for tests only (a person needs to see the window)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from regrunner.build.session import BuildSession
from regrunner.config import Config
from regrunner.workbook.builder import BuildDocument
from tests.flow_books import book

pytestmark = pytest.mark.browser

MAX_BUTTON = "//h3[.='Max']/..//button"


def plans_book(path: Path, site: str, *, pay_side_effects: str = "Y", second_click: str = MAX_BUTTON) -> Path:
    """Open the plans page, choose Max, pay (a side effect), read what was paid."""
    envs = [["Variable", "Required", "Secret", "UAT", "PROD"], ["DOMAIN", "Y", "", site.rstrip("/"), site.rstrip("/")]]
    return book(path, {"Plans": [
        ("Open", "open plans", {"Page": "chrome", "Value": "{DOMAIN}/build_pick.html"}),
        ("Click", "choose", {"FindBy": "xpath", "FindBy_Value": second_click, "Index": 0}),
        ("Click", "pay", {"FindBy": "CSS_SELECTOR", "FindBy_Value": "[data-testid=pay-now]", "Index": 0, "SIDE_EFFECTS": pay_side_effects}),
        ("Output", "paid once", {"FindBy": "CSS_SELECTOR", "FindBy_Value": "#paid", "Index": 0, "Output_Property": "innertext",
                                 "Expected_Value": "paid 1", "Exact_Match": "Y"}),
    ]}, params={"Plans": [{"PLAN": "Basic"}, {"PLAN": "Max"}]}, environments=envs)


@pytest.fixture
async def session(site, tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.timeouts.element_s = 3
    cfg.timeouts.optional_s = 1
    cfg.output.match_timeout_s = 1.5
    cfg.build.headless = True
    cfg.build.idle_close_s = 0
    doc = BuildDocument(plans_book(tmp_path / "plans.xlsx", site), tmp_path / "runs")
    s = BuildSession(doc, cfg, tmp_path / "runs" / ".build" / "plans", environment="UAT", headless=True)
    await s.start("Plans", None)
    await settled(s)
    yield s
    await s.close()


async def settled(s: BuildSession, timeout: float = 30, answer: str | None = None) -> dict:
    """Wait for the replay in flight to end (answering a question with ``answer`` when one comes)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while s._task is not None and not s._task.done():
        if s.question and answer is not None:
            s.asker.answer(s.question["id"], answer)
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the replay did not end")
        await asyncio.sleep(0.1)
    return s.state()


async def until(check, timeout: float = 10):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = await check()
        if value:
            return value
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.1)


async def pick_on_page(s: BuildSession, locator, row: int | None = None) -> dict:
    s.pick = None
    await s.set_mode("pick", row)
    await locator.click()
    return await until(lambda: asyncio.sleep(0, s.pick))


def results(state: dict) -> list[tuple[int, str]]:
    return [(r["n"], r["status"]) for r in state["replay"]["results"]]


async def test_opening_the_window_runs_the_first_open_step_and_the_overlay_is_in_every_frame_window_and_new_page(session):
    s = session
    state = s.state()
    assert state["open"] and results(state) == [(1, "PASSED")] and state["cursor"]["n"] == 1
    page = s._page()
    assert await page.evaluate("!!window.__rrBuild") and await page.locator("rr-build-overlay").count() == 1
    frame = page.frame(name="inner")
    await until(lambda: frame.evaluate("!!window.__rrBuild"))
    async with page.context.expect_page() as popup:
        await page.locator("#new-window").click()                     # (not picking: the site gets the click and opens a window)
    new = await popup.value
    await new.wait_for_load_state()
    assert await new.evaluate("!!window.__rrBuild")
    await page.locator("#next-page").click()
    await page.wait_for_url("**/second.html")
    await until(lambda: page.evaluate("!!window.__rrBuild && !!document.querySelector('rr-build-overlay')"))
    assert await page.evaluate("typeof window.__rrBuildCall") == "function"


async def test_a_pick_never_reaches_the_sites_listeners_and_gets_the_most_stable_unique_locator(session):
    s = session
    page = s._page()
    pick = await pick_on_page(s, page.locator(".card").nth(2).locator("button"), row=3)
    assert await page.evaluate("[window.sitePresses, window.siteClicks.length]") == [0, 0]
    assert await page.locator("#chosen").inner_text() == "none"
    assert pick["ok"] and pick["text"] == "button “Choose” inside card “Max”" and pick["forN"] == 2
    loc = pick["locator"]
    assert loc["findBy"] == "BY_XPATH" and loc["how"] == "context" and loc["matches"] == 1 and "'Max'" in loc["value"]
    assert 1 <= len(loc["backups"]) <= 3
    field = await pick_on_page(s, page.locator("#firstName"))
    assert (field["locator"]["findBy"], field["locator"]["value"]) == ("BY_ID", "firstName")
    pay = await pick_on_page(s, page.get_by_text("Pay now"))
    assert pay["locator"]["how"] == "testid" and await page.locator("#paid").inner_text() == "not paid"
    await s.set_mode("browse")
    await page.locator(".card").nth(0).locator("button").click()          # browsing: the site works as usual
    assert await page.locator("#chosen").inner_text() == "Basic"


async def test_a_pick_inside_a_frame_is_located_in_that_frame_and_says_so(session):
    s = session
    frame = s._page().frame_locator("iframe[name=inner]")
    pick = await pick_on_page(s, frame.locator("#frame-button"))
    assert pick["locator"]["value"] == "frame-button" and pick["frame"] == "inner"


async def test_which_one_numbers_every_match_and_the_chosen_one_gets_a_direct_locator(session):
    s = session
    which = await s.find_matches("Choose", "button")
    assert [m["context"] for m in which["matches"]] == ["Basic", "Plus", "Max"] and s.mode == "which"
    pick = await s.choose(1)
    assert "'Plus'" in pick["locator"]["value"] and pick["locator"]["matches"] == 1 and s.mode == "browse"
    assert (await s.find_matches("Nothing like this"))["matches"] == []


async def test_a_word_becomes_a_variable_and_the_locator_is_rechecked_with_every_data_row(session):
    s = session
    await pick_on_page(s, s._page().locator(".card").nth(2).locator("button"), row=3)
    pick = await s.make_variable("context", "PLAN")
    assert pick["ok"] and pick["text"] == "button “Choose” inside card {PLAN}"
    assert "'{PLAN}'" in pick["locator"]["value"] and "Max" not in pick["locator"]["value"]
    assert [(r["row"], r["values"]["PLAN"], r["matches"]) for r in pick["rows"]] == [(2, "Basic", 1), (3, "Max", 1)]
    assert pick["values"] == {"PLAN": "Basic"}                                                   # "Building with" row 2
    with pytest.raises(Exception, match="variable name"):
        await s.make_variable("name", "not a name")


async def test_use_for_step_puts_the_locator_and_its_backups_on_the_step_and_the_step_shows_its_words(session):
    s = session
    await pick_on_page(s, s._page().locator(".card").nth(2).locator("button"), row=3)
    await s.make_variable("context", "PLAN")
    before = s.doc.version
    await s.use()
    assert s.doc.version > before
    step = next(x for t in s.doc.model()["tests"] if t["id"] == "Plans" for x in t["steps"] if x["row"] == 3)
    assert step["locator"]["findBy"] == "BY_XPATH" and "{PLAN}" in step["locator"]["value"] and step["locator"]["backups"]
    assert [w["text"] for w in step["locator"]["plainWords"]] == ["button", "Choose", "inside card", "{PLAN}"]
    s.run("to", row=3)
    state = await settled(s)
    assert results(state) == [(1, "PASSED"), (2, "PASSED")]                                     # row 2's PLAN is Basic: its card's button
    assert await s._page().locator("#chosen").inner_text() == "Basic"


async def test_run_up_to_here_then_this_step_then_next_keep_the_same_window_and_state(session):
    s = session
    s.run("to", row=3)
    state = await settled(s)
    assert results(state) == [(1, "PASSED"), (2, "PASSED")] and state["cursor"]["n"] == 2 and state["next"]["n"] == 3
    page = s._page()
    assert await page.locator("#chosen").inner_text() == "Max"
    s.run("step", row=4)                                                     # pay: a side effect, so a person is asked first
    state = await settled(s, answer="yes")
    assert results(state) == [(3, "PASSED")] and await page.locator("#paid").inner_text() == "paid 1"
    assert s._page() is page                                                 # the same window: nothing was replayed from the start
    s.run("next", count=5)
    state = await settled(s)
    assert results(state) == [(4, "PASSED")] and state["replay"]["stopped"] == ""


async def test_a_side_effect_step_is_not_run_when_the_person_says_no_and_the_replay_stops_before_it(session):
    s = session
    s.run("to", row=5)
    question = await until(lambda: asyncio.sleep(0, s.question))
    assert question["sideEffect"]["name"] == "pay" and question["sideEffect"]["environment"] == "UAT"
    state = await settled(s, answer="no")
    assert results(state)[-1] == (3, "FAILED") and "chose not to run it" in state["replay"]["stopped"]
    assert await s._page().locator("#paid").inner_text() == "not paid"
    assert any(e["type"] == "side_effect_paused" for e in state["log"]) and not state["question"]


async def test_a_replay_stops_at_its_first_failed_step(site, tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.timeouts.element_s = 1
    cfg.build.headless, cfg.build.idle_close_s = True, 0
    doc = BuildDocument(plans_book(tmp_path / "broken.xlsx", site, second_click="//button[@id='gone']"), tmp_path / "runs")
    s = BuildSession(doc, cfg, tmp_path / "runs" / ".build" / "broken", environment="UAT", headless=True)
    try:
        await s.start("Plans", None)
        await settled(s)
        s.run("to", row=5)
        state = await settled(s)
        assert results(state) == [(1, "PASSED"), (2, "FAILED")] and state["replay"]["stopped"].startswith("Step 2 failed")
        assert state["next"]["n"] == 3
    finally:
        await s.close()


async def test_changing_a_step_that_already_ran_says_replay_from_the_start_but_a_later_one_does_not(session):
    s = session
    s.run("to", row=3)
    await settled(s)
    assert not s.state()["stale"]
    s.doc.apply([{"op": "update_step", "test": "Plans", "row": 4, "set": {"timeout": 9}}])      # after the window: fine
    assert not s.state()["stale"]
    s.doc.apply([{"op": "update_step", "test": "Plans", "row": 3, "set": {"timeout": 9}}])      # the step that just ran
    assert s.state()["stale"]
    s.run("to", row=3)
    await settled(s)
    assert not s.state()["stale"]
    s.doc.apply([{"op": "set_cell", "sheet": "Plans_Params", "row": 2, "column": "PLAN", "value": "Plus"}])   # the data it ran with
    assert s.state()["stale"]


async def test_a_steps_edit_after_the_window_is_read_by_the_next_steps_without_a_replay(session):
    s = session
    s.run("to", row=2)
    await settled(s)
    s.doc.apply([{"op": "update_step", "test": "Plans", "row": 3, "set": {"locator": "//h3[.='Plus']/..//button"}}])
    s.run("next", count=1)
    state = await settled(s)
    assert results(state) == [(2, "PASSED")] and await s._page().locator("#chosen").inner_text() == "Plus"


async def test_the_sites_own_scripts_can_reach_the_overlay_but_never_change_the_workbook(session):
    s = session
    before = s.doc.version
    page = s._page()
    await page.evaluate("window.__rrBuildCall({kind: 'use'})")
    await page.evaluate("window.__rrBuildCall({kind: 'pick', element: {tag: 'button', text: 'Choose'}})")
    await asyncio.sleep(0.5)
    assert s.doc.version == before and s.doc.status()["modified"] is False
    assert await page.evaluate("Object.keys(window).includes('__rrBuild')") is False           # (not enumerable: the site's globals look the same)


async def test_switching_to_another_data_row_starts_the_test_again_in_the_window(session):
    s = session
    s.run("to", row=3)
    await settled(s)
    await s.switch("Plans", 3, "UAT")
    state = await settled(s)
    assert state["dataRow"] == 3 and results(state) == [(1, "PASSED")] and state["cursor"]["n"] == 1
    s.run("next", count=1)
    await settled(s)
    assert await s._page().locator("#chosen").inner_text() == "Max"
