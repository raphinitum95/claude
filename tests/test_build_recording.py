"""Recording in the build window (build/recorder.py, P09) on the mock site: a person's clicks, typing, choices and ticks become steps at the cursor;
typed text becomes a variable (a password a secret); windows, frames and Back get their switch steps; calendars and suggestions collapse into one
step; a new page gets its page check (fingerprint + ASSERT_PAGE) and a page (block) of its own; Check / Save / Wait until from the live element.  What is recorded replays with the
runner's own actions.  Headless (``build.headless`` is for tests only)."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from regrunner.build.recorder import relative_date
from regrunner.build.session import BuildSession
from regrunner.config import Config
from regrunner.workbook.builder import BuildDocument, read_fingerprints
from tests.flow_books import book
from tests.test_build_session import results, settled, until

pytestmark = pytest.mark.browser


def record_book(path: Path, site: str, page: str = "build_record.html") -> Path:
    envs = [["Variable", "Required", "Secret", "UAT", "PROD"], ["DOMAIN", "Y", "", site.rstrip("/"), site.rstrip("/")]]
    return book(path, {"Rec": [("Open", "open the form", {"Page": "chrome", "Value": "{DOMAIN}/" + page})]},
                params={"Rec": [{"LAST_NAME": "Doe", "NOTES": ""}]}, environments=envs)


async def open_session(site, tmp_path, page: str = "build_record.html") -> BuildSession:
    cfg = Config(base_dir=tmp_path)
    cfg.timeouts.element_s = 3
    cfg.timeouts.optional_s = 1
    cfg.output.match_timeout_s = 1.5
    cfg.build.headless = True
    cfg.build.idle_close_s = 0
    doc = BuildDocument(record_book(tmp_path / "rec.xlsx", site, page), tmp_path / "runs")
    s = BuildSession(doc, cfg, tmp_path / "runs" / ".build" / "rec", environment="UAT", headless=True)
    await s.start("Rec", None)
    await settled(s)
    return s


@pytest.fixture
async def session(site, tmp_path):
    s = await open_session(site, tmp_path)
    yield s
    await s.close()


def steps(s: BuildSession) -> list[tuple]:
    """(method, value) of every step after the Open step."""
    return [(st["method"], st["value"]) for st in s._steps()[1:]]


def step_at(s: BuildSession, n: int) -> dict:
    return next(st for st in s._steps() if st["n"] == n)


async def quiet(s: BuildSession, count: int | None = None, timeout: float = 10) -> None:
    """Wait until the recorder has handled what the page sent (and has written ``count`` steps, when given)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        await asyncio.sleep(0.25)
        if not s.recorder.lock.locked() and (count is None or s.recorder.count >= count):
            await asyncio.sleep(0.2)
            if not s.recorder.lock.locked():
                return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"the recorder did not get there: {s.recorder.count} steps, {steps(s)}")


def params(s: BuildSession) -> dict[str, list]:
    with s.doc.lock:
        rows = s.doc.editor.rows("Rec_Params")
    return {str(h): [r[i] if i < len(r) else None for r in rows[1:]] for i, h in enumerate(rows[0])}


async def test_clicks_typing_choices_and_ticks_become_steps_at_the_cursor_and_no_wait_is_ever_added(session):
    s = session
    await s.recorder.start(after=2)
    page = s._page()
    await page.click("#firstName")
    await page.keyboard.type("Jane")
    await page.click("input[name=lastName]")                     # (leaving First name records it)
    await page.keyboard.type("Doe")
    await page.focus("#plan")
    await page.keyboard.press("ArrowDown")                       # Basic -> Plus
    await page.click("#offers")
    await page.click("#continue")
    await page.wait_for_url("**/build_record2.html")
    await quiet(s, 5)
    await until(lambda: asyncio.sleep(0, len(steps(s)) == 6))                  # the page it landed on gets its check straight away
    assert steps(s) == [("SET", "{FIRST_NAME}"), ("SET", "{LAST_NAME}"), ("SELECT", "{PLAN_VALUE}"), ("TICK", ""), ("CLICK", ""),
                        ("ASSERT_PAGE", "Payment details page")]
    assert not any(m in ("WAIT", "WAIT_UNTIL") for m, _ in steps(s))
    assert step_at(s, 2)["locator"]["value"] == "firstName" and step_at(s, 6)["locator"]["value"] == "continue"
    assert params(s)["FIRST_NAME"] == ["Jane"] and params(s)["PLAN_VALUE"] == ["Plus"] and params(s)["LAST_NAME"] == ["Doe"]
    tags = {p["token"]: p["tag"] for p in s.recorder.prompts if p["kind"] == "variable"}
    assert tags == {"FIRST_NAME": "new", "LAST_NAME": "reused", "PLAN_VALUE": "new"}   # (PLAN would replace the locator "plan" at run time)
    events = [e for e in s.log if e["type"] == "build_session_step_recorded"]
    assert [e["method"] for e in events] == ["SET", "SET", "SELECT", "TICK", "CLICK", "ASSERT_PAGE"] and "Jane" not in json.dumps(events)
    assert s.state()["cursor"]["n"] == 7 and not s.state()["stale"]  # the window is past the recorded steps and the page check: nothing to replay


