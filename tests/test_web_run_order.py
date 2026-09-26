"""The web UI: what waits for what, chains built with the arrows, remembered per workbook, and sent with the run."""
from __future__ import annotations

import concurrent.futures

import openpyxl
import pytest
from playwright.async_api import async_playwright

from regrunner.engine.order import chains_file
from tests.test_run_order import ALL, build
from regrunner.workbook import Workbook
from tests.test_web_ui import js_until, open_ui, pick_only
from tests.web_fixtures import web  # noqa: F401  (fixture)


def test_the_order_endpoint_says_what_waits_and_chains_are_remembered_beside_the_workbook(web):
    build(web.root / "workbooks" / "order-api.xlsx", web.site)
    with web.client() as c:
        first = c.post("/api/workbooks/order-api.xlsx/order", json={"tests": ALL, "chains": None}).json()
        assert first["deps"]["View#1"] == ["Buy#1"] and first["source"] == "none"
        assert [s["tests"] for s in first["streams"]][0] == ["Buy#1", "Cancel#1", "View#1"]
        assert c.get("/api/workbooks/order-api.xlsx/tests").json()["chains"] == []

        chains = [["Buy#1", "View#1", "Cancel#1"], ["junk"], "not a list"]
        assert c.put("/api/workbooks/order-api.xlsx/chains", json={"chains": chains}).json() == {"chains": [["Buy#1", "View#1", "Cancel#1"]]}
        assert chains_file(web.root / "workbooks" / "order-api.xlsx").is_file()
        info = c.get("/api/workbooks/order-api.xlsx/tests").json()
        assert info["chains"] == [["Buy#1", "View#1", "Cancel#1"]] and info["chains_source"] == "saved"
        second = c.post("/api/workbooks/order-api.xlsx/order", json={"tests": ALL, "chains": None}).json()       # null = the saved ones
        assert [s["tests"] for s in second["streams"]][0] == ["Buy#1", "View#1", "Cancel#1"] and second["source"] == "saved"
        edited = c.post("/api/workbooks/order-api.xlsx/order", json={"tests": ALL, "chains": []}).json()          # [] = none, whatever is saved
        assert edited["chains"] == [] and edited["source"] == "edited"

        cmd = c.post("/api/runs/command", json={"workbook": "order-api.xlsx", "tests": ["Buy#1", "View#1"], "chains": [["Buy#1", "View#1"]]}).json()["text"]
        assert "--chain Buy#1,View#1" in cmd
        assert "--no-chains" in c.post("/api/runs/command", json={"workbook": "order-api.xlsx", "chains": []}).json()["text"]
        assert "--chain" not in c.post("/api/runs/command", json={"workbook": "order-api.xlsx"}).json()["text"]

        c.put("/api/workbooks/order-api.xlsx/chains", json={"chains": []})
        assert not chains_file(web.root / "workbooks" / "order-api.xlsx").exists()


def test_deleting_a_workbook_takes_its_chains_with_it(web):
    path = web.root / "workbooks" / "order-del.xlsx"
    build(path, web.site)
    with web.client() as c:
        c.put("/api/workbooks/order-del.xlsx/chains", json={"chains": [["Buy#1", "View#1"]]})
        assert chains_file(path).is_file()
        assert c.delete("/api/workbooks/order-del.xlsx").status_code == 200
    assert not chains_file(path).exists()


@pytest.mark.browser
async def test_the_run_order_card_shows_the_streams_and_the_arrows_build_a_chain(web):
    build(web.root / "workbooks" / "order-ui.xlsx", web.site)
    async with open_ui(web) as page:
        await pick_only(page, "order-ui.xlsx")
        await js_until(page, "document.body.innerText.includes('Run order')")
        card = page.locator("#run-order")
        text = await card.inner_text()
        assert "2 streams" in text and "DT_Policy_Out" in text and "waits for Buy#1" in text and "starts first" in text
        assert "Cancel#1 and View#1 run at the same time" in text                            # the hint that a chain may be needed

        await card.locator('[aria-label="Run earlier: View#1"]').click()                     # View before Cancel
        await js_until(page, "document.body.innerText.includes('not saved') && !document.body.innerText.includes('Cancel#1 and View#1 run at the same time')")
        rows = await card.locator('[data-key="stream-0"] b.mono').all_inner_texts()
        assert rows == ["Buy#1", "View#1", "Cancel#1"]                                       # now one waits for the other, so no hint
        await js_until(page, "document.body.innerText.includes('--chain Buy#1,View#1,Cancel#1')")     # the command shows it, so it can be repeated

        await card.locator('[data-act="order-save"]').click()
        await js_until(page, "document.body.innerText.includes('saved for this workbook')")
        assert chains_file(web.root / "workbooks" / "order-ui.xlsx").is_file()
        assert page.errors == []

    async with open_ui(web) as page:                                                            # a fresh page: the order is still there
        await pick_only(page, "order-ui.xlsx")
        await js_until(page, "document.body.innerText.includes('saved for this workbook')")
        assert await page.locator("#run-order").locator('[data-key="stream-0"] b.mono').all_inner_texts() == ["Buy#1", "View#1", "Cancel#1"]
        await page.locator("#run-order").locator('[data-act="order-reset"]').click()
        await js_until(page, "!document.body.innerText.includes('--chain')")
        assert page.errors == []
    chains_file(web.root / "workbooks" / "order-ui.xlsx").unlink(missing_ok=True)


