"""Carrie mode in the QA app: the Run tab's toggle and the unicorn scorekeeper in the corner of the live run screen
(static/js/carrie.js is the adapter, static/unicorn/js/carrie.js is the widget). Runs against the web fixture's mock site."""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import expect

from tests.test_web_ui import command, command_has, js_until, open_ui, wait_ready
from tests.web_fixtures import bad_run, web  # noqa: F401  (fixtures)

pytestmark = pytest.mark.browser

BOARDS = """() => { const h = document.getElementById('carrie-root'); if (!h) return null; const s = h.shadowRoot;
  const w = s.querySelector('.wrap'); return { shown: !w.hidden, pass: s.querySelector('.pass .n').textContent, fail: s.querySelector('.fail .n').textContent,
    mood: (s.querySelector('#unicorn') || {dataset: {}}).dataset.mood || null }; }"""


async def boards(page):
    return await page.evaluate(BOARDS)


async def turn_on(page):
    await page.get_by_label("Carrie mode").click(force=True)
    await expect(page.get_by_label("Carrie mode")).to_be_checked()


async def test_carrie_mode_is_a_toggle_in_run_settings_that_is_off_by_default_and_changes_nothing_else(web):
    async with open_ui(web) as page:
        await wait_ready(page)
        toggle = page.get_by_label("Carrie mode")
        await expect(toggle).to_be_visible()
        await expect(toggle).not_to_be_checked()
        await command_has(page, "regrunner run")
        before = await command(page)
        await turn_on(page)
        assert await command(page) == before                                   # a preference of this browser, not a setting of the run
        assert await page.evaluate("localStorage.getItem('rr.carrie')") == "1"
        await page.reload()
        await wait_ready(page)
        await expect(page.get_by_label("Carrie mode")).to_be_checked()          # remembered
        assert not page.errors


async def test_with_carrie_mode_off_none_of_her_files_are_ever_requested(web, bad_run):
    async with open_ui(web, path=f"/#/run/{bad_run}") as page:
        asked = []
        page.on("request", lambda r: asked.append(r.url) if "/static/unicorn/" in r.url else None)
        await page.wait_for_selector("text=2 of 2 tests failed")
        await page.wait_for_timeout(500)
        assert asked == [] and await boards(page) is None


async def test_a_finished_run_opens_with_her_already_at_rest_showing_the_final_score(web, bad_run):
    async with open_ui(web) as page:
        await wait_ready(page)
        await turn_on(page)
        await page.evaluate(f"location.hash = '#/run/{bad_run}'")
        await page.wait_for_selector("text=2 of 2 tests failed")
        await js_until(page, "!!document.getElementById('carrie-root') && !document.getElementById('carrie-root').shadowRoot.querySelector('.wrap').hidden "
                             "&& !!document.getElementById('carrie-root').shadowRoot.querySelector('svg')")
        got = await boards(page)
        assert (got["pass"], got["fail"]) == ("0", "2")
        assert got["mood"] == "sad"
        root = page.locator("#carrie-root")
        box = await root.bounding_box()
        vw = await page.evaluate("innerWidth")
        assert box["x"] + box["width"] > vw - 40                                # bottom-right corner
        assert (await page.evaluate("getComputedStyle(document.getElementById('carrie-root')).pointerEvents")) == "none"
        assert not page.errors


async def test_she_keeps_score_on_a_live_run_and_goes_away_with_the_page_or_the_close_button(web):
    with web.client() as c:
        run_id = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA", "FlowB"]}).json()["run_id"]
    async with open_ui(web) as page:
        await wait_ready(page)
        await turn_on(page)
        await page.evaluate(f"location.hash = '#/run/{run_id}'")
        await js_until(page, "(() => { const h = document.getElementById('carrie-root'); return !!h && !h.shadowRoot.querySelector('.wrap').hidden; })()")
        await js_until(page, "(() => { const s = document.getElementById('carrie-root').shadowRoot; "
                             "return Number(s.querySelector('.pass .n').textContent) + Number(s.querySelector('.fail .n').textContent) === 2; })()", timeout=60)
        done = await asyncio.to_thread(web.wait_finished, run_id)
        statuses = [t["status"] for t in done["results"]["tests"]]
        got = await boards(page)
        assert (int(got["pass"]), int(got["fail"])) == (statuses.count("PASSED"), statuses.count("FAILED"))
        await page.evaluate("location.hash = '#/'")                             # another page: she is put away
        await js_until(page, "document.getElementById('carrie-root').shadowRoot.querySelector('.wrap').hidden")
        await page.evaluate(f"location.hash = '#/run/{run_id}'")
        await js_until(page, "!document.getElementById('carrie-root').shadowRoot.querySelector('.wrap').hidden")
        await page.evaluate("document.getElementById('carrie-root').shadowRoot.querySelector('.x').click()")          # the × turns Carrie mode off
        await js_until(page, "document.getElementById('carrie-root').shadowRoot.querySelector('.wrap').hidden")
        assert await page.evaluate("localStorage.getItem('rr.carrie')") == "0"
        assert not page.errors