async def test_steps_go_after_the_step_recording_started_from_and_follow_each_other(session):
    s = session
    s.doc.apply([{"op": "insert_step", "test": "Rec", "step": {"method": "CLICK", "findBy": "BY_ID", "locator": "continue"}}])
    await s.recorder.start(after=2)                              # between Open (row 2) and the Click (row 3)
    page = s._page()
    await page.click("#offers")
    await page.click("[data-testid=pay]")
    await quiet(s, 2)
    assert [m for m, _ in steps(s)] == ["TICK", "CLICK", "CLICK"] and step_at(s, 4)["locator"]["value"] == "continue"
    assert step_at(s, 3)["sideEffects"] is True                  # "Pay now": flagged, replays will ask first
    assert any(p["kind"] == "side" for p in s.recorder.prompts)


async def test_a_typed_value_can_be_kept_as_fixed_text_or_renamed_and_nothing_is_left_behind(session):
    s = session
    await s.recorder.start(after=2)
    page = s._page()
    await page.fill("#firstName", "Jane")
    await page.focus("input[name=lastName]")
    await quiet(s, 1)
    prompt = next(p for p in s.recorder.prompts if p["kind"] == "variable")
    await s.recorder.answer(prompt["id"], "fixed")
    assert steps(s) == [("SET", "Jane")] and "FIRST_NAME" not in params(s)       # (the recorded edit was the last one: taken back cleanly)
    await page.fill("input[name=lastName]", "Smith")
    await page.focus("#firstName")
    await quiet(s, 2)
    prompt = next(p for p in s.recorder.prompts if p["kind"] == "variable")
    assert prompt["token"] == "LAST_NAME_2"                      # Smith is not LAST_NAME's value in the row being built with
    await s.recorder.answer(prompt["id"], "rename", token="SURNAME")
    assert steps(s) == [("SET", "Jane"), ("SET", "{SURNAME}")] and params(s)["SURNAME"] == ["Smith"] and "LAST_NAME_2" not in params(s)


async def test_a_password_becomes_a_secret_in_secrets_env_and_its_value_is_never_shown(session, tmp_path):
    s = session
    key = "RR_SECRET_UAT_ACCOUNT_PASSWORD"
    try:
        await s.recorder.start(after=2)
        page = s._page()
        await page.fill("#password", "Hunter2!x")
        await page.focus("#firstName")
        await quiet(s, 1)
        assert steps(s) == [("SET", "{SECRET:ACCOUNT_PASSWORD}")]
        assert f"{key}=Hunter2!x" in (tmp_path / "secrets.env").read_text(encoding="utf-8")
        assert "ACCOUNT_PASSWORD" not in params(s)
        variables = s.doc.model()["variables"]
        assert any(v["key"] == "ACCOUNT_PASSWORD" and v["secret"] for v in variables)
        assert "Hunter2" not in json.dumps(s.state()) and "Hunter2" not in s.doc.editor.to_bytes().decode("latin-1")
        await s.recorder.stop()
        pick = await pick_for(s, "check", page.locator("#password"))              # a password field picked to check: its value stays out
        assert pick["current"]["value"] == "" and "Hunter2" not in json.dumps(s.state())
        s.run("to", row=3)                                        # the replay types the secret from secrets.env
        state = await settled(s)
        assert results(state) == [(1, "PASSED"), (2, "PASSED")] and await s._page().input_value("#password") == "Hunter2!x"
        assert "Hunter2" not in json.dumps(s.state())
        await s.recorder.start(after=3)
        await s._page().fill("#password", "Hunter2!x")           # the same value again: the same secret
        await s._page().focus("#firstName")
        await quiet(s, 1)
        assert steps(s)[-1] == ("SET", "{SECRET:ACCOUNT_PASSWORD}")
    finally:
        os.environ.pop(key, None)


