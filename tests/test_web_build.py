"""The Build tab in a real browser: open a workbook, browse its map, edit a test, save to Excel (P04-build-ui.md)."""
from __future__ import annotations

import asyncio
import re

import openpyxl
import pytest
from playwright.async_api import async_playwright

from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser
HEADERS = {"X-Requested-With": "regrunner"}


@pytest.fixture
async def build_copy(web, request):
    """A workbook this file's tests can edit freely, independent of the shared ``mock.xlsx`` and of each other."""
    name = f"build_ui_{request.node.name}"[:80]
    async with web.aclient() as c:
        r = await c.post("/api/build/workbooks", json={"name": name, "from": "mock.xlsx"})
        assert r.status_code == 201, r.text
        return r.json()["name"]


async def open_ui(web, path="/"):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width": 1440, "height": 1000})
    await ctx.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"), lambda route: route.fulfill(status=200, content_type="text/css", body=""))
    page = await ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(f"pageerror: {e}"))
    noise = re.compile(r"Failed to load resource: the server responded with a status of 4\d\d")
    page.on("console", lambda m: page.errors.append(f"console: {m.text}") if m.type == "error" and not noise.search(m.text) else None)
    await page.goto(web.base + path)
    return pw, browser, page


async def js_until(page, expression: str, timeout: float = 20.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not await page.evaluate(expression):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"page condition not reached: {expression[:120]}")
        await asyncio.sleep(0.1)