@pytest.mark.browser
async def test_the_run_plan_has_an_order_view_and_a_timeline_view(web):
    build(web.root / "workbooks" / "order-timeline.xlsx", web.site)
    async with open_ui(web) as page:
        await pick_only(page, "order-timeline.xlsx")
        await js_until(page, "!!document.getElementById('run-order')")
        order_btn = page.locator('[data-act="plan-view"][data-val="order"]')
        timeline_btn = page.locator('[data-act="plan-view"][data-val="timeline"]')
        assert "on" in (await order_btn.get_attribute("class") or "").split()

        await timeline_btn.click()
        await js_until(page, "!document.getElementById('run-order')")
        assert "on" in (await timeline_btn.get_attribute("class") or "").split()
        await js_until(page, "document.querySelectorAll('[data-key^=tl-]').length > 0")            # one lane per worker
        assert "worker 1" in await page.locator("main").inner_text()
        assert "No run history yet" in await page.locator("main").inner_text()                     # this workbook has never actually run

        await order_btn.click()
        await js_until(page, "!!document.getElementById('run-order')")
        assert page.errors == []
    chains_file(web.root / "workbooks" / "order-timeline.xlsx").unlink(missing_ok=True)


async def tick(page, label: str) -> None:
    """Tick a test's box and make sure the page took it: right after a re-render (the run order arriving) Playwright's click can land on a node the page has
    just replaced, and the page then puts the box back as its state says.  Looking again is what a person does."""
    box = page.locator(f'input[aria-label="{label}"]')
    for _ in range(6):
        await box.check(force=True)
        await page.wait_for_timeout(300)
        if await box.is_checked():
            return
    raise AssertionError(f"{label} could not be ticked")


@pytest.mark.browser
async def test_a_missing_producer_is_a_warning_before_the_run(web):
    build(web.root / "workbooks" / "order-missing.xlsx", web.site)
    async with open_ui(web) as page:
        await pick_only(page, "order-missing.xlsx")
        await js_until(page, "document.body.innerText.includes('Run order')")                  # every test is a default Y, so the card is up
        await page.locator('[data-act="sel-none"]').click()
        await js_until(page, "!document.body.innerText.includes('2 streams')")                # the card goes with the selection
        await tick(page, "Run View#1")
        await js_until(page, "document.body.innerText.includes('A test uses an empty parameter')")
        text = await page.locator("body").inner_text()
        assert "View#1 uses DT_Policy_Out, which is empty and nothing in this run sets it. Buy#1 does: add it to the run" in text
        assert page.errors == []


# -- it knows without being asked ---------------------------------------------------------------------------------------------------------------
@pytest.mark.browser
async def test_the_run_order_is_worked_out_on_page_load_from_the_default_selection(web):
    """Nothing is clicked: the page opens on the remembered workbook with its default tests selected, and the Run order card and the Preflight line are there."""
    build(web.root / "workbooks" / "order-load.xlsx", web.site)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await ctx.add_init_script("try { localStorage.setItem('rr.workbook', 'order-load.xlsx') } catch (e) {}")
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(web.base + "/")
        await js_until(page, "document.body.innerText.includes('Working out which tests wait for which') || document.body.innerText.includes('Run order')")
        await js_until(page, "!!document.getElementById('run-order')")
        text = await page.locator("#run-order").inner_text()
        assert "2 streams" in text and "waits for Buy#1" in text
        preflight = await page.locator("#preflight").inner_text()
        assert "Run order" in preflight and "2 streams" in preflight and "Working out" not in preflight
        assert errors == []
        await browser.close()


@pytest.mark.browser
async def test_the_run_order_follows_the_selection_however_it_changes_and_survives_leaving_the_screen(web):
    build(web.root / "workbooks" / "order-follow.xlsx", web.site)
    async with open_ui(web) as page:
        await pick_only(page, "order-follow.xlsx")
        await js_until(page, "!!document.getElementById('run-order')")
        await page.locator('[data-act="sel-none"]').click()
        await js_until(page, "!document.getElementById('run-order') && document.body.innerText.includes('No test waits for another')")
        await page.locator('[data-act="sel-all"]').click()                                        # a different control than the checkbox: same result
        await js_until(page, "!!document.getElementById('run-order')")
        await page.locator('[data-act="sel-defaults"]').click()
        await js_until(page, "!!document.getElementById('run-order')")
        await page.evaluate("location.hash = '#/run/20200101-000000-UAT'")                        # away to a (missing) run, and back
        await js_until(page, "document.body.innerText.includes('That run does not exist')")
        await page.evaluate("location.hash = '#/'")
        await js_until(page, "!!document.getElementById('run-order')")
        assert page.errors == []


def test_asking_for_the_same_workbook_answer_many_times_reads_the_workbook_once(web, monkeypatch):
    """The page asks for the tests, the run order (and more) the moment a workbook is chosen, then again on clicks: on a big workbook every read is seconds
    of CPU, so answers being computed are shared instead of started again."""
    import regrunner.web.app as app_module
    build(web.root / "workbooks" / "order-once.xlsx", web.site)
    loads = []

    class Counting(app_module.Workbook):
        def __init__(self, *a, **kw):
            loads.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr(app_module, "Workbook", Counting)
    def ask(n):
        with web.client() as c:
            if n % 2:
                return c.get("/api/workbooks/order-once.xlsx/tests").status_code
            return c.post("/api/workbooks/order-once.xlsx/order", json={"tests": ALL, "chains": None}).status_code
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        assert list(pool.map(ask, range(6))) == [200] * 6
    assert len(loads) == 1, f"the workbook was read {len(loads)} times"


def test_asking_a_workbook_for_its_tests_twice_does_not_say_every_warning_twice(tmp_path, site):
    path = build(tmp_path / "a.xlsx", site)
    wb = openpyxl.load_workbook(path)
    wb["DataSheets"]["C2"] = "No_Such_Params"                                                     # Buy's parameter sheet does not exist: a warning
    wb.save(path)
    book = Workbook(path, seed=1)
    book.discover()
    first = list(book.warnings)
    book.discover()
    assert first and book.warnings == first