async def test_windows_frames_and_back_get_their_switch_steps_and_the_recording_replays(session):
    s = session
    await s.recorder.start(after=2)
    page = s._page()
    await page.frame_locator("iframe[name=inner]").locator("#frame-button").click()
    await page.click("#offers")
    async with page.context.expect_page() as popup:
        await page.click("#new-window")
    new = await popup.value
    await new.wait_for_load_state()
    await until(lambda: new.evaluate("!!window.__rrBuild"))
    await new.click("#frame-button")
    await page.bring_to_front()
    await page.click("#continue")
    await page.wait_for_url("**/build_record2.html")
    await quiet(s)
    await page.go_back()
    await page.wait_for_url("**/build_record.html")
    await quiet(s, 10)
    assert [m for m, _ in steps(s)] == ["SWITCHTOFRAME", "CLICK", "SWITCHTODEFAULT", "TICK", "CLICK", "SWITCHTOWINDOW", "CLICK",
                                         "SWITCHTOMAINWINDOW", "CLICK", "ASSERT_PAGE", "BACK"]        # (a new window's first page gets no check)
    assert steps(s)[0] == ("SWITCHTOFRAME", "inner") and steps(s)[5] == ("SWITCHTOWINDOW", "-1")
    await s.recorder.stop()
    s.run("to", row=s._steps()[-1]["row"])                        # the whole recording, from the start, in a fresh window
    state = await settled(s, timeout=60)
    assert [st for _, st in results(state)] == ["PASSED"] * 12, state["replay"]


async def test_a_new_page_gets_its_check_and_its_own_page_straight_away_and_the_check_passes_on_replay(session):
    s = session
    await s.recorder.start(after=2)
    page = s._page()
    await page.click("#continue")
    await page.wait_for_url("**/build_record2.html")
    await quiet(s, 1)
    prompt = await until(lambda: asyncio.sleep(0, next((p for p in s.recorder.prompts if p["kind"] == "gate_added"), None)))
    assert prompt["name"] == "Payment details page" and prompt["urlContains"] == "/build_record2.html"
    assert prompt["landmark"] == "id=pay-heading" and prompt["landmarkText"] == "Payment details"
    assert steps(s) == [("CLICK", ""), ("ASSERT_PAGE", "Payment details page")]              # added without asking
    with s.doc.lock:
        assert [f["name"] for f in read_fingerprints(s.doc.editor)] == ["Payment details page"]
    await s._page().fill("#card", "4111")                         # recording carries on after the check...
    await s._page().evaluate("document.getElementById('card').blur()")
    await quiet(s, 2)
    assert [m for m, _ in steps(s)] == ["CLICK", "ASSERT_PAGE", "SET"]
    blocks = [st["block"] for st in s._steps()]
    assert blocks[2:] == ["Payment details page", "Payment details page"] and blocks[1] != "Payment details page"   # ...on its own page
    await s.recorder.stop()
    s.run("to", row=s._steps()[-1]["row"])
    state = await settled(s)
    assert [st for _, st in results(state)] == ["PASSED"] * 4, [(r["name"], r["error"]) for r in state["replay"]["results"]]
    assert any(e["type"] == "page_gate" and e.get("passed") for e in state["log"])


async def test_an_automatic_page_check_can_be_removed_or_its_fingerprint_renamed_from_its_card(session):
    s = session
    await s.recorder.start(after=2)
    page = s._page()
    await page.click("#continue")
    await page.wait_for_url("**/build_record2.html")
    prompt = await until(lambda: asyncio.sleep(0, next((p for p in s.recorder.prompts if p["kind"] == "gate_added"), None)))
    await s.recorder.answer(prompt["id"], "regate", fields={"name": "Pay page"})
    assert steps(s) == [("CLICK", ""), ("ASSERT_PAGE", "Pay page")]
    with s.doc.lock:
        assert [f["name"] for f in read_fingerprints(s.doc.editor)] == ["Pay page"]
    await s._page().go_back()
    await s._page().wait_for_url("**/build_record.html")
    await s._page().click("#continue")
    await s._page().wait_for_url("**/build_record2.html")
    second = await until(lambda: asyncio.sleep(0, next((p for p in s.recorder.prompts if p["kind"] == "gate_added"), None)))
    assert second["exists"] and second["name"] == "Pay page"                                  # a page it knows: the same fingerprint
    count = len(s._steps())
    await s.recorder.answer(second["id"], "ungate")
    assert len(s._steps()) == count - 1 and steps(s)[-1] == ("CLICK", "")


