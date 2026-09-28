"""Variables and environments in a real browser (builder feedback items 12, 18, 24): the Build tab's Variables screen edits variables, the Run
tab offers exactly a builder workbook's own environments (no "Workbook default") and waits for one to be picked, and Download says which
secrets are not in the file."""
from __future__ import annotations

import asyncio
import os
import re

import pytest
from playwright.async_api import async_playwright

from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


async def open_ui(web, path="/"):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
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


async def builder_workbook(web, name: str, envs: list[str]) -> str:
    """A workbook the way the Build tab makes it: its own environment table, one test that types a data variable and a secret."""
    async with web.aclient() as c:
        r = await c.post("/api/build/workbooks", json={"name": name, "environments": [
            {"name": e, "domain": web.site.rstrip("/"), "production": e == "PROD"} for e in envs]})
        assert r.status_code == 201, r.text
        wb = r.json()["name"]
        ops = [{"op": "add_test", "name": "Login", "kind": "web"},
               {"op": "add_variable", "test": "Login", "token": "FIRST_NAME", "value": "Ann"},
               {"op": "insert_step", "test": "Login", "step": {"method": "OPEN", "value": "{DOMAIN}/form.html", "page": "chrome"}},
               {"op": "insert_step", "test": "Login", "step": {"method": "SET", "findBy": "xpath", "locator": "//input[@id='first']", "value": "{FIRST_NAME}"}},
               {"op": "insert_step", "test": "Login", "step": {"method": "SET", "findBy": "xpath", "locator": "//input[@id='pw']", "value": "{SECRET:PASSWORD}"}},
               {"op": "set_variable", "token": "PASSWORD", "secret": True, "label": "Password"}]
        r = await c.post(f"/api/build/workbooks/{wb}/edit", json={"ops": ops})
        assert r.status_code == 200, r.text
        assert (await c.post(f"/api/build/workbooks/{wb}/save", json={})).status_code == 200
        return wb


async def pick_only(page, name: str):
    for value in await page.locator("input[name=workbook]:checked").evaluate_all("els => els.map(e => e.value)"):
        if value != name:
            await page.locator(f'input[name=workbook][value="{value}"]').uncheck(force=True)
    await page.locator(f'input[name=workbook][value="{name}"]').check(force=True)


async def test_the_variables_screen_adds_edits_renames_and_keeps_a_secret_in_secrets_env(web):
    wb = await builder_workbook(web, "vars_screen", ["QA", "UAT", "PROD"])
    pw, browser, page = await open_ui(web, f"/#/build/{wb}/variables")
    try:
        await js_until(page, "!!document.querySelector('#bv-new')")
        assert await page.locator("#build-env").input_value() == "QA"         # no default: the table's first, and the header says which
        await page.locator("#bv-new").click()
        await page.locator("#bv-add-token").fill("CITY")
        await page.locator('#bv-add input[data-field="value"]').fill("Paris")
        await page.locator("#bv-add-create").click()
        await js_until(page, "!!document.querySelector('input[data-change=\"bv-data-cell\"]')")
        assert await page.locator("#bv-label").input_value() == "City"
        cell = page.locator('input[data-change="bv-data-cell"]').first
        assert await cell.input_value() == "Paris"
        await cell.fill("Lyon")
        await cell.press("Tab")
        async with web.aclient() as c:
            for _ in range(100):
                values = (await c.get(f"/api/build/workbooks/{wb}/variables/CITY/values")).json()
                if values["sources"][0]["rows"][0]["value"] == "Lyon":
                    break
                await asyncio.sleep(0.1)
        assert values["sources"] == [{"sheet": "Login_Params", "column": "CITY", "tests": ["Login"],
                                      "rows": [{"row": 2, "label": "", "enabled": True, "value": "Lyon", "formula": False, "masked": False}]}]

        await page.locator('[data-act="build-select-variable"][data-field="FIRST_NAME"]').click()
        await page.get_by_role("button", name="Rename").click()
        await page.locator("#bv-rename-to").fill("GIVEN_NAME")
        await page.get_by_role("button", name="Show what changes").click()
        await js_until(page, "document.querySelectorAll('#bv-rename-changes tbody tr').length === 2")
        assert "{GIVEN_NAME}" in await page.locator("#bv-rename-changes").inner_text()
        await page.locator("#bv-rename-apply").click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-select-variable\"][data-field=\"GIVEN_NAME\"]')")
        async with web.aclient() as c:
            model = (await c.get(f"/api/build/workbooks/{wb}")).json()
        login = next(t for t in model["tests"] if t["id"] == "Login")
        assert any(s["value"] == "{GIVEN_NAME}" for s in login["steps"])

        await page.locator('[data-act="build-select-variable"][data-field="DOMAIN"]').click()
        await js_until(page, "document.querySelectorAll('#bv-env-values tbody tr').length === 3")
        assert not await page.locator("#bv-delete").count()                  # every environment needs its DOMAIN
        qa = page.locator('#bv-env-values input[data-env="QA"]')
        await qa.fill("https://qa.changed.example")
        await qa.press("Tab")
        async with web.aclient() as c:
            for _ in range(100):
                rows = (await c.get(f"/api/build/workbooks/{wb}")).json()["environments"]["rows"]
                if rows[0]["values"]["QA"] == "https://qa.changed.example":
                    break
                await asyncio.sleep(0.1)
        assert rows[0]["variable"] == "DOMAIN" and rows[0]["values"]["QA"] == "https://qa.changed.example" and rows[0]["required"]

        await page.locator('[data-act="build-select-variable"][data-field="PASSWORD"]').click()
        await js_until(page, "!!document.querySelector('#bv-secret')")
        await page.locator('#bv-secret input[data-env="UAT"]').fill("s3cret-value")
        await page.locator('#bv-secret button[data-env="UAT"]').click()
        await js_until(page, "document.querySelector('#bv-secret tr[data-key=\"sv-UAT\"]').textContent.includes('set') && "
                             "!document.querySelector('#bv-secret tr[data-key=\"sv-UAT\"]').textContent.includes('not set')")
        assert "RR_SECRET_UAT_PASSWORD=s3cret-value" in (web.root / "secrets.env").read_text()
        assert "s3cret-value" not in await page.content()
        assert not page.errors, page.errors
    finally:
        os.environ.pop("RR_SECRET_UAT_PASSWORD", None)
        await browser.close()
        await pw.stop()


