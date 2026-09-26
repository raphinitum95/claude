"""The New run screen with several workbooks: tick more than one, each with its own tests and run order, one command, one run each on shared workers."""
from __future__ import annotations

import json
import re

import pytest
from playwright.async_api import expect

from tests.test_web_api import zip_bytes
from tests.test_web_ui import command_is, js_until, open_ui, pick_only, until, wait_ready
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser
CHECKED = "Array.from(document.querySelectorAll('input[name=workbook]:checked')).map(e => e.value).sort().join(',')"


async def tick_both(page):
    await pick_only(page, "mock.xlsx")
    await page.locator('input[name=workbook][value="bad.xlsx"]').check(force=True)
    await js_until(page, f"{CHECKED} === 'bad.xlsx,mock.xlsx'")
    await expect(page.locator('section[data-key="tests-bad.xlsx"] input.cb').first).to_be_visible()
    await js_until(page, "document.querySelectorAll('section[data-key^=tests-] input.cb:checked').length === 4")      # both workbooks have been read


async def test_each_ticked_workbook_gets_its_own_tests_and_the_command_and_button_cover_all_of_them(web):
    async with open_ui(web) as page:
        await wait_ready(page)
        await tick_both(page)
        assert await page.locator("h2", has_text="Tests").count() == 2                                       # a Tests card per workbook
        await command_is(page, "regrunner run mock.xlsx --all bad.xlsx --all")
        await expect(page.get_by_role("button", name="Run 4 tests in 2 workbooks")).to_be_enabled()
        assert "one per workbook, on 2 shared workers" in await page.locator("#launch-books").inner_text()
        assert "2 workbooks read" in await page.locator("#preflight").inner_text()

        bad_tests = page.locator('section[data-key="tests-bad.xlsx"]')
        await bad_tests.locator('label[data-key="FlowY"] input').uncheck()                                   # what runs is decided per workbook
        await command_is(page, "regrunner run mock.xlsx --all bad.xlsx --tests FlowX")
        await expect(page.get_by_role("button", name="Run 3 tests in 2 workbooks")).to_be_enabled()
        await expect(page.locator('section[data-key="tests-mock.xlsx"] input.cb:checked')).to_have_count(2)
        await bad_tests.get_by_role("button", name="None").click()
        await expect(page.get_by_role("button", name="Select tests to run")).to_be_disabled()               # a ticked workbook with nothing ticked in it blocks the run...
        assert "No tests selected · bad.xlsx" in await page.locator("#preflight").inner_text()
        await bad_tests.get_by_role("button", name="Workbook defaults").click()
        await expect(page.get_by_role("button", name="Run 4 tests in 2 workbooks")).to_be_enabled()

        await page.locator('input[name=workbook][value="bad.xlsx"]').uncheck(force=True)                     # ...and unticking the workbook takes it out
        await command_is(page, "regrunner run mock.xlsx --all")
        await expect(page.get_by_role("button", name="Run 2 tests", exact=True)).to_be_enabled()
        assert await page.locator('section[data-key="tests-bad.xlsx"]').count() == 0
        assert not page.errors, page.errors


async def test_the_request_carries_one_entry_per_workbook_and_the_settings_once(web):
    async with open_ui(web) as page:
        await wait_ready(page)
        await tick_both(page)
        await page.locator('section[data-key="tests-bad.xlsx"] label[data-key="FlowY"] input').uncheck()
        await page.get_by_role("button", name="QA", exact=True).click()
        await page.get_by_role("button", name="More workers").click()
        await command_is(page, "regrunner run mock.xlsx --all bad.xlsx --tests FlowX --env QA --workers 3")
        sent: dict = {}

        async def capture(route):
            if route.request.method != "POST":
                return await route.continue_()
            sent.update(json.loads(route.request.post_data))
            await route.fulfill(status=200, content_type="application/json", body='{"run_id": "20990101-000000-QA", "run_ids": ["20990101-000000-QA"], "command": "x"}')
        await page.route(re.compile(r".*/api/runs$"), capture)
        await page.get_by_role("button", name="Run 3 tests in 2 workbooks").click()
        await until(lambda: bool(sent))
        assert sent["workbooks"] == [{"workbook": "mock.xlsx", "all": True, "tests": [], "chains": None},
                                     {"workbook": "bad.xlsx", "all": False, "tests": ["FlowX"], "chains": None}]
        assert sent["env"] == "QA" and sent["workers"] == 3 and "workbook" not in sent and "tests" not in sent      # the settings are shared: said once