async def test_the_build_tab_shows_the_workbook_map_and_a_test_opens_its_editor(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}")
    try:
        await js_until(page, "!!document.querySelector('.tab-btn.on')")
        assert await page.locator('.tab-btn.on').inner_text() == 'Build'
        await js_until(page, "document.querySelectorAll('main a.disp').length >= 2")           # FlowA, FlowB cards
        names = await page.locator('main a.disp').evaluate_all("els => els.map(e => e.textContent)")
        assert set(names) >= {"FlowA", "FlowB"}
        card = page.locator('.tcard', has_text="FlowA").first
        box = await card.bounding_box()
        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] - 8)        # anywhere on the card, not only its name
        await js_until(page, "location.hash.includes('/test/FlowA')")
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        await page.get_by_role("button", name=re.compile("^Grid$")).click()
        await js_until(page, "document.querySelector('table.mono thead') != null")
        assert "Method" in await page.locator("table.mono thead").inner_text()
        assert await page.evaluate("getComputedStyle(document.querySelector('table.gtable tbody td')).display") == "table-cell"
        assert await page.locator("table.gtable tbody tr").first.locator("td").first.inner_text() == "2"     # Excel row numbers
        header_cells = await page.locator("table.gtable thead th").count()
        assert await page.locator("table.gtable tbody tr").first.locator("td").count() == header_cells    # every row lines up with the header
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_editing_a_step_autosaves_a_draft_that_save_to_excel_writes_to_disk(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        timeout_box = page.locator('input[data-input="build-step-timeout"]')
        await timeout_box.fill("42")
        await timeout_box.blur()
        await js_until(page, "!document.querySelector('[data-act=\"build-undo\"]').disabled", timeout=10)   # the edit landed: undo is now possible
        await js_until(page, "!!document.querySelector('[data-act=\"build-save\"]')")
        await page.get_by_role("button", name=re.compile("Save to Excel")).click()

        async def saved_to_disk():
            r = await page.request.get(f"{web.base}/api/build/workbooks/{build_copy}/status")
            return not (await r.json())["modified"]
        deadline = asyncio.get_running_loop().time() + 15
        while not await saved_to_disk():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("save to Excel did not clear the modified flag in time")
            await asyncio.sleep(0.2)
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()

    wb = openpyxl.load_workbook(web.root / "workbooks" / build_copy)
    ws = wb["FlowA"]
    headers = [c.value for c in ws[1]]
    timeout_col = headers.index("Timeout") + 1
    values = [ws.cell(r, timeout_col).value for r in range(2, ws.max_row + 1)]
    assert 42 in values


async def test_new_workbook_dialog_creates_a_workbook_ready_to_build(web):
    pw, browser, page = await open_ui(web, "/#/build")
    try:
        await js_until(page, "!!document.querySelector('.tab-btn.on')")
        await page.get_by_role("button", name=re.compile("New workbook")).first.click()
        await js_until(page, "!!document.querySelector('[data-input=\"build-nw-name\"]')")
        await page.locator('[data-input="build-nw-name"]').fill("Fresh Build Test")
        await page.get_by_role("button", name="Create workbook").click()
        await js_until(page, "location.hash.includes('/build/Fresh')", timeout=15)
        await js_until(page, "document.querySelector('main .ttl') != null")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_all_workbooks_is_one_click_away_and_the_whole_card_opens_a_workbook(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}")
    try:
        await js_until(page, "document.querySelectorAll('main a.disp').length >= 2")
        await page.locator('header a[href="#/build/all"]').click()
        await js_until(page, "location.hash === '#/build/all' && document.querySelectorAll('.wb-card').length >= 2")
        names = await page.locator(".wb-card b").all_inner_texts()
        assert build_copy in names and "mock.xlsx" in names
        assert "Open now" in await page.locator(".wb-card", has_text=build_copy).inner_text()
        await page.locator(".wb-card", has_text="mock.xlsx").click(position={"x": 90, "y": 20})     # anywhere on the card, not only its name
        await js_until(page, "location.hash === '#/build/mock.xlsx' && document.querySelectorAll('main a.disp').length >= 2")
        await page.locator('.b-rail a[href="#/build/all"]').click()                                 # the rail has the way back too
        await js_until(page, "location.hash === '#/build/all'")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_the_download_button_gives_the_saved_workbook_as_a_file(web, build_copy):
    async with web.aclient() as c:
        r = await c.get(f"/api/workbooks/{build_copy}/download")
        assert r.status_code == 200 and r.content == (web.root / "workbooks" / build_copy).read_bytes()
        assert "attachment" in r.headers["content-disposition"] and build_copy in r.headers["content-disposition"]
        assert (await c.get("/api/workbooks/nope.xlsx/download")).status_code == 404
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}")
    try:
        await js_until(page, "!!document.querySelector('header [data-act=\"build-download\"]')")
        async with page.expect_download() as info:
            await page.locator('header [data-act="build-download"]').click()
        download = await info.value
        assert download.suggested_filename == build_copy
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_a_step_that_acts_on_an_element_always_offers_on_which_element_and_a_typed_locator_is_saved(web, build_copy):
    async with web.aclient() as c:
        r = await c.post(f"/api/build/workbooks/{build_copy}/edit", headers=HEADERS,
                         json={"ops": [{"op": "insert_step", "test": "FlowA", "step": {"method": "CLICK"}}]})
        assert r.status_code == 200, r.text
        row = r.json()["applied"][0]["row"]
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        await page.locator('[data-act="build-pick-block"]').last.click()                         # (the new last step is in the last block)
        await page.locator(f'.scard [data-act="build-pick-step"][data-row="{row}"]').click()
        box = page.locator(f'input[data-input="build-step-locator"][data-row="{row}"]')
        await js_until(page, f"!!document.querySelector('input[data-input=\"build-step-locator\"][data-row=\"{row}\"]')")
        assert await box.input_value() == ""
        assert await page.locator(f'[data-act="build-sess-pick-for"][data-row="{row}"]').inner_text() == "Open the site and pick"
        await box.fill("#go-now")
        await box.blur()

        async def locator_of_step():
            async with web.aclient() as c:
                model = (await c.get(f"/api/build/workbooks/{build_copy}")).json()
            step = next(s for s in next(t for t in model["tests"] if t["id"] == "FlowA")["steps"] if s["row"] == row)
            return step["locator"]
        deadline = asyncio.get_running_loop().time() + 10
        while (await locator_of_step())["value"] != "#go-now":
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the typed locator did not reach the workbook")
            await asyncio.sleep(0.2)
        assert (await locator_of_step())["findBy"] == "BY_CSSSELECTOR"                              # guessed from what was typed
        await page.locator(f'select[data-change="build-step-findby"][data-row="{row}"]').select_option("BY_XPATH")
        deadline = asyncio.get_running_loop().time() + 10
        while (await locator_of_step())["findBy"] != "BY_XPATH":
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the FindBy change did not reach the workbook")
            await asyncio.sleep(0.2)
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_a_page_check_step_shows_what_its_fingerprint_checks_and_opens_it_for_editing(web, build_copy):
    async with web.aclient() as c:
        r = await c.post(f"/api/build/workbooks/{build_copy}/edit", headers=HEADERS, json={"ops": [
            {"op": "set_fingerprint", "name": "Review page", "urlContains": "/buy/review.html", "landmark": "css=title", "landmarkText": "Review"},
            {"op": "insert_step", "test": "FlowA", "step": {"method": "ASSERT_PAGE", "value": "Review page"}}]})
        assert r.status_code == 200, r.text
        row = next(a["row"] for a in r.json()["applied"] if a.get("op") == "insert_step")
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        await page.locator('[data-act="build-pick-block"]').last.click()
        await page.locator(f'.scard [data-act="build-pick-step"][data-row="{row}"]').click()
        button = page.locator('button[data-act="build-fp-edit"][data-name="Review page"]')
        await js_until(page, "!!document.querySelector('button[data-act=\"build-fp-edit\"][data-name=\"Review page\"]')")
        section = button.locator("xpath=ancestor::div[2]")
        assert "/buy/review.html" in await section.inner_text() and "css=title" in await section.inner_text()
        await button.click()
        await js_until(page, "!!document.querySelector('[data-input=\"build-fp-url\"]')")
        assert await page.locator('[data-input="build-fp-url"]').input_value() == "/buy/review.html"
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_the_new_workbook_dialog_says_production_or_not_production_on_each_environment(web):
    pw, browser, page = await open_ui(web, "/#/build/all")
    try:
        await page.get_by_role("button", name=re.compile("New workbook")).first.click()
        await js_until(page, "!!document.querySelector('[data-change=\"build-nw-env-prod\"]')")
        labels = await page.locator('.modal tbody label').all_inner_texts()
        assert [x.strip() for x in labels] == ["Not production", "Not production", "Production"]            # QA, UAT, PROD
        assert "is it production?" in (await page.locator(".modal thead").inner_text()).lower()
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_the_selected_bar_wraps_inside_a_narrow_window(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await page.set_viewport_size({"width": 760, "height": 800})
        await js_until(page, "document.querySelectorAll('.scard').length > 1")
        page_width = await page.evaluate("document.documentElement.scrollWidth")
        boxes = page.locator('.scard input[data-act="build-toggle-multi"]')
        await boxes.nth(0).click()
        await boxes.nth(1).click()
        await js_until(page, "!!document.querySelector('.bulk-bar')")
        bar = await page.locator(".bulk-bar").bounding_box()
        column = await page.locator(".bulk-bar").evaluate("el => el.offsetParent.getBoundingClientRect().toJSON()")
        assert bar["x"] >= column["x"] and bar["x"] + bar["width"] <= column["x"] + column["width"] + 1      # nothing cut off at the sides
        assert await page.evaluate("document.documentElement.scrollWidth") <= page_width                      # the bar never widens the page
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_the_build_tab_button_always_opens_all_workbooks(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        await page.locator('.tab-btn', has_text="Run").click()
        await js_until(page, "!location.hash.startsWith('#/build')")
        await page.locator('.tab-btn', has_text="Build").click()
        await js_until(page, "location.hash === '#/build/all' && document.querySelectorAll('.wb-card').length >= 2")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def steps_of(web, name: str, test: str = "FlowA") -> list[dict]:
    async with web.aclient() as c:
        model = (await c.get(f"/api/build/workbooks/{name}")).json()
    return next(t for t in model["tests"] if t["id"] == test)["steps"]


async def model_until(web, name: str, check, timeout: float = 10):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        steps = await steps_of(web, name)
        if check(steps):
            return steps
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"the workbook did not get there: {[(s['n'], s['block'], s['name']) for s in steps][:12]}")
        await asyncio.sleep(0.2)


async def test_move_to_block_puts_the_steps_at_the_end_of_that_block_not_at_the_end_of_the_test(web, build_copy):
    before = await steps_of(web, build_copy)
    first_block = before[0]["block"]
    moving = next(s for s in before if s["block"] != first_block and s["n"] > 10)
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept(first_block)))
        await page.locator('[data-act="build-pick-block"]').nth(1).click()
        await page.locator(f'.scard input[data-act="build-toggle-multi"][data-row="{moving["row"]}"]').click()
        await page.locator('.bulk-bar [data-act="build-move-block"]').click()
        steps = await model_until(web, build_copy, lambda st: any(s["name"] == moving["name"] and s["block"] == first_block for s in st))
        moved = next(s for s in steps if s["name"] == moving["name"])
        in_first = [s["n"] for s in steps if s["block"] == first_block]
        assert moved["n"] == max(in_first) and moved["n"] < len(steps)                         # the end of that block, not of the test
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_a_step_can_start_a_new_page_and_a_new_page_can_be_added_at_the_end(web, build_copy):
    before = await steps_of(web, build_copy)
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        answers = iter(["Cookies page", "Wrap up"])
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept(next(answers))))
        second = before[1]
        await page.locator(f'.scard [data-act="build-pick-step"][data-row="{second["row"]}"]').click()
        await page.locator(f'aside [data-act="build-start-page"][data-row="{second["row"]}"]').click()
        steps = await model_until(web, build_copy, lambda st: st[1]["block"] == "Cookies page")
        assert steps[0]["block"] != "Cookies page"                                              # the steps before it keep their page
        await page.locator('[data-act="build-new-page"]').first.click()
        await js_until(page, "document.body.textContent.includes('starts the new page')")
        await js_until(page, "document.querySelectorAll('[data-act=\"build-insert\"]').length > 0")
        await page.locator('[data-act="build-insert"][data-method="CLICK"]').first.click()
        steps = await model_until(web, build_copy, lambda st: st[-1]["block"] == "Wrap up")
        assert steps[-1]["method"] == "CLICK" and len(steps) == len(before) + 1
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_dragging_a_step_card_moves_the_step(web, build_copy):
    before = await steps_of(web, build_copy)
    first, third = before[0], before[2]
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 2")
        target = page.locator(f'.scard[data-row="{first["row"]}"]')
        await page.locator(f'.scard[data-row="{third["row"]}"] .sgrip').drag_to(target, target_position={"x": 40, "y": 4})   # top half: before it
        steps = await model_until(web, build_copy, lambda st: st[0]["name"] == third["name"])
        assert [s["name"] for s in steps[:3]] == [third["name"], first["name"], before[1]["name"]]
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_the_selected_bar_sits_under_the_lowest_ticked_card_and_can_be_dragged_away_and_back(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 2")
        boxes = page.locator('.scard input[data-act="build-toggle-multi"]')
        await boxes.nth(0).click()
        await boxes.nth(1).click()                                                              # (the bar never covers the next box)
        await js_until(page, "!!document.querySelector('.bulk-anchor .bulk-bar')")
        above = await page.evaluate("document.querySelector('.bulk-anchor').previousElementSibling.dataset.row")
        rows = await page.locator(".scard").evaluate_all("els => els.map((e) => e.dataset.row)")
        assert above == rows[1]                                                                 # right under the lowest ticked card
        grip = await page.locator(".bulk-grip").bounding_box()
        await page.mouse.move(grip["x"] + 3, grip["y"] + 5)
        await page.mouse.down()
        await page.mouse.move(300, 600, steps=6)
        await page.mouse.up()
        await js_until(page, "!!document.querySelector('.bulk-bar.moved') && !document.querySelector('.bulk-anchor')")
        box = await page.locator(".bulk-bar.moved").bounding_box()
        assert abs(box["y"] - 595) < 30                                                         # it stays where it was put
        await page.locator('[data-act="build-bulk-home"]').click()
        await js_until(page, "!!document.querySelector('.bulk-anchor .bulk-bar')")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()
