"""Arrow keys sent to a native drop-down: a headless browser ignores them, so the runner moves the choice the way a real browser would."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from regrunner.engine.actions import _move_select_choice

pytestmark = pytest.mark.browser

PAGE = ("<select id='g' required><option value=''>Gender</option><option>Male</option><option disabled>Hidden</option>"
        "<option>Female</option></select><script>g.addEventListener('change', () => { document.title = 'changed:' + g.value; });</script>")


async def press(keys, html=PAGE, focus="#g"):
    """Focus ``focus`` (like a click on it) and send ``keys`` through the runner's key handling. Returns (value, title, notes)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(html)
            await page.focus(focus)
            ctx = SimpleNamespace(session=SimpleNamespace(scope=lambda: _scope(page)), out=SimpleNamespace(notes=[]))
            handled = [await _move_select_choice(ctx, key) for key in keys]
            return await page.evaluate("g.value"), await page.title(), ctx.out.notes, handled
        finally:
            await browser.close()


async def _scope(page):
    return page


async def test_arrow_down_moves_the_drop_down_and_the_page_hears_the_change():
    value, title, notes, handled = await press(["ArrowDown"])
    assert value == "Male" and title == "changed:Male" and handled == [True] and "'Male'" in notes[0]


async def test_a_second_arrow_down_skips_a_disabled_option_and_a_third_stays_at_the_end():
    value, _, notes, _ = await press(["ArrowDown", "ArrowDown"])
    assert value == "Female"
    value, _, notes, _ = await press(["ArrowDown", "ArrowDown", "ArrowDown"])
    assert value == "Female" and "already at its end" in notes[-1]


async def test_arrow_up_and_home_go_back():
    value, *_ = await press(["End", "ArrowUp"])
    assert value == "Male"
    value, *_ = await press(["End", "Home"])
    assert value == ""


async def test_other_keys_and_other_elements_are_left_to_the_browser():
    _, _, _, handled = await press(["Enter", "Tab"])
    assert handled == [False, False]
    _, _, _, handled = await press(["ArrowDown"], html=PAGE + "<input id='t'>", focus="#t")
    assert handled == [False]
