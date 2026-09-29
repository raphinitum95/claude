"""The UI on a phone-sized and a small-laptop-sized window: nothing sideways-scrolls, and the header's buttons stay reachable."""
from __future__ import annotations

import os
import re

import pytest
from playwright.async_api import async_playwright

from tests.test_web_build import build_copy, js_until  # noqa: F401  (fixtures/helpers)
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser

SIZES = [(390, 800), (800, 900)]
SHOTS = os.environ.get("RR_SHOTS")          # a folder: keep a screenshot of every screen checked (for looking at by hand)

OFF_SCREEN = """() => {
  const w = document.documentElement.clientWidth, out = [];
  for (const el of document.querySelectorAll('.app-header button, .app-header a, .app-header .tab-btn, .app-header .icon-btn')) {
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > w + 1 || r.left < -1)) out.push(`${el.textContent.trim() || el.getAttribute('aria-label')} at ${Math.round(r.left)}-${Math.round(r.right)}`);
  }
  return { sideways: document.documentElement.scrollWidth - w, header: out };
}"""


async def check(web, path, width, height, wait, tag):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width": width, "height": height})
    await ctx.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"), lambda route: route.fulfill(status=200, content_type="text/css", body=""))
    page = await ctx.new_page()
    try:
        await page.goto(web.base + path)
        await js_until(page, wait)
        await page.wait_for_timeout(300)
        if SHOTS:
            await page.screenshot(path=f"{SHOTS}/{tag}_{width}.png", full_page=True)
        return await page.evaluate(OFF_SCREEN)
    finally:
        await browser.close()
        await pw.stop()


@pytest.mark.parametrize("width,height", SIZES)
async def test_no_screen_scrolls_sideways_and_the_header_stays_on_screen(web, build_copy, width, height):
    screens = [
        ("/", "!!document.querySelector('.tab-btn.on')", "run"),
        (f"/#/build/all", "!!document.querySelector('.wb-grid')", "build_all"),
        (f"/#/build/{build_copy}", "document.querySelectorAll('main a.disp').length >= 2", "build_map"),
        (f"/#/build/{build_copy}/test/FlowA", "document.querySelectorAll('.scard').length > 0", "build_editor"),
        (f"/#/build/{build_copy}/variables", "!!document.querySelector('#bv-new')", "build_variables"),
        ("/#/results", "!!document.querySelector('.tab-btn.on')", "results"),
    ]
    for path, wait, tag in screens:
        got = await check(web, path, width, height, wait, tag)
        assert got["sideways"] <= 0, f"{tag} at {width}px scrolls sideways by {got['sideways']}px"
        assert not got["header"], f"{tag} at {width}px: header controls off screen: {got['header']}"