async def test_the_calendars_clicks_become_one_pick_date_step_and_the_raw_clicks_can_come_back(site, tmp_path):
    s = await open_session(site, tmp_path, "widgets.html")
    try:
        page = s._page()
        await page.wait_for_selector("#promo", state="visible")
        await page.evaluate("document.getElementById('promo').remove()")
        await s.recorder.start(after=2)
        await page.click("#cal")
        await page.click("#next")
        await page.click("#next")
        await page.click("[data-date='2027-03-15']")
        await quiet(s, 1)
        assert steps(s) == [("PICK_DATE", "{DEPARTURE_DATE}")] and params(s)["DEPARTURE_DATE"] == [relative_date("15/03/2027") or "15/03/2027"]
        widget = next(p for p in s.recorder.prompts if p["kind"] == "widget")
        assert widget["text"].startswith("4 clicks became one step")
        await s.recorder.answer(widget["id"], "raw")
        assert [m for m, _ in steps(s)] == ["CLICK"] * 4 and step_at(s, 2)["locator"]["value"] == "cal"
        await s.recorder.stop()
        s.doc.undo()                                              # back to PICK_DATE: it replays (the engine opens the calendar itself)
        s.run("to", row=3)
        state = await settled(s)
        assert results(state) == [(1, "PASSED"), (2, "PASSED")] and await s._page().input_value("#cal") == "15/03/2027"
    finally:
        await s.close()


async def test_typing_then_a_suggestion_becomes_one_choose_suggestion_step(site, tmp_path):
    s = await open_session(site, tmp_path, "widgets.html")
    try:
        page = s._page()
        await page.wait_for_selector("#promo", state="visible")
        await page.evaluate("document.getElementById('promo').remove()")
        await s.recorder.start(after=2)
        await page.click("#city")
        await page.keyboard.type("Syd")
        await page.click("#city-list li:has-text('Sydney Airport')")
        await quiet(s, 1)
        await asyncio.sleep(0.3)
        assert steps(s) == [("CHOOSE_SUGGESTION", "{CITY_VALUE}")] and step_at(s, 2)["expected"] == "Sydney Airport"
        s.run("to", row=3)
        state = await settled(s)
        assert results(state) == [(1, "PASSED"), (2, "PASSED")], [(r["name"], r["error"], r["notes"]) for r in state["replay"]["results"]]
        assert await s._page().input_value("#city") == "Sydney Airport"
        widget = next(p for p in s.recorder.prompts if p["kind"] == "widget")
        await s.recorder.answer(widget["id"], "raw")
        assert [m for m, _ in steps(s)] == ["SET", "CLICK"]
    finally:
        await s.close()


async def pick_for(s: BuildSession, mode: str, locator) -> dict:
    s.pick = None
    await s.set_mode(mode)
    await locator.click()
    pick = await until(lambda: asyncio.sleep(0, s.pick))
    return pick


def kinds(pick: dict) -> dict[str, dict]:
    return {k["id"]: k for k in pick["card"]["form"]["kinds"]}


async def test_check_this_offers_every_check_prefilled_from_the_page_and_the_added_checks_pass(session):
    s = session
    page = s._page()
    total = kinds(await pick_for(s, "check", page.locator("#total")))
    assert total["text_is"]["expected"] == "$1,234.50" and total["gt"]["expected"] == "1234.5" and total["between"]["expected"] == "1234.5;1234.5"
    assert not total["ticked"]["enabled"] and not total["value"]["enabled"]            # control-state checks: not for plain text
    assert await page.locator("#paid").inner_text() == "not paid"                       # (the site never saw the pick)
    plan = kinds(await pick_for(s, "check", page.locator("#plan")))
    assert plan["selected"]["enabled"] and plan["selected"]["expected"] == "Basic" and plan["value"]["enabled"]
    offers = kinds(await pick_for(s, "check", page.locator("#offers")))
    assert offers["ticked"]["expected"] == "N" and offers["enabled"]["expected"] == "Y"
    ref = kinds(await pick_for(s, "check", page.locator("#ref")))
    assert ref["regex"]["expected"] == r"^REF\-\d+$"
    starts = kinds(await pick_for(s, "check", page.locator("#starts")))
    assert starts["date_format"]["expected"] == "dd/mm/yyyy"
    item = kinds(await pick_for(s, "check", page.locator("#items li").nth(1)))
    assert item["count"]["enabled"] and item["count"]["expected"] == "3"
    added = []
    for sel, kind in [("#total", "text_is"), ("#total", "text_contains"), ("#total", "gt"), ("#total", "between"), ("#ref", "regex"),
                      ("#starts", "date_format"), ("#plan", "selected"), ("#offers", "ticked"), ("#continue", "enabled"), ("#continue", "shown"),
                      ("#items li >> nth=1", "count")]:
        pick = await pick_for(s, "check", page.locator(sel))
        k = kinds(pick)[kind]
        expected = "1000" if kind == "gt" else "1234;1235" if kind == "between" else "1,234" if kind == "text_contains" else k["expected"]
        await s.recorder.add_check(kind, expected)
        added.append(kind)
    methods = [m for m, _ in steps(s)]
    assert methods == ["OUTPUT", "OUTPUT", "CHECK_COMPARE", "CHECK_COMPARE", "CHECK_REGEX", "CHECK_DATE_FORMAT", "CHECK_SELECTED", "CHECK_CHECKED",
                       "CHECK_ENABLED", "EXIST", "CHECK_COUNT"]
    s.run("to", row=s._steps()[-1]["row"])
    state = await settled(s)
    assert [st for _, st in results(state)] == ["PASSED"] * 12, state["replay"]


