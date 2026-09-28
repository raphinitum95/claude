"""Concurrency scenarios in the web UI: the Build tab's scenario board (lanes, sync lines, order markers, edits through /edit), a scenario
run started through /api/runs, the Run tab's test list, the finished run's per-lane view and the live view's reducer + lanes."""
from __future__ import annotations

import re

import pytest

from regrunner.workbook.scenarios import HEADERS
from tests.flow_books import at, book
from tests.site import server as mock_server
from tests.test_web_build import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser
SC = "Two agents"

STEPS = [
    ("Open", "Open the policy", {"Value": "DT_URL", "BLOCK": "Open policy"}),
    ("Output", "Version 1 is open", {**at("//span[@id='version']"), "Output_Property": "innertext", "Expected_Value": "1", "Exact_Match": "Y",
                                     "BLOCK": "Open policy"}),
    ("Click", "Save changes", {**at("//button[@id='save']"), "BLOCK": "Save"}),
    ("Output", "What the site said", {**at("//p[@id='msg']"), "Output_Property": "innertext", "Expected_Value": "DT_EXPECT", "Exact_Match": "Y",
                                      "BLOCK": "Check"}),
]


def table() -> list[list]:
    row = lambda item, name="", lane="", test="", data=None, block="", then="", then_block="": [SC, item, name or None, lane or None, test or None, data,
                                                                                             block or None, then or None, then_block or None, None, None, None]
    return [list(HEADERS), [SC, "scenario", None, None, None, None, None, None, None, None, "Y", "two users, one policy"],
            row("lane", "Ana", "A", "Edit", 2), row("lane", "Ben", "B", "Edit", 3),
            row("sync", "Sync 1", "A", block="Open policy"), row("sync", "Sync 1", "B", block="Open policy"),
            row("order", "A saves first", "A", block="Save", then="B", then_block="Save")]


@pytest.fixture(scope="module")
def scenario_book(web):
    """``scen.xlsx`` in the UI's workbooks folder: one test, two agents, one scenario."""
    params = [{"DT_URL": f"{web.site}scenario_policy.html?agent={who}", "DT_EXPECT": expect}
              for who, expect in (("Ana", "Saved"), ("Ben", "Changed by another user"))]
    book(web.root / "workbooks" / "scen.xlsx", {"Edit": STEPS}, params={"Edit": params}, sheets={"_rr_scenarios": table()})
    return "scen.xlsx"


@pytest.fixture
async def board_copy(web, scenario_book, request):
    name = f"scen_{request.node.name}"[:60]
    async with web.aclient() as c:
        r = await c.post("/api/build/workbooks", json={"name": name, "from": scenario_book})
        assert r.status_code == 201, r.text
        return r.json()["name"]


async def scenarios_of(web, name) -> list[dict]:
    async with web.aclient() as c:
        return (await c.get(f"/api/build/workbooks/{name}/scenarios")).json()["scenarios"]