async def test_the_run_tab_offers_only_a_builder_workbooks_environments_and_waits_for_one_to_be_picked(web):
    wb = await builder_workbook(web, "envs_run", ["QA", "UAT", "PROD"])
    other = await builder_workbook(web, "envs_other", ["QA", "SIT"])
    pw, browser, page = await open_ui(web, "/")
    try:
        await js_until(page, "document.querySelectorAll('input[name=workbook]').length >= 3")
        await pick_only(page, wb)
        await js_until(page, "!!document.querySelector('#env-pick')")         # (read: its own environments, none picked yet)
        labels = await page.locator("#env-choice button").all_inner_texts()
        assert labels == ["QA", "UAT", "PROD"]                                # no "Workbook default"
        launch = page.locator('button[data-act="launch"]')
        await js_until(page, "document.querySelector('button[data-act=\"launch\"]').textContent.includes('Pick an environment')")
        assert await launch.is_disabled() and await page.locator("#env-pick").is_visible()
        await page.locator("#env-choice button", has_text="UAT").click()
        await js_until(page, "/Run \\d+ test/.test(document.querySelector('button[data-act=\"launch\"]').textContent)")
        assert await launch.is_enabled()
        await js_until(page, "document.querySelector('[aria-label=\"Command line for this run\"]').textContent.includes('--env UAT')")
        await page.locator(f'input[name=workbook][value="{other}"]').check(force=True)      # two builder workbooks: only what both define
        await js_until(page, "document.querySelectorAll('#env-choice button').length === 1")
        assert await page.locator("#env-choice button").all_inner_texts() == ["QA"]
        assert "UAT: not in envs_other" in await page.locator("#env-missing").inner_text()
        assert await launch.is_disabled()                                     # UAT was picked: not one they share
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_download_says_which_secrets_are_not_in_the_file(web):
    wb = await builder_workbook(web, "envs_download", ["QA", "UAT"])
    pw, browser, page = await open_ui(web, "/#/build/all")
    try:
        await js_until(page, f"!!document.querySelector('[data-act=\"build-download\"][data-name=\"{wb}\"]')")
        await page.locator(f'[data-act="build-download"][data-name="{wb}"]').click()
        await js_until(page, "!!document.querySelector('#bv-download-secrets')")
        text = await page.locator("#bv-download-secrets").inner_text()
        assert "{SECRET:PASSWORD}" in text and "secrets.env" in text
        async with page.expect_download() as info:
            await page.locator("#bv-download-go").click()
        download = await info.value
        assert download.suggested_filename == wb
        await js_until(page, "!document.querySelector('#bv-download-secrets')")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()