async def test_save_this_and_wait_until_become_steps_that_save_and_wait(session):
    s = session
    page = s._page()
    pick = await pick_for(s, "save", page.locator("#total"))
    assert pick["card"]["form"]["token"] == "PRICE" and pick["card"]["form"]["text"] == "$1,234.50"
    await s.recorder.add_check("save", token="TOTAL_SHOWN")
    pick = await pick_for(s, "wait", page.locator("#continue"))
    assert [k["id"] for k in pick["card"]["form"]["kinds"]] == ["wait_shown", "wait_gone", "wait_text"]
    await s.recorder.add_check("wait_text", "Continue")
    assert steps(s) == [("OUTPUT", ""), ("WAIT_UNTIL", "")] and step_at(s, 2)["saveAs"].upper() == "TOTAL_SHOWN"
    s.run("to", row=s._steps()[-1]["row"])
    state = await settled(s)
    assert [st for _, st in results(state)] == ["PASSED"] * 3
    assert s._runner.written.get("TOTAL_SHOWN") == "$1,234.50" or any(
        e["type"] == "variable_set" and e.get("name", "").upper() == "TOTAL_SHOWN" for e in state["log"])


async def test_a_sites_own_script_cannot_record_or_add_steps(session):
    s = session
    await s.recorder.start(after=2)
    page = s._page()
    await page.evaluate("document.querySelector('[data-testid=pay]').dispatchEvent(new MouseEvent('click', {bubbles: true}))")
    assert await page.locator("#paid").inner_text() == "paid 1"                            # the site saw its own click...
    await page.evaluate("window.__rrBuildCall({kind: 'rec', what: 'click', element: {tag: 'button', text: 'Pay now'}})")
    await page.evaluate("window.__rrBuildCall({kind: 'rec', what: 'click', key: 'guess', element: {tag: 'button', text: 'Pay now'}})")
    await page.evaluate("window.__rrBuildCall({kind: 'check-add', check: 'shown'})")
    await quiet(s)
    assert steps(s) == [] and s.recorder.count == 0                                          # ...and nothing was recorded


async def test_steps_a_replay_drives_are_not_recorded(session):
    s = session
    s.doc.apply([{"op": "insert_step", "test": "Rec", "step": {"method": "CLICK", "findBy": "BY_ID", "locator": "offers"}}])
    await s.recorder.start(after=3)
    s.run("next", count=1)
    await settled(s)
    await quiet(s)
    assert await s._page().is_checked("#offers") and steps(s) == [("CLICK", "")] and s.recorder.count == 0


async def pill_x(page) -> float:
    """Where the pill starts (the overlay's closed shadow root cannot be queried: find its host at the pill's height)."""
    return await page.evaluate("""() => { const host = document.querySelector('rr-build-overlay');
      for (let x = 0; x < innerWidth; x += 2) { if (document.elementFromPoint(x, 31) === host) return x; } return -1; }""")


async def test_the_pills_rec_button_turns_recording_on_and_off(session):
    s = session
    page = s._page()
    await s.broadcast()
    x = await pill_x(page)
    assert x > 0
    await page.mouse.click(x + 40, 31)                            # "Rec off" -> recording
    await until(lambda: asyncio.sleep(0, s.recorder.on))
    await page.click("#offers")
    await quiet(s, 1)
    assert steps(s) == [("TICK", "")]
    await page.mouse.click(await pill_x(page) + 40, 31)             # (the pill is centred: "Rec" is narrower than "Rec off")
    await until(lambda: asyncio.sleep(0, not s.recorder.on))


async def pill_right(page) -> float:
    """Where the pill ends (its last button is Done)."""
    return await page.evaluate("""() => { const host = document.querySelector('rr-build-overlay');
      for (let x = innerWidth - 1; x > 0; x -= 2) { if (document.elementFromPoint(x, 31) === host) return x; } return -1; }""")