async def test_the_board_shows_the_lanes_and_sync_line_and_edits_go_through_the_draft(web, board_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{board_copy}/scenario/{SC}")
    try:
        await js_until(page, "document.querySelectorAll('.sc-head').length === 2")
        heads = await page.locator(".sc-head").all_inner_texts()
        assert heads[0].startswith("A") and "Edit" in heads[0] and "Ana" in heads[0] and "Ben" in heads[1]
        assert (await page.locator('[data-act="sc-select"][data-kind="sync"]').inner_text()).strip() == "Sync 1"
        assert await page.locator("text=then B").count() == 1 and await page.locator("text=after A").count() == 1      # the order marker's two ends
        await page.get_by_role("button", name=re.compile("^Lane$")).click()
        await js_until(page, "document.querySelectorAll('.sc-head').length === 3")
        assert [l["key"] for l in (await scenarios_of(web, board_copy))[0]["lanes"]] == ["A", "B", "C"]
        await page.locator('[data-act="sc-select"][data-kind="sync"]').click()
        await page.locator('select[data-change="sc-sync-point"][data-lane="B"]').select_option("-")
        await js_until(page, "document.body.innerText.includes('a sync line needs at least two lanes')")
        sync = (await scenarios_of(web, board_copy))[0]["syncs"][0]
        assert [p["lane"] for p in sync["points"]] == ["A"]
        await page.locator('[data-act="build-undo"]').click()                     # one edit = one undo step, like every other edit
        await js_until(page, "!document.body.innerText.includes('a sync line needs at least two lanes')")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_the_map_lists_scenarios_and_new_scenario_opens_a_board_with_two_lanes(web, board_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{board_copy}")
    try:
        await js_until(page, "!!document.querySelector('[data-key=\"scc-Two agents\"]')")
        assert "2 lanes · 1 sync line · 1 order marker" in await page.locator('[data-key="scc-Two agents"]').inner_text()
        page.once("dialog", lambda d: d.accept("Night shift"))
        await page.locator('main [data-act="sc-new"]').click()
        await js_until(page, "location.hash.endsWith('/scenario/Night%20shift')")
        await js_until(page, "document.querySelectorAll('.sc-head').length === 2")          # the test with two data rows, once per row
        lanes = next(s for s in await scenarios_of(web, board_copy) if s["name"] == "Night shift")["lanes"]
        assert [(l["test"], l["dataRow"]) for l in lanes] == [("Edit", 2), ("Edit", 3)]
        assert await page.locator('.b-rail [data-key="sr-Night shift"]').count() == 1
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_a_scenario_run_reports_each_lane_on_the_run_screens(web, scenario_book):
    mock_server.SHARED_POLICY.update(version=1, log=[])
    async with web.aclient() as c:
        listed = (await c.get(f"/api/workbooks/{scenario_book}/tests")).json()["tests"]
        entry = next(t for t in listed if t["id"] == SC)
        assert entry["kind"] == "scenario" and entry["runnable"] and [l["id"] for l in entry["lanes"]] == [f"{SC} · A", f"{SC} · B"]
        res = await c.post("/api/runs", json={"workbook": scenario_book, "tests": [SC]})
        assert res.status_code == 200, res.text
        run_id = res.json()["run_id"]
    detail = web.wait_finished(run_id)
    assert {t["id"]: t["status"] for t in detail["results"]["tests"]} == {f"{SC} · A": "PASSED", f"{SC} · B": "PASSED"}, detail["results"]["tests"]
    async with web.aclient() as c:
        runs = (await c.get(f"/api/build/workbooks/{scenario_book}/scenarios/{SC}/runs")).json()["runs"]
    assert runs[0]["runId"] == run_id and [l["key"] for l in runs[0]["lanes"]] == ["A", "B"] and runs[0]["lanes"][1]["syncs"]

    pw, browser, page = await open_ui(web, f"/#/run/{run_id}")
    try:
        await js_until(page, "!!document.querySelector('[data-key=\"scenario-Two agents\"]')")
        text = await page.locator('[data-key="scenario-Two agents"]').inner_text()
        assert "Sync 1 · all arrived" in text and "A saves first" in text and "Ana" in text and "Ben" in text
        # the live view, part way through: replay the run's events up to the first lane waiting at Sync 1 (or released there)
        live = await page.evaluate("""async (id) => {
            const { newRun, apply } = await import('/static/js/runstate.js');
            const { scenarioLive } = await import('/static/js/views/scenario_lanes.js');
            const events = (await (await fetch(`/api/runs/${id}/events`)).json()).events;
            const run = newRun(id);
            for (const e of events) { apply(run, e); if (e.type === 'scenario_sync' && e.sync === 'Sync 1') break; }
            const lanes = run.order.map((t) => run.tests[t]);
            return { markup: scenarioLive(run).map(String).join(''), lanes: lanes.map((t) => t.lane && t.lane.key), syncs: run.scenarios.map((s) => s.name),
                     events: lanes.reduce((n, t) => n + t.syncs.length, 0) };
        }""", run_id)
        assert live["lanes"] == ["A", "B"] and live["syncs"] == [SC] and live["events"] == 1
        assert "Scenario · live" in live["markup"] and "Sync 1" in live["markup"] and 'data-key="lane-Two agents · A"' in live["markup"]
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()
