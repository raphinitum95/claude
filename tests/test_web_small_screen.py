"""The UI on a phone-sized and a small-laptop-sized window: nothing sideways-scrolls, and the header's buttons stay reachable."""
from __future__ import annotations

import os
import re

import pytest
from playwright.async_api import async_playwright

from tests.test_web_build import build_copy, js_until  # noqa: F401  (fixtures/helpers)
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser

SIZES = [(390, 844), (768, 1024), (1024, 768)]          # phone, tablet portrait, tablet landscape
SHOTS = os.environ.get("RR_SHOTS")          # a folder: keep a screenshot of every screen checked (for looking at by hand)

OFF_SCREEN = """() => {
  const w = document.documentElement.clientWidth, out = [], clipped = [];
  for (const el of document.querySelectorAll('.app-header button, .app-header a, .app-header .tab-btn, .app-header .icon-btn, .app-header select')) {
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > w + 1 || r.left < -1)) out.push(`${el.textContent.trim() || el.getAttribute('aria-label')} at ${Math.round(r.left)}-${Math.round(r.right)}`);
  }
  // Content the app clips instead of scrolling: sticks out past the window with no horizontally scrolling box around it.
  const scrolls = (el) => { for (let p = el.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll') return true; } return false; };
  for (const el of document.querySelectorAll('main *, aside *')) {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (!r.width || cs.visibility === 'hidden' || cs.position === 'fixed') continue;
    if (el.closest('.b-rail:not(.open)')) continue;
    if (r.right > w + 1 && !scrolls(el) && el.children.length === 0) clipped.push(`"${(el.textContent || '').trim().slice(0, 24)}" ends at ${Math.round(r.right)} in ${(() => { const c = []; for (let p = el; p && p.tagName !== 'BODY' && c.length < 7; p = p.parentElement) c.push(p.tagName.toLowerCase() + '.' + String(p.className).slice(0, 18)); return c.join(' < '); })()}`);
  }
  // text broken one or two characters per line (a column squeezed to nothing)
  const squeezed = [];
  for (const el of document.querySelectorAll('main *')) {
    if (el.children.length || !el.textContent.trim() || getComputedStyle(el).visibility === 'hidden') continue;
    const r = el.getBoundingClientRect(), t = el.textContent.trim();
    if (r.width && r.width < 28 && t.length > 10 && r.height > 60) squeezed.push(`"${t.slice(0, 20)}" is ${Math.round(r.width)}px wide`);
  }
  const hdr = document.querySelector('.app-header');
  return { sideways: document.documentElement.scrollWidth - w, header: out, clipped: clipped.slice(0, 5), squeezed: squeezed.slice(0, 5), headerHeight: hdr ? hdr.getBoundingClientRect().height : 0 };
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
        found = await page.evaluate(OFF_SCREEN)
        if SHOTS:
            await page.screenshot(path=f"{SHOTS}/{tag}_{width}.png", full_page=True)
        return found
    finally:
        await browser.close()
        await pw.stop()


@pytest.mark.parametrize("width,height", SIZES)
async def test_no_screen_scrolls_sideways_and_the_header_stays_on_screen(web, build_copy, width, height):
    screens = [
        ("/", "document.querySelectorAll('label.trow').length > 0", "run"),
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
        assert not got["clipped"], f"{tag} at {width}px: content cut off at the right edge: {got['clipped']}"
        assert not got["squeezed"], f"{tag} at {width}px: text squeezed into a sliver: {got['squeezed']}"
        assert got["headerHeight"] <= (150 if width <= 1060 else 64), f"{tag} at {width}px: the header is {got['headerHeight']}px tall"


async def open_at(web, path, width, height):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width": width, "height": height})
    await ctx.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"), lambda route: route.fulfill(status=200, content_type="text/css", body=""))
    page = await ctx.new_page()
    await page.goto(web.base + path)
    return pw, browser, page


async def shot(page, tag):
    if SHOTS:
        await page.screenshot(path=f"{SHOTS}/{tag}.png", full_page=False)


async def test_on_a_phone_the_editor_shows_one_pane_at_a_time_and_the_header_menu_and_rail_open(web, build_copy):
    pw, browser, page = await open_at(web, f"/#/build/{build_copy}/test/FlowA", 390, 844)
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        visible = "(sel) => { const e = document.querySelector(sel); return !!e && e.getBoundingClientRect().width > 0 && getComputedStyle(e).display !== 'none' }"
        assert await page.evaluate(visible, ".pane-switch")
        assert not await page.evaluate(visible, "aside.pane-details"), "the inspector must wait for its own pane"
        await page.locator(".phone-bar").get_by_role("button", name=re.compile("Edit details")).click()
        await js_until(page, "document.querySelector('.app-body').dataset.pane === 'details'")
        assert await page.evaluate(visible, "aside.pane-details")
        assert not await page.evaluate(visible, ".scard"), "the step list is hidden while the details show"
        await shot(page, "phone_details")
        await page.get_by_role("button", name="Next").click()                               # the neighbouring step, still in Details
        await js_until(page, "document.querySelector('.app-body').dataset.pane === 'details'")
        await page.get_by_role("tab", name="Test").click()
        await js_until(page, "document.querySelector('.app-body').dataset.pane === 'test'")
        await shot(page, "phone_test")
        await page.get_by_role("button", name=re.compile("^More")).click()                    # header menu: the buttons that do not fit
        await js_until(page, "!!document.querySelector('.hdr-menu')")
        names = await page.locator(".hdr-menu [role=menuitem]").all_inner_texts()
        assert any("Undo" in n for n in names) and any("Download" in n for n in names) and any("New workbook" in n for n in names), names
        await shot(page, "phone_menu")
        await page.locator(".hdr-menu").get_by_role("menuitem", name=re.compile("History")).click()
        await js_until(page, "!document.querySelector('.hdr-menu')")                        # choosing closes the menu
        await js_until(page, "!!document.querySelector('.modal')")
    finally:
        await browser.close()
        await pw.stop()


async def test_on_a_tablet_steps_and_details_sit_side_by_side_and_the_rail_is_a_drawer(web, build_copy):
    pw, browser, page = await open_at(web, f"/#/build/{build_copy}/test/FlowA", 768, 1024)
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        boxes = await page.evaluate("() => { const b = (s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right, r.top]; }; return { steps: b('.scard'), aside: b('aside.pane-details') } }")
        assert boxes["steps"][1] <= boxes["aside"][0] + 1 and abs(boxes["steps"][2] - boxes["aside"][2]) < 400, boxes     # beside each other, not stacked
        assert not await page.evaluate("document.querySelector('.pane-switch').getBoundingClientRect().width")
        await js_until(page, "getComputedStyle(document.querySelector('.b-rail')).visibility === 'hidden'")      # (it slides away, so it takes a moment)
        await page.get_by_role("button", name=re.compile("^Show this workbook")).click()
        await js_until(page, "document.querySelector('.b-rail.open') != null")
        await shot(page, "tablet_rail")
        await page.locator(".rail-close").click()
        await js_until(page, "document.querySelector('.b-rail.open') == null")
        await page.get_by_role("button", name=re.compile("^More")).click()
        await js_until(page, "!!document.querySelector('.hdr-menu')")
        await shot(page, "tablet_menu")
    finally:
        await browser.close()
        await pw.stop()


CLIPPED_IN_HEADER = """() => {
  const mid = document.querySelector('.hdr-mid'), out = [];
  if (!mid) return ['no .hdr-mid'];
  const m = mid.getBoundingClientRect(), vw = document.documentElement.clientWidth;
  for (const [name, el] of [['the All workbooks button', document.querySelector('.hdr-mid a[aria-label="All workbooks"]')],
                            ['the environment picker', document.querySelector('#build-env')?.closest('label')],
                            ['the workbook name', document.querySelector('.hdr-mid a[title]')]]) {
    if (!el) { out.push(`${name} is missing`); continue; }
    const r = el.getBoundingClientRect();
    if (r.width < 20 || r.left < m.left - 1 || r.right > m.right + 1 || r.right > vw + 1) out.push(`${name} is cut off (${Math.round(r.left)}-${Math.round(r.right)} in a header area ${Math.round(m.left)}-${Math.round(m.right)}, window ${vw})`);
  }
  for (const el of document.querySelectorAll('.app-header button, .app-header a, .app-header select, .app-header label')) {
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > vw + 1 || r.left < -1)) out.push(`${(el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 24)} is off the screen (${Math.round(r.left)}-${Math.round(r.right)}, window ${vw})`);
  }
  if (document.documentElement.scrollWidth > vw) out.push(`the page scrolls sideways by ${document.documentElement.scrollWidth - vw}px`);
  return out;
}"""


@pytest.mark.parametrize("width", [360, 420, 560, 700, 780, 820, 830, 900, 980, 1040, 1060, 1061, 1100, 1140, 1240, 1300, 1360, 1361, 1400, 1600])
async def test_header_keeps_env_and_all_workbooks(web, build_copy, width):
    pw, browser, page = await open_at(web, f"/#/build/{build_copy}/test/FlowA", width, 900)
    try:
        await js_until(page, "document.querySelectorAll('.scard').length > 0")
        await page.wait_for_timeout(300)
        problems = await page.evaluate(CLIPPED_IN_HEADER)
        assert not problems, f"at {width}px: {problems}"
    finally:
        await browser.close()
        await pw.stop()