async def test_the_pills_done_stops_recording_and_leaves_a_summary_of_what_was_recorded(session):
    s = session
    page = s._page()
    await s.recorder.start(after=2)
    await page.click("#firstName")
    await page.keyboard.type("Jane")
    await page.click("#offers")                                  # (leaving First name records it)
    await quiet(s, 2)
    await s.broadcast()
    right = await pill_right(page)
    assert right > 0
    await page.mouse.click(right - 22, 31)                    # Done
    await until(lambda: asyncio.sleep(0, not s.recorder.on))
    summary = s.state()["record"]["summary"]
    assert summary["count"] == 2 and summary["test"] == "Rec"
    assert [st["n"] for st in s._steps() if st["row"] in summary["rows"]] == [summary["first"], summary["last"]] == [2, 3]
    assert s.overlay_state()["label"] == "✓ Recorded 2 steps (steps 2-3)" and s.mode == "browse"


async def test_done_while_picking_just_goes_back_to_browsing(session):
    s = session
    page = s._page()
    await s.set_mode("pick", None)
    await page.mouse.click(await pill_right(page) - 22, 31)
    await until(lambda: asyncio.sleep(0, s.mode == "browse"))
    assert s.recorder.on is False and s.state()["record"]["summary"] is None


async def test_recording_an_empty_test_starts_with_an_open_step_on_the_domain(site, tmp_path):
    envs = [["Variable", "Required", "Secret", "UAT", "PROD"], ["DOMAIN", "Y", "", site.rstrip("/") + "/build_record.html", ""]]
    cfg = Config(base_dir=tmp_path)
    cfg.timeouts.element_s = 3
    cfg.build.headless = True
    cfg.build.idle_close_s = 0
    doc = BuildDocument(book(tmp_path / "new.xlsx", {"Rec": []}, params={"Rec": [{"NOTE": ""}]}, environments=envs), tmp_path / "runs")
    s = BuildSession(doc, cfg, tmp_path / "runs" / ".build" / "new", environment="UAT", headless=True)
    await s.start("Rec", None)
    await settled(s)
    try:
        page = s._page()
        assert page.url.endswith("/build_record.html")        # the window opened on the Domain
        await s.recorder.start()
        await page.click("#offers")
        await quiet(s, 2)
        assert [(st["method"], st["value"]) for st in s._steps()] == [("OPEN", "{DOMAIN}"), ("TICK", "")]
        await s.recorder.stop()
        assert s.state()["record"]["summary"]["count"] == 2
        s.run("to", row=s._steps()[-1]["row"])                # what was recorded replays on its own
        state = await settled(s)
        assert results(state) == [(1, "PASSED"), (2, "PASSED")]
    finally:
        await s.close()


async def test_check_and_pick_work_while_recording_and_recording_carries_on_after_them(session):
    s = session
    page = s._page()
    await s.recorder.start(after=2)
    await page.click("#offers")                                   # a recorded click...
    await quiet(s, 1)
    await s.set_mode("check", None)                                 # ...then the pill's Check, then a click on the page (the pick, never recorded)
    await s.broadcast()
    await page.click("#total")
    await until(lambda: asyncio.sleep(0, s.pick is not None and s.pick.get("purpose") == "check"))
    assert s.mode == "browse" and s.recorder.on and s.recorder.count == 1
    await s.recorder.add_check("shown")
    assert [m for m, _ in steps(s)] == ["TICK", "EXIST"]           # the check went in after the recorder's cursor
    await page.click("#offers")                                   # ...and recording carries on after the check
    await quiet(s, 3)
    assert [m for m, _ in steps(s)] == ["TICK", "EXIST", "UNTICK"]


async def test_a_plain_pick_while_recording_offers_the_checks_instead_of_doing_nothing(session):
    s = session
    await s.recorder.start(after=2)
    await s.set_mode("pick", None)
    assert s.mode == "check"


