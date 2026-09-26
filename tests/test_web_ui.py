"""The web UI in a real browser, driven like a non-technical person would: pick a workbook, press Run, watch, read results."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from contextlib import asynccontextmanager

import pytest
from playwright.async_api import async_playwright, expect

from tests.test_web_api import make_interrupted_copy, zip_bytes
from tests.web_fixtures import bad_run, web  # noqa: F401  (fixtures)
from tests.workbook_factory import build_workbook

pytestmark = pytest.mark.browser
LONG = 120_000


@asynccontextmanager
async def open_ui(web, *, path="/", width=1440, height=1000, permissions=None):
    """A page on the UI with console/page errors collected (the fonts CDN is answered locally: no network needed)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True,
                                        permissions=permissions or [])
        await ctx.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
                        lambda route: route.fulfill(status=200, content_type="text/css", body=""))
        page = await ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(f"pageerror: {e}"))
        # The browser logs every 4xx response as a console error; the UI shows those to the person, so they are expected noise.
        noise = re.compile(r"Failed to load resource: the server responded with a status of 4\d\d")
        page.on("console", lambda m: page.errors.append(f"console: {m.text}") if m.type == "error" and not noise.search(m.text) else None)
        await page.goto(web.base + path)
        try:
            yield page
        finally:
            await browser.close()


