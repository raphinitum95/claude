"""P11 in a real browser: templates, copy/paste, duplicate, find & replace, the value builder, and merge-on-disk-change."""
from __future__ import annotations

import asyncio
import re

import openpyxl
import pytest
from playwright.async_api import async_playwright

from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


@pytest.fixture
async def build_copy(web, request):
    name = f"p11_{request.node.name}"[:80]
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


async def test_save_selection_as_template_then_insert_it_into_another_test(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        await page.locator(".scard input.cb").first.check(force=True)
        await page.locator('[data-act="build-save-template"]').click()
        await page.locator('[data-input="build-tpl-name"]').fill("Open browser")
        await page.locator('[data-act="build-tpl-save"]').click()
        await js_until(page, "!document.querySelector('.modal-back')")

        await page.evaluate(f"location.hash = '#/build/{build_copy}'")
        await js_until(page, "location.hash.endsWith('/build/" + build_copy + "')")
        await page.locator("main a.disp", has_text="FlowB").click()
        await js_until(page, "location.hash.includes('/test/FlowB')")
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        before = await page.locator(".scard").count()

        await page.locator('[data-act="build-toggle-menu"]').click()
        await page.locator('[data-act="build-open-insert-template"]').click()
        await page.locator('[data-act="build-tpl-choose"]').first.click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-tpl-insert\"]')")
        await page.locator('[data-act="build-tpl-insert"]').click()
        await js_until(page, "!document.querySelector('.modal-back')")
        await js_until(page, f"document.querySelectorAll('.scard').length === {before} + 1")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_duplicate_workbook_creates_a_new_file_and_navigates_to_it(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}")
    try:
        await js_until(page, "document.querySelectorAll('main a.disp').length >= 2")
        await page.locator('[data-act="build-open-duplicate"]').click()
        await page.locator('[data-input="build-dup-name"]').fill(f"{build_copy}_dup")
        await page.locator('[data-act="build-dup-run"]').click()
        await js_until(page, f"location.hash.includes('build/{build_copy}_dup')", timeout=10)
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_find_and_replace_across_the_workbook(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}")
    try:
        await js_until(page, "document.querySelectorAll('main a.disp').length >= 2")
        await page.locator('[data-act="build-open-find-replace"]').click()
        await page.locator('[data-input="build-fr-find"]').fill("Singapore")
        await page.locator('[data-input="build-fr-repl"]').fill("Tokyo")
        await page.locator('[data-act="build-fr-preview"]').click()
        await js_until(page, "document.querySelectorAll('.modal tbody tr').length > 0")
        await page.locator('[data-act="build-fr-apply"]').click()
        await js_until(page, "!document.querySelector('.modal-back')")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_value_builder_writes_a_formula_into_the_value_field(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        await page.locator(".scard").first.click()
        await page.locator('[data-act="build-open-value-builder"]').click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-vb-use\"]')")
        await page.locator('[data-act="build-vb-use"]').click()
        await js_until(page, "!document.querySelector('.modal-back')")
        await js_until(page, "(document.querySelector('[data-input=\"build-step-value\"]') || {}).value?.startsWith('=TEXT(TODAY()')")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_file_changed_on_disk_offers_a_per_step_merge(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/FlowA")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        row = await page.locator(".scard").first.get_attribute("data-key")
        row_n = row.split("-")[1]
        await page.locator(".scard").first.click()
        await page.locator('[data-input="build-step-value"]').fill("mine")
        await page.locator('[data-input="build-step-value"]').press("Tab")
        await js_until(page, "document.body.innerText.includes('Draft autosaved')", timeout=10)

        wb_path = web.root / "workbooks" / build_copy
        wb = openpyxl.load_workbook(wb_path)
        ws = wb["FlowA"]
        ws.cell(int(row_n), 13, "theirs")
        wb.save(wb_path)

        await page.reload()
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        await js_until(page, "!!document.querySelector('[data-act=\"build-file-changed\"]')")
        await page.locator('[data-act="build-file-changed"]').click()
        await js_until(page, "document.querySelectorAll('.modal tbody tr').length > 0")
        await page.locator('[data-act="build-fc-pick"][data-val="theirs"]').first.click()
        await page.locator('[data-act="build-fc-merge"]').click()
        await js_until(page, "!document.querySelector('.modal-back')")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()