async def test_a_calendar_opened_from_a_box_that_is_not_a_field_still_becomes_one_pick_date_step(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_datebox.html")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click("#depart-box")
        await quiet(s, 1)
        assert steps(s) == [("CLICK", "")]
        await page.click("#nx")
        await page.click("#nx")
        await page.click("#days td:nth-of-type(1) a >> text=15")
        await quiet(s, 1)
        assert len(steps(s)) == 1 and steps(s)[0][0] == "PICK_DATE"          # the opener's CLICK is gone: PICK_DATE opens the calendar itself
        assert "depart-box" in step_at(s, 2)["locator"]["value"]
        value = list(params(s).values())[-1][0]
        assert value in (relative_date("15/03/2027"), "15/03/2027")
        widget = next(p for p in s.recorder.prompts if p["kind"] == "widget")
        assert widget["text"].startswith("4 clicks became one step")
        s.run("to", row=3)
        state = await settled(s)
        assert results(state) == [(1, "PASSED"), (2, "PASSED")], {k: v for k, v in state["replay"]["results"][-1].items() if k in ("error", "detail", "notes", "diagnosis")}
        assert (await s._page().inner_text("#depart-box")) == "15/03/2027"
    finally:
        await s.close()


async def test_a_calendar_whose_cells_do_not_say_their_month_is_read_from_its_heading(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_datebox.html?plain=1")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click("#depart-box")
        await page.click("#nx")
        await page.wait_for_timeout(200)
        await page.click("#days td:nth-of-type(1) a >> text=15")
        await quiet(s, 1)
        assert [m for m, _ in steps(s)] == ["PICK_DATE"]
        value = list(params(s).values())[-1][0]
        assert value in (relative_date("15/02/2027"), "15/02/2027")
        assert "March 2025" not in value and "2025" not in value
        name = step_at(s, 2)["name"]
        assert ("today +" in name) == value.startswith("=TEXT(TODAY()") and name.startswith("Pick date ")
        assert not [p for p in s.state()["record"]["prompts"] if p.get("widget") == "date"]      # nobody is asked about the calendar's clicks
    finally:
        await s.close()


async def test_calendar_clicks_that_never_named_a_day_are_written_as_clicks_not_dropped(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_datebox.html")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click("#depart-box")
        await page.click("#nx")
        await page.click("#ttl")                                # (not a day: nothing names a date)
        await s.recorder.stop()
        assert [m for m, _ in steps(s)] == ["CLICK", "CLICK", "CLICK"]
    finally:
        await s.close()


async def test_pressing_the_pill_does_not_close_a_list_that_closes_when_its_field_loses_focus(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_blur.html")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click("#q")
        await page.keyboard.type("a")
        await s.broadcast()
        await page.mouse.click(812, 34)                             # the pill's Check
        await until(lambda: asyncio.sleep(0, s.mode == "check"))
        assert await page.is_visible("#list") and await page.evaluate("document.activeElement.id") == "q"
        await page.click("#list li:nth-child(1)")                   # the list is still there to be picked
        await until(lambda: asyncio.sleep(0, s.pick is not None and s.pick.get("purpose") == "check"))
        assert "Albania" in s.pick["text"]
    finally:
        await s.close()


@pytest.mark.parametrize("query", ["plain=1&aria=1&noheading=1", "plain=1&noheading=1"])
async def test_a_calendar_day_is_read_from_its_label_or_failing_that_from_what_the_box_shows(site, tmp_path, query):
    s = await open_session(site, tmp_path, "build_record_datebox.html?" + query)
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click("#depart-box")
        await page.click("#nx")
        await page.wait_for_timeout(200)
        await page.click("#days td:nth-of-type(1) a >> text=15")
        await quiet(s, 1)
        assert [m for m, _ in steps(s)] == ["PICK_DATE"]
        value = list(params(s).values())[-1][0]
        assert value in (relative_date("15/02/2027"), "15/02/2027")
    finally:
        await s.close()


async def test_a_jquery_ui_calendar_with_month_and_year_lists_records_and_replays_as_one_pick_date_step(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_datebox.html?real=1")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click("#depart-box")
        await page.click("#nx")
        await page.wait_for_timeout(200)
        await page.click("#days td:nth-of-type(1) a >> text=15")
        await quiet(s, 1)
        assert [m for m, _ in steps(s)] == ["PICK_DATE"]
        value = list(params(s).values())[-1][0]
        assert value in (relative_date("15/02/2027"), "15/02/2027")
        s.run("to", row=3)
        state = await settled(s)
        assert results(state) == [(1, "PASSED"), (2, "PASSED")], {k: v for k, v in state["replay"]["results"][-1].items() if k in ("error", "notes")}
        assert (await s._page().inner_text("#depart-box")) == "15/02/2027"
    finally:
        await s.close()


async def test_a_link_the_page_shows_in_capitals_through_css_is_found_by_its_text_not_by_its_position(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_caps.html")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click("li:nth-child(2) a")
        await quiet(s, 1)
        loc = step_at(s, 2)["locator"]
        assert "translate(" in loc["value"] and "algeria" in loc["value"] and not loc["index"]
        await s.recorder.stop()
    finally:
        await s.close()


async def test_parts_of_a_custom_multi_select_are_found_and_named_through_the_select_underneath(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_multiselect.html")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click(".multiSelectDropdown .inputField")
        await page.keyboard.type("alb")
        await page.click("#opts li:nth-child(1) a")                 # (the list closes as it is clicked)
        await quiet(s, 2)
        typed, chosen = step_at(s, 2), step_at(s, 3)
        for step in (typed, chosen):
            assert "myMulti" in step["locator"]["value"] and not step["locator"]["index"], step["locator"]
            assert "my multi" in step["name"]
        await s.recorder.stop()
    finally:
        await s.close()


async def test_the_second_input_of_a_repeatable_set_is_recorded_with_its_own_duplication_id(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_repeat.html")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click(".traveller:nth-child(2) input")
        await page.keyboard.type("41")
        await page.keyboard.press("Tab")
        await quiet(s, 1)
        loc = step_at(s, 2)["locator"]
        assert loc["value"] == 'input[name="insuredAge"][data-cmp-duplication-input-id="t2"]' and not loc["index"]
        await s.recorder.stop()
    finally:
        await s.close()


async def test_a_list_check_on_an_item_checks_the_list_is_showing_and_reads_the_item_at_its_place(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_multiselect.html")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click(".multiSelectDropdown .inputField")
        await page.keyboard.type("alb")
        await page.keyboard.press("Tab")                         # (leaving the field records the typing)
        await quiet(s, 1)
        pick = await pick_for(s, "check", page.locator("#opts li:nth-child(2) a"))
        assert kinds(pick)["list_item"]["enabled"]
        await s.recorder.add_check("list_item")
        step = step_at(s, 3)
        assert step["method"] == "CHECK_LIST_ITEM" and step["outputProperty"] == "2" and step["expected"].lower() == "algeria"
        assert "opts" in step["locator"]["value"] and "data-" not in step["locator"]["value"]          # the LIST, not the item
        await s.recorder.stop()
        s.run("to", row=4)
        state = await settled(s)
        assert results(state)[-1] == (3, "PASSED"), state["replay"]["results"][-1]
        await s._page().reload()                                 # the list is not showing any more: the same step must fail
        s.run("step", row=4)
        state = await settled(s)
        assert results(state)[-1] == (3, "FAILED")
    finally:
        await s.close()


async def test_a_page_shaped_like_the_real_quote_page_records_specific_locators_for_what_a_person_can_use(site, tmp_path):
    s = await open_session(site, tmp_path, "build_record_quote.html")
    try:
        page = s._page()
        await s.recorder.start(after=2)
        await page.click("#singleTripKeepHTML #cmp-Input")
        await page.keyboard.type("alb")
        await page.click("#drop1 a:nth-child(1)")                     # (the copy in the other tab is hidden and has the same ids)
        await page.click("#drop1 .drop-screen")                       # the click-catcher laid over the page
        s.recorder.prompts.clear()                                    # (the prompt cards drawn beside a field would cover the next one)
        await s.broadcast()
        await page.click("input[name=tripDepartureDate]")
        await page.click("#nx")
        await page.wait_for_timeout(200)
        await page.click("#days a >> text=/^8$/")
        s.recorder.prompts.clear()
        await s.broadcast()
        await page.click("input[name=tripReturnDate]")
        await page.click("#nx")
        await page.wait_for_timeout(200)
        await page.click("#days a >> text=/^20$/")
        s.recorder.prompts.clear()
        await s.broadcast()
        await page.click("input[name=insuredAge] >> nth=1")
        await page.keyboard.type("41")
        await page.keyboard.press("Tab")
        await quiet(s, 6)
        by_method = [(st["method"], st["name"], st["locator"]["findBy"], st["locator"]["value"], st["locator"]["index"]) for st in s._steps()[1:]]
        methods = [m for m, *_ in by_method]
        assert methods == ["SET", "CLICK", "CLICK", "PICK_DATE", "PICK_DATE", "SET"], by_method
        typed, item, overlay, depart, ret, age = by_method
        assert "myMulti" in typed[3] and typed[3].endswith(">> visible=true") and typed[4] == 0 and "my multi" in typed[1]
        assert "myMulti" in item[3] and item[3].endswith(">> visible=true") and "my multi" in item[1]
        assert "drop-screen" in overlay[3] and "overlay" in overlay[1]
        assert depart[3].startswith('input[name="tripDepartureDate"]') and "departure date" in depart[1].lower()
        assert ret[3].startswith('input[name="tripReturnDate"]') and "return date" in ret[1].lower()
        assert 'data-cmp-duplication-input-id="multiTravellerLoop-replication-index-iteration_2_input_insuredAge"' in age[3] and not age[4]
        await s.recorder.stop()
        s.run("to", row=8)                                           # the whole recording replays: visible copies only, the overlay click included
        state = await settled(s)
        assert [st for _, st in results(state)] == ["PASSED"] * 7, [(r["n"], r["status"], r.get("error")) for r in state["replay"]["results"]]
    finally:
        await s.close()