async def until(predicate, timeout: float = 10.0):
    """Wait for a plain condition."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.05)


async def js_until(page, expression: str, timeout: float = 20.0):
    """Poll a page expression until it is truthy (the app's strict CSP forbids in-page string evaluation)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not await page.evaluate(expression):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"page condition not reached: {expression[:90]}")
        await asyncio.sleep(0.1)


def cmd_text(page):
    return page.locator('[aria-label="Command line for this run"]')


async def command(page) -> str:
    return re.sub(r"\s+", " ", (await cmd_text(page).inner_text()).replace("$", "", 1)).strip()


async def command_is(page, text: str, timeout: float = 10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while (got := await command(page)) != text:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"command was {got!r}, expected {text!r}")
        await asyncio.sleep(0.05)


async def command_has(page, part: str, timeout: float = 10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while part not in (got := await command(page)):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"command was {got!r}, expected it to contain {part!r}")
        await asyncio.sleep(0.05)


async def pick_only(page, name: str):
    """Tick exactly this workbook: the page opens with the newest one ticked, and ticking another adds it (several workbooks can run at once)."""
    for value in await page.locator("input[name=workbook]:checked").evaluate_all("els => els.map(e => e.value)"):
        if value != name:
            await page.locator(f'input[name=workbook][value="{value}"]').uncheck(force=True)
    await page.locator(f'input[name=workbook][value="{name}"]').check(force=True)


async def wait_ready(page):
    """The page has loaded its data and read whichever workbook it opened with."""
    await expect(page.get_by_role("button", name=re.compile(r"^Run \d+ tests?$"))).to_be_enabled(timeout=20_000)


# ------------------------------------------------------------------------------------------------------------
async def test_every_setting_is_a_control_and_shows_up_in_the_command_and_the_request(web):
    async with open_ui(web, permissions=["clipboard-read", "clipboard-write"]) as page:
        await wait_ready(page)
        assert await page.locator("h1").inner_text() == "Set up a regression run"
        assert await page.locator("input[name=workbook]:checked").get_attribute("value") in ("mock.xlsx", "bad.xlsx")
        await pick_only(page, "mock.xlsx")
        await page.wait_for_selector('text=2 test sheets')
        await expect(page.locator("input.cb:checked")).to_have_count(2)
        await command_has(page, "regrunner run")
        await command_is(page, "regrunner run mock.xlsx --all")

        await page.locator('label[data-key="FlowB"] input').uncheck()
        await command_has(page, "--tests FlowA")
        await page.get_by_role("button", name=re.compile(r"^full · 1$")).click()             # tag chip selects its tests
        await command_has(page, "--tests FlowB")
        await page.get_by_role("button", name=re.compile(r"^smoke · 1$")).click()
        await expect(page.get_by_role("button", name=re.compile(r"^smoke · 1$"))).to_have_attribute("aria-pressed", "true")

        await page.get_by_role("button", name="More workers").click()
        await page.get_by_role("button", name="Failures").click()
        await page.get_by_role("button", name="More retries").click()
        await page.locator("#seed").fill("12ab3")
        assert await page.locator("#seed").input_value() == "123"                               # digits only
        for label in ("PDF report", "Harvest selectors", "Show browsers", "Low OS priority"):
            await page.get_by_label(label).click(force=True)
        await page.get_by_text("More options").click()
        await expect(page.get_by_label("Skip the HTML report")).to_be_visible()
        await page.get_by_label("Skip the HTML report").click(force=True)
        await page.get_by_role("button", name="QA", exact=True).click()
        want = ("regrunner run mock.xlsx --tests FlowA --env QA --workers 3 --screenshots on_failure --retries 1 --seed 123 "
                "--pdf --harvest --headed --no-nice --no-report")
        await command_is(page, want)
        assert "recaptchaBypassToken · QA: missing" in await page.locator("main").inner_text()
        assert "No saved session" in await page.locator("#preflight").inner_text()

        await page.get_by_role("button", name="Copy", exact=True).click()                        # what the button copies is what is shown
        assert (await page.evaluate("navigator.clipboard.readText()")).replace("\n", " ") == want

        # the request the Run button sends carries every one of those choices (nothing is started here)
        sent = {}

        async def capture(route):
            if route.request.method != "POST":                                                   # the sidebar polls the run list
                return await route.continue_()
            sent.update(json.loads(route.request.post_data))
            await route.fulfill(status=200, content_type="application/json", body='{"run_id": "20990101-000000-UAT", "command": "x"}')
        await page.route(re.compile(r".*/api/runs$"), capture)
        await page.get_by_role("button", name="Run 1 test").click()
        await until(lambda: bool(sent))
        assert sent == {"workbook": "mock.xlsx", "all": False, "tests": ["FlowA"], "env": "QA", "workers": 3, "screenshots": "on_failure",
                        "retries": 1, "seed": 123, "pdf": True, "harvest": True, "headed": True, "nice": False, "no_report": True, "chains": None,
                    "browser": "chromium"}                                                           # the browser the person saw is always sent, so a config.yaml edit meanwhile cannot change it
        await page.wait_for_selector("text=That run does not exist")                             # the fake id is reported, not a blank page
        assert not page.errors, page.errors


async def test_prod_needs_typed_confirmation_and_the_server_is_only_told_after_it(web):
    async with open_ui(web) as page:
        await wait_ready(page)
        posts: list[dict] = []

        async def capture(route):
            if route.request.method != "POST":
                return await route.continue_()
            posts.append(json.loads(route.request.post_data))
            await route.fulfill(status=200, content_type="application/json", body='{"run_id": "20990101-000001-PROD", "command": "x"}')
        await page.route(re.compile(r".*/api/runs$"), capture)
        await page.get_by_role("button", name="PROD", exact=True).click()
        run = page.get_by_role("button", name="Review and run on PROD…")
        await expect(run).to_be_visible()
        assert "PROD is locked" in await page.locator("#preflight").inner_text()
        assert "You will be asked to type PROD" in await page.locator("main").inner_text()

        await run.click()
        dialog = page.get_by_role("dialog")
        await expect(dialog.get_by_role("heading", name="Run on PROD?")).to_be_visible()
        confirm = dialog.get_by_role("button", name="Run on PROD")
        await expect(confirm).to_be_disabled()
        await dialog.get_by_label("Type PROD to confirm").fill("prod")
        await expect(confirm).to_be_disabled()
        await page.keyboard.press("Escape")
        await expect(dialog).to_have_count(0)
        assert posts == []                                                                       # escaping did not start anything

        await run.click()
        await page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
        assert posts == []
        await run.click()
        field = page.get_by_role("dialog").get_by_label("Type PROD to confirm")
        await field.fill("PROD")
        await expect(page.get_by_role("dialog").get_by_role("button", name="Run on PROD")).to_be_enabled()
        await field.press("Enter")
        await until(lambda: len(posts) == 1)
        assert posts[0]["env"] == "PROD" and posts[0]["allow_prod"] is True and posts[0]["confirm_prod"] == "PROD"


async def test_confirming_prod_shows_the_click_registered_while_the_server_starts_the_run(web):
    """Reading a big workbook and starting the runner takes seconds; the dialog used to sit there unchanged and look dead."""
    async with open_ui(web) as page:
        await wait_ready(page)
        posts: list[dict] = []
        release = asyncio.Event()
        answer = {"status": 200, "body": '{"run_id": "20990101-000002-PROD", "command": "x"}'}

        async def hold(route):                                                                   # the server is "still working"
            if route.request.method != "POST":
                return await route.continue_()
            posts.append(json.loads(route.request.post_data))
            await release.wait()
            await route.fulfill(status=answer["status"], content_type="application/json", body=answer["body"])
        await page.route(re.compile(r".*/api/runs$"), hold)
        await page.get_by_role("button", name="PROD", exact=True).click()
        run = page.get_by_role("button", name="Review and run on PROD…")
        await run.click()
        dialog = page.get_by_role("dialog")
        field = dialog.get_by_label("Type PROD to confirm")
        await field.fill("PROD")
        await dialog.get_by_role("button", name="Run on PROD").click()
        await until(lambda: len(posts) == 1)

        starting = dialog.get_by_role("button", name="Starting the run…")                       # the click visibly registered
        await expect(starting).to_be_visible()
        assert await starting.locator(".spin").count() == 1
        await expect(dialog).to_have_attribute("aria-busy", "true")
        await expect(dialog.locator("#prod-starting")).to_contain_text("Reading the workbook and starting the runner")
        note = dialog.locator("#prod-starting .bn")                                              # information, not a failure: the accent (blue) banner, labelled Info
        await expect(note).to_have_class(re.compile(r"\bbn-acc\b"))
        await expect(note).to_contain_text("Info:")
        await expect(note).to_have_attribute("role", "status")
        assert await dialog.locator(".bn-fail, .bn-warn").count() == 0
        await expect(dialog.get_by_role("button", name="Cancel")).to_be_disabled()
        await expect(dialog.get_by_role("button", name="Close")).to_be_disabled()
        await expect(field).to_have_attribute("readonly", "")

        await page.keyboard.press("Escape")                                                     # nothing can dismiss it or send it twice
        await page.mouse.click(4, 4)
        await starting.click(force=True)
        await field.press("Enter")
        await asyncio.sleep(0.4)
        assert len(posts) == 1
        await expect(dialog).to_be_visible()

        answer.update(status=409, body='{"error": "A run is already in progress (20990101-000000-UAT).", "kind": "busy", "run_id": "20990101-000000-UAT"}')
        release.set()                                                                            # the server refuses: the dialog closes and says why
        await expect(dialog).to_have_count(0)
        await expect(page.get_by_text("A run is already in progress").first).to_be_visible()
        await expect(run).to_be_visible()

        answer.update(status=200, body='{"run_id": "20990101-000003-PROD", "command": "x"}')   # and it can be confirmed again
        await run.click()
        field = page.get_by_role("dialog").get_by_label("Type PROD to confirm")
        assert await field.input_value() == "" and not await field.get_attribute("readonly")
        await field.fill("PROD")
        await page.get_by_role("dialog").get_by_role("button", name="Run on PROD").click()
        await page.wait_for_selector("text=That run does not exist")                            # success moved on to the run screen (the fake id is reported)
        assert len(posts) == 2 and not page.errors, page.errors


async def test_uploading_a_workbook_by_picker_and_drag_with_every_rejection_state(web):
    good = (web.root / "workbooks" / "mock.xlsx").read_bytes()
    junk = zip_bytes({"xl/workbook.xml": "<nope>"})
    async with open_ui(web) as page:
        await wait_ready(page)
        pick = lambda name, data, mime="application/octet-stream": page.set_input_files(
            "#file-input", files=[{"name": name, "mimeType": mime, "buffer": data}])
        await pick("notes.txt", b"hello", "text/plain")
        await expect(page.get_by_role("alert")).to_contain_text("Only .xlsx and .xlsm workbooks can be uploaded.")
        await pick("fake.xlsx", b"not a zip")
        await expect(page.get_by_role("alert")).to_contain_text("That does not look like an Excel workbook.")

        await pick("broken.xlsx", junk)                                                          # saved, but cannot be read
        await expect(page.get_by_text("Could not read broken.xlsx.")).to_be_visible()
        assert await page.get_by_role("button", name="Show details").is_visible()
        await page.get_by_role("button", name="Show details").click()
        await expect(page.get_by_role("button", name="Hide details")).to_be_visible()
        assert "unreadable" in (await page.locator("main").inner_text()).lower()               # the pill on the workbook row
        assert "broken.xlsx could not be read" in await page.locator("#preflight").inner_text()
        await expect(page.locator(".btn-lg")).to_be_disabled()

        await pick("second copy.xlsx", good)                                                     # a good one selects and reads itself (it joins the ones chosen)
        await expect(page.locator('label[data-key="second copy.xlsx"]').get_by_text("Read OK")).to_be_visible()
        assert "second copy.xlsx" in await page.locator("input[name=workbook]:checked").evaluate_all("els => els.map(e => e.value)")
        await page.get_by_role("button", name="Remove it").click()                               # the unreadable one goes
        await pick_only(page, "second copy.xlsx")
        await command_is(page, 'regrunner run "second copy.xlsx" --all')

        # dragging a file over the page shows the drop target; dropping it uploads
        dt = await page.evaluate_handle("() => { const d = new DataTransfer(); d.items.add(new File(['x'], 'dragged.xlsx')); return d; }")
        await page.dispatch_event("body", "dragenter", {"dataTransfer": dt})
        await expect(page.get_by_text("Release to upload")).to_be_visible()
        await page.dispatch_event("body", "drop", {"dataTransfer": dt})
        await expect(page.get_by_role("alert")).to_contain_text("does not look like an Excel workbook")
        assert not page.errors, page.errors
    for name in ("broken.xlsx", "second copy.xlsx"):
        (web.root / "workbooks" / name).unlink(missing_ok=True)


async def test_workbook_text_is_shown_as_text_never_as_markup(web):
    hostile = "<img src=x onerror=__x=1>"                                                       # a sheet name that is markup
    build_workbook(web.root / "workbooks" / "hostile.xlsx", flows=[hostile], base_url=web.site)
    async with open_ui(web) as page:
        await page.wait_for_selector("text=Set up a regression run")
        await pick_only(page, "hostile.xlsx")
        await page.wait_for_selector("text=1 test sheet")
        assert hostile in await page.locator("main").inner_text()                               # visible literally
        assert await page.evaluate("window.__x") is None and await page.locator("main img[src=x]").count() == 0
    (web.root / "workbooks" / "hostile.xlsx").unlink()


# ------------------------------------------------------------------------------------------------------------
async def test_a_run_from_click_to_results_and_back_again_after_a_reload(web):
    async with open_ui(web, permissions=["clipboard-read", "clipboard-write"]) as page:
        await wait_ready(page)
        await pick_only(page, "mock.xlsx")
        await page.wait_for_selector("text=2 test sheets")
        await page.locator('label[data-key="FlowB"] input').uncheck()
        await page.get_by_role("button", name="Run 1 test").click()

        await page.wait_for_selector("text=Now running", timeout=30_000)                         # the live board
        assert (await page.locator("h1").inner_text()) == "mock"
        lane = page.locator('article[data-key="FlowA"]')
        await expect(lane).to_be_visible()
        await js_until(page, "(() => { const i = document.querySelector('article img'); return !!(i && i.complete && i.naturalWidth > 0); })()", 30)
        assert await page.locator(".ring").count() >= 1 and "Cancel run" in await page.locator("main").inner_text()
        assert re.search(r"\b\d+\s*%", await page.locator("main").inner_text())
        await expect(page.locator(".side-run.on")).to_have_count(1)                              # the sidebar follows along
        await expect(page.locator("aside .bar")).to_have_count(1)

        await page.wait_for_selector("text=The test passed", timeout=LONG)                       # switches to results by itself
        main = await page.locator("main").inner_text()
        assert "1/1" in main and "100.0%" in main and "Open HTML report" in main and "wall time" in main.lower()
        assert "Re-run" not in main                                                              # nothing failed
        run_id = re.search(r"/run/([\w.-]+)", page.url).group(1)
        href = await page.get_by_role("link", name="Open HTML report").get_attribute("href")
        report = await page.evaluate("async u => (await fetch(u)).text()", href)
        assert "Step-by-step evidence" in report and "data:image/jpeg;base64," in report
        await page.get_by_role("button", name="Copy command").first.click()
        await page.wait_for_selector("text=Command copied")
        assert (await page.evaluate("navigator.clipboard.readText()")) == "regrunner run mock.xlsx --tests FlowA"

        await page.reload()                                                                      # the same page from the past-runs list
        await page.wait_for_selector("text=The test passed")
        await page.get_by_role("button", name="New run").click()
        await page.wait_for_selector("text=Set up a regression run")
        await page.locator(f'button[data-id="{run_id}"]').click()
        await page.wait_for_selector("text=The test passed")
        assert not page.errors, page.errors


async def test_a_failed_run_shows_what_differed_and_reruns_only_the_failures(web, bad_run):
    async with open_ui(web, path=f"/#/run/{bad_run}", permissions=["clipboard-read"]) as page:
        await page.wait_for_selector("text=2 of 2 tests failed")
        main = page.locator("main")
        assert await page.locator(".pill", has_text="Failed").count() >= 1
        assert "failed steps · 1" in (await main.inner_text()).lower()
        card = page.locator('[data-key="step-48"]').first
        await expect(card).to_contain_text("Plan total")
        await expect(card).to_contain_text("$1.00")
        await expect(card).to_contain_text("(empty)")
        await expect(card).to_contain_text("Exact match: text must equal the expected value")
        await js_until(page, "(() => { const i = document.querySelector('[data-key=\"step-48\"] img'); return !!(i && i.complete && i.naturalWidth > 0); })()")
        assert "Things to review" in await main.inner_text() and "legacy_noop" in await main.inner_text()
        assert "Everything" not in await main.inner_text() and "Run parameters" in await main.inner_text()

        await card.locator(".shot").first.click()                                                # the screenshot opens large
        await expect(page.locator(".lightbox img")).to_be_visible()
        await page.keyboard.press("Escape")
        await expect(page.locator(".lightbox")).to_have_count(0)

        await expect(main.locator('[data-key="step-48"]')).to_have_count(2)                       # both failed tests are open
        await page.locator('button[data-act="expand-test"]').first.click()                       # a row folds away and back
        await expect(main.locator('[data-key="step-48"]')).to_have_count(1)
        await page.locator('button[data-act="expand-test"]').first.click()
        await expect(main.locator('[data-key="step-48"]')).to_have_count(2)

        async with page.context.expect_page() as popup:
            await page.get_by_role("link", name="Open HTML report").click()
        report = await popup.value
        await report.wait_for_load_state()
        assert "Regression report" in await report.title() or "Regression report" in await report.inner_text("body")
        await report.close()

        await page.get_by_role("button", name="Re-run 2 failed tests").click()                   # same settings, only what failed
        await page.wait_for_selector("text=Now running", timeout=30_000)
        new_id = re.search(r"/run/([\w.-]+)", page.url).group(1)
        assert new_id != bad_run
        meta = web.wait_finished(new_id)["meta"]
        assert meta["test_ids"] == ["FlowX", "FlowY"] and meta["environment"] == "UAT"
        assert meta["command"] == "regrunner run bad.xlsx --tests FlowX,FlowY --env UAT --harvest"     # same settings as before


async def test_a_run_in_progress_is_offered_to_join_and_the_cancel_flow(web):
    with web.client() as c:
        started = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA"]}).json()["run_id"]
    try:
        async with open_ui(web) as page:
            await page.wait_for_selector("text=1 run in progress.")
            await expect(page.get_by_role("status").filter(has_text="in progress")).to_contain_text("joins it and shares the workers")
            await expect(page.locator(".btn-lg")).to_be_visible()
            await page.get_by_role("button", name="Open run").click()
            await page.wait_for_selector("text=Now running", timeout=30_000)
            await page.get_by_role("button", name="Cancel run").click()
            await expect(page.get_by_text("Cancelling…")).to_be_visible()
            await expect(page.get_by_text(re.compile(r"forced stop in \d+ s"))).to_be_visible()
            await expect(page.get_by_role("button", name="Cancel run")).to_be_disabled()
            await page.wait_for_selector("text=Run cancelled", timeout=LONG)
            await js_until(page, "document.querySelector('aside').innerText.includes('stopped')", 10)
            await page.get_by_role("button", name="New run").click()
            await page.wait_for_selector("text=Set up a regression run")
            await expect(page.get_by_text("in progress.")).to_have_count(0)
    finally:
        with web.client() as c:
            c.post(f"/api/runs/{started}/cancel")
        web.wait_finished(started)


async def test_a_failed_step_says_why_it_failed(web, bad_run):
    """A run brought over from another computer explains itself: the findings in words, the browser's whole error folded under them."""
    copy = web.run_dir("20260304-000000-UAT")
    shutil.copytree(web.run_dir(bad_run), copy)
    (copy / "run.json").write_text(json.dumps({**json.loads((copy / "run.json").read_text()), "run_id": copy.name}))
    data = json.loads((copy / "results.json").read_text())
    for test in data["tests"]:
        for step in test["steps"]:
            if step["seq"] == 48:
                step["detail"] = "Locator.click: Timeout 30000ms exceeded.\nCall log:\n  - <div id=\"veil\"> intercepts pointer events"
                step["diagnosis"] = {"summary": ["On the main page, above the frame at that point, is <div#veil.page-loader>: it takes the click before the frame does."],
                                     "dom": {"frame": "tests/Flow/dom/0048_r99_x.frame.html"}}
    (copy / "results.json").write_text(json.dumps(data))
    async with open_ui(web, path=f"/#/run/{copy.name}") as page:
        card = page.locator('[data-key="step-48"]').first
        await expect(card).to_contain_text("Why it failed")
        await expect(card).to_contain_text("above the frame at that point, is <div#veil.page-loader>")           # shown as text, not taken for markup
        await expect(card.get_by_text("intercepts pointer events")).to_be_hidden()                                    # the whole error is folded away ...
        await card.get_by_text("The browser's whole error and saved HTML").click()
        await expect(card.get_by_text("intercepts pointer events")).to_be_visible()                                  # ... until asked for
        await expect(card).to_contain_text("tests/Flow/dom/0048_r99_x.frame.html")
        assert not page.errors, page.errors


async def test_an_interrupted_run_can_be_replayed_and_turned_into_a_report(web, bad_run):
    run_id = make_interrupted_copy(web, bad_run, "20260202-000000-UAT")
    async with open_ui(web, path=f"/#/run/{run_id}") as page:
        await page.wait_for_selector("text=This run stopped responding.")
        assert "process stopped responding" in await page.locator("aside").inner_text()
        assert await page.get_by_role("button", name="Cancel run").count() == 0                  # nothing to cancel
        assert "interrupted" in (await page.locator(".pill").first.inner_text()).lower()
        await js_until(page, "document.querySelector('main').innerText.includes('Finished')")     # what did finish is still shown (the event log replays a moment after the banner)

        await page.evaluate("import('/static/js/state.js').then(m => { m.S.view.conn = 'reconnecting'; m.rerender(); })")
        await expect(page.get_by_text("Reconnecting…")).to_be_visible()
        await page.evaluate("import('/static/js/state.js').then(m => { m.S.view.conn = 'closed'; m.rerender(); })")

        await page.get_by_role("button", name="Build report from what ran").click()
        await page.wait_for_selector("text=Run interrupted · 1 of 2 tests finished")
        await expect(page.get_by_text("Rebuilt from the event log.")).to_be_visible()
        assert await page.get_by_role("link", name="Open HTML report").is_visible()
        assert not page.errors, page.errors


# ------------------------------------------------------------------------------------------------------------
async def test_lint_plan_and_audit_dialogs_and_keyboard_behaviour(web):
    async with open_ui(web) as page:
        await wait_ready(page)
        await pick_only(page, "mock.xlsx")
        await page.wait_for_selector("text=2 test sheets")

        lint = page.get_by_role("button", name="Run lint")
        await lint.click()
        dialog = page.get_by_role("dialog")
        await expect(dialog.get_by_role("heading", name="Lint")).to_be_visible()
        await expect(dialog.locator("table tbody tr").first).to_be_visible()
        assert "never implemented" in await dialog.inner_text()
        await dialog.get_by_role("button", name=re.compile(r"^Errors · 0$")).click()
        await expect(dialog).to_contain_text("Nothing at this level.")
        await dialog.get_by_role("button", name=re.compile(r"^Warnings")).click()
        await expect(dialog.locator("table tbody tr").first).to_be_visible()
        await page.keyboard.press("Escape")
        await expect(dialog).to_have_count(0)
        assert await page.evaluate("document.activeElement.textContent.trim()") == "Run lint"     # focus returns to what opened it

        await page.get_by_role("button", name="Preview").click()
        await expect(dialog.get_by_role("heading", name="Dry-run plan")).to_be_visible()
        await expect(dialog.locator("table tbody tr").first).to_be_visible()
        rows_all = await dialog.locator("table tbody tr").count()
        assert rows_all > 40
        await dialog.get_by_label("Filter steps").fill("Submit")
        await js_until(page, "document.querySelectorAll('.modal table tbody tr').length < %d" % rows_all)
        await dialog.get_by_role("button", name="FlowB").click()
        await expect(dialog.get_by_role("button", name="FlowB")).to_have_attribute("aria-pressed", "true")
        await dialog.get_by_role("button", name="Close").click()

        await page.get_by_role("button", name="Audit").click()
        await expect(dialog.get_by_role("heading", name="Locator health")).to_be_visible()
        shown = (await dialog.inner_text()).lower()
        assert "locator uses" in shown and "weakest locators" in shown
        await page.keyboard.press("Escape")

        await page.get_by_role("button", name="Re-check everything").click()
        await expect(dialog.get_by_role("heading", name="Doctor")).to_be_visible()
        await dialog.get_by_text("launches headless").wait_for(timeout=30_000)
        await page.keyboard.press("Escape")
        assert not page.errors, page.errors


async def test_signing_in_once_walks_through_the_steps_and_saves_the_session(web):
    async with open_ui(web) as page:
        await wait_ready(page)
        await pick_only(page, "mock.xlsx")
        await page.wait_for_selector("text=2 test sheets")
        await page.get_by_role("button", name="Sign in…").click()
        dialog = page.get_by_role("dialog")
        url = dialog.get_by_label("Site to sign in to")
        await expect(url).to_have_value(web.site)                                                # filled from the workbook
        assert "Sign in yourself in that window" in await dialog.inner_text()
        await url.fill("javascript:alert(1)")
        await dialog.get_by_role("button", name="Open sign-in window").click()
        await expect(dialog.get_by_role("alert")).to_contain_text("http://")                     # refused, and said why
        await url.fill(web.site)
        await dialog.get_by_role("button", name="Open sign-in window").click()
        await expect(dialog.get_by_text("A browser window opened")).to_be_visible()
        await dialog.get_by_role("button", name="I'm signed in, save").click()
        await page.wait_for_selector("text=Session saved.")
        await expect(page.get_by_role("dialog")).to_have_count(0)
        await expect(page.locator("#preflight")).to_contain_text("A saved session is reused")
        assert (web.root / ".auth" / "state.json").is_file()
        assert not page.errors, page.errors
    (web.root / ".auth" / "state.json").unlink()


async def test_harvested_locators_are_reviewed_then_merged(web, bad_run):
    copy = web.run_dir("20260303-000000-UAT")
    shutil.copytree(web.run_dir(bad_run), copy)
    (copy / "run.json").write_text(json.dumps({**json.loads((copy / "run.json").read_text()), "run_id": copy.name}))
    (copy / "selector_suggestions.json").write_text(json.dumps({"suggestions": {
        "xpath=//input[3]": {"use": ['css=input[name="a"]'], "index": 0, "score": 90, "kind": "name", "legacy_score": 30, "uses": 4, "example_step": "Age"},
        "xpath=//button[9]": {"use": ["css=#go"], "index": 0, "score": 92, "kind": "id", "legacy_score": 20, "uses": 2, "example_step": "Go"}},
        "skipped": {}}))
    async with open_ui(web, path=f"/#/run/{copy.name}") as page:
        await page.get_by_role("button", name="Review and merge locators").click()
        dialog = page.get_by_role("dialog")
        await expect(dialog.get_by_role("heading", name="Review locators")).to_be_visible()
        await expect(dialog.get_by_role("button", name="Merge 2 locators")).to_be_enabled()
        await dialog.get_by_label("Merge xpath=//input[3]").uncheck()
        await dialog.get_by_role("button", name="Merge 1 locator").click()
        await expect(dialog.get_by_text("1 locator added")).to_be_visible()
        await dialog.get_by_role("button", name="Done").click()
    text = (web.root / "selectors.yaml").read_text()
    assert "css=#go" in text and 'input[name=\\"a\\"]' not in text and "input[name" not in text


async def test_the_screen_reducer_agrees_with_the_results_file(web, bad_run):
    async with open_ui(web) as page:
        await page.wait_for_selector("text=Set up a regression run")
        summary = await page.evaluate("""async (id) => {
            const { newRun, applyAll, counts, groupReview, reviewOfRun, reviewTotal } = await import('/static/js/runstate.js');
            const events = (await (await fetch(`/api/runs/${id}/events`)).json()).events;
            const results = (await (await fetch(`/api/runs/${id}`)).json()).results;
            const run = newRun(id); applyAll(run, events);
            const c = counts(run);
            const fromResults = results.tests.reduce((n, t) => n + t.review.reduce((m, r) => m + r.count, 0), 0);
            return { status: run.status, done: c.done, total: c.total, failed: c.failedSteps, tests: run.order.length,
                     steps: results.tests.reduce((n, t) => n + t.steps.length, 0), failedSteps: results.summary.steps_failed,
                     review: reviewTotal(groupReview(reviewOfRun(run))), fromResults, workers: run.workers, percent: c.percent };
        }""", bad_run)
        assert summary["status"] == "FAILED" and summary["done"] == summary["steps"] == summary["total"] and summary["percent"] == 100
        assert summary["failed"] == summary["failedSteps"] == 2 and summary["tests"] == 2 and summary["workers"] == 2
        assert summary["review"] == summary["fromResults"] > 0                                   # live counts settle to the final ones


async def test_theme_toggle_and_a_narrow_window(web):
    async with open_ui(web, width=900, height=900) as page:
        await wait_ready(page)
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")   # nothing spills sideways
        before = await page.evaluate("document.documentElement.dataset.theme")
        bg = await page.evaluate("getComputedStyle(document.body).backgroundColor")
        await page.get_by_role("button", name="Switch between light and dark").click()
        after = await page.evaluate("document.documentElement.dataset.theme")
        assert {before, after} == {"dark", "light"}
        assert await page.evaluate("getComputedStyle(document.body).backgroundColor") != bg
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not page.errors, page.errors