async def test_a_workbook_that_cannot_be_read_can_be_removed_and_the_others_carry_on(web):
    (web.root / "workbooks" / "junk-multi.xlsx").write_bytes(zip_bytes({"xl/workbook.xml": "<not really a workbook>"}))
    try:
        async with open_ui(web) as page:                                                                     # (the newest workbook, this one, is ticked when the page opens)
            await expect(page.get_by_text("Could not read junk-multi.xlsx.")).to_be_visible(timeout=20_000)
            await page.locator('input[name=workbook][value="mock.xlsx"]').check(force=True)
            await expect(page.locator('section[data-key="tests-mock.xlsx"] input.cb:checked')).to_have_count(2)
            await expect(page.get_by_text("Could not read junk-multi.xlsx.")).to_be_visible()
            await expect(page.locator(".btn-lg")).to_be_disabled()
            assert "junk-multi.xlsx could not be read" in await page.locator("#preflight").inner_text()
            await page.get_by_role("button", name="Remove it").click()
            await expect(page.get_by_text("Could not read junk-multi.xlsx.")).to_have_count(0)
            await command_is(page, "regrunner run mock.xlsx --all")
            await expect(page.locator(".btn-lg")).to_be_enabled()
    finally:
        (web.root / "workbooks" / "junk-multi.xlsx").unlink(missing_ok=True)


async def test_several_workbooks_run_from_the_screen_and_each_run_says_who_it_shares_the_workers_with(web):
    async with open_ui(web) as page:
        await wait_ready(page)
        await tick_both(page)
        await page.locator('section[data-key="tests-mock.xlsx"] label[data-key="FlowB"] input').uncheck()
        await page.locator('section[data-key="tests-bad.xlsx"] label[data-key="FlowY"] input').uncheck()
        await page.get_by_role("button", name="Run 2 tests in 2 workbooks").click()
        await page.wait_for_selector("text=Now running", timeout=30_000)
        first = re.search(r"/run/([\w.-]+)", page.url).group(1)
        strip = page.locator("#shares")
        await expect(strip).to_contain_text("Sharing workers with")
        await expect(strip.locator("button")).to_have_count(1)
        await expect(page.locator("aside .side-run")).to_have_count(2)                                        # both runs are in the sidebar
        await js_until(page, "document.querySelectorAll('aside .bar').length === 2")                        # ...and both are going
        await expect(page.get_by_text("Started 2 runs on shared workers")).to_be_visible()
        other = await strip.locator("button").get_attribute("data-id")
        assert other and other != first
        title_first = await page.locator("h1").inner_text()
        await strip.locator("button").click()                                                              # the chip opens the other run
        await js_until(page, f"location.hash === '#/run/{other}'")
        await expect(page.locator("h1")).not_to_have_text(title_first)
        await expect(page.locator("#shares")).to_contain_text(title_first.replace(".xlsx", "") + ".xlsx")
        done = {rid: web.wait_finished(rid, 240) for rid in (first, other)}
        assert {d["meta"]["status"] for d in done.values()} == {"PASSED", "FAILED"}                          # mock passes, bad fails: each run has its own verdict
        assert not page.errors, page.errors


async def test_a_run_in_progress_is_joined_and_a_different_browser_mode_is_explained(web):
    with web.client() as c:
        started = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA"]}).json()["run_id"]
    try:
        async with open_ui(web) as page:
            await page.wait_for_selector("text=1 run in progress.")
            await pick_only(page, "bad.xlsx")
            await expect(page.get_by_role("status").filter(has_text="1 run in progress.")).to_contain_text("joins it and shares the workers")
            await expect(page.locator(".btn-lg")).to_be_enabled()
            await page.get_by_label("Show browsers").click(force=True)                                       # windows shown: the run going is headless
            warn = page.get_by_role("status").filter(has_text="Runs share one set of workers")
            await expect(warn).to_be_visible()
            await expect(page.locator(".btn-lg")).to_be_disabled()
            await warn.get_by_role("button", name="Use their settings").click()
            await expect(warn).to_have_count(0)
            await expect(page.locator(".btn-lg")).to_be_enabled()
            assert "Shared with the run in progress" in await page.locator("main").inner_text()

            await pick_only(page, "mock.xlsx")                                                               # the workbook that is being run right now
            await expect(page.locator("#preflight")).to_contain_text("Already running · mock.xlsx")
            await expect(page.locator(".btn-lg")).to_be_disabled()
            await pick_only(page, "bad.xlsx")
            await page.get_by_role("button", name=re.compile(r"^Run 2 tests$")).click()                     # joins: the run screen opens for the new run
            await expect(page.get_by_text("Joined the workers of the run in progress.")).to_be_visible(timeout=60_000)
            await page.wait_for_selector("text=Now running", timeout=60_000)
            joined = re.search(r"/run/([\w.-]+)", page.url).group(1)
            assert joined != started
            await expect(page.locator("#shares")).to_contain_text("mock.xlsx")
            web.wait_finished(joined, 240)
            assert not page.errors, page.errors
    finally:
        web.wait_finished(started, 240)
